import json

from odoo import fields, models, _, tools
from odoo.exceptions import UserError


class DeforestationGeometryWizard(models.TransientModel):
    _name = 'deforestation.geometry.wizard'
    _description = 'Deforestation Geometry Check Wizard'

    provider_code = fields.Selection(
        selection=[
            ('gfw', 'Global Forest Watch'),
            ('plant4', 'Plant-for-the-Planet Farm Analysis'),
        ],
        string="Deforestation Provider",
        required=True,
        default=lambda self: self._default_provider_code(),
        help="Seleziona il servizio per l'analisi della geometria.",
    )
    geojson_input = fields.Text(
        string="GeoJSON Geometry",
        required=True,
        help="Inserisci una geometria GeoJSON (Point o Polygon).",
    )
    result_json = fields.Text(
        string="Result JSON",
        readonly=True,
        help="Risultato dell'analisi restituito dal provider selezionato.",
    )

    def _default_provider_code(self):
        icp = self.env['ir.config_parameter'].sudo()
        value = (icp.get_param('planetio.deforestation_provider') or 'gfw').strip()
        codes = {code for code, _label in self._fields['provider_code'].selection}
        return value if value in codes else 'gfw'

    # ------------------------------------------------------------------
    def _parse_geojson(self):
        self.ensure_one()
        raw = (self.geojson_input or '').strip()
        if not raw:
            raise UserError(_("Inserisci una geometria GeoJSON."))

        try:
            data = json.loads(raw)
        except Exception as exc:
            raise UserError(_("GeoJSON non valido: %s") % tools.ustr(exc))

        if not isinstance(data, dict):
            raise UserError(_("Il GeoJSON deve essere un oggetto."))

        geom = data
        data_type = data.get('type')
        if data_type == 'Feature':
            geom = data.get('geometry') or {}
        elif data_type == 'FeatureCollection':
            features = data.get('features') or []
            if not features:
                raise UserError(_("La FeatureCollection non contiene geometrie."))
            first = features[0]
            if not isinstance(first, dict):
                raise UserError(_("La FeatureCollection contiene elementi non validi."))
            geom = first.get('geometry') or {}

        if not isinstance(geom, dict):
            raise UserError(_("La geometria estratta non è un oggetto valido."))

        geom_type = geom.get('type')
        if geom_type not in ('Point', 'Polygon', 'MultiPolygon'):
            raise UserError(_("Tipo di geometria non supportato: %s") % geom_type)

        return geom

    # ------------------------------------------------------------------
    def action_analyze(self):
        self.ensure_one()
        geometry = self._parse_geojson()

        service = self.env['deforestation.service']
        result = service.analyze_geojson(geometry, providers=[self.provider_code], display_name=_('Wizard geometry'))

        try:
            pretty = json.dumps(result, ensure_ascii=False, indent=2)
        except Exception:
            pretty = tools.ustr(result)

        self.result_json = pretty

        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'view_mode': 'form',
            'res_id': self.id,
            'target': 'new',
        }
