from odoo import models, fields, api, _
from odoo.exceptions import ValidationError


class PharmacyProductBarcode(models.Model):
    _name = 'pharmacy.product.barcode'
    _description = 'Product Additional Barcodes'

    product_id = fields.Many2one(
        'product.template',
        string='Product',
        required=True,
        ondelete='cascade'
    )
    barcode = fields.Char(
        string='Barcode Value',
        required=True
    )
    barcode_type = fields.Selection([
        ('international', 'International (Manufacturer)'),
        ('internal', 'Internal (Auto-Generated)'),
    ], string='Barcode Type', required=True, default='international')

    unit_type = fields.Selection([
        ('package', 'Package'),
        ('unit', 'Unit'),
    ], string='Unit', required=True, default='package')

    notes = fields.Char(string='Notes')

    @api.constrains('barcode')
    def _check_barcode_unique(self):
        for rec in self:
            # Check duplicates inside sub-table itself
            duplicate = self.search([
                ('barcode', '=', rec.barcode),
                ('id', '!=', rec.id)
            ])
            if duplicate:
                raise ValidationError(
                    _('Barcode "%s" already exists on product: "%s".')
                    % (rec.barcode, duplicate[0].product_id.name)
                )
            # Check against primary barcode of any other product
            product = self.env['product.template'].search([
                ('barcode', '=', rec.barcode),
                ('id', '!=', rec.product_id.id)
            ])
            if product:
                raise ValidationError(
                    _('Barcode "%s" is already used as the primary barcode of product: "%s".')
                    % (rec.barcode, product[0].name)
                )