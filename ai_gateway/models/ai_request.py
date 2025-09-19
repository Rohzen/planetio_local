from odoo import api, fields, models
import json
import time

class AiRequest(models.Model):
    _name = 'ai.request'
    _description = 'AI Request'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    def _default_provider(self):
        return (
            self.env['ir.config_parameter']
            .sudo()
            .get_param('ai_gateway.default_provider', 'gemini')
        )

    name = fields.Char(required=True, default=lambda self: 'AI Request')
    provider = fields.Selection([
        ('gemini', 'Gemini'),
        ('claude', 'Claude'),
    ], default=_default_provider, required=True, tracking=True)

    task_type = fields.Selection([
        ('chat', 'Chat/Generate'),
        ('summarize', 'Summarize'),
        ('classify', 'Classify'),
        ('embed', 'Embed'),
    ], default='chat', required=True, tracking=True)

    model_ref = fields.Char(help='model,res_id per collegare la richiesta a un record')
    payload = fields.Text(help='Prompt o JSON con istruzioni')
    status = fields.Selection([
        ('draft', 'Draft'),
        ('running', 'Running'),
        ('done', 'Done'),
        ('error', 'Error'),
        ('queued', 'Queued'),
    ], default='draft', tracking=True)

    tokens_in = fields.Integer()
    tokens_out = fields.Integer()
    duration_ms = fields.Integer()
    cost_estimate = fields.Float(help='Stima costi se disponibile')
    error_message = fields.Text()

    response_text = fields.Text(help='Risposta principale')
    meta = fields.Text(help='Metadata provider grezzi in JSON')

    attachment_ids = fields.Many2many('ir.attachment', string='Allegati')

    def run_now(self):
        start = time.time()
        for rec in self:
            rec.write({'status': 'running'})
            try:
                svc = self.env['ai.gateway.service']
                result = svc.run_request(rec)
                rec.write({
                    'response_text': result.get('text'),
                    'meta': json.dumps(result.get('meta', {})),
                    'tokens_in': result.get('tokens_in') or 0,
                    'tokens_out': result.get('tokens_out') or 0,
                    'status': 'done',
                    'duration_ms': int((time.time() - start) * 1000),
                    'cost_estimate': result.get('cost'),
                })
                self.env['ir.logging'].create({
                    'name': 'ai_gateway',
                    'type': 'server',
                    'level': 'INFO',
                    'message': 'AI request completed',
                    'path': 'ai.request',
                    'line': '0',
                    'func': 'run_now',
                })
            except Exception as e:
                rec.write({'status': 'error', 'error_message': str(e)})
                self.env['ir.logging'].create({
                    'name': 'ai_gateway',
                    'type': 'server',
                    'level': 'ERROR',
                    'message': 'AI request error: %s' % e,
                    'path': 'ai.request',
                    'line': '0',
                    'func': 'run_now',
                })
