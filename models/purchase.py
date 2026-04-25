from odoo import models, api
from odoo.exceptions import ValidationError


class PurchaseOrderLine(models.Model):
    _inherit = 'purchase.order.line'

    def _get_allowed_uoms(self):
        self.ensure_one()
        allowed = self.env['uom.uom']

        unit_uom = self.env.ref('pharmacy.product_uom_unit', raise_if_not_found=False)
        package_uom = self.env.ref('pharmacy.product_uom_package', raise_if_not_found=False)

        if unit_uom:
            allowed |= unit_uom
        if package_uom:
            allowed |= package_uom

        return allowed

    @api.onchange('product_id')
    def _onchange_product_id_limit_uom(self):
        for line in self:
            allowed_uoms = line._get_allowed_uoms()

            if not line.product_id:
                return {'domain': {'product_uom': [('id', 'in', allowed_uoms.ids)]}}

            product = line.product_id.product_tmpl_id
            package_uom = self.env.ref('pharmacy.product_uom_package', raise_if_not_found=False)
            unit_uom = self.env.ref('pharmacy.product_uom_unit', raise_if_not_found=False)

            if product.sell_as == 'unit' and package_uom:
                line.product_uom = package_uom
            elif unit_uom:
                line.product_uom = unit_uom

            return {'domain': {'product_uom': [('id', 'in', allowed_uoms.ids)]}}

    @api.onchange('product_uom')
    def _onchange_product_uom_limit_choices(self):
        for line in self:
            allowed_uoms = line._get_allowed_uoms()

            if line.product_uom and line.product_uom not in allowed_uoms:
                line.product_uom = False

            return {'domain': {'product_uom': [('id', 'in', allowed_uoms.ids)]}}

    @api.constrains('product_uom')
    def _check_product_uom_allowed(self):
        for line in self:
            if not line.product_uom:
                continue

            allowed_uoms = line._get_allowed_uoms()
            if line.product_uom not in allowed_uoms:
                raise ValidationError("Purchase UoM must be only Unit or Package.")
