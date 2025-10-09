# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError

class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

    osapiens_lot_id = fields.Char(string="oSapiens Lot ID", copy=False, readonly=True)
    osapiens_dds_reference = fields.Char(string="DDS Reference")
    osapiens_dds_status = fields.Char(string="DDS Status", readonly=True)

    def _get_osapiens_client(self):
        from ..services.osapiens_client import OsapiensClient
        return OsapiensClient(self.env)

    def action_osapiens_push(self):
        """
        Esempio: crea un lot su oSapiens a partire dalle righe d'ordine
        e, se presente, collega un DDS.
        """
        for order in self:
            client = order._get_osapiens_client()

            line = order.order_line[:1]
            if not line:
                raise UserError(_("Nessuna riga ordine."))

            product = line.product_id
            if not product or not product.default_code:
                raise UserError(_("Manca il product SKU (default_code) su %s") % product.display_name)

            harvest_year = fields.Date.context_today(self).year

            # Get plot IDs from linked EUDR declaration if available
            # Otherwise use a default placeholder plot ID
            plot_ids = []
            if hasattr(order, 'eudr_declaration_ids') and order.eudr_declaration_ids:
                for declaration in order.eudr_declaration_ids:
                    if declaration.line_ids:
                        plot_ids.extend([f"PLOT-{line.id}" for line in declaration.line_ids])

            if not plot_ids:
                plot_ids = ['PLOT-DEFAULT']  # Fallback to default plot ID

            lot_resp = client.create_lot(product.default_code, harvest_year, plot_ids, extra={
                'po_name': order.name,
                'vendor': order.partner_id.name,
            })
            lot_id = lot_resp.get('id') or lot_resp.get('lot_id')
            if not lot_id:
                raise UserError(_("Creazione lot fallita su oSapiens: %s") % lot_resp)

            order.write({'osapiens_lot_id': lot_id})

            if order.osapiens_dds_reference:
                client.attach_dds_reference('lot', lot_id, order.osapiens_dds_reference)
                status = client.get_dds_status(order.osapiens_dds_reference)
                if isinstance(status, dict):
                    order.write({'osapiens_dds_status': status.get('status')})
                else:
                    order.write({'osapiens_dds_status': status})

    def action_osapiens_push_dds(self):
        for order in self:
            if not order.osapiens_lot_id:
                raise UserError(_("Lot oSapiens non presente sull'ordine."))

            if not order.osapiens_dds_reference:
                raise UserError(_("Inserisci un DDS Reference."))

            client = order._get_osapiens_client()
            client.attach_dds_reference('lot', order.osapiens_lot_id, order.osapiens_dds_reference)
            status = client.get_dds_status(order.osapiens_dds_reference)
            if isinstance(status, dict):
                order.write({'osapiens_dds_status': status.get('status')})
            else:
                order.write({'osapiens_dds_status': status})