from odoo import api, fields, models

class PlanetioSummarizeWizard(models.TransientModel):
    _name = 'planetio.summarize.wizard'
    _description = 'Riassunto documenti AI per Planetio'

    planetio_model = fields.Char(required=True)
    planetio_res_id = fields.Integer(required=True)
    attachment_ids = fields.Many2many('ir.attachment', string='Allegati da valutare')
    provider = fields.Selection([('gemini','Gemini')], default='gemini', required=True)
    output_post_to_chatter = fields.Boolean(default=True, string='Posta risultato in chatter')

    def action_run(self):
        self.ensure_one()
        req = self.env['ai.request'].create({
            'name': 'Planetio summarize',
            'provider': self.provider,
            'task_type': 'summarize',
            'model_ref': f"{self.planetio_model},{self.planetio_res_id}",
            'attachment_ids': [(6,0,self.attachment_ids.ids)],
            'status': 'draft',
        })
        req.run_now()
        if self.output_post_to_chatter and req.response_text:
            rec = self.env[self.planetio_model].browse(self.planetio_res_id)
            if rec and rec.exists() and hasattr(rec, 'message_post'):
                rec.message_post(
                    body=f"<p><b>AI Summary</b></p><pre>{(req.response_text or '')}</pre>",
                    message_type='comment',
                    subtype_xmlid='mail.mt_comment'
                )
        action = self.env.ref('ai_gateway.action_ai_request')
        return action.read()[0]
