
from odoo import models, fields

class ExcelHeaderAlias(models.Model):
    _name = "excel.header.alias"
    _description = "Header Alias"

    template_field_id = fields.Many2one("excel.import.template.field", required=True, ondelete="cascade")
    alias = fields.Char(required=True)
    language = fields.Char()
    weight = fields.Float(default=1.0)
