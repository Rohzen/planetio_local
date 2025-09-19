from odoo import models, _
from odoo.exceptions import UserError
import requests
import json

class DeforestationProviderGFW(models.AbstractModel):
    _name = 'deforestation.provider.gfw'
    _inherit = 'deforestation.provider.base'
    _description = 'Deforestation Provider - GFW'

    def _get_token(self):
        return self.env['ir.config_parameter'].sudo().get_param('deforestation.gfw.token')

    def check_prerequisites(self):
        if not self._get_token():
            raise UserError(_("Token API GFW mancante. Inseriscilo in Impostazioni > Deforestazione."))

    def analyze_line(self, line):
        token = self._get_token()

        # determine geometry from the line
        geom = None
        if hasattr(line, '_line_geometry'):
            try:
                geom = line._line_geometry()
            except Exception:
                geom = None
        if not geom:
            raw = getattr(line, 'geojson', None)
            if raw:
                try:
                    geom = json.loads(raw) if isinstance(raw, str) else raw
                except Exception:
                    geom = None
        if not geom or not isinstance(geom, dict):
            raise UserError(_("Geometria mancante sulla riga %s") % (getattr(line, 'display_name', line.id)))

        payload = {}
        if geom.get('type') == 'Point':
            coords = geom.get('coordinates') or []
            if len(coords) < 2:
                raise UserError(_("Geometria Point non valida sulla riga %s") % (getattr(line, 'display_name', line.id)))
            payload['lat'] = coords[1]
            payload['lon'] = coords[0]
        else:
            payload['geometry'] = geom

        headers = {
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json',
        }
        try:
            r = requests.post(
                "https://data-api.globalforestwatch.org/deforestation-alerts/check",
                json=payload,
                headers=headers,
                timeout=60,
            )
        except requests.exceptions.RequestException as ex:
            raise UserError(_("Connessione a GFW non riuscita: %s") % str(ex))

        if r.status_code == 401:
            raise UserError(_("Token GFW non valido o scaduto."))
        if r.status_code >= 500:
            raise UserError(_("GFW ha risposto con errore temporaneo (%s).") % r.status_code)
        if r.status_code >= 400:
            detail = None
            if r.headers.get('Content-Type', '').startswith('application/json'):
                try:
                    detail = r.json().get('detail')
                except Exception:
                    detail = None
            raise UserError(_("Richiesta rifiutata da GFW: %s") % (detail or r.text))

        try:
            data = r.json()
        except Exception:
            data = {}

        alerts = (data.get('data') or {}).get('alerts') or []
        summary = (data.get('data') or {}).get('summary') or {}
        alert_count = summary.get('alert_count') or len(alerts)
        area_ha = summary.get('area_ha') or summary.get('areaHa') or 0.0
        message = _("GFW: %(cnt)s allerta/e") % {'cnt': alert_count}

        return {
            'message': message,
            'alerts': alerts,
            'metrics': {'alert_count': alert_count, 'area_ha_total': area_ha},
            'meta': {'provider': 'gfw'},
        }
