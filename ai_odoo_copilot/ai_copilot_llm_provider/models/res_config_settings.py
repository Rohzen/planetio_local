from odoo import api, fields, models

PARAM_URL = "ai_copilot.provider_url"
PARAM_KEY = "ai_copilot.api_key"
PARAM_MODEL = "ai_copilot.model"
PARAM_TEMPERATURE = "ai_copilot.temperature"
PARAM_TIMEOUT = "ai_copilot.timeout"

class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    ai_provider_url = fields.Char(string="LLM Endpoint URL")
    ai_api_key = fields.Char(string="LLM API Key", help="Conservata in Parametri di Sistema")
    ai_model = fields.Char(string="Model hint", help="es. gpt-4o, llama3.1, ecc.")
    ai_temperature = fields.Float(string="Temperature", default=0.0)
    ai_timeout = fields.Integer(string="Timeout (s)", default=20)

    def set_values(self):
        super().set_values()
        ICP = self.env['ir.config_parameter'].sudo()
        ICP.set_param(PARAM_URL, self.ai_provider_url or '')
        ICP.set_param(PARAM_KEY, self.ai_api_key or '')
        ICP.set_param(PARAM_MODEL, self.ai_model or '')
        ICP.set_param(PARAM_TEMPERATURE, str(self.ai_temperature or 0.0))
        ICP.set_param(PARAM_TIMEOUT, str(self.ai_timeout or 20))

    @api.model
    def get_values(self):
        res = super().get_values()
        ICP = self.env['ir.config_parameter'].sudo()
        res.update(
            ai_provider_url=ICP.get_param(PARAM_URL, default=''),
            ai_api_key=ICP.get_param(PARAM_KEY, default=''),
            ai_model=ICP.get_param(PARAM_MODEL, default=''),
            ai_temperature=float(ICP.get_param(PARAM_TEMPERATURE, default='0') or 0.0),
            ai_timeout=int(ICP.get_param(PARAM_TIMEOUT, default='20') or 20),
        )
        return res
