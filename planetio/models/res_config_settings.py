from odoo import fields, models, _
from odoo.exceptions import UserError

class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    debug_import = fields.Boolean(string="Debug Excel Import",
                                  config_parameter='planetio.debug_import',
                                  default=True)

    gfw_email = fields.Char(string="GFW Email", config_parameter='planetio.gfw_email')
    gfw_password = fields.Char(string="GFW Password", config_parameter='planetio.gfw_password')
    gfw_org = fields.Char(string="GFW Organization", config_parameter='planetio.gfw_org', default='Planetio')
    gfw_alias = fields.Char(string="GFW API Alias", config_parameter='planetio.gfw_alias', default='planetio-dev')
    gfw_api_key = fields.Char(string="GFW API Key", config_parameter='planetio.gfw_api_key', readonly=False)

    eudr_endpoint = fields.Char(string="EUDR Endpoint", config_parameter='planetio.eudr_endpoint', readonly=False, placeholder="https://acceptance.eudr.webcloud.ec.europa.eu/tracesnt/ws/EUDRSubmissionServiceV1")
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

        from ..services.gfw_client import get_access_token, create_or_get_api_key

        token = get_access_token(email, password)
        api_key = create_or_get_api_key(
            token, alias=alias, email=email, organization=org, domains=allowed_domains
        )
        icp.set_param('planetio.gfw_api_key', api_key)
        self.gfw_api_key = api_key
