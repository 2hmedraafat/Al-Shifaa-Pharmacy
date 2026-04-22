from odoo import models, api
from odoo.exceptions import ValidationError


class PurchaseOrderLine(models.Model):
    _inherit = 'purchase.order.line'

    @api.onchange('product_id')
    def _onchange_force_package_uom(self):
        """
        When a Unit product is selected on a purchase line,
        automatically set UoM to Package (purchase always in Packages).
        """
        for line in self:
            product = line.product_id.product_tmpl_id
            if product.sell_as == 'unit' and product.package_uom_id:
                line.product_uom = product.package_uom_id

    @api.constrains('product_uom', 'product_id')
    def _check_purchase_uom(self):
        """
        Hard block: Unit products can only be purchased in Packages.
        Prevents manual UoM override on purchase order lines.
        """
        for line in self:
            product = line.product_id.product_tmpl_id
            if product.sell_as == 'unit' and product.package_uom_id:
                if line.product_uom != product.package_uom_id:
                    raise ValidationError(
                        f'"{product.name}" can only be purchased in Packages.\n'
                        f'Please set UoM to: {product.package_uom_id.name}'
                    )
