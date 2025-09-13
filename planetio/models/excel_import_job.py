
from odoo import models, fields
import json

class ExcelImportJob(models.Model):
    _name = "excel.import.job"
    _description = "Excel Import Job"

    declaration_id = fields.Many2one("eudr.declaration", readonly=True)
    attachment_id = fields.Many2one("ir.attachment", required=True)
    template_id = fields.Many2one("excel.import.template", required=True)
    status = fields.Selection(
        [("draft","Draft"),("mapped","Mapped"),("validated","Validated"),
         ("done","Done"),("error","Error")], default="draft")
    sheet_name = fields.Char()
    mapping_json = fields.Text()   # proposta [{field, header, score, source}]
    preview_json = fields.Text()   # prime righe normalizzate
    result_json = fields.Text()    # righe trasformate pronte
    log = fields.Text()

    def log_info(self, msg):
        pass
        # self.ensure_one()
        # self.log = (self.log or "") + msg + "\n"
        # self.env["ir.logging"].create({
        #     "name":"excel_ai_import",
        #     "type":"server",
        #     "dbname": self._cr.dbname,
        #     "level":"INFO",
        #     "message": msg,
        #     "path":"excel_ai_import",
        #     "func":"job",
        #     "line":0
        # })
