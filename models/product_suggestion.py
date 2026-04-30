from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class PharmacyProductSuggestion(models.Model):
    _name = 'pharmacy.product.suggestion'
    _description = 'Similar and Complementary Product Suggestion'
    _order = 'sequence, id'

    active = fields.Boolean(default=True)
    sequence = fields.Integer(default=10)
    product_tmpl_id = fields.Many2one(
        'product.template',
        string='Base Product',
        required=True,
        ondelete='cascade',
        index=True,
    )
    suggested_product_tmpl_id = fields.Many2one(
        'product.template',
        string='Suggested Product',
        required=True,
        ondelete='cascade',
        index=True,
    )
    suggestion_type = fields.Selection(
        [
            ('similar', 'Similar Alternative'),
            ('complementary', 'Complementary Product'),
        ],
        string='Suggestion Type',
        required=True,
        default='complementary',
    )
    note = fields.Char(string='Note')
    list_price = fields.Float(
        string='Sales Price',
        related='suggested_product_tmpl_id.list_price',
        readonly=True,
    )

    _sql_constraints = [
        (
            'unique_product_suggestion_type',
            'unique(product_tmpl_id, suggested_product_tmpl_id, suggestion_type)',
            'This suggestion already exists for this product.',
        ),
    ]

    @api.constrains('product_tmpl_id', 'suggested_product_tmpl_id')
    def _check_not_same_product(self):
        for rec in self:
            if rec.product_tmpl_id and rec.suggested_product_tmpl_id and rec.product_tmpl_id == rec.suggested_product_tmpl_id:
                raise ValidationError(_('The suggested product cannot be the same as the base product.'))


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    suggestion_ids = fields.One2many(
        'pharmacy.product.suggestion',
        'product_tmpl_id',
        string='Product Suggestions',
    )
    similar_suggestion_ids = fields.One2many(
        'pharmacy.product.suggestion',
        'product_tmpl_id',
        string='Similar Alternatives',
        domain=[('suggestion_type', '=', 'similar')],
    )
    complementary_suggestion_ids = fields.One2many(
        'pharmacy.product.suggestion',
        'product_tmpl_id',
        string='Complementary Products',
        domain=[('suggestion_type', '=', 'complementary')],
    )

    # Backward compatibility for any older XML that still references *_line_ids.
    similar_suggestion_line_ids = fields.One2many(
        'pharmacy.product.suggestion',
        'product_tmpl_id',
        string='Similar Alternatives Lines',
        domain=[('suggestion_type', '=', 'similar')],
    )
    complementary_suggestion_line_ids = fields.One2many(
        'pharmacy.product.suggestion',
        'product_tmpl_id',
        string='Complementary Products Lines',
        domain=[('suggestion_type', '=', 'complementary')],
    )
