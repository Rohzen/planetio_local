from odoo import fields, models


class SurveyUserInput(models.Model):
    _inherit = 'survey.user_input'

    declaration_id = fields.Many2one(
        'eudr.declaration',
        string='Declaration',
        index=True,
        ondelete='set null',
    )
