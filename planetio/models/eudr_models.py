
import base64
from odoo import models, fields, api, _
from odoo.tools.misc import formatLang
from odoo.exceptions import UserError
from ..services.eudr_adapter_odoo import action_retrieve_dds_numbers
import json
import math
import urllib.parse
from odoo.modules.module import get_module_resource


EUDR_HS_SELECTION = [
    ('0901',    '0901 – Coffee, whether or not roasted or decaffeinated; coffee husks and skins; coffee substitutes containing coffee'),
    ('090111',  '0901 11 – non-decaffeinated'),
    ('090112',  '0901 12 – decaffeinated'),
    ('090121',  '0901 21 – non-decaffeinated'),
    ('090122',  '0901 22 – decaffeinated'),
    ('090190',  '0901 90 – others'),
]

try:
    from shapely.geometry import Point, mapping, shape
    from shapely.ops import transform
except ImportError:
    # Se le librerie non sono installate, la funzionalità non sarà disponibile.
    # In un ambiente di produzione, sarebbe meglio loggare un avviso.
    Point = None
    mapping = None
    shape = None
    transform = None


try:
    from pyproj import Geod, Transformer, CRS  # optional but recommended
except Exception:
    Geod = None
    Transformer = None
    CRS = None

class EUDRStage(models.Model):
    _name = "eudr.stage"
    _description = "CRM Stages"
    _rec_name = 'name'
    _order = "sequence, name, id"

    name = fields.Char('Stage Name', required=True, translate=True)
    sequence = fields.Integer('Sequence', default=1, help="Used to order stages. Lower is better.")

class EUDRDeclaration(models.Model):
    _name = "eudr.declaration"
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _description = "EUDR Declaration"

    def _default_stage_id(self):
        """Return the Draft stage id when available."""
        try:
            stage = self.env.ref('planetio.eudr_stage_draft')
        except ValueError:
            return False
        except Exception:
            return False
        return stage.id

    def _get_stage_from_xmlid(self, xmlid):
        """Safely fetch a stage from its xmlid."""
        try:
            return self.env.ref(xmlid)
        except ValueError:
            return self.env['eudr.stage']
        except Exception:
            return self.env['eudr.stage']

    def _set_stage_from_xmlid(self, xmlid):
        stage = self._get_stage_from_xmlid(xmlid)
        if stage:
            self.filtered(lambda rec: rec.stage_id != stage).write({'stage_id': stage.id})
        return stage

    company_id = fields.Many2one('res.company', default=lambda s: s.env.company, required=True)
    datestamp = fields.Datetime(string="Datestamp", default=lambda self: fields.Datetime.now())
    name = fields.Char(required=False)
    partner_id = fields.Many2one(
        'res.partner', string="Partner")
    eudr_id = fields.Char(required=False)
    dds_identifier = fields.Char(string="DDS Identifier (UUID)", readonly=True, copy=False)
    stage_id = fields.Many2one(
        'eudr.stage',
        string='Stage',
        index=True,
        tracking=True,
        default=lambda self: self._default_stage_id(),
    )
    farmer_name = fields.Char()
    farmer_id_code = fields.Char()
    tax_code = fields.Char()
    country = fields.Char()
    region = fields.Char()
    municipality = fields.Char()
    farm_name = fields.Char()
    area_ha = fields.Float(compute="_compute_area_ha", store=True, readonly=True)
    source_attachment_id = fields.Many2one("ir.attachment")
    line_ids = fields.One2many("eudr.declaration.line", "declaration_id", string="Lines")
    alert_ids = fields.One2many(
        "eudr.declaration.line.alert",
        "declaration_id",
        string="Deforestation Alerts",
        domain=[("line_id.external_ok", "=", False)],
        readonly=True,
    )

    attachment_ids = fields.One2many(
        'ir.attachment',
        'res_id',
        string='Documenti visibili',
        help="Allegati collegati."
    )
    # Allegati mostrati nella tab Documenti
    attachment_visible_ids = fields.One2many(
        'ir.attachment',
        'res_id',
        string='Documenti visibili',
        domain=[('res_model', '=', 'eudr.declaration'),
                ('eudr_document_visible', '=', True)],
        help="Allegati collegati e visibili nella sezione Documenti."
    )

    # Allegati non visibili
    attachment_hidden_ids = fields.One2many(
        'ir.attachment',
        'res_id',
        string='Documenti nascosti',
        domain=[('res_model', '=', 'eudr.declaration'),
                ('eudr_document_visible', '!=', True)],
        help="Allegati collegati ma non mostrati nella sezione Documenti."
    )

    dds_mode = fields.Selection(
        [
            ('single_one', 'Single commodity – current'),
            ('single_multi', 'Multiple commodities'),
            ('trader_refs', 'Trader references upstream DDS'),
        ],
        string="Submission mode",
        default='single_one',
        required=True,
        help="Choose how this declaration will be submitted to TRACES DDS.",
    )
    eudr_type_override = fields.Selection([
        ('TRADER', 'Trader'),
        ('OPERATOR', 'Operator')
    ], string="Operator", default='OPERATOR', help="Specify whether you're acting as Trader or Operator for this batch.")
    eudr_third_party_client_id = fields.Many2one(
        'res.partner', string="Client (3rd Party Trader)", help="Client on behalf of whom the DDS is being submitted."
    )
    # Dati generali (DDS TRACES)
    activity_type = fields.Selection(
        [
            ('import', 'Import'),
            ('export', 'Export'),
            ('domestic', 'Domestic'),
        ], string="Activity", default='import')
    operator_name = fields.Char(string="Operator")
    extra_info = fields.Text(string="Additional info")
    hs_code = fields.Selection(EUDR_HS_SELECTION, string="HS Code", default="090111", required=True)
    product_id  = fields.Many2one('product.product', string="Product template")
    product_description = fields.Char(string="Description of raw materials or products", required=True)
    net_mass_kg = fields.Float(string="Net weight", placeholder="Net Mass in Kg", digits=(16, 3), required=True)
    common_name = fields.Char(string="Common name")
    producer_name = fields.Char(string="Producer name")
    lot_name = fields.Char(string="Lot info")
    supplier_id = fields.Many2one('res.partner', string="Producer/Supplier")
    coffee_species  = fields.Many2one('coffee.species', string="Product", required=True)
    area_ha_display = fields.Char(compute="_compute_area_ha_display", store=False)
    commodity_ids = fields.One2many("eudr.commodity.line", "declaration_id", string="Commodities")
    associated_statement_ids = fields.One2many("eudr.associated.statement", "declaration_id", string="Associated statements")

    # Mirrors from company settings (for XML attrs)
    eudr_company_type_rel = fields.Selection(related="company_id.eudr_company_type", store=False, readonly=True)
    eudr_is_sme_rel = fields.Boolean(related="company_id.eudr_is_sme", store=False, readonly=True)
    eudr_tp_has_mandate_rel = fields.Boolean(related="company_id.eudr_third_party_has_mandate", store=False, readonly=True)
    eudr_tp_in_eu_rel = fields.Boolean(related="company_id.eudr_third_party_established_in_eu", store=False, readonly=True)

    @api.onchange('eudr_company_type_rel', 'eudr_is_sme_rel', 'eudr_type_override')
    def _onchange_eudr_context_cleanup(self):
        for r in self:
            # l’override ha senso solo per Mixed
            if r.eudr_company_type_rel != 'mixed':
                r.eudr_type_override = False
            # se non third party nascondiamo eventuale client_id
            if r.eudr_company_type_rel != 'third_party_trader':
                r.eudr_third_party_client_id = False

    @api.depends('area_ha')
    def _compute_area_ha_display(self):
        for rec in self:
            rec.area_ha_display = formatLang(self.env, rec.area_ha or 0.0, digits=4)

    @api.onchange('product_id')
    def _onchange_product_id_set_description(self):
        for rec in self:
            rec.product_description = rec.product_id.name or False

    # ---------------------- helpers ----------------------

    @staticmethod
    def _safe_json_load(s):
        if not s:
            return None
        try:
            return json.loads(s)
        except Exception:
            return None

    @staticmethod
    def _iter_geojson_geometries(obj):
        """
        Yields raw GeoJSON geometry dicts from:
        - Geometry
        - Feature with .geometry
        - FeatureCollection with .features[*].geometry
        Anything else is ignored.
        """
        if not obj:
            return
        t = obj.get("type")
        if t in ("Point", "Polygon", "MultiPolygon", "MultiPoint", "LineString", "MultiLineString"):
            yield obj
        elif t == "Feature" and isinstance(obj.get("geometry"), dict):
            yield obj["geometry"]
        elif t == "FeatureCollection" and isinstance(obj.get("features"), list):
            for f in obj["features"]:
                if isinstance(f, dict) and isinstance(f.get("geometry"), dict):
                    yield f["geometry"]

    @staticmethod
    def _poly_rings_lonlat(geom):
        """
        Returns list of polygons, each polygon is a list of linear rings,
        each ring is a list of (lon, lat) tuples. Holes are included but area is computed geodesically later.
        """
        gtype = geom.get("type")
        coords = geom.get("coordinates")
        if gtype == "Polygon" and isinstance(coords, list):
            return [coords]  # [ [ [lon,lat], ... ] , hole?, ... ]
        if gtype == "MultiPolygon" and isinstance(coords, list):
            return coords    # [ polygon1_rings, polygon2_rings, ... ]
        return []

    # ----------------- geodesic area via pyproj.Geod -----------------

    @staticmethod
    def _geodesic_area_m2_of_polygons(polygons_rings):
        """
        polygons_rings: iterable of polygons, each polygon is list of rings (outer + holes),
        where each ring is list of [lon, lat] pairs.
        Uses WGS84 ellipsoid. Returns total absolute area in m².
        """
        if not Geod:
            return None  # signal that geodesic computation isn't available
        geod = Geod(ellps="WGS84")
        total = 0.0
        for rings in polygons_rings:
            if not rings:
                continue
            # exterior ring first per GeoJSON spec
            lon_ex, lat_ex = zip(*[(pt[0], pt[1]) for pt in rings[0] if isinstance(pt, (list, tuple)) and len(pt) >= 2])
            # area is negative if ring is counterclockwise; take absolute
            area_ex, _ = geod.polygon_area_perimeter(lon_ex, lat_ex)
            poly_area = abs(area_ex)
            # subtract holes if any
            for hole in rings[1:]:
                if not hole:
                    continue
                lon_h, lat_h = zip(*[(pt[0], pt[1]) for pt in hole if isinstance(pt, (list, tuple)) and len(pt) >= 2])
                area_h, _ = geod.polygon_area_perimeter(lon_h, lat_h)
                poly_area -= abs(area_h)
            total += max(0.0, poly_area)
        return total

    # -------------- convex hull of points (fallback / points-only) --------------

    @staticmethod
    def _convex_hull(points_xy):
        """
        Monotone chain convex hull. points_xy is a list of (x, y).
        Returns hull as list of (x, y) in CCW order without duplicate closing point.
        """
        pts = sorted(set(points_xy))
        if len(pts) <= 1:
            return pts

        def cross(o, a, b):
            return (a[0]-o[0])*(b[1]-o[1]) - (a[1]-o[1])*(b[0]-o[0])

        lower = []
        for p in pts:
            while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
                lower.pop()
            lower.append(p)

        upper = []
        for p in reversed(pts):
            while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
                upper.pop()
            upper.append(p)

        return lower[:-1] + upper[:-1]

    @staticmethod
    def _shoelace_area_m2(coords_xy):
        """Planar polygon area by shoelace formula. coords_xy is list of (x, y)."""
        if len(coords_xy) < 3:
            return 0.0
        area = 0.0
        n = len(coords_xy)
        for i in range(n):
            x1, y1 = coords_xy[i]
            x2, y2 = coords_xy[(i + 1) % n]
            area += x1 * y2 - x2 * y1
        return abs(area) * 0.5

    @staticmethod
    def _project_points_to_meters(lonlat_list):
        """
        Projects (lon, lat) to meters.
        Prefers UTM via pyproj; otherwise uses local equirectangular approximation.
        Returns list of (x, y) in meters.
        """
        if not lonlat_list:
            return []

        # centroid to choose projection
        lon0 = sum(p[0] for p in lonlat_list) / len(lonlat_list)
        lat0 = sum(p[1] for p in lonlat_list) / len(lonlat_list)

        # If pyproj available, choose UTM zone based on centroid
        if Transformer and CRS:
            zone = int(math.floor((lon0 + 180.0) / 6.0) + 1)
            north = lat0 >= 0.0
            epsg = 32600 + zone if north else 32700 + zone
            try:
                transformer = Transformer.from_crs("EPSG:4326", f"EPSG:{epsg}", always_xy=True)
                return [transformer.transform(lon, lat) for lon, lat in lonlat_list]
            except Exception:
                pass  # fall through to equirectangular

        # equirectangular approximation (good for compact clusters)
        R = 6371008.8
        lat0_rad = math.radians(lat0)
        x0 = R * math.radians(lon0) * math.cos(lat0_rad)
        y0 = R * math.radians(lat0)
        out = []
        for lon, lat in lonlat_list:
            x = R * math.radians(lon) * math.cos(lat0_rad)
            y = R * math.radians(lat)
            out.append((x - x0, y - y0))  # shift near origin to improve stability
        return out

    def _polygon_area_m2(self, polygons_rings):
        """Compute area in m² for the given polygons (list of rings)."""
        if not polygons_rings:
            return 0.0

        area_geo = self._geodesic_area_m2_of_polygons(polygons_rings)
        if area_geo is not None:
            return area_geo

        total = 0.0
        for rings in polygons_rings:
            if not rings:
                continue
            exterior = [
                (pt[0], pt[1])
                for pt in rings[0]
                if isinstance(pt, (list, tuple)) and len(pt) >= 2
            ]
            if not exterior:
                continue
            ex_xy = self._project_points_to_meters(exterior)
            poly_area = self._shoelace_area_m2(ex_xy)
            for hole in rings[1:]:
                hole_ll = [
                    (pt[0], pt[1])
                    for pt in hole
                    if isinstance(pt, (list, tuple)) and len(pt) >= 2
                ]
                if not hole_ll:
                    continue
                hole_xy = self._project_points_to_meters(hole_ll)
                poly_area -= self._shoelace_area_m2(hole_xy)
            total += max(0.0, poly_area)
        return total

    # ------------------ main compute ------------------

    @api.depends(
        "line_ids", "line_ids.geometry", "line_ids.geo_type",
        "commodity_ids.producer_ids.plot_ids.geometry",
        "commodity_ids.producer_ids.plot_ids.area_ha",
    )
    def _compute_area_ha(self):
        ICP = self.env['ir.config_parameter'].sudo()
        # valore in ettari per punto (default 4 ha)
        ha_per_point = float(ICP.get_param('planetio.eudr_point_area_ha', '4'))
        fallback_m2_per_point = ha_per_point * 10000.0

        for rec in self:
            total_area_m2 = 0.0
            def _float(value):
                try:
                    return float(value)
                except (TypeError, ValueError):
                    return None

            def _accumulate_from_geojson(raw_geojson, area_hint=None):
                gobj = self._safe_json_load(raw_geojson)
                if not gobj:
                    if area_hint and area_hint > 0:
                        return area_hint * 10000.0
                    return 0.0

                polygons, point_count = [], 0
                for geom in self._iter_geojson_geometries(gobj):
                    gtype = geom.get("type")
                    if gtype in ("Polygon", "MultiPolygon"):
                        polygons.extend(self._poly_rings_lonlat(geom))
                    elif gtype == "Point":
                        coords = geom.get("coordinates") or []
                        if isinstance(coords, (list, tuple)) and len(coords) >= 2:
                            point_count += 1
                    elif gtype == "MultiPoint":
                        coords = geom.get("coordinates") or []
                        for pt in coords:
                            if isinstance(pt, (list, tuple)) and len(pt) >= 2:
                                point_count += 1

                if polygons:
                    return rec._polygon_area_m2(polygons)
                if point_count:
                    return point_count * fallback_m2_per_point
                if area_hint and area_hint > 0:
                    return area_hint * 10000.0
                return 0.0

            for line in rec.line_ids:
                total_area_m2 += _accumulate_from_geojson(
                    getattr(line, "geometry", None),
                    _float(getattr(line, "area_ha", None)),
                )

            for plot in rec.mapped("commodity_ids.producer_ids.plot_ids"):
                total_area_m2 += _accumulate_from_geojson(
                    getattr(plot, "geometry", None),
                    _float(getattr(plot, "area_ha", None)),
                )

            rec.area_ha = (total_area_m2 / 10000.0) if total_area_m2 > 0.0 else 0.0

    @api.model
    def create(self, vals):
        # pick default stage
        default_stage_id = self._default_stage_id()

        # ensure company context is correct before drawing the sequence
        target_company = vals.get('company_id') or self.env.company.id
        env_in_company = self.with_company(target_company)

        # choose the sequence date (use provided datestamp or now)
        seq_dt = vals.get('datestamp') or fields.Datetime.now()
        ctx = dict(env_in_company.env.context, ir_sequence_date=seq_dt)

        if not vals.get('name'):
            vals['name'] = env_in_company.with_context(ctx).env['ir.sequence'].next_by_code('eudr.declaration') or _('New')

        if not vals.get('stage_id'):
            vals['stage_id'] = default_stage_id
        if 'net_mass_kg' not in vals:
            vals['net_mass_kg'] = 0.0

        # try once, and if a rare race triggers the unique constraint, regenerate and retry
        try:
            return super(EUDRDeclaration, self).create(vals)
        except Exception as e:
            # Only retry on unique violation on our constraint
            if hasattr(e, 'pgerror') and 'name_company_uniq' in getattr(e, 'pgerror', ''):
                vals['name'] = env_in_company.with_context(ctx).env['ir.sequence'].next_by_code('eudr.declaration') or _('New')
                return super(EUDRDeclaration, self).create(vals)
            raise

    def action_open_excel_import_wizard(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Excel Import Wizard',
            'res_model': 'excel.import.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_template_id': self.env.ref('planetio.tmpl_eudr_declaration').id,
                'declaration_id': self.id,
            },
        }



    def action_export_geojson(self):
        """Esporta una FeatureCollection con tutte le geometrie delle linee."""
        self.ensure_one()
        features = []
        for line in self.line_ids:
            if not line.geometry:
                continue
            try:
                geom = json.loads(line.geometry)
            except Exception:
                continue
            props = {
                "name": line.name,
                "farmer_name": line.farmer_name,
                "farm_name": line.farm_name,
                "area_ha": line.area_ha,
                "geo_type": line.geo_type,
            }
            features.append({"type": "Feature", "geometry": geom, "properties": props})
        payload = {"type": "FeatureCollection", "features": features}
        return {
            "type": "ir.actions.act_url",
            "url": "data:application/json," + json.dumps(payload),
            "target": "new",
        }

    def action_download_external_ok_json(self):
        """Download JSON data for lines flagged as externally validated."""

        self.ensure_one()

        ok_lines = self.line_ids.filtered(lambda line: line.external_ok)
        if not ok_lines:
            raise UserError(_("No lines marked as OK are available for download."))

        payload = []
        for line in ok_lines:
            line_payload = {
                "id": line.id,
                "name": line.name,
                "farmer_id_code": line.farmer_id_code,
                "farmer_name": line.farmer_name,
                "farm_name": line.farm_name,
                "country": line.country,
                "region": line.region,
                "municipality": line.municipality,
                "area_ha": line.area_ha,
                "geo_type": line.geo_type,
            }

            if line.geometry:
                try:
                    line_payload["geometry"] = json.loads(line.geometry)
                except Exception:
                    line_payload["geometry"] = line.geometry

            if line.external_properties_json:
                try:
                    line_payload["external_properties"] = json.loads(line.external_properties_json)
                except Exception:
                    line_payload["external_properties_raw"] = line.external_properties_json

            payload.append(line_payload)

        data = json.dumps({"lines": payload}, ensure_ascii=False, indent=2)

        return {
            "type": "ir.actions.act_url",
            "url": "data:application/json," + urllib.parse.quote(data),
            "target": "new",
        }

    def action_create_geojson(self):
        from ..services.eudr_adapter_odoo import attach_dds_geojson, build_dds_geojson

        for record in self:
            geojson_dict = build_dds_geojson(record)
            attachment = attach_dds_geojson(record, geojson_dict)
            record.message_post(
                body=_("GeoJSON creato e salvato come <b>%s</b>.") % attachment.name
            )
        return {"type": "ir.actions.client", "tag": "reload"}

    def open_otp_wizard(self):
        self.ensure_one()

        # Simula invio OTP
        self.message_post(body=_("OTP sent to the phone number entered during certification."))

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'otp.verification.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_batch_id': self.id
            }
        }

    # messo in services per evitare dipendenze circolari e troppe modifiche al codice esistente
    def action_transmit_dds(self):
        from ..services.eudr_adapter_odoo import submit_dds_for_batch
        for record in self:
            dds_id = submit_dds_for_batch(record)
            if dds_id:
                record._set_stage_from_xmlid('planetio.eudr_stage_sent')

    def action_open_import_wizard(self):
        self.ensure_one()
        template = None
        try:
            template = self.env.ref('planetio.tmpl_eudr_declaration')
        except ValueError:
            template = self.env['excel.import.template'].search([], limit=1)
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'excel.import.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'active_model': 'eudr.declaration',
                'active_id': self.id,
                'default_declaration_id': self.id,
                'default_template_id': template.id if template else False,
            }
        }

    def action_retrieve_dds(self):
        for rec in self:
            action_retrieve_dds_numbers(rec)
        return True

class EUDRDeclarationLine(models.Model):
    _name = "eudr.declaration.line"
    _description = "EUDR Declaration Line"
    # _inherit = ['mail.thread', 'mail.activity.mixin']

    declaration_id = fields.Many2one("eudr.declaration", ondelete="cascade")
    name = fields.Char()
    farmer_name = fields.Char()
    farmer_id_code = fields.Char()
    tax_code = fields.Char()
    country = fields.Char()
    country_id = fields.Many2one('res.country', string='Country (M2O)')

    country_flag_bin = fields.Binary(
        string="Flag",
        compute="_compute_country_flag_bin",
        store=False,
    )

    @api.depends('country', 'country_id')
    def _compute_country_flag_bin(self):
        """Carica il file bandiera da base/static in base al codice ISO a due lettere."""
        for rec in self:
            rec.country_flag_bin = False
            # 1) prova con M2O se presente
            iso_code = False
            if rec.country_id and rec.country_id.code:
                iso_code = rec.country_id.code
            else:
                # 2) fallback: se hai solo il Char, prova a risalire al paese per nome o codice
                if rec.country:
                    # cerca prima per codice (es. "IT"), poi per nome (es. "Italy")
                    Country = self.env['res.country'].sudo()
                    country_rec = Country.search([
                        '|',
                        ('code', '=ilike', rec.country.strip()),
                        ('name', '=ilike', rec.country.strip()),
                    ], limit=1)
                    if country_rec:
                        iso_code = country_rec.code

            if not iso_code:
                continue

            fname = f"{iso_code.lower()}.png"
            # path tipici delle bandiere core (variano per build)
            path = get_module_resource('base', 'static/img/country_flags', fname)
            if not path:
                path = get_module_resource('base', 'static/img/flags', fname)

            if path:
                try:
                    with open(path, 'rb') as f:
                        rec.country_flag_bin = base64.b64encode(f.read())
                except Exception:
                    rec.country_flag_bin = False

    region = fields.Char()
    municipality = fields.Char()
    farm_name = fields.Char()
    area_ha = fields.Char()
    geo_type_raw = fields.Char()
    geo_type = fields.Selection([("point","Point"),("polygon","Polygon")])
    geometry = fields.Text()  # GeoJSON string

    external_uid = fields.Char(index=True)
    external_status = fields.Selection([
        ('ok', 'OK'),
        ('pass', 'Pass'),
        ('fail', 'Fail'),
        ('error', 'Error'),
    ], readonly=True)
    external_message = fields.Char()
    external_properties_json = fields.Text()
    external_http_code = fields.Integer(readonly=True)
    external_message_short = fields.Char(readonly=True)
    external_ok = fields.Boolean(
        string="OK",
        readonly=True,
    )
    area_ha_float = fields.Float(string="Area (ha)", compute="_compute_area_ha_float", store=True)

    @api.onchange('area_ha_float')
    def _sync_area_char(self):
        for rec in self:
            if rec.area_ha_float and rec.area_ha_float > 0:
                rec.area_ha = f"{rec.area_ha_float:.4f}"
            else:
                rec.area_ha = "0.0000"

    @api.depends('geometry','farmer_id_code')
    def _compute_area_ha_float(self):
        geod = Geod(ellps="WGS84") if Geod else None

        for rec in self:
            rec.area_ha_float = 0.0
            if not rec.geometry:
                continue
            try:
                gobj = json.loads(rec.geometry)
            except Exception:
                continue
            if not shape:
                continue

            def _collect_polygons(payload):
                """Return a list of shapely Polygons from a GeoJSON payload."""
                if not isinstance(payload, dict):
                    return []
                gtype = payload.get("type")
                if gtype == "Feature":
                    return _collect_polygons(payload.get("geometry"))
                if gtype == "FeatureCollection":
                    polygons = []
                    for feature in payload.get("features") or []:
                        polygons.extend(_collect_polygons((feature or {}).get("geometry")))
                    return polygons
                try:
                    geom = shape(payload)
                except Exception:
                    return []
                if transform:
                    minx, miny, maxx, maxy = geom.bounds
                    if maxy > 90 or miny < -90 or maxx > 180 or minx < -180:
                        try:
                            swapped = transform(lambda x, y, z=None: (y, x), geom)
                        except Exception:
                            swapped = None
                        if swapped is not None and not swapped.is_empty:
                            s_minx, s_miny, s_maxx, s_maxy = swapped.bounds
                            if (
                                -180 <= s_minx <= 180
                                and -180 <= s_maxx <= 180
                                and -90 <= s_miny <= 90
                                and -90 <= s_maxy <= 90
                            ):
                                geom = swapped
                if geom.is_empty:
                    return []
                if geom.geom_type == "Polygon":
                    return [geom]
                if geom.geom_type == "MultiPolygon":
                    return list(geom.geoms)
                return []

            polygons = _collect_polygons(gobj)
            if not polygons:
                continue

            area_m2 = 0.0
            if geod:
                for poly in polygons:
                    try:
                        area, _ = geod.geometry_area_perimeter(poly)
                    except Exception:
                        continue
                    area_m2 += abs(area)
            elif Transformer and CRS and transform:
                for poly in polygons:
                    try:
                        lon, lat = poly.representative_point().coords[0]
                        zone = int((lon + 180) // 6) + 1
                        epsg = 32600 + zone if lat >= 0 else 32700 + zone
                        transformer = Transformer.from_crs("EPSG:4326", f"EPSG:{epsg}", always_xy=True)
                        projected = transform(transformer.transform, poly)
                    except Exception:
                        continue
                    area_m2 += abs(projected.area)

            if area_m2:
                rec.area_ha_float = area_m2 / 10000.0


    def action_visualize_area_on_map(self):
        """
        Questo metodo viene chiamato quando si preme il pulsante.
        Calcola un'area di 50mq attorno a un punto oppure visualizza un poligono
        esistente e lo apre in geojson.io.
        """
        self.ensure_one()

        if not self.geometry:
            raise UserError("Il campo 'Geometria' è vuoto. Inserisci le coordinate GeoJSON.")

        try:
            geo_data = json.loads(self.geometry)
        except json.JSONDecodeError:
            raise UserError("Il formato del GeoJSON nel campo 'Geometria' non è valido.")

        geom_type = geo_data.get('type')

        if geom_type == 'Point' and 'coordinates' in geo_data:
            lon, lat = geo_data['coordinates']

            # --- Calcolo Geospaziale ---
            # 1. Calcoliamo il raggio di un cerchio con area di 50 mq.
            #    Area = π * r^2  =>  r = sqrt(Area / π)
            area_mq = 50.0
            radius_in_meters = math.sqrt(area_mq / math.pi)

            # 2. Le coordinate GeoJSON sono in WGS84 (gradi). Per creare un buffer in metri,
            #    dobbiamo proiettare il punto in un sistema di coordinate che usi i metri,
            #    come UTM (Universal Transverse Mercator).

            # Definiamo il sistema di coordinate di partenza (WGS84)
            wgs84 = CRS("EPSG:4326")

            # Troviamo la zona UTM corretta per la longitudine del punto
            utm_zone = int((lon + 180) / 6) + 1
            utm_crs_str = f"EPSG:326{utm_zone}" if lat >= 0 else f"EPSG:327{utm_zone}"
            utm = CRS(utm_crs_str)

            # Creiamo i trasformatori per passare da WGS84 a UTM e viceversa
            transformer_to_utm = Transformer.from_crs(wgs84, utm, always_xy=True)
            transformer_to_wgs84 = Transformer.from_crs(utm, wgs84, always_xy=True)

            # 3. Trasformiamo il punto in coordinate UTM (metri)
            point_utm = transformer_to_utm.transform(lon, lat)

            # 4. Creiamo il buffer (l'area circolare) in metri
            shapely_point_utm = Point(point_utm)
            buffered_area_utm = shapely_point_utm.buffer(radius_in_meters)

            # 5. Riproiettiamo il poligono risultante di nuovo in WGS84 (gradi) per visualizzarlo
            buffered_area_wgs84 = transform(transformer_to_wgs84.transform, buffered_area_utm)

            # 6. Convertiamo il poligono di shapely in un dizionario GeoJSON
            final_geojson = mapping(buffered_area_wgs84)

        elif geom_type in ('Polygon', 'MultiPolygon'):
            final_geojson = geo_data
        else:
            raise UserError("Il formato del GeoJSON nel campo 'Geometria' non è valido. "
                            "Assicurati che sia un punto o un poligono valido")

        # --- Costruzione dell'URL ---
        # Codifichiamo il GeoJSON per inserirlo nell'URL
        encoded_geojson = urllib.parse.quote(json.dumps(final_geojson))

        # Costruiamo l'URL finale per geojson.io
        url = f"https://geojson.io/#data=data:application/json,{encoded_geojson}"

        # Restituiamo un'azione di Odoo per aprire l'URL in una nuova scheda
        return {
            'type': 'ir.actions.act_url',
            'url': url,
            'target': 'new',
        }

    def action_visualize_point_on_map(self):
        """
        Questo metodo viene chiamato quando si preme il pulsante.
        Visualizza il singolo punto GeoJSON su geojson.io.
        """
        self.ensure_one()

        if not self.geometry:
            raise UserError("Il campo 'Geometria' è vuoto. Inserisci le coordinate GeoJSON.")

        try:
            # Verifichiamo che il JSON sia valido e di tipo 'Point'
            geo_data = json.loads(self.geometry)
            if geo_data.get('type') != 'Point' or 'coordinates' not in geo_data:
                raise ValueError()
        except (json.JSONDecodeError, ValueError):
            raise UserError("Il formato del GeoJSON nel campo 'Geometria' non è valido. "
                            "Assicurati che sia un punto valido, ad es: "
                            '{"type": "Point", "coordinates": [9.19, 45.46]}')

        # --- Costruzione dell'URL ---
        # Codifichiamo il GeoJSON originale (contenuto nel campo geometry) per inserirlo nell'URL
        encoded_geojson = urllib.parse.quote(self.geometry)

        # Costruiamo l'URL finale per geojson.io
        url = f"https://geojson.io/#data=data:application/json,{encoded_geojson}"

        # Restituiamo un'azione di Odoo per aprire l'URL in una nuova scheda
        return {
            'type': 'ir.actions.act_url',
            'url': url,
            'target': 'new',
        }


class EUDRCommodityLine(models.Model):
    _name = "eudr.commodity.line"
    _description = "EUDR Commodity"

    declaration_id = fields.Many2one("eudr.declaration", ondelete="cascade", required=True)
    hs_heading = fields.Selection(EUDR_HS_SELECTION, string="HS heading", default="090111")
    description_of_goods = fields.Char(string="Description of goods")
    net_weight_kg = fields.Float(string="Net weight (kg)", digits=(16, 3))
    producer_ids = fields.One2many("eudr.producer", "commodity_id", string="Producers")


class EUDRProducer(models.Model):
    _name = "eudr.producer"
    _description = "EUDR Producer"

    commodity_id = fields.Many2one("eudr.commodity.line", ondelete="cascade", required=True)
    name = fields.Char(string="Name", required=True)
    country = fields.Char(string="Country (ISO2)")
    plot_ids = fields.One2many("eudr.plot", "producer_id", string="Plots")


class EUDRPlot(models.Model):
    _name = "eudr.plot"
    _description = "EUDR Plot"

    producer_id = fields.Many2one("eudr.producer", ondelete="cascade", required=True)
    plot_id = fields.Char(string="Plot ID")
    country_of_production = fields.Char(string="Country of production")
    geometry = fields.Text(string="Geometry (GeoJSON)")
    area_ha = fields.Float(string="Area (ha)")

    def action_open_geojson(self):
        self.ensure_one()
        if not self.geometry:
            raise UserError(_('GeoJSON geometry missing on plot.'))
        try:
            geo_data = json.loads(self.geometry)
        except json.JSONDecodeError:
            raise UserError(_('Invalid GeoJSON payload on plot.'))
        encoded_geojson = urllib.parse.quote(json.dumps(geo_data))
        url = f"https://geojson.io/#data=data:application/json,{encoded_geojson}"
        return {
            'type': 'ir.actions.act_url',
            'name': _('Plot geometry'),
            'target': 'new',
            'url': url,
        }


class EUDRAssociatedStatement(models.Model):
    _name = "eudr.associated.statement"
    _description = "EUDR Associated Statement"

    declaration_id = fields.Many2one("eudr.declaration", ondelete="cascade", required=True)
    upstream_reference_number = fields.Char(string="Upstream reference number")
    upstream_dds_identifier = fields.Char(string="Upstream DDS identifier")
    note = fields.Char(string="Note")

