from odoo import models, fields


class PharmacyPriceHistory(models.Model):
    _name = 'pharmacy.price.history'
    _description = 'UC-07 — Public Price Change History'
    _order = 'date desc, id desc'
    _rec_name = 'product_tmpl_id'

    product_tmpl_id = fields.Many2one(
        'product.template',
        string='Product',
        required=True,
        ondelete='cascade',
        index=True,
    )
    date = fields.Datetime(
        string='Date',
        default=fields.Datetime.now,
        required=True,
        readonly=True,
    )
    old_price = fields.Float(
        string='Old Price',
        digits='Product Price',
        required=True,
        readonly=True,
    )
    new_price = fields.Float(
        string='New Price',
        digits='Product Price',
        required=True,
        readonly=True,
    )
    currency_id = fields.Many2one(
        'res.currency',
        string='Currency',
        required=True,
        readonly=True,
        default=lambda self: self.env.company.currency_id,
    )
    user_id = fields.Many2one(
        'res.users',
        string='Changed By',
        default=lambda self: self.env.user,
        required=True,
        readonly=True,
    )
    source = fields.Selection(
        selection=[
            ('manual', 'Manual'),
            ('bulk_update', 'Bulk Update'),
            ('import_api', 'Import / API'),
        ],
        string='Source',
        default='manual',
        required=True,
        readonly=True,
    )
