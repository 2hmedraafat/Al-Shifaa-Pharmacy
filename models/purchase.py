from odoo import models, fields, api, _
from odoo.exceptions import ValidationError


class PurchaseOrderLine(models.Model):
    _inherit = 'purchase.order.line'

    allowed_purchase_uom_ids = fields.Many2many(
        'uom.uom',
        compute='_compute_allowed_purchase_uom_ids',
        string='Allowed Purchase UoMs',
    )

    purchase_uom_display = fields.Char(
        string='UoM',
        compute='_compute_purchase_uom_display',
    )

    purchase_package_qty_display = fields.Char(
        string='Package Quantity',
        compute='_compute_purchase_package_qty_display',
    )

    @api.depends('product_id', 'product_id.product_tmpl_id.package_uom_id')
    def _compute_allowed_purchase_uom_ids(self):
        for line in self:
            tmpl = line.product_id.product_tmpl_id
            if tmpl and tmpl.package_uom_id:
                line.allowed_purchase_uom_ids = tmpl.package_uom_id
            else:
                line.allowed_purchase_uom_ids = self.env['uom.uom']

    @api.depends('product_id', 'product_uom')
    def _compute_purchase_uom_display(self):
        for line in self:
            line.purchase_uom_display = 'Package' if line.product_id else ''

    @api.depends('product_id', 'product_id.product_tmpl_id.units_per_package')
    def _compute_purchase_package_qty_display(self):
        for line in self:
            if line.product_id:
                units = int(line.product_id.product_tmpl_id.units_per_package or 1)
                line.purchase_package_qty_display = '%s Unit%s' % (units, '' if units == 1 else 's')
            else:
                line.purchase_package_qty_display = ''

    def _get_product_package_uom(self):
        self.ensure_one()
        if not self.product_id:
            return False

        tmpl = self.product_id.product_tmpl_id
        package_uom = tmpl.package_uom_id

        if not package_uom or package_uom.category_id != tmpl.uom_id.category_id:
            package_uom = tmpl.sudo()._sync_package_uom()

        return package_uom

    @api.onchange('product_id')
    def _onchange_product_id_force_package_uom(self):
        """Purchase is always in the product Package UoM."""
        for line in self:
            package_uom = line._get_product_package_uom()
            if package_uom:
                line.product_uom = package_uom
                line.purchase_uom_display = 'Package'
                units = int(line.product_id.product_tmpl_id.units_per_package or 1)
                line.purchase_package_qty_display = '%s Unit%s' % (units, '' if units == 1 else 's')
                return {
                    'domain': {
                        'product_uom': [('id', '=', package_uom.id)]
                    }
                }
        return {'domain': {'product_uom': []}}

    @api.onchange('product_uom')
    def _onchange_product_uom_force_package(self):
        """Revert if user manually changes to anything other than Package."""
        for line in self:
            if not line.product_id:
                continue
            package_uom = line._get_product_package_uom()
            if package_uom:
                line.purchase_uom_display = 'Package'
                units = int(line.product_id.product_tmpl_id.units_per_package or 1)
                line.purchase_package_qty_display = '%s Unit%s' % (units, '' if units == 1 else 's')
            if package_uom and line.product_uom != package_uom:
                line.product_uom = package_uom
                return {
                    'warning': {
                        'title': _('Invalid Unit of Measure'),
                        'message': _('Purchase must be done by Package only.'),
                    },
                    'domain': {
                        'product_uom': [('id', '=', package_uom.id)]
                    }
                }
        return {}

    @api.constrains('product_id', 'product_uom')
    def _check_purchase_uom_is_product_package(self):
        for line in self:
            if not line.product_id or not line.product_uom:
                continue

            tmpl = line.product_id.product_tmpl_id
            package_uom = tmpl.package_uom_id

            if package_uom and line.product_uom != package_uom:
                raise ValidationError(_(
                    'Purchase UoM must be Package only for product "%s".'
                ) % line.product_id.display_name)

    def _pharmacy_get_last_purchase_discount(self):
        self.ensure_one()
        if not self.product_id:
            return 0.0
        return self.product_id.product_tmpl_id.sudo().last_purchase_discount or 0.0

    def _pharmacy_apply_last_purchase_discount(self):
        """SC1-UC-01: default PO line discount from product latest purchase discount."""
        for line in self:
            if line.product_id and 'discount' in line._fields:
                line.discount = line._pharmacy_get_last_purchase_discount()

    @api.onchange('product_id')
    def _onchange_product_id_apply_last_purchase_discount(self):
        self._pharmacy_apply_last_purchase_discount()

    @api.onchange('price_unit', 'product_qty', 'product_uom', 'taxes_id')
    def _onchange_purchase_line_values_apply_last_purchase_discount(self):
        """Keep the PO line default discount visible after Odoo product onchange fills price/taxes.

        In editable purchase order lines, Odoo may set price/taxes after product_id onchange
        and leave Disc.% at 0. This second onchange reapplies the saved product discount
        while the line is still new and the user has not entered another discount.
        """
        if 'discount' not in self._fields:
            return
        for line in self:
            if not line.product_id:
                continue
            last_discount = line._pharmacy_get_last_purchase_discount()
            if last_discount and not (line.discount or 0.0):
                line.discount = last_discount

    @api.model_create_multi
    def create(self, vals_list):
        if 'discount' in self._fields:
            for vals in vals_list:
                if vals.get('product_id') and not (vals.get('discount') or 0.0):
                    product = self.env['product.product'].browse(vals['product_id'])
                    vals['discount'] = product.product_tmpl_id.sudo().last_purchase_discount or 0.0
        return super().create(vals_list)



class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

    def button_confirm(self):
        res = super().button_confirm()
        self._pharmacy_update_last_purchase_discount_from_po()
        return res

    def _pharmacy_update_last_purchase_discount_from_po(self):
        """SC1-UC-01: capture confirmed Purchase Order line discounts into product history.

        Vendor Bills remain supported separately; this covers the purchase operation itself.
        If the same product appears more than once on a PO, the highest line discount is used.
        """
        History = self.env['pharmacy.purchase.discount.history'].sudo()
        for order in self.sudo():
            if order.state not in ('purchase', 'done'):
                continue
            doc_date = fields.Date.to_date(order.date_approve or order.date_order or fields.Date.context_today(order))
            best_by_template = {}
            for line in order.order_line.filtered(lambda l: l.product_id and not l.display_type):
                discount = line.discount if 'discount' in line._fields else 0.0
                discount = discount or 0.0
                tmpl = line.product_id.product_tmpl_id.sudo()
                current = best_by_template.get(tmpl.id)
                if not current or discount > current['discount']:
                    best_by_template[tmpl.id] = {
                        'template': tmpl,
                        'product': line.product_id.sudo(),
                        'discount': discount,
                    }

            for data in best_by_template.values():
                product_tmpl = data['template']
                values = {
                    'product_tmpl_id': product_tmpl.id,
                    'product_id': data['product'].id,
                    'partner_id': order.partner_id.id or False,
                    'purchase_order_id': order.id,
                    'move_id': False,
                    'invoice_date': doc_date,
                    'discount': data['discount'],
                    'user_id': self.env.user.id,
                    'company_id': order.company_id.id or self.env.company.id,
                }
                existing = History.search([
                    ('product_tmpl_id', '=', product_tmpl.id),
                    ('purchase_order_id', '=', order.id),
                ], limit=1)
                if existing:
                    existing.write(values)
                else:
                    History.create(values)
                product_tmpl._pharmacy_recompute_last_purchase_discount()

    def button_cancel(self):
        affected_products = self.mapped('order_line.product_id.product_tmpl_id').sudo()
        res = super().button_cancel()
        if affected_products:
            affected_products._pharmacy_recompute_last_purchase_discount()
        return res
