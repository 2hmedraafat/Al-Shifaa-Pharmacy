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
