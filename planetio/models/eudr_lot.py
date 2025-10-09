# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError


class EUDRLot(models.Model):
    _name = "eudr.lot"
    _description = "EUDR Lot/Batch Management"
    _order = "create_date desc, name"
    _rec_name = "name"
    _inherit = ['mail.thread', 'mail.activity.mixin']

    # Core identification
    name = fields.Char(
        string="Lot/Batch Reference",
        required=True,
        tracking=True,
        help="Free-text lot identifier (internal reference)"
    )

    # Optional Odoo integration
    stock_lot_id = fields.Many2one(
        'stock.production.lot',
        string="Stock Lot",
        ondelete='restrict',
        tracking=True,
        help="Optional link to Odoo Stock/Production Lot"
    )

    # EUDR-specific fields
    hs_code_id = fields.Many2one(
        'hs.code',
        string="HS Code",
        required=True,
        tracking=True,
        help="Harmonized System code for this lot"
    )

    product_species_id = fields.Many2one(
        'hs.code.species',
        string="Species",
        domain="[('hs_code_id', '=', hs_code_id)]",
        tracking=True,
        help="Species for this lot"
    )

    # Product information
    product_id = fields.Many2one(
        'product.product',
        string="Product",
        tracking=True,
        help="Optional product reference"
    )

    product_description = fields.Char(
        string="Product Description",
        compute="_compute_product_description",
        store=True,
        readonly=False
    )

    # Quantity/Weight
    net_mass_kg = fields.Float(
        string="Net Mass (kg)",
        digits=(16, 3),
        tracking=True,
        help="Net weight of this lot in kilograms"
    )

    # Supplier (main supplier, can be different from plot producers)
    supplier_id = fields.Many2one(
        'res.partner',
        string="Main Supplier",
        tracking=True,
        help="Main supplier for this lot (can differ from individual plot producers)"
    )

    # Activity type
    activity_type = fields.Selection(
        [
            ('import', 'Import'),
            ('export', 'Export'),
            ('domestic', 'Domestic'),
        ],
        string="Activity Type",
        default='import',
        tracking=True
    )

    # PLOTS - Multiple plots per lot
    plot_ids = fields.Many2many(
        'eudr.plot',
        'eudr_lot_plot_rel',
        'lot_id',
        'plot_id',
        string="Plots/Locations",
        help="Geographic plots/farms included in this lot"
    )

    plot_count = fields.Integer(
        compute="_compute_plot_count",
        string="Plot Count"
    )

    total_area_ha = fields.Float(
        compute="_compute_total_area",
        string="Total Area (ha)",
        store=True
    )

    # DDS REFERENCE - For assessment-only scenarios
    reference_dds_identifier = fields.Char(
        string="Reference DDS Identifier (UUID)",
        tracking=True,
        help="UUID of existing DDS to load for assessment (no new submission)"
    )

    reference_dds_number = fields.Char(
        string="Reference DDS Number",
        tracking=True,
        help="Human-readable DDS reference number"
    )

    is_assessment_only = fields.Boolean(
        string="Assessment Only",
        tracking=True,
        help="Load existing DDS for assessment without creating new submission"
    )

    # Declaration relationship
    declaration_ids = fields.One2many(
        'eudr.declaration',
        'lot_id',
        string="EUDR Declarations",
        readonly=True
    )

    declaration_count = fields.Integer(
        string="Declaration Count",
        compute="_compute_declaration_count"
    )

    # Status
    state = fields.Selection([
        ('draft', 'Draft'),
        ('ready', 'Ready for DDS'),
        ('declared', 'DDS Submitted'),
        ('compliant', 'Compliant'),
    ], string="Status", default='draft', tracking=True, copy=False)

    # Additional info
    notes = fields.Text(string="Notes")
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        'res.company',
        string="Company",
        default=lambda self: self.env.company,
        required=True
    )

    # Computed fields from stock.lot if linked
    stock_lot_product_id = fields.Many2one(
        related='stock_lot_id.product_id',
        string="Stock Lot Product",
        store=False
    )

    stock_lot_qty = fields.Float(
        related='stock_lot_id.product_qty',
        string="Stock Quantity",
        store=False
    )

    _sql_constraints = [
        (
            'name_company_unique',
            'unique(name, company_id)',
            'Lot reference must be unique per company.'
        )
    ]

    @api.depends('product_id', 'product_species_id', 'name')
    def _compute_product_description(self):
        for rec in self:
            if rec.product_id:
                rec.product_description = rec.product_id.display_name
            elif rec.product_species_id:
                rec.product_description = rec.product_species_id.name
            else:
                rec.product_description = rec.name or ''

    @api.depends('declaration_ids')
    def _compute_declaration_count(self):
        for rec in self:
            rec.declaration_count = len(rec.declaration_ids)

    @api.depends('plot_ids')
    def _compute_plot_count(self):
        for rec in self:
            rec.plot_count = len(rec.plot_ids)

    @api.depends('plot_ids.area_ha')
    def _compute_total_area(self):
        for rec in self:
            rec.total_area_ha = sum(rec.plot_ids.mapped('area_ha'))

    @api.onchange('stock_lot_id')
    def _onchange_stock_lot_id(self):
        """Auto-populate fields from stock.lot if linked."""
        if self.stock_lot_id and self.stock_lot_id.product_id:
            self.product_id = self.stock_lot_id.product_id
            # Auto-populate from product template
            template = self.stock_lot_id.product_id.product_tmpl_id
            if template.hs_code_id:
                self.hs_code_id = template.hs_code_id
            if template.product_species_id:
                self.product_species_id = template.product_species_id

    @api.onchange('product_id')
    def _onchange_product_id(self):
        """Auto-populate HS code and species from product."""
        if self.product_id:
            template = self.product_id.product_tmpl_id
            if template.hs_code_id and not self.hs_code_id:
                self.hs_code_id = template.hs_code_id
            if template.product_species_id and not self.product_species_id:
                self.product_species_id = template.product_species_id

    @api.onchange('hs_code_id')
    def _onchange_hs_code_id(self):
        """Clear species if it doesn't match the selected HS code."""
        if self.product_species_id and self.product_species_id.hs_code_id != self.hs_code_id:
            self.product_species_id = False

    def action_load_dds_data(self):
        """Load existing DDS data from TRACES using reference identifier."""
        self.ensure_one()

        if not self.reference_dds_identifier:
            raise UserError(_("DDS Identifier (UUID) is required to load DDS data."))

        # Use existing retrieval client
        from ..services.eudr_adapter_odoo import action_retrieve_dds_numbers

        # Create temporary declaration to retrieve data
        temp_declaration = self.env['eudr.declaration'].create({
            'dds_identifier': self.reference_dds_identifier,
            'name': f"TEMP-{self.name}",
            'product_description': self.name,
            'net_mass_kg': 1.0,  # Dummy value
            'hs_code_id': self.hs_code_id.id,
            'company_id': self.company_id.id,
        })

        try:
            # Retrieve DDS data
            action_retrieve_dds_numbers(temp_declaration)

            # Store retrieved reference number
            if temp_declaration.eudr_id:
                self.reference_dds_number = temp_declaration.eudr_id

            self.message_post(
                body=_('DDS data retrieved. Reference: <b>%s</b>') % (
                    self.reference_dds_number or self.reference_dds_identifier
                )
            )

        finally:
            # Clean up temp declaration
            temp_declaration.unlink()

        return True

    def action_create_dds_declaration(self):
        """Create a new EUDR declaration from this lot."""
        self.ensure_one()

        if self.is_assessment_only:
            raise UserError(_("This lot is marked as 'Assessment Only'. Cannot create new DDS declaration."))

        if not self.hs_code_id:
            raise UserError(_("HS Code is required to create a DDS declaration."))

        if not self.net_mass_kg or self.net_mass_kg <= 0:
            raise UserError(_("Net mass must be greater than 0 to create a DDS declaration."))

        if not self.plot_ids:
            raise UserError(_("At least one plot is required to create a DDS declaration."))

        # Create declaration
        declaration_vals = {
            'lot_id': self.id,
            'hs_code_id': self.hs_code_id.id,
            'product_species_id': self.product_species_id.id if self.product_species_id else False,
            'product_id': self.product_id.id if self.product_id else False,
            'product_description': self.product_description or self.name,
            'net_mass_kg': self.net_mass_kg,
            'supplier_id': self.supplier_id.id if self.supplier_id else False,
            'lot_name': self.name,
            'activity_type': self.activity_type,
            'company_id': self.company_id.id,
        }

        declaration = self.env['eudr.declaration'].create(declaration_vals)

        # Create declaration lines from plots
        declaration._create_lines_from_lot_plots(self)

        # Update lot state
        if self.state == 'draft':
            self.state = 'ready'

        self.message_post(
            body=_('EUDR Declaration <b>%s</b> created from this lot with %d plot(s).') % (
                declaration.name, len(self.plot_ids)
            )
        )

        return {
            'type': 'ir.actions.act_window',
            'name': _('EUDR Declaration'),
            'res_model': 'eudr.declaration',
            'res_id': declaration.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_view_declarations(self):
        """Open declarations linked to this lot."""
        self.ensure_one()
        action = {
            'type': 'ir.actions.act_window',
            'name': _('EUDR Declarations for %s') % self.name,
            'res_model': 'eudr.declaration',
            'domain': [('lot_id', '=', self.id)],
            'context': {'default_lot_id': self.id},
        }

        if self.declaration_count == 1:
            action.update({
                'view_mode': 'form',
                'res_id': self.declaration_ids[0].id,
            })
        else:
            action['view_mode'] = 'tree,form'

        return action

    def action_view_plots(self):
        """Open plots linked to this lot."""
        self.ensure_one()

        return {
            'type': 'ir.actions.act_window',
            'name': _('Plots for %s') % self.name,
            'res_model': 'eudr.plot',
            'domain': [('id', 'in', self.plot_ids.ids)],
            'view_mode': 'tree,form',
            'context': {'default_lot_ids': [(4, self.id)]},
        }

    def action_set_ready(self):
        """Mark lot as ready for DDS."""
        for rec in self:
            if not rec.hs_code_id:
                raise UserError(_("HS Code is required to mark lot as ready."))
            if not rec.net_mass_kg or rec.net_mass_kg <= 0:
                raise UserError(_("Net mass must be greater than 0."))
            if not rec.plot_ids and not rec.is_assessment_only:
                raise UserError(_("At least one plot is required."))
            rec.state = 'ready'

    def action_set_draft(self):
        """Reset lot to draft."""
        self.write({'state': 'draft'})
