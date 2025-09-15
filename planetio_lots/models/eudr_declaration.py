from odoo import fields, models


class EUDRDeclaration(models.Model):
    _inherit = "eudr.declaration"

    stock_lot_id = fields.Many2one(
        comodel_name="stock.production.lot",
        string="Stock Lot",
        help="Select an existing stock lot to link with this declaration.",
    )
