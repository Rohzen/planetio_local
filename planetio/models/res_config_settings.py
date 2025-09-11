# -*- coding: utf-8 -*-
import logging
from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    gfw_auth_mode = fields.Selection(
        selection=[('api_key', 'API Key'), ('email_password', 'Email + Password')],
        string='GFW auth mode',
        default='api_key',
        config_parameter='planetio.gfw_auth_mode',
        help='Scegli se usare una API key statica oppure ottenere un token via email e password.'
    )
    gfw_api_key = fields.Char(string='GFW API key', config_parameter='planetio.gfw_api_key')
    gfw_email = fields.Char(string='GFW email', config_parameter='planetio.gfw_email')
    gfw_password = fields.Char(string='GFW password', config_parameter='planetio.gfw_password')
    gfw_auth_url = fields.Char(string='GFW auth URL', config_parameter='planetio.gfw_auth_url')
    gfw_auth_method = fields.Selection(
        selection=[('POST', 'POST'), ('GET', 'GET')],
        string='Auth HTTP method',
        default='POST',
        config_parameter='planetio.gfw_auth_method'
    )
    gfw_auth_header = fields.Selection(
        selection=[('x-api-key', 'x-api-key: <token>'),
                   ('authorization_bearer', 'Authorization: Bearer <token>')],
        string='Header da usare',
        default='x-api-key',
        config_parameter='planetio.gfw_auth_header'
    )
    gfw_token_field = fields.Char(string='JSON token field', config_parameter='planetio.gfw_token_field')
    gfw_expires_at_field = fields.Char(string='JSON expires_at field', config_parameter='planetio.gfw_expires_at_field')
    gfw_expires_in_field = fields.Char(string='JSON expires_in field', config_parameter='planetio.gfw_expires_in_field')
    gfw_key_expires_at = fields.Char(
        string='GFW key expires at (ISO8601)',
        config_parameter='planetio.gfw_key_expires_at',
        help='Timestamp ISO8601 della scadenza token (es. 2025-09-11T10:15:00+00:00).'
    )
    gfw_base_url = fields.Char(string='GFW base URL', config_parameter='planetio.gfw_base_url')
    gfw_ping_url = fields.Char(string='GFW ping URL', config_parameter='planetio.gfw_ping_url')

    def action_test_gfw_connection(self):
        ICP = self.env['ir.config_parameter'].sudo()
        from ..services.api.gfw_client import GFWClient
        client = GFWClient(self.env)
        token = client.ensure_api_key()
        if not token:
            raise UserError(_('Autenticazione GFW fallita: token vuoto.'))
        base = ICP.get_param('planetio.gfw_base_url') or 'https://api.globalforestwatch.org'
        url = (ICP.get_param('planetio.gfw_ping_url') or (base.rstrip('/') + '/v1/glad-alerts'))
        resp = client.request('GET', url, timeout=20)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'GFW',
                'message': 'Connessione riuscita (HTTP %s).' % getattr(resp, 'status_code', 'N/A'),
                'type': 'success',
                'sticky': False,
            }
        }
