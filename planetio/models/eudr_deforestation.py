# -*- coding: utf-8 -*-
from odoo import models, fields, api
from odoo.exceptions import UserError
import json

class EUDRDeclarationLineDeforestation(models.Model):
    _inherit = "eudr.declaration.line"

    defor_provider = fields.Char(string="Deforestation Provider", readonly=True)
    defor_alerts = fields.Integer(string="Deforestation Alerts", readonly=True)
    defor_area_ha = fields.Float(string="Deforestation Area (ha)", readonly=True)
    defor_details_json = fields.Text(string="Deforestation Details (JSON)", readonly=True)

    def action_analyze_deforestation(self):
        """Analyze deforestation for this line's AOI (geometry GeoJSON)."""
        for rec in self:
            if not rec.geometry:
                raise UserError("Nessuna geometria disponibile (campo 'geometry' vuoto)." )
            try:
                geojson = json.loads(rec.geometry) if isinstance(rec.geometry, str) else rec.geometry
            except Exception:
                raise UserError("Il campo 'geometry' non contiene un GeoJSON valido.")
            svc = self.env['planetio.deforestation.service']
            status = svc.analyze_geojson(geojson)
            metrics = status.get('metrics', {})
            rec.write({
                'defor_provider': (status.get('meta') or {}).get('provider'),
                'defor_alerts': int(metrics.get('alert_count') or 0),
                'defor_area_ha': float(metrics.get('area_ha_total') or 0.0),
                'defor_details_json': json.dumps(status, ensure_ascii=False),
            })
        return True

class EUDRDeclarationDeforestation(models.Model):
    _inherit = "eudr.declaration"

    def action_analyze_deforestation(self):
        """Bulk analyze all lines in the declaration."""
        for decl in self:
            lines = decl.mapped('line_ids') if hasattr(decl, 'line_ids') else self.env['eudr.declaration.line'].search([('declaration_id','=',decl.id)])
            for line in lines:
                try:
                    line.action_analyze_deforestation()
                except Exception as e:
                    # swallow per-line errors but collect message to chatter
                    # decl.message_post(body=f"Deforestation analysis failed on line {line.display_name or line.id}: {e}")
                    raise UserError("Deforestation analysis failed on line {line.display_name or line.id}: {e}")
        return True
