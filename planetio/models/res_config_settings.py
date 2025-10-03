from odoo import fields, models, api, _
from odoo.exceptions import UserError

class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    debug_import = fields.Boolean(string="Debug Excel Import", config_parameter='planetio.debug_import')
    eudr_company_type = fields.Selection(related="company_id.eudr_company_type", readonly=False)
    eudr_is_sme = fields.Boolean(related="company_id.eudr_is_sme", readonly=False)
    eudr_third_party_has_mandate = fields.Boolean(related="company_id.eudr_third_party_has_mandate", readonly=False)
    eudr_third_party_established_in_eu = fields.Boolean(related="company_id.eudr_third_party_established_in_eu", readonly=False)

    gfw_email = fields.Char(string="GFW Email", config_parameter='planetio.gfw_email')
    gfw_password = fields.Char(string="GFW Password", config_parameter='planetio.gfw_password')
    gfw_org = fields.Char(string="GFW Organization", config_parameter='planetio.gfw_org', default='Planetio')
    gfw_alias = fields.Char(string="GFW API Alias", config_parameter='planetio.gfw_alias', default='planetio-dev')
    gfw_api_key = fields.Char(string="GFW API Key", config_parameter='planetio.gfw_api_key', readonly=False)
    gfw_alert_years = fields.Selection(
        selection=[(str(i), _("%s year(s)") % i) for i in range(1, 6)],
        string="GFW Alert Lookback",
        config_parameter='planetio.gfw_alert_years',
        default='1',
        help="Number of years back to include when fetching alerts from GFW (1-5 years).",
    )
    gfw_min_area_ha = fields.Float(
        string="GFW - Area minima (ha)",
        default=4.0,
        help="Area minima da rispettare per la normativa. Default 4 ha."
    )
    gfw_area_policy = fields.Selection(
        selection=[('buffer', 'Buffer automatico (< soglia → espandi)'),
                   ('strict', 'Strict (< soglia → rifiuta)')],
        string="GFW - Politica area minima",
        default='buffer',
        help="Se 'buffer': le geometrie sotto soglia vengono espanse.\n"
             "Se 'strict': le geometrie sotto soglia vengono rifiutate."
    )

    deforestation_provider = fields.Selection(
        selection=[
            ('gfw', 'Global Forest Watch'),
            ('plant4', 'Plant-for-the-Planet Farm Analysis'),
        ],
        string="Deforestation Provider",
        config_parameter='planetio.deforestation_provider',
        default='gfw',
        help="Select the service used to run deforestation analysis on EUDR declarations.",
    )

    plant4_api_key = fields.Char(
        string="Plant-for-the-Planet API Key",
        config_parameter='deforestation.plant4.api_key',
        readonly=False,
    )
    plant4_base_url = fields.Char(
        string="Plant-for-the-Planet Base URL",
        config_parameter='deforestation.plant4.base_url',
        readonly=False,
        default='https://farm.tracer.eco',
    )

    eudr_endpoint = fields.Char(string="EUDR Endpoint", config_parameter='planetio.eudr_endpoint', readonly=False,
                                placeholder="https://acceptance.eudr.webcloud.ec.europa.eu/tracesnt/ws/EUDRSubmissionServiceV1",
                                default = "https://acceptance.eudr.webcloud.ec.europa.eu/tracesnt/ws/EUDRSubmissionServiceV1"
                                )
    eudr_user = fields.Char(string="EUDR User", config_parameter='planetio.eudr_user', readonly=False)
    eudr_apikey = fields.Char(string="api-key", config_parameter='planetio.eudr_apikey', readonly=False)
    eudr_wsse_mode = fields.Char(string="WSSE mode", config_parameter='planetio.eudr_wsse_mode', readonly=False, default="digest")
    eudr_webservice_client_id = fields.Char(string="Client ID", config_parameter='planetio.eudr_webservice_client_id', readonly=False, default="eudr-test")

    def action_generate_gfw_api_key(self):
        self.ensure_one()
        icp = self.env['ir.config_parameter'].sudo()
        email = icp.get_param('planetio.gfw_email') or ''
        password = icp.get_param('planetio.gfw_password') or ''
        alias = icp.get_param('planetio.gfw_alias') or 'planetio-dev'
        org = icp.get_param('planetio.gfw_org') or 'Planetio'

        if not email or not password:
            raise UserError(_("Imposta email e password GFW prima di generare la chiave."))

        base_url = icp.get_param('web.base.url') or ''
        from urllib.parse import urlparse
        parsed = urlparse(base_url) if base_url else None
        domain = (parsed.netloc or '').split(':')[0] if parsed else ''
        allowed_domains = [domain] if domain else ['localhost']

        from ..services.api.gfw_client import get_access_token, create_or_get_api_key

        token = get_access_token(email, password)
        api_key = create_or_get_api_key(
            token, alias=alias, email=email, organization=org, domains=allowed_domains
        )
        icp.set_param('planetio.gfw_api_key', api_key)
        self.gfw_api_key = api_key

    @api.model
    def get_values(self):
        res = super().get_values()
        icp = self.env['ir.config_parameter'].sudo()

        min_area_ha = icp.get_param('planetio.gfw_min_area_ha', default='4.0')
        policy = icp.get_param('planetio.gfw_area_policy', default='buffer')

        try:
            min_area_ha_val = float(min_area_ha)
        except Exception:
            min_area_ha_val = 4.0

        if policy not in ('buffer', 'strict'):
            policy = 'buffer'

        res.update(
            gfw_min_area_ha=min_area_ha_val,
            gfw_area_policy=policy,
        )
        return res

    def set_values(self):
        super().set_values()
        icp = self.env['ir.config_parameter'].sudo()

        # salva area minima
        min_area = self.gfw_min_area_ha if self.gfw_min_area_ha and self.gfw_min_area_ha > 0 else 4.0
        icp.set_param('planetio.gfw_min_area_ha', str(min_area))

        # salva policy
        policy = self.gfw_area_policy or 'buffer'
        if policy not in ('buffer', 'strict'):
            policy = 'buffer'
        icp.set_param('planetio.gfw_area_policy', policy)