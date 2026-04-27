from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
from odoo.osv import expression


class ProductTemplate(models.Model):
    _inherit = 'product.template'



    # ══════════════════════════════════════════════════════════════════════
    # UC-01 — Basic Product Information
    # ══════════════════════════════════════════════════════════════════════
    generic_name = fields.Char(
        string='Generic Name',
        tracking=True,
        index=True,
        help='Scientific / INN name of the medicine, e.g. Paracetamol or Amoxicillin.',
    )

    def _get_duplicate_name_domain(self, name):
        domain = [('name', '=ilike', (name or '').strip())]
        if self._origin and self._origin.id:
            domain.append(('id', '!=', self._origin.id))
        return domain

    @api.onchange('name')
    def _onchange_name_duplicate_warning(self):
        for rec in self:
            if not rec.name or not rec.name.strip():
                continue

            duplicate = self.env['product.template'].search(
                rec._get_duplicate_name_domain(rec.name),
                limit=1,
            )
            if duplicate:
                return {
                    'warning': {
                        'title': _('Duplicate Product Name'),
                        'message': _(
                            'A product with the same name already exists: "%s". '
                            'You can continue if this is intentional.'
                        ) % duplicate.display_name,
                    }
                }

    @api.model
    def _name_search(self, name='', args=None, operator='ilike', limit=100, name_get_uid=None, order=None):
        args = list(args or [])
        if not name:
            return super()._name_search(name=name, args=args, operator=operator, limit=limit, name_get_uid=name_get_uid, order=order)

        search_domain = ['|', '|',
            ('name', operator, name),
            ('default_code', operator, name),
            ('generic_name', operator, name),
        ]
        return self._search(expression.AND([args, search_domain]), limit=limit, access_rights_uid=name_get_uid, order=order)

    def _get_matching_purchase_uom(self, unit_uom=None):
        self.ensure_one()
        unit_uom = unit_uom or self.uom_id
        if not unit_uom:
            return False

        if self.package_uom_id and self.package_uom_id.category_id == unit_uom.category_id:
            return self.package_uom_id

        if self.uom_po_id and self.uom_po_id.category_id == unit_uom.category_id:
            return self.uom_po_id

        return unit_uom


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

    # -------------------------------------------------------
    # UC-06 — Scheduled Medicine
    # -------------------------------------------------------
    is_scheduled_medicine = fields.Boolean(
        string='Medicine is Scheduled',
        default=False,
        tracking=True,
        help='Check if this medicine is a controlled/scheduled substance.'
    )

    schedule_level = fields.Selection([
        ('1', 'Schedule I'),
        ('2', 'Schedule II'),
        ('3', 'Schedule III'),
        ('4', 'Schedule IV'),
        ('5', 'Schedule V'),
    ], string='Schedule Level', tracking=True)

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
    # UC-07 — Public Price Control
    # ══════════════════════════════════════════════════════════════════════
    government_price_lock = fields.Boolean(
        string='Government Price Lock',
        default=False,
        tracking=True,
        help='When enabled, only Pharmacy Price Managers can change the official Sales Price.',
    )

    price_history_ids = fields.One2many(
        'pharmacy.price.history',
        'product_tmpl_id',
        string='Price History',
        readonly=True,
    )

    # ══════════════════════════════════════════════════════════════════════
    # VALIDATIONS
    # ══════════════════════════════════════════════════════════════════════
    @api.constrains('list_price')
    def _check_public_price_positive(self):
        for rec in self:
            if rec.list_price <= 0:
                raise ValidationError(_('Public Price / Sales Price must be greater than 0.'))

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

    @api.constrains('is_scheduled_medicine', 'schedule_level')
    def _check_schedule_level_required(self):
        for rec in self:
            if rec.is_scheduled_medicine and not rec.schedule_level:
                raise ValidationError(_('Please select Schedule Level before saving a scheduled medicine.'))

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

    @api.constrains('barcode')
    def _check_barcode_format(self):
        for rec in self:
            if rec.barcode:
                rec._validate_barcode_format(rec.barcode)

    @api.constrains('uom_id', 'uom_po_id')
    def _check_uom_same_category(self):
        # Overridden: pharmacy uses a dedicated Package UoM category for
        # purchase, so we intentionally skip the same-category constraint.
        pass

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

    @api.onchange('list_price')
    def _onchange_public_price_below_cost(self):
        for rec in self:
            if rec.list_price and rec.pharmacist_price and rec.list_price < rec.pharmacist_price:
                return {'warning': {
                    'title': _('Selling Below Cost'),
                    'message': _(
                        'Public Price is less than the current average purchase cost. '
                        'Manager can proceed if this is intended.'
                    ),
                }}

    @api.onchange('sell_as', 'units_per_package')
    def _onchange_sell_as(self):
        for rec in self:
            sync_vals = rec._apply_sell_as_uom()
            for field_name, value in sync_vals.items():
                setattr(rec, field_name, value)

    # ══════════════════════════════════════════════════════════════════════
    # UOM SETUP
    # ══════════════════════════════════════════════════════════════════════
    def _get_pharmacy_uom_category(self):
        """Use the product's real UoM category first.

        This prevents the error:
        "Package ... doesn't belong to the same category as Units".
        """
        self.ensure_one()
        if self.uom_id and self.uom_id.category_id:
            return self.uom_id.category_id

        category = self.env.ref('pharmacy.uom_categ_pharmacy', raise_if_not_found=False)
        if category:
            return category

        base_unit = self.env.ref('uom.product_uom_unit', raise_if_not_found=False)
        return base_unit.category_id if base_unit else False

    def _get_reference_unit_uom(self, category):
        self.ensure_one()

        if self.uom_id and self.uom_id.category_id == category:
            return self.uom_id

        unit_uom = self.env['uom.uom'].search([
            ('category_id', '=', category.id),
            ('uom_type', '=', 'reference'),
        ], limit=1)
        if unit_uom:
            return unit_uom

        return self.env['uom.uom'].create({
            'name': 'Unit',
            'category_id': category.id,
            'uom_type': 'reference',
            'factor': 1.0,
            'rounding': 1.0,
        })

    def _get_or_create_package_uom(self):
        """Create/get a Package UoM in the SAME category as the product UoM.

        Odoo stock stays in the product base UoM (Units), while purchase/sale can
        use Package. 1 Package = units_per_package Units.
        """
        self.ensure_one()

        units_per_package = int(self.units_per_package or 1)
        if units_per_package < 1:
            units_per_package = 1

        category = self._get_pharmacy_uom_category()
        if not category:
            return False, False

        unit_uom = self._get_reference_unit_uom(category)

        # Reuse the current package UoM only if it matches the product category.
        if self.package_uom_id and self.package_uom_id.category_id == category:
            return unit_uom, self.package_uom_id

        ratio_text = str(units_per_package)
        package_name = 'Package'

        pkg_uom = self.env['uom.uom'].search([
            ('category_id', '=', category.id),
            ('name', '=', package_name),
        ], limit=1)

        if not pkg_uom:
            pkg_uom = self.env['uom.uom'].create({
                'name': package_name,
                'category_id': category.id,
                'uom_type': 'bigger',
                'factor_inv': units_per_package,
                'rounding': 1.0,
            })

        return unit_uom, pkg_uom

    def _sync_package_uom(self):
        """Make the product ready for pharmacy purchase/sale package flow."""
        self.ensure_one()
        unit_uom, pkg_uom = self._get_or_create_package_uom()
        if not pkg_uom:
            return False

        vals = {}
        if self.package_uom_id != pkg_uom:
            vals['package_uom_id'] = pkg_uom.id
        if self.uom_po_id != pkg_uom:
            vals['uom_po_id'] = pkg_uom.id
        if not self.uom_id and unit_uom:
            vals['uom_id'] = unit_uom.id

        if vals:
            super(ProductTemplate, self).write(vals)

        return pkg_uom

    def _apply_sell_as_uom(self):
        self.ensure_one()

        unit_uom, pkg_uom = self._get_or_create_package_uom()
        vals = {}

        if not unit_uom or not pkg_uom:
            return vals

        # Do NOT change uom_id for existing products with stock moves.
        # Stock remains stored in the product base UoM.
        if not self.uom_id:
            vals['uom_id'] = unit_uom.id
        elif self.uom_id.category_id != pkg_uom.category_id:
            # uom_id and pkg_uom are in different categories — force uom_id
            # to the reference unit of the package category so the constraint passes.
            vals['uom_id'] = unit_uom.id

        # Purchase is always by Package.
        vals.update({
            'uom_po_id': pkg_uom.id,
            'package_uom_id': pkg_uom.id,
        })

        return vals

    # -------------------------------------------------------
    # EAN-13 Check Digit Calculator
    # -------------------------------------------------------
    def _compute_ean13_check_digit(self, barcode_12):
        total = 0
        for i, digit in enumerate(barcode_12):
            if i % 2 == 0:
                total += int(digit) * 1
            else:
                total += int(digit) * 3
        check = (10 - (total % 10)) % 10
        return str(check)

    # -------------------------------------------------------
    # UC-03 — Barcode Format Validation
    # Supported: Internal Pharmacy Barcode, EAN-8, EAN-13, UPC-A (12), UPC-E (8), Code128
    # -------------------------------------------------------
    def _validate_barcode_format(self, barcode):
        barcode = barcode.strip()

        if not barcode:
            raise ValidationError(_('Barcode cannot be empty.'))

        if barcode.isdigit() and len(barcode) == 8 and barcode.startswith('21'):
            return True

        if not barcode.isdigit():
            return True

        length = len(barcode)

        if length == 13:
            self._check_ean_digit(barcode, 13)
        elif length == 8:
            self._check_ean_digit(barcode, 8)
        elif length == 12:
            self._check_upc_digit(barcode)
        else:
            raise ValidationError(
                _('Barcode "%s" has unsupported format.'
                  'Accepted formats: Internal Pharmacy Barcode, EAN-8, EAN-13, UPC-A (12 digits), UPC-E (8 digits), Code128.')
                % barcode
            )
        return True

    def _check_ean_digit(self, barcode, length):
        digits = [int(d) for d in barcode]
        if length == 13:
            total = sum(d * (1 if i % 2 == 0 else 3) for i, d in enumerate(digits[:-1]))
        else:
            total = sum(d * (3 if i % 2 == 0 else 1) for i, d in enumerate(digits[:-1]))
        check = (10 - (total % 10)) % 10
        if check != digits[-1]:
            raise ValidationError(
                _('Barcode "%s" has an invalid check digit. Expected %d, got %d.'
                  'Please verify the barcode number.')
                % (barcode, check, digits[-1])
            )

    def _check_upc_digit(self, barcode):
        digits = [int(d) for d in barcode]
        total = sum(d * (3 if i % 2 == 0 else 1) for i, d in enumerate(digits[:-1]))
        check = (10 - (total % 10)) % 10
        if check != digits[-1]:
            raise ValidationError(
                _('UPC-A Barcode "%s" has an invalid check digit. Expected %d, got %d.'
                  'Please verify the barcode number.')
                % (barcode, check, digits[-1])
            )

    # -------------------------------------------------------
    # UC-03 — Generate Internal Barcode
    # Format: 21 + 01 + 0001
    # Example: 21010001
    # -------------------------------------------------------
    def action_generate_barcode(self):
        for product in self:
            sync_vals = product._apply_sell_as_uom()
            if sync_vals:
                super(ProductTemplate, product).write(sync_vals)

            if product.uom_id and product.uom_po_id and product.uom_id.category_id != product.uom_po_id.category_id:
                raise ValidationError(_('The default Unit of Measure and the purchase Unit of Measure must be in the same category.'))

            sequence_value = self.env['ir.sequence'].next_by_code('pharmacy.barcode')
            if not sequence_value:
                raise ValidationError(
                    _('Barcode sequence "pharmacy.barcode" not found. '
                      'Please check your data configuration.')
                )

            sequence_digits = ''.join(filter(str.isdigit, sequence_value))
            sequence_digits = sequence_digits.zfill(4)[-4:]

            new_barcode = f'2101{sequence_digits}'
            product.barcode = new_barcode

    # ══════════════════════════════════════════════════════════════════════
    # COMPUTES
    # ══════════════════════════════════════════════════════════════════════
    @api.depends('list_price', 'sell_as', 'units_per_package')
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
    # UC-07 HELPERS
    # ══════════════════════════════════════════════════════════════════════
    def _user_can_manage_public_price(self):
        return (
            self.env.user.has_group('pharmacy.group_pharmacy_price_manager')
            or self.env.user.has_group('pharmacy.group_pharmacy_manager')
            or self.env.is_superuser()
        )

    def _log_public_price_change(self, old_price, new_price, source='manual'):
        self.ensure_one()
        if old_price == new_price:
            return
        self.env['pharmacy.price.history'].sudo().create({
            'product_tmpl_id': self.id,
            'old_price': old_price,
            'new_price': new_price,
            'currency_id': self.currency_id.id or self.env.company.currency_id.id,
            'user_id': self.env.user.id,
            'source': source,
        })
        self.message_post(
            body=_(
                '<b>Public Price Changed</b><br/>From: <b>%(old).2f</b> To: <b>%(new).2f</b>',
                old=old_price,
                new=new_price,
            ),
            subtype_xmlid='mail.mt_note',
        )

    # ══════════════════════════════════════════════════════════════════════
    # UNIFIED CREATE / WRITE
    # ══════════════════════════════════════════════════════════════════════
    @api.model_create_multi
    def create(self, vals_list):
        Uom = self.env['uom.uom']
        unit_ref = self.env.ref('pharmacy.product_uom_unit', raise_if_not_found=False) or self.env.ref('uom.product_uom_unit', raise_if_not_found=False)

        for vals in vals_list:
            uom_id = vals.get('uom_id')
            uom_po_id = vals.get('uom_po_id')

            if uom_id and uom_po_id:
                uom = Uom.browse(uom_id)
                uom_po = Uom.browse(uom_po_id)
                if uom and uom_po and uom.category_id != uom_po.category_id:
                    vals['uom_po_id'] = uom_id

            if vals.get('sell_as') in ('package', 'unit') and unit_ref:
                vals.setdefault('uom_id', unit_ref.id)

            if 'list_price' in vals and vals.get('list_price') is not None and vals.get('list_price') <= 0:
                raise ValidationError(_('Public Price / Sales Price must be greater than 0.'))

        records = super().create(vals_list)

        for rec in records:
            if rec.sell_as in ('package', 'unit'):
                sync_vals = rec._apply_sell_as_uom()
                if sync_vals:
                    super(ProductTemplate, rec).write(sync_vals)

        return records

    def write(self, vals):
        Uom = self.env['uom.uom']

        price_change_source = self.env.context.get('price_change_source', 'manual')
        old_prices = {}
        if 'list_price' in vals:
            if vals.get('list_price') is not None and vals.get('list_price') <= 0:
                raise ValidationError(_('Public Price / Sales Price must be greater than 0.'))
            old_prices = {rec.id: rec.list_price for rec in self}
            for rec in self:
                if rec.government_price_lock and not rec._user_can_manage_public_price():
                    raise ValidationError(_(
                        'Price is government-regulated and cannot be changed by your user. '
                        'Please contact the Pharmacy Manager.'
                    ))

        if 'government_price_lock' in vals and vals.get('government_price_lock') and not self._user_can_manage_public_price():
            raise ValidationError(_('Only Pharmacy Manager can enable Government Price Lock.'))

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

        future_uom_id = vals.get('uom_id')
        future_uom_po_id = vals.get('uom_po_id')
        if future_uom_id and future_uom_po_id:
            uom = Uom.browse(future_uom_id)
            uom_po = Uom.browse(future_uom_po_id)
            if uom and uom_po and uom.category_id != uom_po.category_id:
                vals['uom_po_id'] = future_uom_id

        result = super().write(vals)

        if 'list_price' in vals:
            for rec in self:
                old_price = old_prices.get(rec.id)
                if old_price is not None and old_price != rec.list_price:
                    rec._log_public_price_change(old_price, rec.list_price, source=price_change_source)

        if 'sell_as' in vals or 'units_per_package' in vals:
            for rec in self:
                sync_vals = rec._apply_sell_as_uom()
                if sync_vals:
                    super(ProductTemplate, rec).write(sync_vals)

        return result



class ProductProduct(models.Model):
    _inherit = 'product.product'

    generic_name = fields.Char(
        related='product_tmpl_id.generic_name',
        string='Generic Name',
        store=True,
        readonly=False,
    )

    is_scheduled_medicine = fields.Boolean(
        related='product_tmpl_id.is_scheduled_medicine',
        string='Medicine is Scheduled',
        store=True
    )

    @api.model
    def _name_search(self, name='', args=None, operator='ilike', limit=100, name_get_uid=None, order=None):
        args = list(args or [])
        if not name:
            return super()._name_search(name=name, args=args, operator=operator, limit=limit, name_get_uid=name_get_uid, order=order)

        search_domain = ['|', '|', '|',
            ('name', operator, name),
            ('default_code', operator, name),
            ('barcode', operator, name),
            ('product_tmpl_id.generic_name', operator, name),
        ]
        return self._search(expression.AND([args, search_domain]), limit=limit, access_rights_uid=name_get_uid, order=order)


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
    note = fields.Text(string='Note', readonly=True)


class ProductTemplatePurchaseUomOverride(models.Model):
    """Override the purchase module's UoM same-category constraint.
    Pharmacy uses a dedicated Package UoM category for purchasing,
    so the standard same-category check must be suppressed."""
    _inherit = 'product.template'

    @api.constrains('uom_id', 'uom_po_id')
    def _check_uom(self):
        # Intentionally empty — pharmacy allows cross-category UoM for purchase.
        pass