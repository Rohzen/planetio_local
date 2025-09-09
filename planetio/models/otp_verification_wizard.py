from odoo import models, fields, api, _
from odoo.exceptions import UserError

class OTPVerificationWizard(models.TransientModel):
    _name = 'otp.verification.wizard'
    _description = 'OTP Verification Wizard'

    otp_code = fields.Char(string="OTP Code", required=True)
    batch_id = fields.Many2one('caffe.crudo.todo.batch', string="Coffee Batch")

    def confirm_otp(self):
        self.ensure_one()
        batch = self.batch_id

        # Simula validazione
        batch.message_post(body=_("OTP correct."))

        # Prosegue col flusso esistente
        batch.action_transmit_dds()

        return {'type': 'ir.actions.act_window_close'}
