from odoo import fields, models


class CaffeCrudoTodoBatch(models.Model):
    _inherit = "eudr.questionnaire"

    declaration_id = fields.Many2one(
        comodel_name="eudr.declaration",
        string="EUDR Declaration",
        ondelete="set null",
    )
