from odoo import models, fields, api, _


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
        """Allow shared barcodes.

        The pharmacy workflow intentionally allows the same barcode to be
        registered on more than one product/variant. Keep this method empty so
        extra barcodes do not block saving; the POS dialog handles selection.
        """
        return True