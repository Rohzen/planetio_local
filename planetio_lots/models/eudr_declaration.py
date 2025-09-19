from odoo import fields, models, api


class EUDRDeclaration(models.Model):
    _inherit = "eudr.declaration"

    stock_lot_id = fields.Many2one(
        comodel_name="stock.production.lot",
        string="Stock Lot",
        help="Select an existing stock lot to link with this declaration.",
    )

class StockProductionLot(models.Model):
    _inherit = 'stock.production.lot'


    def name_get(self):
        self.ensure_one() if len(self) == 1 else None
        if self._context.get('lot_label_with_product'):
            result = []
            for lot in self:
                parts = []
                if lot.product_id:
                    parts.append(lot.product_id.display_name)
                if lot.name:
                    parts.append(lot.name)
                # Fallback to record name if both are somehow empty
                label = ' / '.join([p for p in parts if p]) or super(StockProductionLot, lot).name_get()[0][1]
                result.append((lot.id, label))
            return result
        # default behavior elsewhere
        return super(StockProductionLot, self).name_get()