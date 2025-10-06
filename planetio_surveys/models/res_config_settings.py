from odoo import fields, models, api, _
from odoo.exceptions import UserError

class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    planetio_survey_id = fields.Many2one(
        'survey.survey',
        string='Planetio Questionnaire (Survey)',
        config_parameter='planetio.survey_id'
    )