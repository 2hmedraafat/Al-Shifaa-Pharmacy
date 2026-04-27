from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
import logging

_logger = logging.getLogger(__name__)


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    # ── UC-09 — Commission ────────────────────────────────────────────────
    commission_amount = fields.Float(
        string='Commission Amount',
        compute='_compute_commission_amount',
        store=True,
        readonly=True,
    )

    stock_at_sale = fields.Float(
        string='Stock at Time of Sale',
        digits='Product Unit of Measure',
        readonly=True,
        help='UC-11: Stock level captured when this line was saved/confirmed.',
    )
    low_stock_override = fields.Boolean(
        string='Low Stock Override Applied',
        default=False,
        readonly=True,
        help='UC-11: True if cashier saved a qty exceeding max_qty_when_low while stock was low.',
    )

    # ── Package Quantity Display ─────────────────────────────────────────
    sale_package_qty_display = fields.Char(
        string='Package Quantity',
        compute='_compute_sale_package_qty_display',
    )

    @api.depends('product_id', 'product_id.product_tmpl_id.units_per_package')
    def _compute_sale_package_qty_display(self):
        for line in self:
            if line.product_id:
                units = int(line.product_id.product_tmpl_id.units_per_package or 1)
                line.sale_package_qty_display = '%s Unit%s' % (units, '' if units == 1 else 's')
            else:
                line.sale_package_qty_display = ''

    # ── UC-SELL — Allowed UoMs based on sell_as ──────────────────────────
    allowed_uom_ids = fields.Many2many(
        'uom.uom',
        compute='_compute_allowed_uom_ids',
        string='Allowed UoMs',
    )

    @api.depends('product_id', 'product_id.product_tmpl_id.sell_as', 'product_id.product_tmpl_id.package_uom_id')
    def _compute_allowed_uom_ids(self):
        for line in self:
            tmpl = line.product_id.product_tmpl_id
            if not tmpl:
                line.allowed_uom_ids = self.env['uom.uom']
                continue

            package_uom = tmpl.package_uom_id or tmpl.sudo()._sync_package_uom()
            unit_uom = tmpl.uom_id

            if tmpl.sell_as == 'unit' and unit_uom and package_uom:
                line.allowed_uom_ids = package_uom | unit_uom
            elif package_uom:
                line.allowed_uom_ids = package_uom
            else:
                line.allowed_uom_ids = self.env['uom.uom']

    @api.depends('product_id', 'product_uom_qty', 'price_unit', 'product_id.commission_pct')
    def _compute_commission_amount(self):
        for line in self:
            pct = line.product_id.product_tmpl_id.commission_pct
            if pct and pct > 0:
                line.commission_amount = line.product_uom_qty * line.price_unit * pct / 100
            else:
                line.commission_amount = 0.0

    @api.onchange('product_id')
    def _onchange_set_default_unit_uom(self):
        for line in self:
            tmpl = line.product_id.product_tmpl_id
            if not tmpl:
                continue

            package_uom = tmpl.package_uom_id or tmpl.sudo()._sync_package_uom()
            unit_uom = tmpl.uom_id

            if tmpl.sell_as == 'unit' and unit_uom:
                line.product_uom = unit_uom
                line.price_unit = tmpl.unit_price
            elif package_uom:
                line.product_uom = package_uom
                line.price_unit = tmpl.list_price

    @api.onchange('product_uom')
    def _onchange_set_price_by_uom(self):
        for line in self:
            tmpl = line.product_id.product_tmpl_id
            if not tmpl:
                continue

            package_uom = tmpl.package_uom_id or tmpl.sudo()._sync_package_uom()
            unit_uom = tmpl.uom_id

            if tmpl.sell_as == 'unit':
                allowed = [u.id for u in (package_uom | unit_uom) if u]
            else:
                allowed = [package_uom.id] if package_uom else []

            if line.product_uom and allowed and line.product_uom.id not in allowed:
                line.product_uom = unit_uom if tmpl.sell_as == 'unit' and unit_uom else package_uom
                return {
                    'warning': {
                        'title': _('Invalid Unit of Measure'),
                        'message': _('This UoM is not allowed for this product.'),
                    }
                }

            if package_uom and line.product_uom == package_uom:
                line.price_unit = tmpl.list_price
            elif unit_uom and line.product_uom == unit_uom:
                line.price_unit = tmpl.unit_price

    @api.constrains('product_uom', 'product_id')
    def _check_sale_uom_allowed(self):
        for line in self:
            if not line.product_id or not line.product_uom:
                continue

            tmpl = line.product_id.product_tmpl_id
            package_uom = tmpl.package_uom_id
            unit_uom = tmpl.uom_id

            if tmpl.sell_as == 'unit':
                allowed = {u.id for u in (package_uom | unit_uom) if u}
            else:
                allowed = {package_uom.id} if package_uom else set()

            if allowed and line.product_uom.id not in allowed:
                raise ValidationError(_(
                    'UoM "%s" is not allowed for product "%s".'
                ) % (line.product_uom.name, tmpl.name))

    # ══════════════════════════════════════════════════════════════════════
    # UC-10 — Hard Block
    # ══════════════════════════════════════════════════════════════════════
    @api.constrains('product_uom_qty', 'product_id')
    def _check_max_qty_per_invoice(self):
        for line in self:
            tmpl = line.product_id.product_tmpl_id
            if not tmpl or tmpl.classification != 'medicine':
                continue
            limit = tmpl.max_qty_per_invoice
            if not limit or limit <= 0:
                continue
            if line.product_uom_qty > limit:
                self.env['pharmacy.invoice.block.log'].sudo().create({
                    'product_id': tmpl.id,
                    'qty_attempted': line.product_uom_qty,
                    'qty_limit': limit,
                    'user_id': self.env.user.id,
                    'note': _('Hard block on Sale Order %s') % (line.order_id.name or 'New'),
                })
                raise ValidationError(_(
                    'You cannot sell more than %(limit)s units of "%(product)s" in a single invoice.'
                    'Please reduce the quantity or create a separate invoice.',
                    limit=limit, product=tmpl.name,
                ))

    @api.onchange('product_uom_qty', 'product_id')
    def _onchange_check_max_qty_per_invoice(self):
        for line in self:
            tmpl = line.product_id.product_tmpl_id
            if not tmpl or tmpl.classification != 'medicine':
                continue
            limit = tmpl.max_qty_per_invoice
            if not limit or limit <= 0:
                continue
            if line.product_uom_qty > limit:
                return {'warning': {
                    'title': _('Max Quantity Exceeded — Hard Block'),
                    'message': _(
                        'You cannot sell more than %(limit)s units of "%(product)s" in a single invoice.',
                        limit=limit, product=tmpl.name,
                    ),
                }}

    # ══════════════════════════════════════════════════════════════════════
    # UC-11 — Soft Warning
    # ══════════════════════════════════════════════════════════════════════
    @api.onchange('product_uom_qty', 'product_id')
    def _onchange_check_low_stock_limit(self):
        for line in self:
            tmpl = line.product_id.product_tmpl_id
            if not tmpl or tmpl.classification != 'medicine':
                continue
            low_limit = tmpl.low_stock_limit
            max_when_low = tmpl.max_qty_when_low
            if not low_limit or not max_when_low:
                continue
            qty_on_hand = sum(tmpl.product_variant_ids.mapped('qty_available'))
            if qty_on_hand <= low_limit and line.product_uom_qty > max_when_low:
                return {'warning': {
                    'title': _('⚠️ Low Stock Warning'),
                    'message': _(
                        'Current stock of "%(product)s" is low (%(stock)s units remaining).'
                        'The recommended maximum per invoice is %(max)s units.'
                        'Do you want to proceed with %(qty)s units anyway?'
                        'Note: This override will be logged for audit.',
                        product=tmpl.name,
                        stock=int(qty_on_hand),
                        max=max_when_low,
                        qty=int(line.product_uom_qty),
                    ),
                }}

    def _check_and_log_low_stock_override(self, vals):
        qty = vals.get('product_uom_qty')
        product_id = vals.get('product_id')

        for line in self:
            product = self.env['product.product'].browse(product_id) if product_id else line.product_id
            qty_to_check = qty if qty is not None else line.product_uom_qty

            if not product:
                continue
            tmpl = product.product_tmpl_id
            if not tmpl or tmpl.classification != 'medicine':
                continue

            low_limit = tmpl.low_stock_limit
            max_when_low = tmpl.max_qty_when_low
            if not low_limit or not max_when_low:
                continue

            qty_on_hand = sum(tmpl.product_variant_ids.mapped('qty_available'))

            if qty_on_hand <= low_limit and qty_to_check > max_when_low:
                self.env['pharmacy.low.stock.override.log'].sudo().create({
                    'product_id': tmpl.id,
                    'qty_sold': qty_to_check,
                    'max_qty_when_low': max_when_low,
                    'stock_at_sale': qty_on_hand,
                    'user_id': self.env.user.id,
                    'order_id': line.order_id.id if line.order_id else False,
                    'note': _(
                        'Cashier proceeded with %(qty)s units despite low-stock warning '
                        '(stock: %(stock)s, limit: %(max)s).',
                        qty=int(qty_to_check),
                        stock=int(qty_on_hand),
                        max=max_when_low,
                    ),
                })
                line.sudo().write({
                    'stock_at_sale': qty_on_hand,
                    'low_stock_override': True,
                })
                _logger.info(
                    'UC-11 override logged: product=%s qty=%s stock=%s user=%s',
                    tmpl.name, qty_to_check, qty_on_hand, self.env.user.name
                )

    @api.model_create_multi
    def create(self, vals_list):
        lines = super().create(vals_list)
        for line, vals in zip(lines, vals_list):
            line._check_and_log_low_stock_override(vals)
        return lines

    def write(self, vals):
        result = super().write(vals)
        if 'product_uom_qty' in vals or 'product_id' in vals:
            self._check_and_log_low_stock_override(vals)
        return result

    def _log_low_stock_override(self):
        for line in self:
            tmpl = line.product_id.product_tmpl_id
            if not tmpl or tmpl.classification != 'medicine':
                continue
            low_limit = tmpl.low_stock_limit
            max_when_low = tmpl.max_qty_when_low
            if not low_limit or not max_when_low:
                continue
            qty_on_hand = sum(tmpl.product_variant_ids.mapped('qty_available'))
            if qty_on_hand <= low_limit and line.product_uom_qty > max_when_low:
                already_logged = self.env['pharmacy.low.stock.override.log'].sudo().search([
                    ('product_id', '=', tmpl.id),
                    ('order_id', '=', line.order_id.id),
                    ('qty_sold', '=', line.product_uom_qty),
                ], limit=1)
                if not already_logged:
                    self.env['pharmacy.low.stock.override.log'].sudo().create({
                        'product_id': tmpl.id,
                        'qty_sold': line.product_uom_qty,
                        'max_qty_when_low': max_when_low,
                        'stock_at_sale': qty_on_hand,
                        'user_id': self.env.user.id,
                        'order_id': line.order_id.id,
                        'note': _('Logged on order confirmation (safety net).'),
                    })
                if not line.low_stock_override:
                    line.sudo().write({
                        'stock_at_sale': qty_on_hand,
                        'low_stock_override': True,
                    })


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    def _get_scheduled_medicine_lines(self):
        return self.order_line.filtered(
            lambda line: line.product_id
            and line.product_id.product_tmpl_id.is_scheduled_medicine
        )

    def action_confirm(self):
        for order in self:
            scheduled_lines = order._get_scheduled_medicine_lines()
            if scheduled_lines and not self.env.context.get('skip_scheduled_medicine_confirm'):
                medicine_names = ', '.join(scheduled_lines.mapped('product_id.display_name'))
                wizard = self.env['sale.scheduled.medicine.confirm.wizard'].create({
                    'sale_order_id': order.id,
                    'medicine_names': medicine_names,
                })
                return {
                    'name': _('Scheduled Medicine!'),
                    'type': 'ir.actions.act_window',
                    'res_model': 'sale.scheduled.medicine.confirm.wizard',
                    'view_mode': 'form',
                    'res_id': wizard.id,
                    'target': 'new',
                }

        res = super().action_confirm()
        for order in self:
            order.order_line._log_low_stock_override()
        return res