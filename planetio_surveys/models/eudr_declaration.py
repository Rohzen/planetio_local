from odoo import fields, models, api, _
from dateutil.relativedelta import relativedelta
from odoo.exceptions import UserError

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

    questionnaire_input_id = fields.Many2one('survey.user_input', string="Questionnaire (Survey Response)", readonly=True, copy=False)
    questionnaire_valid = fields.Boolean(compute="_compute_questionnaire_status", store=False)
    questionnaire_valid_until = fields.Date(compute="_compute_questionnaire_status", store=False)
    questionnaire_alert_message = fields.Char(compute="_compute_questionnaire_status", store=False)

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
    
    def _get_planetio_survey(self):
        ICP = self.env['ir.config_parameter'].sudo()
        sid = int(ICP.get_param('planetio.survey_id', '0') or 0)
        return self.env['survey.survey'].browse(sid) if sid else self.env['survey.survey']

    def _find_latest_completed_input(self, partner, survey):
        if not partner or not survey:
            return self.env['survey.user_input']
        return self.env['survey.user_input'].sudo().search([
            ('partner_id', '=', partner.id),
            ('survey_id', '=', survey.id),
            ('state', '=', 'done'),
        ], order="write_date desc, id desc", limit=1)

    @api.depends('supplier_id')
    def _compute_questionnaire_status(self):
        today = fields.Date.context_today(self)
        for r in self:
            r.questionnaire_input_id = False
            r.questionnaire_valid = False
            r.questionnaire_valid_until = False
            r.questionnaire_alert_message = False

            if not r.supplier_id:
                continue

            survey = r._get_planetio_survey()
            if not survey:
                r.questionnaire_alert_message = _("Configura il questionario in Impostazioni Planetio.")
                continue

            ui = r._find_latest_completed_input(r.supplier_id, survey)
            if not ui:
                r.questionnaire_alert_message = _("Nessun questionario completato per questo Producer/Supplier.")
                continue

            anchor_dt = ui.write_date or ui.create_date  # Odoo datetime
            anchor = anchor_dt.date()
            valid_until = fields.Date.add(anchor, years=1, days=-1)

            r.questionnaire_input_id = ui.id
            r.questionnaire_valid_until = valid_until
            r.questionnaire_valid = valid_until >= today
            if not r.questionnaire_valid:
                r.questionnaire_alert_message = _("Questionario scaduto il %s.") % valid_until

    @api.onchange('supplier_id')
    def _onchange_supplier_id_survey_notice(self):
        for r in self:
            if r.supplier_id and not r.questionnaire_valid and r.questionnaire_alert_message:
                return {
                    'warning': {'title': _("Questionario"), 'message': r.questionnaire_alert_message}
                }

    # Azione: apri o crea nuova risposta survey per questo partner
    def action_open_or_create_questionnaire(self):
        self.ensure_one()
        if not self.supplier_id:
            raise UserError(_("Seleziona prima un Producer/Supplier."))
        survey = self._get_planetio_survey()
        if not survey:
            raise UserError(_("Configura il questionario in Impostazioni Planetio."))

        if self.questionnaire_input_id and self.questionnaire_valid:
            return self._open_user_input(self.questionnaire_input_id)

        ui = self.env['survey.user_input'].sudo().create({
            'survey_id': survey.id,
            'partner_id': self.supplier_id.id,
            'email': self.supplier_id.email or False,
            'state': 'new',
            'deadline': fields.Datetime.now() + relativedelta(months=1),
        })
        self.write({'questionnaire_input_id': ui.id})
        return self._open_user_input(ui)
    
    def _open_user_input(self, ui):
        self.ensure_one()
        ui = ui.sudo()

        # 1) Se esiste un helper ufficiale, usalo
        if hasattr(ui, 'get_start_url') and callable(ui.get_start_url):
            start_url = ui.get_start_url()
            return {'type': 'ir.actions.act_url', 'url': start_url, 'target': 'new'}

        # 2) Fallback manuale: token + URL pubblico
        token = getattr(ui, 'access_token', False) or getattr(ui, 'token', False)
        if not token and hasattr(ui, '_get_access_token'):
            token = ui._get_access_token()

        if token:
            start_url = '/survey/start/%s?token=%s' % (ui.survey_id.id, token)
            return {'type': 'ir.actions.act_url', 'url': start_url, 'target': 'new'}

        # 3) Ultimo fallback: apri la form backend del user_input
        return {
            'type': 'ir.actions.act_window',
            'name': _('Survey Response'),
            'res_model': 'survey.user_input',
            'view_mode': 'form',
            'res_id': ui.id,
            'target': 'current',
        }

    # (opzionale) blocco invio DDS se vuoi obbligare questionario valido
    def action_transmit_dds(self):
        for rec in self:
            if not rec.questionnaire_valid:
                raise UserError(_("Questionario Producer/Supplier mancante o scaduto, risolvi prima di trasmettere la DDS."))
        return super().action_transmit_dds()

