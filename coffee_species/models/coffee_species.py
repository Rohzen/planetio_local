# -*- coding: utf-8 -*-
from odoo import fields, models

class CoffeeSpecies(models.Model):
    _name = "coffee.species"
    _description = "Coffee Species"
    _order = "is_commercial desc, name"

    name = fields.Char("Common Name", required=True, index=True, translate=True)
    scientific_name = fields.Char("Scientific Name", required=True, index=True)
    synonyms = fields.Char("Synonyms")
    is_commercial = fields.Boolean("Commercially Cultivated", default=False)
    region = fields.Char("Region/Origin")
    notes = fields.Text("Notes")
    active = fields.Boolean(default=True)

    _sql_constraints = [
        ("scientific_name_uniq", "unique(scientific_name)", "Scientific name must be unique."),
    ]

    def name_get(self):
        res = []
        for rec in self:
            display = rec.name
            if rec.scientific_name:
                display = "%s (%s)" % (rec.name, rec.scientific_name)
            res.append((rec.id, display))
        return res
