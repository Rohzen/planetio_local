
from odoo import models, fields, api
from odoo.exceptions import UserError, ValidationError
import json

class EUDRDeclaration(models.Model):
    _name = "eudr.declaration"
    _description = "EUDR Declaration"

    datestamp = fields.Datetime(string="Datestamp", default=lambda self: fields.Datetime.now())
    name = fields.Char() #required=True
    farmer_name = fields.Char()
    farmer_id_code = fields.Char()
    tax_code = fields.Char()
    country = fields.Char()
    region = fields.Char()
    municipality = fields.Char()
    farm_name = fields.Char()
    area_ha = fields.Float()
    geo_type = fields.Selection([("point","Point"),("polygon","Polygon")])
    geometry = fields.Text()  # GeoJSON string
    source_attachment_id = fields.Many2one("ir.attachment")

    # nuovo: righe figlie
    line_ids = fields.One2many("eudr.declaration.line", "declaration_id", string="Lines")

    def action_analyze_external(self):
        self.ensure_one()
        Job = self.env["excel.import.job"].sudo()
        job = Job.search([("declaration_id", "=", self.id)], order="id desc", limit=1)
        if not job:
            raise UserError(_("No import job found for this declaration. Please run the Excel Import Wizard first."))
        self.env["planetio.tracer.api"].analyze_job_and_update(job)
        return {"type": "ir.actions.act_window", "res_model": "eudr.declaration", "view_mode": "form", "res_id": self.id, "target": "current"}

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
        from ...services.eudr_adapter_odoo import submit_dds_for_batch
        for record in self:
            if record.status_planetio != 'completed':
                raise UserError(_("Puoi trasmettere la DDS solo se il questionario è completato."))
            dds_id = submit_dds_for_batch(record)

class EUDRDeclarationLine(models.Model):
    _name = "eudr.declaration.line"
    _description = "EUDR Declaration Line"

    declaration_id = fields.Many2one("eudr.declaration", ondelete="cascade", required=True)
    name = fields.Char()
    farmer_name = fields.Char()
    farmer_id_code = fields.Char()
    tax_code = fields.Char()
    country = fields.Char()
    region = fields.Char()
    municipality = fields.Char()
    farm_name = fields.Char()
    area_ha = fields.Float()
    geo_type = fields.Selection([("point","Point"),("polygon","Polygon")])
    geometry = fields.Text()  # GeoJSON string

    external_uid = fields.Char(index=True)
    external_status = fields.Selection(
        selection=[("pass", "Pass"), ("ok", "OK"), ("fail", "Fail"), ("error", "Error")],
        index=True,
    )
    external_message = fields.Char()
    external_properties_json = fields.Text()