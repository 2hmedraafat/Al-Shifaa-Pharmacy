from odoo import api, fields, models, _
from odoo.exceptions import ValidationError
class StockLocation(models.Model):
    _inherit = 'stock.location'

    usage = fields.Selection(
        selection_add=[('expired', 'Expired')],
        ondelete={'expired': 'set default'},
    )

    is_expired_location = fields.Boolean(
        string='Expired Product Location',
        compute='_compute_is_expired_location',
        store=True,
        index=True,
        help='Technical safety flag. Stock here is excluded from POS, sales availability, forecasting, and reorder rules.',
    )

    @api.depends('usage')
    def _compute_is_expired_location(self):
        for location in self:
            location.is_expired_location = location.usage == 'expired'

    @api.constrains('usage')
    def _check_expired_location_is_not_scrap_or_replenishment(self):
        for location in self:
            if location.usage == 'expired' and getattr(location, 'scrap_location', False):
                raise ValidationError(_('Expired locations cannot be configured as Scrap Locations.'))
            if location.usage == 'expired' and getattr(location, 'replenish_location', False):
                raise ValidationError(_('Expired locations cannot be configured as Replenishment Locations.'))


class ProductProduct(models.Model):
    _inherit = 'product.product'

    pharmacy_saleable_qty = fields.Float(
        string='Saleable Qty (Excluding Expired Locations)',
        compute='_compute_pharmacy_saleable_qty',
        search='_search_pharmacy_saleable_qty',
        digits='Product Unit of Measure',
        help='Available quantity in normal internal locations only. Expired locations are always excluded.',
    )

    def _pharmacy_saleable_quant_domain(self):
        return [
            ('product_id', 'in', self.ids),
            ('location_id.usage', '=', 'internal'),
            ('location_id.is_expired_location', '=', False),
        ]

    def _pharmacy_get_saleable_qty_map(self):
        products = self.exists()
        result = {product.id: 0.0 for product in products}
        if not products:
            return result

        groups = self.env['stock.quant'].sudo().read_group(
            products._pharmacy_saleable_quant_domain(),
            ['quantity:sum', 'reserved_quantity:sum'],
            ['product_id'],
        )
        for group in groups:
            product_id = group['product_id'][0]
            qty = (group.get('quantity') or 0.0) - (group.get('reserved_quantity') or 0.0)
            result[product_id] = max(qty, 0.0)
        return result

    @api.depends_context('company', 'warehouse')
    def _compute_pharmacy_saleable_qty(self):
        qty_map = self._pharmacy_get_saleable_qty_map()
        for product in self:
            product.pharmacy_saleable_qty = qty_map.get(product.id, 0.0)


    @api.model
    def _load_pos_data_fields(self, config_id):
        """Odoo 18 POS loader: make saleable qty available in the POS product cache.

        Without this, POS receives the product without pharmacy_saleable_qty,
        so the JS safety limit treats it as unknown and cannot block extra clicks.
        """
        fields_list = super()._load_pos_data_fields(config_id)
        if 'pharmacy_saleable_qty' not in fields_list:
            fields_list.append('pharmacy_saleable_qty')
        return fields_list

    @api.model
    def _search_pharmacy_saleable_qty(self, operator, value):
        products = self.search([])
        qty_map = products._pharmacy_get_saleable_qty_map()

        def _match(qty):
            if operator == '>':
                return qty > value
            if operator == '>=':
                return qty >= value
            if operator == '<':
                return qty < value
            if operator == '<=':
                return qty <= value
            if operator == '=':
                return qty == value
            if operator == '!=':
                return qty != value
            if operator in ('in', 'not in'):
                matched = qty in value
                return matched if operator == 'in' else not matched
            return False

        matched_ids = [product_id for product_id, qty in qty_map.items() if _match(qty)]
        return [('id', 'in', matched_ids or [0])]


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    pharmacy_saleable_qty = fields.Float(
        string='Saleable Qty (Excluding Expired Locations)',
        compute='_compute_pharmacy_template_saleable_qty',
        search='_search_pharmacy_template_saleable_qty',
        digits='Product Unit of Measure',
        help='Total saleable quantity of all variants excluding Expired locations.',
    )

    @api.depends('product_variant_ids.pharmacy_saleable_qty')
    def _compute_pharmacy_template_saleable_qty(self):
        for template in self:
            template.pharmacy_saleable_qty = sum(template.product_variant_ids.mapped('pharmacy_saleable_qty'))

    @api.model
    def _search_pharmacy_template_saleable_qty(self, operator, value):
        product_domain = [('pharmacy_saleable_qty', operator, value)]
        products = self.env['product.product'].search(product_domain)
        return [('id', 'in', products.mapped('product_tmpl_id').ids or [0])]


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    def _pharmacy_check_no_expired_stock_used(self):
        """Patient safety gate: SO confirmation can only use normal internal stock."""
        errors = []
        for order in self:
            for line in order.order_line.filtered(lambda l: l.product_id and l.product_id.type != 'service'):
                product = line.product_id
                requested_qty = line.product_uom._compute_quantity(
                    line.product_uom_qty,
                    product.uom_id,
                    rounding_method='HALF-UP',
                ) if line.product_uom else line.product_uom_qty
                saleable_qty = product.pharmacy_saleable_qty
                if requested_qty > saleable_qty:
                    errors.append(_(
                        '%(product)s: requested %(requested).2f %(uom)s, saleable %(saleable).2f %(uom)s. '
                        'Expired-location stock is excluded for patient safety.',
                        product=product.display_name,
                        requested=requested_qty,
                        saleable=saleable_qty,
                        uom=product.uom_id.display_name,
                    ))
        if errors:
            raise ValidationError(_('Cannot confirm this Sale Order because available stock exists only in normal saleable locations.\n\n%s') % '\n'.join(errors))

    def action_confirm(self):
        self._pharmacy_check_no_expired_stock_used()
        return super().action_confirm()
