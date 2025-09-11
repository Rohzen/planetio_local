from odoo import _
from odoo.exceptions import UserError
from .gfw_client import get_access_token, create_or_get_api_key, validate_api_key

def get_valid_gfw_api_key(env):
    icp = env['ir.config_parameter'].sudo()
    api_key = icp.get_param('planetio.gfw_api_key') or ''
    if api_key and validate_api_key(api_key):
        return api_key

    email = icp.get_param('planetio.gfw_email') or ''
    password = icp.get_param('planetio.gfw_password') or ''
    alias = icp.get_param('planetio.gfw_alias') or 'planetio-dev'
    org = icp.get_param('planetio.gfw_org') or 'Planetio'

    if not email or not password:
        raise UserError(_("Configura email e password GFW nei Parametri di sistema."))

    base_url = icp.get_param('web.base.url') or ''
    from urllib.parse import urlparse
    parsed = urlparse(base_url) if base_url else None
    domain = (parsed.netloc or '').split(':')[0] if parsed else ''
    allowed_domains = [domain] if domain else ['localhost']

    token = get_access_token(email, password)
    new_key = create_or_get_api_key(token, alias=alias, email=email, organization=org, domains=allowed_domains)
    icp.set_param('planetio.gfw_api_key', new_key)
    return new_key
