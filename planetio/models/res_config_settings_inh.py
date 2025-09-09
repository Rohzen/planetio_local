from odoo import models, fields, api

class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    pftp_api_key = fields.Char(string="API Key Plant for the Planet", config_parameter='planetio.pftp_api_key')

    eudr_tracer_user = fields.Char(string="User TRACES EUDR", config_parameter='planetio.eudr_tracer_user')
    eudr_tracer_authentication_key = fields.Char(string="Authentication key TRACES EUDR", config_parameter='planetio.eudr_tracer_authentication_key')
    eudr_tracer_endpoint_url = fields.Char(string="Endpoint URL TRACES EUDR", config_parameter='planetio.eudr_tracer_endpoint_url')
    eudr_tracer_dds_submission_wsdl = fields.Char(string="DDS submission WSDL Method TRACES EUDR", config_parameter='planetio.eudr_tracer_dds_submission_wsdl')
    eudr_tracer_webservice_access_identifier = fields.Char(string="DDS submission Web Service access TRACES EUDR", config_parameter='planetio.eudr_tracer_webservice_access_identifier')
    eudr_company_type = fields.Selection(
        selection=[
            ('trader', 'Trader'),
            ('operator', 'Operator'),
            ('mixed', 'Mixed'),
            ('third_party_trader', 'Trader on behalf of client')
        ],
        string="EUDR Company Type",
        config_parameter='planetio.eudr_company_type'
    )