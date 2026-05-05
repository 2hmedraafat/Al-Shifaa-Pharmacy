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
    note = fields.Char(string='Relationship Note')
    priority = fields.Selection(
        [(str(i), '%s Star%s' % (i, '' if i == 1 else 's')) for i in range(1, 6)],
        string='Priority',
        default='3',
        required=True,
        help='Priority 1-5 used to sort suggestions. 5 is highest.',
    )
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

    @api.constrains('product_tmpl_id', 'suggestion_type', 'active')
    def _check_suggestion_limit(self):
        limit = int(self.env['ir.config_parameter'].sudo().get_param('pharmacy.max_product_suggestions', 10) or 10)
        if limit <= 0:
            return
        for rec in self.filtered(lambda r: r.product_tmpl_id and r.suggestion_type and r.active):
            count = self.search_count([
                ('product_tmpl_id', '=', rec.product_tmpl_id.id),
                ('suggestion_type', '=', rec.suggestion_type),
                ('active', '=', True),
            ])
            if count > limit:
                raise ValidationError(_(
                    'You cannot add more than %(limit)s %(stype)s suggestion(s) for %(product)s.'
                ) % {
                    'limit': limit,
                    'stype': rec.suggestion_type,
                    'product': rec.product_tmpl_id.display_name,
                })

    def action_make_reciprocal(self):
        for rec in self:
            if not rec.product_tmpl_id or not rec.suggested_product_tmpl_id:
                continue
            reverse = self.search([
                ('product_tmpl_id', '=', rec.suggested_product_tmpl_id.id),
                ('suggested_product_tmpl_id', '=', rec.product_tmpl_id.id),
                ('suggestion_type', '=', rec.suggestion_type),
            ], limit=1)
            if reverse:
                if not reverse.active:
                    reverse.active = True
                continue
            self.create({
                'product_tmpl_id': rec.suggested_product_tmpl_id.id,
                'suggested_product_tmpl_id': rec.product_tmpl_id.id,
                'suggestion_type': rec.suggestion_type,
                'note': rec.note,
                'priority': rec.priority,
            })
        return True


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
