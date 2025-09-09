
from odoo import models, fields

class ExcelImportTemplate(models.Model):
    _name = "excel.import.template"
    _description = "Excel Import Template"

    name = fields.Char(required=True)
    model_id = fields.Many2one("ir.model", required=True, ondelete='cascade', index=True)
    strictness_level = fields.Selection(
        [("low","Low"),("medium","Medium"),("high","High")],
        default="medium"
    )
    field_ids = fields.One2many("excel.import.template.field","template_id")

class ExcelImportTemplateField(models.Model):
    _name = "excel.import.template.field"
    _description = "Excel Import Template Field"

    template_id = fields.Many2one("excel.import.template", required=True, ondelete="cascade")
    field_id = fields.Many2one(
        "ir.model.fields", required=True,
        domain="[('model_id','=',parent.model_id)]", ondelete='cascade', index=True
    )
    required = fields.Boolean(default=False)
    transformer = fields.Char(default="identity")  # identity|to_date|to_float|geo_point|geo_polygon|custom:py
    selector_policy = fields.Selection(
        [("by_header","By Header"),("by_regex","By Regex"),("by_ai","By AI")],
        default="by_ai"
    )
    alias_ids = fields.One2many("excel.header.alias","template_field_id")
