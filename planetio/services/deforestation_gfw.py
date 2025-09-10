from odoo import models, _
from odoo.exceptions import UserError
import requests

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
        try:
            payload = {"farmer_id": line.farmer_code, "geometry": line.geojson}
            r = requests.post("https://gfw.example/api/analyze", json=payload,
                              headers={"Authorization": f"Bearer {token}"}, timeout=60)
        except requests.exceptions.RequestException as ex:
            raise UserError(_("Connessione a GFW non riuscita: %s") % str(ex))

        if r.status_code == 401:
            raise UserError(_("Token GFW non valido o scaduto."))
        if r.status_code >= 500:
            raise UserError(_("GFW ha risposto con errore temporaneo (%s).") % r.status_code)
        if r.status_code >= 400:
            detail = (r.json().get('detail') if r.headers.get('Content-Type','').startswith('application/json') else r.text)
            raise UserError(_("Richiesta rifiutata da GFW: %s") % detail)

        data = r.json()
        message = data.get('summary') or (_("Possibile rischio di deforestazione") if data.get('flag') else _("Nessun segnale di deforestazione"))
        return {'message': message, 'flag': data.get('flag'), 'score': data.get('score'), 'raw': data}
