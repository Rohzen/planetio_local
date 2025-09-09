
from odoo import models, fields, api
import json

class EUDRDeclaration(models.Model):
    _name = "eudr.declaration"
    _description = "EUDR Declaration"

    # campi esistenti (lasciati per retrocompatibilità)
    name = fields.Char(required=True)
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
