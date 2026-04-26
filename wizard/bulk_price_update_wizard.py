from odoo import models, fields, api, _
from odoo.exceptions import ValidationError, AccessError


class PharmacyBulkPriceUpdateWizard(models.TransientModel):
    _name = 'pharmacy.bulk.price.update.wizard'
    _description = 'UC-07 — Bulk Public Price Update Wizard'

    product_ids = fields.Many2many(
        'product.template',
        string='Products',
        required=True,
        domain=[('sale_ok', '=', True)],
    )

    update_type = fields.Selection(
        selection=[
            ('percentage', 'Percentage Increase / Decrease'),
            ('fixed', 'Fixed Amount Increase / Decrease'),
        ],
        string='Update Type',
        default='percentage',
        required=True,
    )

    percentage = fields.Float(
        string='Percentage %',
        help='Use positive value to increase and negative value to decrease.',
    )

    fixed_amount = fields.Float(
        string='Fixed Amount',
        digits='Product Price',
        help='Use positive value to increase and negative value to decrease.',
    )

    skip_locked_products = fields.Boolean(
        string='Skip Government Locked Products',
        default=False,
        help='If enabled, locked products are skipped instead of blocking the wizard.',
    )

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        active_ids = self.env.context.get('active_ids') or []

        if active_ids and self.env.context.get('active_model') == 'product.template':
            res['product_ids'] = [(6, 0, active_ids)]

        return res

    def _check_price_manager_access(self):
        if not (
            self.env.user.has_group('pharmacy.group_pharmacy_price_manager')
            or self.env.user.has_group('pharmacy.group_pharmacy_manager')
            or self.env.is_superuser()
        ):
            raise AccessError(_('Only Pharmacy Price Manager can use Bulk Price Update.'))

    def action_apply(self):
        self.ensure_one()
        self._check_price_manager_access()

        if not self.product_ids:
            raise ValidationError(_('Please select at least one product.'))

        products = self.product_ids

        if self.skip_locked_products:
            products = products.filtered(lambda product: not product.government_price_lock)

        if not products:
            raise ValidationError(_('No products to update. All selected products are locked.'))

        locked_products = products.filtered(lambda product: product.government_price_lock)
        if locked_products and not (
            self.env.user.has_group('pharmacy.group_pharmacy_manager')
            or self.env.is_superuser()
        ):
            raise AccessError(_('Only Pharmacy Manager can bulk-update government locked products.'))

        for product in products:
            old_price = product.list_price

            if self.update_type == 'percentage':
                new_price = old_price + (old_price * self.percentage / 100.0)
            else:
                new_price = old_price + self.fixed_amount

            if new_price <= 0:
                raise ValidationError(_(
                    'New price for product "%(product)s" must be greater than 0.',
                    product=product.display_name,
                ))

            product.with_context(price_change_source='bulk_update').write({
                'list_price': new_price,
            })

        return {'type': 'ir.actions.act_window_close'}