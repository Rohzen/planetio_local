from odoo import fields, models


class EUDRDeclaration(models.Model):
    _inherit = "eudr.declaration"

    todo_batch_ids = fields.One2many(
        comodel_name="caffe.crudo.todo.batch",
        inverse_name="declaration_id",
        string="To-Do Batches",
    )
    todo_batch_count = fields.Integer(
        compute="_compute_todo_batch_count",
        string="To-Do Batches",
    )

    def _compute_todo_batch_count(self):
        count_map = {}
        if self.ids:
            grouped_data = self.env["caffe.crudo.todo.batch"].read_group(
                [("declaration_id", "in", self.ids)],
                ["declaration_id"],
                ["declaration_id"],
            )
            count_map = {
                data["declaration_id"][0]: data["declaration_id_count"]
                for data in grouped_data
                if data["declaration_id"]
            }
        for declaration in self:
            declaration.todo_batch_count = count_map.get(declaration.id, 0)

    def action_open_todo_batches(self):
        self.ensure_one()
        action = self.env.ref(
            "planetio_questionnaire.action_coffee_batch_todo_from_declaration"
        ).read()[0]
        action["domain"] = [
            ("declaration_id", "=", self.id),
        ]
        action.setdefault("context", {})
        action["context"].update(
            {
                "default_declaration_id": self.id,
            }
        )
        return action
