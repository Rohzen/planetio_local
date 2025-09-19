from odoo import fields, models


class EudrDeclaration(models.Model):
    _inherit = 'eudr.declaration'

    survey_user_input_ids = fields.One2many(
        'survey.user_input',
        'declaration_id',
        string='Questionnaires',
    )
    survey_user_input_count = fields.Integer(
        string='Questionnaires',
        compute='_compute_survey_user_input_count',
    )

    def _compute_survey_user_input_count(self):
        if not self:
            return
        data = self.env['survey.user_input'].read_group(
            [('declaration_id', 'in', self.ids)],
            ['declaration_id'],
            ['declaration_id'],
        )
        counts = {item['declaration_id'][0]: item['declaration_id_count'] for item in data}
        for declaration in self:
            declaration.survey_user_input_count = counts.get(declaration.id, 0)

    def action_view_survey_user_inputs(self):
        self.ensure_one()
        action = self.env.ref('planetio_surveys.action_eudr_declaration_survey_user_input').read()[0]
        action['domain'] = [('declaration_id', '=', self.id)]
        action['context'] = dict(self.env.context, default_declaration_id=self.id)
        return action
