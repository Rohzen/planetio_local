from odoo import models, fields, _
from odoo.exceptions import UserError
import base64, json

def extract_geojson_features(obj):
    """Return list of (geometry_dict, properties_dict) tuples from a GeoJSON object."""
    if not isinstance(obj, dict):
        return []
    t = obj.get("type")
    if t == "FeatureCollection":
        feats = []
        for f in obj.get("features", []) or []:
            if isinstance(f, dict) and isinstance(f.get("geometry"), dict):
                feats.append((f["geometry"], f.get("properties") or {}))
        return feats
    if t == "Feature" and isinstance(obj.get("geometry"), dict):
        return [(obj["geometry"], obj.get("properties") or {})]
    if t in ("Point", "Polygon", "MultiPolygon", "MultiPoint", "LineString", "MultiLineString"):
        return [(obj, {})]
    return []


class ExcelImportWizard(models.TransientModel):
    _name = "excel.import.wizard"
    _description = "Excel Import Wizard"

    file_data = fields.Binary(string="File", required=True, attachment=False)
    file_name = fields.Char(string="Filename")
    template_id = fields.Many2one("excel.import.template", required=True)

    def _default_debug_import(self):
        icp = self.env['ir.config_parameter'].sudo()
        val = icp.get_param('planetio.debug_import', default='True')
        return str(val).lower() in ('1', 'true', 'yes')

    debug_import = fields.Boolean(default=_default_debug_import, readonly=True)

    step = fields.Selection(
        [("upload","Upload"),
         ("map","Mapping"),
         ("validate","Validate"),
         ("confirm","Confirm")],
        default="upload"
    )

    attachment_id = fields.Many2one("ir.attachment")
    sheet_name = fields.Char()
    declaration_id = fields.Many2one("eudr.declaration")
    mapping_json = fields.Text(readonly=True)
    preview_json = fields.Text(readonly=True)
    result_json = fields.Text(readonly=True)
    analysis_json = fields.Text(readonly=True)

    def _create_attachment(self):
        self.ensure_one()
        return self.env["ir.attachment"].create({
            "name": self.file_name or "upload.xlsx",
            "datas": self.file_data,
            "res_model": "excel.import.wizard",
            "res_id": self.id,
            "type": "binary",
            "mimetype": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        })

    def action_detect_and_map(self):
        self.ensure_one()
        fname = (self.file_name or "").lower()

        # Detect GeoJSON either by extension or by inspecting the content. Some
        # browsers/clients may omit the filename, which previously caused the
        # wizard to treat the upload as an Excel file and crash when pandas
        # could not detect a workbook format.
        is_geojson = fname.endswith((".geojson", ".json"))
        obj = None
        if not is_geojson:
            try:
                data = base64.b64decode(self.file_data or b"")
                obj = json.loads(data.decode("utf-8"))
                is_geojson = bool(extract_geojson_features(obj))
            except Exception:
                obj = None

        if is_geojson:
            try:
                if obj is None:
                    data = base64.b64decode(self.file_data or b"")
                    obj = json.loads(data.decode("utf-8"))
            except Exception as e:
                raise UserError(_("Invalid GeoJSON file: %s") % e)
            feats = extract_geojson_features(obj)
            preview = [g for g, _p in feats[:20]]
            self.preview_json = json.dumps(preview, ensure_ascii=False)
            self.mapping_json = "{}"
            self.step = "validate"
            return {
                "type": "ir.actions.act_window",
                "res_model": "excel.import.wizard",
                "view_mode": "form",
                "res_id": self.id,
                "target": "new",
            }

        attachment = self._create_attachment()
        self.attachment_id = attachment.id

        sheet, score = self.env["excel.import.service"].pick_best_sheet(self)
        self.sheet_name = sheet

        mapping, preview = self.env["excel.import.service"].propose_mapping(self)
        self.mapping_json = json.dumps(mapping, ensure_ascii=False)
        self.preview_json = json.dumps(preview, ensure_ascii=False)
        self.step = "map"

        return {
            "type": "ir.actions.act_window",
            "res_model": "excel.import.wizard",
            "view_mode": "form",
            "res_id": self.id,
            "target": "new",
        }

    def action_validate(self):
        self.ensure_one()
        transformed = self.env["excel.import.service"].transform_and_validate(self)
        self.result_json = transformed
        self.step = "validate"
        return {
            "type": "ir.actions.act_window",
            "res_model": "excel.import.wizard",
            "view_mode": "form",
            "res_id": self.id,
            "target": "new",
        }

    def action_confirm(self):
        self.ensure_one()
        fname = (self.file_name or "").lower()

        # Same detection logic as in action_detect_and_map: allow GeoJSON even
        # when the client does not provide a proper filename/extension.
        is_geojson = fname.endswith((".geojson", ".json"))
        obj = None
        if not is_geojson:
            try:
                data = base64.b64decode(self.file_data or b"")
                obj = json.loads(data.decode("utf-8"))
                is_geojson = bool(extract_geojson_features(obj))
            except Exception:
                obj = None

        if is_geojson:
            # Import GeoJSON directly into declaration lines
            try:
                if obj is None:
                    data = base64.b64decode(self.file_data or b"")
                    obj = json.loads(data.decode("utf-8"))
            except Exception:
                raise UserError(_("Invalid GeoJSON file"))

            decl_id = self.env.context.get("active_id")
            Decl = self.env["eudr.declaration"]
            if decl_id:
                decl = Decl.browse(decl_id)
            else:
                decl = Decl.create({})
                decl_id = decl.id

            feats = extract_geojson_features(obj)
            Line = self.env["eudr.declaration.line"]
            created = 0
            for geom, props in feats:
                if not isinstance(geom, dict) or not geom.get("type"):
                    continue
                vals = {
                    "declaration_id": decl_id,
                    "geometry": json.dumps(geom, ensure_ascii=False),
                }
                gtype = str(geom.get("type", "")).lower()
                if gtype in ("point", "polygon", "multipolygon"):
                    vals["geo_type"] = "point" if gtype == "point" else "polygon"
                name = props.get("name") or props.get("id")
                if name:
                    vals["name"] = name
                Line.create(vals)
                created += 1

            # store attachment on declaration
            attach = self.env["ir.attachment"].create({
                "name": self.file_name or "upload.geojson",
                "datas": self.file_data,
                "res_model": "eudr.declaration",
                "res_id": decl_id,
                "type": "binary",
                "mimetype": "application/geo+json",
            })
            try:
                decl.write({"source_attachment_id": attach.id})
            except Exception:
                pass

            self.step = "confirm"
            return {
                "type": "ir.actions.act_window",
                "res_model": "eudr.declaration",
                "view_mode": "form",
                "res_id": decl_id,
                "target": "current",
            }

        if not self.debug_import and self.step == 'upload':
            # run full pipeline silently
            self.action_detect_and_map()
            self.action_validate()

        result = self.env["excel.import.service"].create_records(self)
        created = result['created'] if isinstance(result, dict) else int(result or 0)
        decl_id = result.get('declaration_id') if isinstance(result, dict) else False
        self.declaration_id = decl_id
        self.step = "confirm"
        if decl_id:
            return {
                "type": "ir.actions.act_window",
                "res_model": "eudr.declaration",
                "view_mode": "form",
                "res_id": decl_id,
                "target": "current",
            }
        return {"type": "ir.actions.act_window_close"}


