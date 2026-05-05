from odoo import api, fields, models, _


class PharmacyPurchaseDiscountHistory(models.Model):
    _name = 'pharmacy.purchase.discount.history'
    _description = 'Pharmacy Purchase Discount History'
    _order = 'invoice_date desc, id desc'
    _rec_name = 'display_name'

    display_name = fields.Char(compute='_compute_display_name', store=False)
    product_tmpl_id = fields.Many2one(
        'product.template',
        string='Product',
        required=True,
        index=True,
        ondelete='cascade',
    )
    product_id = fields.Many2one(
        'product.product',
        string='Variant',
        index=True,
        ondelete='set null',
    )
    partner_id = fields.Many2one(
        'res.partner',
        string='Supplier',
        index=True,
        ondelete='set null',
    )
    move_id = fields.Many2one(
        'account.move',
        string='Supplier Invoice',
        index=True,
        ondelete='cascade',
    )
    purchase_order_id = fields.Many2one(
        'purchase.order',
        string='Purchase Order',
        index=True,
        ondelete='cascade',
    )
    invoice_date = fields.Date(string='Date', index=True)
    discount = fields.Float(string='Discount %', digits=(5, 2))
    user_id = fields.Many2one('res.users', string='Updated By', default=lambda self: self.env.user)
    company_id = fields.Many2one('res.company', string='Company', default=lambda self: self.env.company, index=True)

    @api.depends('product_tmpl_id', 'discount', 'invoice_date', 'move_id', 'purchase_order_id')
    def _compute_display_name(self):
        for rec in self:
            product = rec.product_tmpl_id.display_name or _('Product')
            source = rec.move_id.name or rec.move_id.ref or rec.purchase_order_id.name or '-'
            rec.display_name = _('%(product)s - %(discount).2f%% - %(source)s') % {
                'product': product,
                'discount': rec.discount or 0.0,
                'source': source,
            }


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    discount_history_ids = fields.One2many(
        'pharmacy.purchase.discount.history',
        'product_tmpl_id',
        string='Discount History',
        readonly=True,
        groups='pharmacy.group_pharmacy_manager,pharmacy.group_pharmacy_pharmacist',
    )

    last_purchase_discount_display = fields.Char(
        string='Last Purchase Discount (%)',
        compute='_compute_last_purchase_discount_display',
        readonly=True,
        groups='pharmacy.group_pharmacy_manager,pharmacy.group_pharmacy_pharmacist',
        help='Last supplier, purchase date, and invoice reference are shown in the fields below.',
    )

    @api.depends('last_purchase_discount', 'last_purchase_discount_date')
    def _compute_last_purchase_discount_display(self):
        for product in self:
            if product.last_purchase_discount_date:
                product.last_purchase_discount_display = '%.2f%%' % (product.last_purchase_discount or 0.0)
            else:
                product.last_purchase_discount_display = '—'
