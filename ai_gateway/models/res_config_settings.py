from odoo import api, fields, models

class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    ai_default_provider = fields.Selection([
        ('gemini', 'Gemini'),
        ('claude', 'Claude'),
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

    ai_claude_api_key = fields.Char(
        string='Claude API Key',
        help='Chiave API per Anthropic Claude',
        config_parameter='ai_gateway.claude_api_key'
    )

    ai_claude_model = fields.Char(
        string='Claude Model name',
        help='es. claude-3-sonnet-20240229',
        default='claude-3-sonnet-20240229',
        config_parameter='ai_gateway.claude_model'
    )

    ai_claude_max_output_tokens = fields.Integer(
        string='Claude max output tokens',
        default=1024,
        help='Numero massimo di token generati dal modello Claude',
        config_parameter='ai_gateway.claude_max_output_tokens'
    )

    ai_max_chunk_chars = fields.Integer(
        string='Max chars per chunk',
        default=20000,
        config_parameter='ai_gateway.max_chunk_chars'
    )
