from odoo import models, fields, api, _
from odoo.exceptions import ValidationError


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    # ══════════════════════════════════════════════════════════════════════
    # PACKAGE / UNIT SELLING
    # ══════════════════════════════════════════════════════════════════════
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

    unit_price = fields.Float(
        string='Unit Price',
        compute='_compute_unit_price',
        store=True,
        readonly=True,
        digits='Product Price',
    )

    sales_price_inline = fields.Char(
        string='Sales Price Display',
        compute='_compute_sales_price_inline',
    )

    display_stock = fields.Char(
        string='Stock Display',
        compute='_compute_display_stock',
        store=False,
    )

    # ══════════════════════════════════════════════════════════════════════
    # UC-04 — Classification
    # ══════════════════════════════════════════════════════════════════════
    classification = fields.Selection(
        selection=[
            ('medicine', 'Medicine'),
            ('non_medicine', 'Non-Medicine'),
        ],
        string='Classification',
        required=True,
        tracking=True,
        index=True,
        help='Medicine or Non-Medicine product.',
    )

    is_scheduled = fields.Boolean(string='Scheduled Drug', tracking=True)

    max_qty = fields.Float(
        string='Max Dispensing Qty',
        digits='Product Unit of Measure',
        tracking=True,
    )

    is_chronic = fields.Boolean(string='Chronic Medication', tracking=True)
    lot_tracking_required = fields.Boolean(string='Lot Tracking Required', tracking=True)
    expiry_tracking_required = fields.Boolean(string='Expiry Tracking Required', tracking=True)

    # ══════════════════════════════════════════════════════════════════════
    # UC-09 — Commission
    # ══════════════════════════════════════════════════════════════════════
    commission_pct = fields.Float(
        string='Commission %',
        digits=(5, 2),
        default=0.0,
        help='Commission percentage per product. 0 = no commission.',
    )

    # ══════════════════════════════════════════════════════════════════════
    # UC-10 — Max Qty Per Invoice (Hard Block)
    # ══════════════════════════════════════════════════════════════════════
    max_qty_per_invoice = fields.Integer(
        string='Max Qty per Invoice',
        default=0,
        tracking=True,
        help='Hard limit per sale invoice — always active. 0 = no restriction.',
        groups='pharmacy.group_pharmacy_manager',
    )

    # ══════════════════════════════════════════════════════════════════════
    # UC-11 — Low Stock Selling Limit (Soft Warning — dynamic)
    # ══════════════════════════════════════════════════════════════════════
    low_stock_limit = fields.Integer(
        string='Low Stock Limit',
        default=0,
        tracking=True,
        help='Stock level that triggers the low-stock restriction. 0 = inactive.',
        groups='pharmacy.group_pharmacy_manager',
    )

    max_qty_when_low = fields.Integer(
        string='Max Qty per Invoice When Low',
        default=0,
        tracking=True,
        help='Max qty per invoice when stock ≤ Low Stock Limit. Must be < Low Stock Limit.',
        groups='pharmacy.group_pharmacy_manager',
    )

    is_low_stock = fields.Boolean(
        string='Low Stock',
        compute='_compute_is_low_stock',
        store=True,
        index=True,
    )

    # ══════════════════════════════════════════════════════════════════════
    # UC-08 — Pharmacist Price (AVCO)
    # ══════════════════════════════════════════════════════════════════════
    pharmacist_price = fields.Float(
        string='Avg. Purchase Cost',
        digits=(16, 3),
        compute='_compute_pharmacist_price',
        store=True,
        readonly=True,
        groups='pharmacy.group_pharmacy_manager,pharmacy.group_pharmacy_pharmacist',
    )

    pharmacist_price_display = fields.Char(
        string='Avg. Purchase Cost (Pharmacist)',
        compute='_compute_pharmacist_price_display',
        readonly=True,
        groups='pharmacy.group_pharmacy_manager,pharmacy.group_pharmacy_pharmacist',
    )

    cost_history_ids = fields.One2many(
        'pharmacy.cost.history',
        'product_tmpl_id',
        string='Cost History',
        readonly=True,
        groups='pharmacy.group_pharmacy_manager,pharmacy.group_pharmacy_pharmacist',
    )

    # ══════════════════════════════════════════════════════════════════════
    # VALIDATIONS
    # ══════════════════════════════════════════════════════════════════════
    @api.constrains('sell_as', 'units_per_package')
    def _check_units(self):
        for rec in self:
            if rec.sell_as == 'unit' and rec.units_per_package < 1:
                raise ValidationError('Number of Units per Package must be at least 1.')

    @api.constrains('classification')
    def _check_classification(self):
        for rec in self:
            if not rec.classification:
                raise ValidationError(_('Classification is mandatory.'))

    @api.constrains('max_qty_per_invoice')
    def _check_max_qty_per_invoice(self):
        for rec in self:
            if rec.max_qty_per_invoice < 0:
                raise ValidationError(_('Max Qty per Invoice must be 0 or a positive integer.'))

    @api.constrains('low_stock_limit', 'max_qty_when_low')
    def _check_low_stock_fields(self):
        for rec in self:
            if rec.low_stock_limit < 0:
                raise ValidationError(_('Low Stock Limit must be 0 or a positive integer.'))
            if rec.max_qty_when_low < 0:
                raise ValidationError(_('Max Qty per Invoice When Low must be 0 or a positive integer.'))
            if rec.low_stock_limit > 0 and rec.max_qty_when_low > 0:
                if rec.max_qty_when_low >= rec.low_stock_limit:
                    raise ValidationError(_(
                        'Max Qty per Invoice When Low (%(when_low)s) must be strictly less than '
                        'Low Stock Limit (%(limit)s).',
                        when_low=rec.max_qty_when_low,
                        limit=rec.low_stock_limit,
                    ))

    # ══════════════════════════════════════════════════════════════════════
    # ONCHANGE
    # ══════════════════════════════════════════════════════════════════════
    @api.onchange('classification')
    def _onchange_classification(self):
        if self.classification == 'non_medicine':
            self.is_scheduled = False
            self.max_qty = 0.0
            self.is_chronic = False
            self.lot_tracking_required = False
            self.expiry_tracking_required = False
            self.max_qty_per_invoice = 0
            self.low_stock_limit = 0
            self.max_qty_when_low = 0

        if self._origin and self._origin.id:
            moves_exist = self.env['stock.move'].sudo().search_count([
                ('product_id.product_tmpl_id', '=', self._origin.id),
                ('state', '=', 'done'),
            ])
            if moves_exist:
                return {'warning': {
                    'title': _('Classification Change Warning'),
                    'message': _('Changing classification may affect existing stock rules. Continue?'),
                }}

    @api.onchange('sell_as', 'units_per_package')
    def _onchange_sell_as(self):
        for rec in self:
            if rec.sell_as == 'package':
                unit = rec.env.ref('uom.product_uom_unit', raise_if_not_found=False)
                if unit:
                    rec.uom_id = unit
                    rec.uom_po_id = unit
                rec.package_uom_id = False
                rec.units_per_package = 1

            elif rec.sell_as == 'unit' and rec.units_per_package > 0:
                unit_uom, pkg_uom = rec._get_or_create_package_uom()
                if unit_uom and pkg_uom:
                    rec.uom_id = unit_uom
                    rec.uom_po_id = pkg_uom
                    rec.package_uom_id = pkg_uom

    # ══════════════════════════════════════════════════════════════════════
    # UOM SETUP
    # ══════════════════════════════════════════════════════════════════════
    def _get_or_create_package_uom(self):
        self.ensure_one()
        if not self.name or self.units_per_package < 1:
            return False, False

        cat_name = 'Pkg/%s' % self.name
        category = self.env['uom.category'].search([('name', '=', cat_name)], limit=1)
        if not category:
            category = self.env['uom.category'].create({'name': cat_name})

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

    # ══════════════════════════════════════════════════════════════════════
    # COMPUTES
    # ══════════════════════════════════════════════════════════════════════
    @api.depends('list_price', 'units_per_package', 'sell_as')
    def _compute_unit_price(self):
        for rec in self:
            if rec.sell_as == 'unit' and rec.units_per_package > 0:
                rec.unit_price = rec.list_price / rec.units_per_package
            else:
                rec.unit_price = rec.list_price

    @api.depends('list_price', 'sell_as')
    def _compute_sales_price_inline(self):
        for rec in self:
            unit_label = 'Unit' if rec.sell_as == 'unit' else 'Package'
            currency = rec.currency_id or self.env.company.currency_id
            symbol = currency.symbol or currency.name or ''
            rec.sales_price_inline = f'{rec.list_price:.2f} {symbol} per {unit_label}'

    @api.depends('qty_available', 'units_per_package', 'sell_as')
    def _compute_display_stock(self):
        for rec in self:
            qty = rec.qty_available
            if rec.sell_as == 'unit' and rec.units_per_package > 0:
                full_packages = int(qty // rec.units_per_package)
                remaining_units = int(qty % rec.units_per_package)
                if remaining_units > 0:
                    rec.display_stock = f'{full_packages} Package ({remaining_units} Units)'
                else:
                    rec.display_stock = f'{full_packages} Package'
            else:
                rec.display_stock = f'{int(qty)} Package'

    @api.depends('product_variant_ids.qty_available', 'low_stock_limit')
    def _compute_is_low_stock(self):
        for tmpl in self:
            if tmpl.low_stock_limit > 0:
                qty = sum(tmpl.product_variant_ids.mapped('qty_available'))
                tmpl.is_low_stock = qty <= tmpl.low_stock_limit
            else:
                tmpl.is_low_stock = False

    @api.depends('product_variant_ids.standard_price', 'product_variant_ids.qty_available')
    def _compute_pharmacist_price(self):
        for tmpl in self:
            variants = tmpl.product_variant_ids
            total_value = sum(v.standard_price * v.qty_available for v in variants if v.qty_available > 0)
            total_qty = sum(v.qty_available for v in variants if v.qty_available > 0)
            if total_qty > 0:
                tmpl.pharmacist_price = total_value / total_qty
            else:
                prices = [v.standard_price for v in variants if v.standard_price > 0]
                tmpl.pharmacist_price = prices[0] if prices else 0.0

    @api.depends('pharmacist_price', 'product_variant_ids.standard_price')
    def _compute_pharmacist_price_display(self):
        for tmpl in self:
            has_purchase = self.env['stock.move'].sudo().search([
                ('product_id.product_tmpl_id', '=', tmpl.id),
                ('picking_id.picking_type_code', '=', 'incoming'),
                ('state', '=', 'done'),
            ], limit=1)
            if has_purchase and tmpl.pharmacist_price > 0:
                currency = tmpl.currency_id or self.env.company.currency_id
                tmpl.pharmacist_price_display = '{:.3f} {}'.format(
                    tmpl.pharmacist_price,
                    currency.symbol or currency.name,
                )
            else:
                tmpl.pharmacist_price_display = '—'

    # ══════════════════════════════════════════════════════════════════════
    # UNIFIED WRITE
    # ══════════════════════════════════════════════════════════════════════
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

        if 'classification' in vals and not self.env.context.get('_skip_classification_log'):
            selection_map = dict(self._fields['classification'].selection)
            for rec in self:
                old_val = selection_map.get(rec.classification, rec.classification)
                new_val = selection_map.get(vals['classification'], vals['classification'])
                if old_val != new_val:
                    rec.with_context(_skip_classification_log=True).message_post(
                        body=_(
                            '<b>Classification Changed</b><br/>'
                            'From: <b>%(old)s</b> To: <b>%(new)s</b>',
                            old=old_val,
                            new=new_val,
                        ),
                        subtype_xmlid='mail.mt_note',
                    )

        return super().write(vals)


class PharmacyLowStockOverrideLog(models.Model):
    _name = 'pharmacy.low.stock.override.log'
    _description = 'UC-11 — Low Stock Soft Warning Override Log'
    _order = 'timestamp desc'
    _rec_name = 'timestamp'

    product_id = fields.Many2one('product.template', string='Product', required=True, ondelete='cascade', index=True)
    qty_sold = fields.Float(string='Qty Sold', digits='Product Unit of Measure')
    max_qty_when_low = fields.Integer(string='Limit at Time of Sale')
    stock_at_sale = fields.Float(string='Stock Level at Time of Sale')
    user_id = fields.Many2one('res.users', string='Cashier', default=lambda self: self.env.user)
    timestamp = fields.Datetime(string='Timestamp', default=fields.Datetime.now, required=True)
    order_id = fields.Many2one('sale.order', string='Sale Order', readonly=True)
    note = fields.Char(string='Note')


class PharmacyInvoiceBlockLog(models.Model):
    _name = 'pharmacy.invoice.block.log'
    _description = 'UC-10 — Max Qty Invoice Hard Block Audit Log'
    _order = 'timestamp desc'
    _rec_name = 'timestamp'

    product_id = fields.Many2one('product.template', string='Product', required=True, ondelete='cascade', index=True)
    qty_attempted = fields.Float(string='Qty Attempted', digits='Product Unit of Measure')
    qty_limit = fields.Integer(string='Qty Limit')
    user_id = fields.Many2one('res.users', string='Blocked User', default=lambda self: self.env.user)
    timestamp = fields.Datetime(string='Timestamp', default=fields.Datetime.now, required=True)
    override_by = fields.Many2one('res.users', string='Override By', readonly=True)
    overridden = fields.Boolean(string='Override Applied', default=False)
    note = fields.Char(string='Note')


class PharmacyCostHistory(models.Model):
    _name = 'pharmacy.cost.history'
    _description = 'Pharmacy Product Cost History (UC-08)'
    _order = 'date desc'
    _rec_name = 'date'

    product_tmpl_id = fields.Many2one('product.template', string='Product', required=True, ondelete='cascade', index=True)
    date = fields.Datetime(string='Date', required=True, default=fields.Datetime.now)
    cost = fields.Float(string='Avg. Cost at Time', digits=(16, 3), required=True)
    qty_received = fields.Float(string='Qty Received', digits='Product Unit of Measure')
    unit_purchase_price = fields.Float(string='Unit Purchase Price', digits=(16, 3))
    picking_id = fields.Many2one('stock.picking', string='Source Receipt', readonly=True)
    purchase_order_id = fields.Many2one('purchase.order', string='Purchase Order', readonly=True)
    note = fields.Char(string='Note')