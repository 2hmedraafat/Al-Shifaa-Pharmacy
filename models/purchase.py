from odoo import models, api, _
from odoo.exceptions import ValidationError


class PurchaseOrderLine(models.Model):
    _inherit = 'purchase.order.line'

    def _get_package_uom(self):
        return self.env.ref('pharmacy.product_uom_package', raise_if_not_found=False)

    @api.onchange('product_id')
    def _onchange_product_id_force_package_uom(self):
        """Purchase is always in Package — no exceptions."""
        package_uom = self._get_package_uom()
        if package_uom:
            self.product_uom = package_uom
        return {
            'domain': {
                'product_uom': [('id', '=', package_uom.id)] if package_uom else []
            }
        }

    @api.onchange('product_uom')
    def _onchange_product_uom_force_package(self):
        """Revert if user manually changes to anything other than Package."""
        package_uom = self._get_package_uom()
        if package_uom and self.product_uom != package_uom:
            self.product_uom = package_uom
        return {
            'domain': {
                'product_uom': [('id', '=', package_uom.id)] if package_uom else []
            }
        }

    @api.constrains('product_uom')
    def _check_purchase_uom_is_package(self):
        package_uom = self.env.ref('pharmacy.product_uom_package', raise_if_not_found=False)
        if not package_uom:
            return
        for line in self:
            if line.product_uom and line.product_uom != package_uom:
                raise ValidationError(_(
                    'Purchase UoM must be "Package" only.\n'
                    'Product "%s" cannot be purchased in "%s".'
                ) % (line.product_id.display_name, line.product_uom.name))
