from odoo import fields, models


class DeclarationAlert(models.Model):
    _name = "declaration.alert"
    _description = "EUDR Declaration AI Alert"
    _order = "sequence, id"

    sequence = fields.Integer(default=10)
    declaration_id = fields.Many2one(
        "eudr.declaration", required=True, ondelete="cascade"
    )
    line_id = fields.Many2one(
        "eudr.declaration.line",
        string="Field",
        ondelete="set null",
    )
    field_identifier = fields.Char(string="Field identifier")
    line_label = fields.Char(string="Label")
    description = fields.Text(required=True)


class DeclarationAction(models.Model):
    _name = "declaration.action"
    _description = "EUDR Declaration Corrective Action"
    _order = "sequence, id"

    sequence = fields.Integer(default=10)
    declaration_id = fields.Many2one(
        "eudr.declaration", required=True, ondelete="cascade"
    )
    line_id = fields.Many2one(
        "eudr.declaration.line",
        string="Field",
        ondelete="set null",
    )
    field_identifier = fields.Char(string="Field identifier")
    line_label = fields.Char(string="Label")
    description = fields.Text(required=True)


class EudrDeclaration(models.Model):
    _inherit = "eudr.declaration"

    ai_alert_ids = fields.One2many(
        "declaration.alert",
        "declaration_id",
        string="AI Alerts",
    )
    ai_action_ids = fields.One2many(
        "declaration.action",
        "declaration_id",
        string="AI Corrective Actions",
    )
