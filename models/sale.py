from odoo import models, fields, api


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    # ── UC-09 — Commission ────────────────────────────────────────────────

    commission_amount = fields.Float(
        string='Commission Amount',
        compute='_compute_commission_amount',
        store=True,
        readonly=True,
    )

    @api.depends('product_id', 'product_uom_qty', 'price_unit',
                 'product_id.commission_pct')
    def _compute_commission_amount(self):
        """
        Commission Amount = Quantity x Unit Price x Commission% / 100
        """
        for line in self:
            pct = line.product_id.product_tmpl_id.commission_pct
            if pct and pct > 0:
                line.commission_amount = (
                    line.product_uom_qty * line.price_unit * pct / 100
                )
            else:
                line.commission_amount = 0.0

    # ── UC-02 — Pricing by UoM ────────────────────────────────────────────

    @api.onchange('product_id')
    def _onchange_set_default_unit_uom(self):
        """
        When adding a Unit product to a sale order,
        default UoM = Unit and price = unit_price.

        The cashier can change UoM to Package manually,
        which will trigger _onchange_set_price_by_uom to update the price.
        """
        for line in self:
            product = line.product_id.product_tmpl_id
            if product.sell_as == 'unit' and product.uom_id:
                line.product_uom = product.uom_id
                line.price_unit = product.unit_price

    @api.onchange('product_uom')
    def _onchange_set_price_by_uom(self):
        """
        Automatically adjusts the price when the cashier changes UoM:
          - Selling as Unit    -> price = unit_price  (list_price / units_per_package)
          - Selling as Package -> price = list_price  (full package price)

        Stock deduction is handled automatically by Odoo UoM conversion:
          - 1 Unit sold    -> deducts 1 Unit from stock
          - 1 Package sold -> deducts N Units from stock (via UoM factor)
        """
        for line in self:
            product = line.product_id.product_tmpl_id
            if not product or product.sell_as != 'unit':
                continue
            if not product.package_uom_id:
                continue

            if line.product_uom == product.package_uom_id:
                # Selling as Package -> full package price
                line.price_unit = product.list_price

            elif line.product_uom == product.uom_id:
                # Selling as Unit -> price per unit
                line.price_unit = product.unit_price
