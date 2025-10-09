# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError
import json


class EUDRPlot(models.Model):
    _name = "eudr.plot"
    _description = "EUDR Plot/Farm Location"
    _rec_name = "name"
    _order = "producer_id, name"

    name = fields.Char(
        string="Plot Reference",
        required=True,
        help="Plot identifier (e.g., Farm-A, Plot-001)"
    )

    producer_id = fields.Many2one(
        'res.partner',
        string="Producer/Farmer",
        required=True,
        domain="[('is_eudr_producer', '=', True)]",
        ondelete='restrict'
    )

    farm_name = fields.Char(string="Farm Name")

    # Geographic data
    geometry = fields.Text(
        string="GeoJSON Geometry",
        required=True,
        help="GeoJSON representation of the plot location"
    )

    geo_type = fields.Selection([
        ('point', 'Point'),
        ('polygon', 'Polygon')
    ], string="Geometry Type", compute="_compute_geo_type", store=True)

    area_ha = fields.Float(
        string="Area (ha)",
        compute="_compute_area_ha",
        store=True,
        help="Computed area in hectares"
    )

    # Location details (from partner or override)
    country_id = fields.Many2one(
        'res.country',
        string="Country",
        related='producer_id.country_id',
        store=True,
        readonly=False
    )

    region = fields.Char(
        string="Region/State",
        related='producer_id.state_id.name',
        store=True,
        readonly=False
    )

    municipality = fields.Char(
        string="Municipality/City",
        related='producer_id.city',
        store=True,
        readonly=False
    )

    # Lot associations
    lot_ids = fields.Many2many(
        'eudr.lot',
        'eudr_lot_plot_rel',
        'plot_id',
        'lot_id',
        string="Associated Lots"
    )

    lot_count = fields.Integer(
        compute="_compute_lot_count",
        string="Lots"
    )

    active = fields.Boolean(default=True)
    notes = fields.Text(string="Notes")
    company_id = fields.Many2one(
        'res.company',
        string="Company",
        default=lambda self: self.env.company
    )

    _sql_constraints = [
        (
            'name_producer_unique',
            'unique(name, producer_id)',
            'Plot reference must be unique per producer.'
        )
    ]

    @api.depends('geometry')
    def _compute_geo_type(self):
        """Detect geometry type from GeoJSON."""
        for rec in self:
            if rec.geometry:
                try:
                    geom = json.loads(rec.geometry)
                    gtype = geom.get('type', '').lower()
                    if gtype == 'point':
                        rec.geo_type = 'point'
                    elif gtype in ('polygon', 'multipolygon'):
                        rec.geo_type = 'polygon'
                    else:
                        rec.geo_type = False
                except Exception:
                    rec.geo_type = False
            else:
                rec.geo_type = False

    @api.depends('geometry', 'geo_type')
    def _compute_area_ha(self):
        """Compute area from GeoJSON geometry."""
        for rec in self:
            if not rec.geometry or rec.geo_type != 'polygon':
                rec.area_ha = 0.0
                continue

            try:
                geom = json.loads(rec.geometry)

                # Use existing area calculation from eudr.declaration
                declaration_model = self.env['eudr.declaration']
                polygons = []

                # Use helper methods from declaration
                for g in declaration_model._iter_geojson_geometries(geom):
                    polygons.extend(declaration_model._poly_rings_lonlat(g))

                if polygons:
                    area_m2 = declaration_model._polygon_area_m2(declaration_model, polygons)
                    rec.area_ha = area_m2 / 10000.0
                else:
                    rec.area_ha = 0.0
            except Exception:
                rec.area_ha = 0.0

    @api.depends('lot_ids')
    def _compute_lot_count(self):
        for rec in self:
            rec.lot_count = len(rec.lot_ids)

    def action_visualize_on_map(self):
        """Open geometry on geojson.io."""
        self.ensure_one()

        if not self.geometry:
            raise UserError(_("No geometry defined for this plot."))

        import urllib.parse

        try:
            geom = json.loads(self.geometry)
            encoded = urllib.parse.quote(json.dumps(geom))
            url = f"https://geojson.io/#data=data:application/json,{encoded}"

            return {
                'type': 'ir.actions.act_url',
                'url': url,
                'target': 'new',
            }
        except Exception as e:
            raise UserError(_("Invalid GeoJSON: %s") % str(e))

    def action_view_lots(self):
        """View lots associated with this plot."""
        self.ensure_one()

        return {
            'type': 'ir.actions.act_window',
            'name': _('Lots for Plot %s') % self.name,
            'res_model': 'eudr.lot',
            'domain': [('id', 'in', self.lot_ids.ids)],
            'view_mode': 'tree,form',
            'context': {'default_plot_ids': [(4, self.id)]},
        }
