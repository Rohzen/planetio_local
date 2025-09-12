from odoo import api, fields, models

class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    ai_default_provider = fields.Selection([
        ('gemini', 'Gemini'),
    ], string='Provider AI predefinito',
       default='gemini',
       config_parameter='ai_gateway.default_provider',
       help='Provider AI di default')

    ai_gemini_api_key = fields.Char(
        string='Gemini API Key',
        help='Chiave API per Google Generative AI',
        config_parameter='ai_gateway.gemini_api_key'
    )

    ai_gemini_model = fields.Char(
        string='Gemini Model name',
        help='es. gemini-1.5-flash o gemini-1.5-pro',
        default='gemini-1.5-flash',
        config_parameter='ai_gateway.gemini_model'
    )

    ai_max_chunk_chars = fields.Integer(
        string='Max chars per chunk',
        default=20000,
        config_parameter='ai_gateway.max_chunk_chars'
    )
