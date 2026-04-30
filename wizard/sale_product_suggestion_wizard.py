from odoo import fields, models, _
from odoo.exceptions import UserError


class SaleProductSuggestionWizard(models.TransientModel):
    _name = 'sale.product.suggestion.wizard'
    _description = 'Sale Product Suggestions Wizard'

    sale_order_id = fields.Many2one('sale.order', string='Sale Order', required=True, readonly=True)
    line_ids = fields.One2many(
        'sale.product.suggestion.wizard.line',
        'wizard_id',
        string='Suggested Products',
    )

    def action_add_selected_products(self):
        self.ensure_one()
        selected_lines = self.line_ids.filtered('selected')
        if not selected_lines:
            raise UserError(_('Please select at least one suggested product.'))

        SaleOrderLine = self.env['sale.order.line']
        for wiz_line in selected_lines:
            product_tmpl = wiz_line.suggested_product_tmpl_id
            product = product_tmpl.product_variant_id or product_tmpl.product_variant_ids[:1]
            if not product:
                continue

            package_uom = product_tmpl.package_uom_id
            if not package_uom and hasattr(product_tmpl, '_sync_package_uom'):
                package_uom = product_tmpl.sudo()._sync_package_uom()
            product_uom = package_uom or product_tmpl.uom_id

            SaleOrderLine.create({
                'order_id': self.sale_order_id.id,
                'product_id': product.id,
                'name': product.display_name,
                'product_uom_qty': 1.0,
                'product_uom': product_uom.id if product_uom else product.uom_id.id,
                'price_unit': product_tmpl.list_price,
            })

        return {'type': 'ir.actions.act_window_close'}


class SaleProductSuggestionWizardLine(models.TransientModel):
    _name = 'sale.product.suggestion.wizard.line'
    _description = 'Sale Product Suggestion Wizard Line'

    wizard_id = fields.Many2one(
        'sale.product.suggestion.wizard',
        required=True,
        ondelete='cascade',
    )
    selected = fields.Boolean(string='Add', default=True)
    suggestion_type = fields.Selection(
        [
            ('similar', 'Similar Alternative'),
            ('complementary', 'Complementary Product'),
        ],
        string='Type',
        readonly=True,
    )
    base_product_tmpl_id = fields.Many2one('product.template', string='Based On', readonly=True)
    suggested_product_tmpl_id = fields.Many2one('product.template', string='Suggested Product', readonly=True)
    list_price = fields.Float(string='Sales Price', related='suggested_product_tmpl_id.list_price', readonly=True)
    note = fields.Char(string='Note', readonly=True)
