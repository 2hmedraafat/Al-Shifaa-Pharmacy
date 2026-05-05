from odoo import api, fields, models, _
from odoo.exceptions import ValidationError
from markupsafe import Markup


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    pharmacy_allow_shared_barcodes = fields.Boolean(
        string='Allow Shared Barcodes',
        config_parameter='pharmacy.allow_shared_barcodes',
        default=True,
        help='Allow the same barcode to be assigned to more than one product. POS will ask the cashier to select the correct product.',
    )


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    pharmacy_is_shared_barcode = fields.Boolean(
        string='Shared Barcode',
        compute='_compute_pharmacy_shared_barcode_info',
        search='_search_pharmacy_is_shared_barcode',
        readonly=True,
    )
    pharmacy_shared_barcode_count = fields.Integer(
        string='Shared Barcode Count',
        compute='_compute_pharmacy_shared_barcode_info',
        readonly=True,
    )
    pharmacy_shared_barcode_product_names = fields.Char(
        string='Products Sharing Barcode',
        compute='_compute_pharmacy_shared_barcode_info',
        readonly=True,
    )
    pharmacy_shared_barcode_status = fields.Selection(
        [('keep', 'Keep'), ('resolved', 'Resolved')],
        string='Shared Barcode Status',
        default='keep',
        tracking=True,
        help='Use Keep when the duplicate barcode is intentional, or Resolved after assigning a unique barcode.',
    )

    def _pharmacy_allow_shared_barcodes(self):
        return self.env['ir.config_parameter'].sudo().get_param('pharmacy.allow_shared_barcodes', 'True') not in ('False', 'false', '0')

    def _pharmacy_products_sharing_barcode(self, barcode):
        if not barcode:
            return self.env['product.template']
        variants = self.env['product.product'].sudo().search([('barcode', '=', barcode)])
        return variants.mapped('product_tmpl_id')

    @api.depends('product_variant_ids.barcode')
    def _compute_pharmacy_shared_barcode_info(self):
        for product in self:
            products = product._pharmacy_products_sharing_barcode(product.barcode)
            count = len(products)
            product.pharmacy_shared_barcode_count = count
            product.pharmacy_is_shared_barcode = bool(product.barcode and count > 1)
            product.pharmacy_shared_barcode_product_names = ', '.join(products.mapped('display_name')) if count > 1 else ''

    def _search_pharmacy_is_shared_barcode(self, operator, value):
        # In Odoo 18 the real stored barcode column is on product_product,
        # not product_template. Use product_product here to avoid SQL errors
        # when the product.template list/report is grouped or filtered.
        self.env.cr.execute("""
            SELECT barcode
              FROM product_product
             WHERE barcode IS NOT NULL AND barcode != ''
          GROUP BY barcode
            HAVING COUNT(id) > 1
        """)
        barcodes = [row[0] for row in self.env.cr.fetchall()]
        if (operator in ('=', '==') and value) or (operator in ('!=', '<>') and not value):
            return [('product_variant_ids.barcode', 'in', barcodes or ['__no_shared_barcode__'])]
        return ['|', ('product_variant_ids.barcode', '=', False), ('product_variant_ids.barcode', 'not in', barcodes or ['__no_shared_barcode__'])]

    def _pharmacy_check_shared_barcode_allowed(self):
        if self._pharmacy_allow_shared_barcodes():
            return
        ProductProduct = self.env['product.product'].sudo()
        for product in self:
            barcode = product.product_variant_id.barcode or product.barcode
            if not barcode:
                continue
            duplicate_variant = ProductProduct.search([
                ('barcode', '=', barcode),
                ('product_tmpl_id', '!=', product.id),
            ], limit=1)
            if duplicate_variant:
                raise ValidationError(_(
                    'Shared barcodes are disabled in Pharmacy Settings.\n'
                    'Barcode "%(barcode)s" is already assigned to "%(product)s".'
                ) % {'barcode': barcode, 'product': duplicate_variant.display_name})

    @api.constrains('barcode')
    def _check_pharmacy_shared_barcode_setting(self):
        self._pharmacy_check_shared_barcode_allowed()

    def _pharmacy_post_shared_barcode_log(self):
        for product in self:
            if not product.barcode:
                continue
            products = product._pharmacy_products_sharing_barcode(product.barcode)
            if len(products) <= 1:
                continue
            names = ', '.join(products.mapped('display_name'))
            body = Markup(_(
                '<b>Shared Barcode</b><br/>'
                'Barcode <b>%(barcode)s</b> is now shared by %(count)s products:<br/>%(names)s'
            ) % {'barcode': product.barcode, 'count': len(products), 'names': names})
            for tmpl in products:
                if hasattr(tmpl, 'message_post'):
                    tmpl.message_post(body=body, subtype_xmlid='mail.mt_note')

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records.filtered(lambda r: r.barcode)._pharmacy_post_shared_barcode_log()
        return records

    def write(self, vals):
        barcode_changed = 'barcode' in vals
        result = super().write(vals)
        if barcode_changed:
            self.filtered(lambda r: r.barcode)._pharmacy_post_shared_barcode_log()
        return result

    def action_pharmacy_shared_barcode_keep(self):
        self.write({'pharmacy_shared_barcode_status': 'keep'})
        return True

    def action_pharmacy_shared_barcode_resolve(self):
        self.write({'pharmacy_shared_barcode_status': 'resolved'})
        return True


class ProductProduct(models.Model):
    _inherit = 'product.product'

    def _pharmacy_allow_shared_barcodes(self):
        return self.env['ir.config_parameter'].sudo().get_param('pharmacy.allow_shared_barcodes', 'True') not in ('False', 'false', '0')

    def _check_barcode_uniqueness(self):
        # Keep Odoo's standard barcode constraint relaxed when shared barcodes are enabled.
        if self._pharmacy_allow_shared_barcodes():
            return True
        return super()._check_barcode_uniqueness()

    @api.constrains('barcode')
    def _check_pharmacy_shared_barcode_setting(self):
        if self._pharmacy_allow_shared_barcodes():
            return
        for product in self:
            if not product.barcode:
                continue
            duplicate = self.search([
                ('barcode', '=', product.barcode),
                ('id', '!=', product.id),
            ], limit=1)
            if duplicate:
                raise ValidationError(_(
                    'Shared barcodes are disabled in Pharmacy Settings.\n'
                    'Barcode "%(barcode)s" is already assigned to "%(product)s".'
                ) % {'barcode': product.barcode, 'product': duplicate.display_name})
