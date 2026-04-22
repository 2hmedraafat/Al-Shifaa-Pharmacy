from odoo import models, fields, api
from odoo.exceptions import ValidationError


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    # ── FIELDS ────────────────────────────────────────────────────────────

    sell_as = fields.Selection([
        ('package', 'Package'),
        ('unit', 'Unit'),
    ], string='Sell As', default='package', required=True)

    units_per_package = fields.Integer(
        string='Units per Package',
        default=1,
    )

    package_uom_id = fields.Many2one(
        'uom.uom',
        string='Package UoM',
        readonly=True,
    )

    # Unit price = Package price / units_per_package (read-only)
    unit_price = fields.Float(
        string='Unit Price',
        compute='_compute_unit_price',
        store=True,
        readonly=True,
        digits='Product Price',
    )

    # Stock display: X Package (Y Units)
    display_stock = fields.Char(
        string='Stock Display',
        compute='_compute_display_stock',
        store=False,
    )

    # ── UC-09 ─────────────────────────────────────────────────────────────

    commission_pct = fields.Float(
        string='Commission %',
        digits=(5, 2),
        default=0.0,
        help='Commission percentage per product. 0 = no commission.',
    )

    # ── VALIDATION ────────────────────────────────────────────────────────

    @api.constrains('sell_as', 'units_per_package')
    def _check_units(self):
        for rec in self:
            if rec.sell_as == 'unit' and rec.units_per_package < 1:
                raise ValidationError(
                    'Number of Units per Package must be at least 1.'
                )

    # ── PREVENT CHANGE AFTER DONE STOCK MOVES ────────────────────────────

    def write(self, vals):
        if 'sell_as' in vals or 'units_per_package' in vals:
            for rec in self:
                done_moves = self.env['stock.move'].search([
                    ('product_id', 'in', rec.product_variant_ids.ids),
                    ('state', '=', 'done'),
                ], limit=1)
                if done_moves:
                    raise ValidationError(
                        "Cannot change 'Sell As' or 'Units per Package' "
                        "after stock transactions have been recorded."
                    )
        return super().write(vals)

    # ── UOM SETUP ─────────────────────────────────────────────────────────

    def _get_or_create_package_uom(self):
        """
        Creates a dedicated UoM category per product with two UoMs:
          - Unit    = reference UoM  (selling unit: tablet, capsule, vial)
          - Package = bigger UoM     (purchase unit: box, carton)
                                      1 Package = N Units
        """
        self.ensure_one()
        if not self.name or self.units_per_package < 1:
            return False, False

        cat_name = 'Pkg/%s' % self.name
        category = self.env['uom.category'].search(
            [('name', '=', cat_name)], limit=1
        )
        if not category:
            category = self.env['uom.category'].create({'name': cat_name})

        # Unit UoM — reference (base for all conversions)
        unit_uom = self.env['uom.uom'].search([
            ('category_id', '=', category.id),
            ('name', '=', 'Unit'),
        ], limit=1)
        if not unit_uom:
            unit_uom = self.env['uom.uom'].create({
                'name': 'Unit',
                'category_id': category.id,
                'uom_type': 'reference',
                'factor': 1.0,
                'rounding': 1.0,
            })

        # Package UoM — bigger than Unit
        # factor_inv = N  means  1 Package = N Units
        pkg_uom = self.env['uom.uom'].search([
            ('category_id', '=', category.id),
            ('name', '=', 'Package'),
        ], limit=1)
        if not pkg_uom:
            pkg_uom = self.env['uom.uom'].create({
                'name': 'Package',
                'category_id': category.id,
                'uom_type': 'bigger',
                'factor_inv': float(self.units_per_package),
                'rounding': 0.01,
            })
        else:
            if pkg_uom.factor_inv != float(self.units_per_package):
                pkg_uom.factor_inv = float(self.units_per_package)

        return unit_uom, pkg_uom

    # ── ONCHANGE ──────────────────────────────────────────────────────────

    @api.onchange('sell_as', 'units_per_package')
    def _onchange_sell_as(self):
        for rec in self:
            if rec.sell_as == 'package':
                # Package mode: buy and sell as Package only
                unit = rec.env.ref('uom.product_uom_unit',
                                   raise_if_not_found=False)
                if unit:
                    rec.uom_id = unit
                    rec.uom_po_id = unit
                rec.package_uom_id = False
                rec.units_per_package = 1

            elif rec.sell_as == 'unit' and rec.units_per_package > 0:
                # Unit mode:
                #   uom_id    = Unit    (default selling UoM)
                #   uom_po_id = Package (purchase UoM — always)
                unit_uom, pkg_uom = rec._get_or_create_package_uom()
                if unit_uom and pkg_uom:
                    rec.uom_id = unit_uom
                    rec.uom_po_id = pkg_uom
                    rec.package_uom_id = pkg_uom

    # ── COMPUTE: UNIT PRICE ───────────────────────────────────────────────

    @api.depends('list_price', 'units_per_package', 'sell_as')
    def _compute_unit_price(self):
        """
        list_price is always the Package price.
        unit_price = Package price / units_per_package
        """
        for rec in self:
            if rec.sell_as == 'unit' and rec.units_per_package > 0:
                rec.unit_price = rec.list_price / rec.units_per_package
            else:
                rec.unit_price = rec.list_price

    # ── COMPUTE: STOCK DISPLAY ────────────────────────────────────────────

    @api.depends('qty_available', 'units_per_package', 'sell_as')
    def _compute_display_stock(self):
        """
        qty_available is stored in uom_id units (Unit when sell_as = unit).

        Example: units_per_package = 30, qty_available = 75 Units
          full_packages   = 75 // 30 = 2 Packages
          remaining_units = 75 %  30 = 15 Units
          Display -> "2 Package (15 Units)"

        Example: units_per_package = 30, qty_available = 60 Units
          full_packages   = 60 // 30 = 2 Packages
          remaining_units = 60 %  30 = 0 Units
          Display -> "2 Package"
        """
        for rec in self:
            qty = rec.qty_available
            if rec.sell_as == 'unit' and rec.units_per_package > 0:
                full_packages = int(qty // rec.units_per_package)
                remaining_units = int(qty % rec.units_per_package)
                if remaining_units > 0:
                    rec.display_stock = (
                        f'{full_packages} Package ({remaining_units} Units)'
                    )
                else:
                    rec.display_stock = f'{full_packages} Package'
            else:
                rec.display_stock = f'{int(qty)} Package'
