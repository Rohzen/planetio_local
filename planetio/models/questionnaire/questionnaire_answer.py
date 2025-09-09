from odoo import models, fields, api, _
from odoo.exceptions import UserError
import base64

class PlanetioQuestionnaireAnswer(models.Model):
    _name = "planetio.questionnaire.answer"
    _description = "Answers to the EUDR Questionnaire"

    # batch_id = fields.Many2one("caffe.crudo.todo.batch", string="Coffee batch", required=True, ondelete="cascade")
    batch_id = fields.Integer()  # fields.Many2one('caffe.crudo.todo.batch', required=True)
    question_id = fields.Many2one("planetio.question", string="Question", required=True, ondelete="cascade")
    answer = fields.Selection([("yes", "Yes"), ("no", "No")], string="Answer", required=True, default="no")
    additional_info = fields.Char(string="Additional information")  
    attachment = fields.Binary(string="Attached document", attachment=True)
    attachment_filename = fields.Char(string="File name", compute="_compute_attachment_filename", store=True)

    section = fields.Selection(related="question_id.section", store=True, index=True, search=True)

    @api.depends('attachment')
    def _compute_attachment_filename(self):
        #Imposta automaticamente il nome del file quando viene caricato
        for record in self:
            if record.attachment and not record.attachment_filename:
                record.attachment_filename = "uploaded_file"

    def _check_attachment_size(self, attachment):
        max_size_mb = 20
        if attachment:
            file_size_mb = len(base64.b64decode(attachment)) / (1024 * 1024)
            if file_size_mb > max_size_mb:
                raise UserError(_("File too large. Maximum allowed size is 20 MB."))

    @api.model
    def create(self, vals):
        attachment = vals.get('attachment')
        self._check_attachment_size(attachment)
        return super().create(vals)

    def write(self, vals):
        attachment = vals.get('attachment')
        # Controlla solo se viene passato un nuovo attachment (se no ignora)
        if attachment:
            self._check_attachment_size(attachment)
        return super().write(vals)