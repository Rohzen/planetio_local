# -*- coding: utf-8 -*-
from odoo import models, fields

class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    osapiens_base_url = fields.Char(string="oSapiens Base URL", config_parameter='osapiens.base_url')
    osapiens_account_id = fields.Char(string="oSapiens Account ID", config_parameter='osapiens.account_id')
    osapiens_api_token = fields.Char(string="oSapiens API Token", config_parameter='osapiens.api_token')
    osapiens_timeout = fields.Integer(string="oSapiens Timeout (s)", default=60, config_parameter='osapiens.timeout')
    osapiens_verify_ssl = fields.Boolean(string="oSapiens Verify SSL", default=True, config_parameter='osapiens.verify_ssl')