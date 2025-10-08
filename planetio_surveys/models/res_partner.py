from odoo import models, fields, api, _

class ResPartner(models.Model):
    _inherit = 'res.partner'

    last_survey_input_id = fields.Many2one('survey.user_input', compute='_compute_last_survey', store=False)
    last_survey_valid_until = fields.Date(compute='_compute_last_survey', store=False)
    last_survey_valid = fields.Boolean(compute='_compute_last_survey', store=False)

    def _compute_last_survey(self):
        Survey = self.env['survey.survey']
        ICP = self.env['ir.config_parameter'].sudo()
        sid = int(ICP.get_param('planetio.survey_id', '0') or 0)
        survey = Survey.browse(sid) if sid else Survey
        today = fields.Date.context_today(self)
        for p in self:
            p.last_survey_input_id = False
            p.last_survey_valid_until = False
            p.last_survey_valid = False
            if not survey:
                continue
            ui = self.env['survey.user_input'].sudo().search([
                ('partner_id', '=', p.id),
                ('survey_id', '=', survey.id),
                ('state', '=', 'done'),
            ], order="end_datetime desc, write_date desc, id desc", limit=1)
            if not ui:
                continue
            anchor = (ui.end_datetime or ui.create_date).date()
            vu = fields.Date.add(anchor, years=1, days=-1)
            p.last_survey_input_id = ui.id
            p.last_survey_valid_until = vu
            p.last_survey_valid = vu >= today

    def action_open_partner_surveys(self):
        self.ensure_one()
        return {
            'name': _("Survey compilations"),
            'type': 'ir.actions.act_window',
            'res_model': 'survey.user_input',
            'view_mode': 'tree,form',
            'domain': [('partner_id', '=', self.id)],
            'context': {},
        }
