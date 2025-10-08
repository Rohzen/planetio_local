# -*- coding: utf-8 -*-
from odoo import fields, models


class HSCode(models.Model):
    _name = "hs.code"
    _description = "HS Code"
    _order = "code"

    code = fields.Char("HS Code", required=True, index=True)
    description = fields.Char("Description", required=True, translate=True)
    commodity = fields.Char("Commodity", translate=True)
    notes = fields.Text("Notes")
    active = fields.Boolean(default=True)
    reference_species_ids = fields.One2many(
        "hs.code.species", "hs_code_id", string="Reference Species"
    )

    _sql_constraints = [
        ("hs_code_unique", "unique(code)", "HS code must be unique."),
    ]

    def name_get(self):
        res = []
        for record in self:
            name = record.code
            if record.description:
                name = f"{record.code} - {record.description}"
            res.append((record.id, name))
        return res


class HSCodeSpecies(models.Model):
    _name = "hs.code.species"
    _description = "HS Code Species"
    _order = "hs_code_id, name"

    hs_code_id = fields.Many2one(
        "hs.code", string="HS Code", required=True, ondelete="cascade"
    )
    name = fields.Char("Common Name", required=True, index=True, translate=True)
    scientific_name = fields.Char("Scientific Name", required=True, index=True)
    synonyms = fields.Char("Synonyms")
    is_primary = fields.Boolean("Primary Species", default=False)
    region = fields.Char("Region/Origin")
    notes = fields.Text("Notes")
    active = fields.Boolean(default=True)

    _sql_constraints = [
        (
            "scientific_name_per_code",
            "unique(hs_code_id, scientific_name)",
            "Scientific name must be unique per HS code.",
        ),
    ]

    def name_get(self):
        res = []
        for rec in self:
            display = rec.name
            if rec.scientific_name:
                display = f"{rec.name} ({rec.scientific_name})"
            if rec.hs_code_id and rec.hs_code_id.code:
                display = f"[{rec.hs_code_id.code}] {display}"
            res.append((rec.id, display))
        return res
