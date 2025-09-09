from odoo import models, fields

class ExcelImportJobInh(models.Model):
    _inherit = "excel.import.job"
    declaration_id = fields.Many2one("eudr.declaration", readonly=True)
