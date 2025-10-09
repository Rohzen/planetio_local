# -*- coding: utf-8 -*-
from odoo import api, fields, models


class ResPartner(models.Model):
    _inherit = "res.partner"

    # EUDR-specific fields
    farmer_id_code = fields.Char(
        string="Farmer ID Code",
        help="National identification code for farmer/producer"
    )

    is_eudr_producer = fields.Boolean(
        string="EUDR Producer",
        help="This partner is a producer/farmer for EUDR declarations"
    )

    eudr_plot_ids = fields.One2many(
        'eudr.plot',
        'producer_id',
        string="EUDR Plots"
    )

    eudr_plot_count = fields.Integer(
        compute="_compute_eudr_plot_count",
        string="Plots"
    )

    @api.depends('eudr_plot_ids')
    def _compute_eudr_plot_count(self):
        for rec in self:
            rec.eudr_plot_count = len(rec.eudr_plot_ids)

    def action_view_eudr_plots(self):
        """View EUDR plots for this producer."""
        self.ensure_one()

        return {
            'type': 'ir.actions.act_window',
            'name': f'EUDR Plots - {self.name}',
            'res_model': 'eudr.plot',
            'domain': [('producer_id', '=', self.id)],
            'view_mode': 'tree,form',
            'context': {
                'default_producer_id': self.id,
                'default_is_eudr_producer': True,
            },
        }
