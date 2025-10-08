# -*- coding: utf-8 -*-
from odoo import api, fields, models


class ProductTemplate(models.Model):
    _inherit = "product.template"

    hs_code_id = fields.Many2one(
        "hs.code", string="HS Code", help="Primary HS code for this product"
    )
    product_species_ids = fields.One2many(
        "product.species", "product_tmpl_id", string="Product Species"
    )


class ProductSpecies(models.Model):
    _name = "product.species"
    _description = "Product Species"
    _order = "sequence, name"

    product_tmpl_id = fields.Many2one(
        "product.template", string="Product", required=True, ondelete="cascade"
    )
    sequence = fields.Integer(default=10)
    hs_code_id = fields.Many2one(
        "hs.code", string="HS Code", required=True, ondelete="restrict"
    )
    hs_code_species_id = fields.Many2one(
        "hs.code.species",
        string="Reference Species",
        domain="[('hs_code_id', '=', hs_code_id)]",
    )
    name = fields.Char("Common Name", required=True, translate=True)
    scientific_name = fields.Char("Scientific Name", required=True)
    notes = fields.Text("Notes")
    active = fields.Boolean(default=True)

    _sql_constraints = [
        (
            "product_species_unique",
            "unique(product_tmpl_id, scientific_name)",
            "Scientific name must be unique per product.",
        ),
    ]

    @api.onchange("hs_code_species_id")
    def _onchange_hs_code_species_id(self):
        for line in self:
            if line.hs_code_species_id:
                line.name = line.hs_code_species_id.name
                line.scientific_name = line.hs_code_species_id.scientific_name
                line.hs_code_id = line.hs_code_species_id.hs_code_id

    @api.onchange("hs_code_id")
    def _onchange_hs_code_id(self):
        for line in self:
            if line.hs_code_species_id and line.hs_code_species_id.hs_code_id != line.hs_code_id:
                line.hs_code_species_id = False

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            species_id = vals.get('hs_code_species_id')
            if species_id and not vals.get('hs_code_id'):
                hs_species = self.env['hs.code.species'].browse(species_id)
                if hs_species.hs_code_id:
                    vals['hs_code_id'] = hs_species.hs_code_id.id
        return super().create(vals_list)

    def write(self, vals):
        res = super().write(vals)
        if 'hs_code_species_id' in vals and not vals.get('hs_code_id'):
            for line in self:
                if line.hs_code_species_id and line.hs_code_species_id.hs_code_id:
                    line.hs_code_id = line.hs_code_species_id.hs_code_id
        return res
