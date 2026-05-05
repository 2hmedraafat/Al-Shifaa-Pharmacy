import logging

from odoo import api, fields, models, _

_logger = logging.getLogger(__name__)


class AccountMove(models.Model):
    _inherit = 'account.move'

    def action_post(self):
        res = super().action_post()
        self._pharmacy_update_last_purchase_discount()
        return res

    def _post(self, soft=True):
        posted_moves = super()._post(soft=soft)
        posted_moves._pharmacy_update_last_purchase_discount()
        return posted_moves

    def button_draft(self):
        affected_products = self._pharmacy_get_discount_products()
        res = super().button_draft()
        affected_products._pharmacy_recompute_last_purchase_discount()
        return res

    def button_cancel(self):
        affected_products = self._pharmacy_get_discount_products()
        res = super().button_cancel()
        affected_products._pharmacy_recompute_last_purchase_discount()
        return res

    def _pharmacy_get_discount_products(self):
        products = self.env['product.template']
        for move in self.sudo():
            if move.move_type not in ('in_invoice', 'in_refund'):
                continue
            lines = move.invoice_line_ids.filtered(
                lambda line: line.product_id and line.display_type not in ('line_section', 'line_note')
            )
            products |= lines.mapped('product_id.product_tmpl_id')
        return products.sudo()

    def _pharmacy_update_last_purchase_discount(self):
        """SC1-UC-01: save the latest posted supplier invoice discount on product.template.

        If the same product appears multiple times on one invoice, the highest line discount
        is used for that invoice.
        """
        History = self.env['pharmacy.purchase.discount.history'].sudo()
        for move in self.sudo():
            if move.move_type not in ('in_invoice', 'in_refund') or move.state != 'posted':
                continue

            invoice_date = move.invoice_date or move.date
            lines = move.invoice_line_ids.filtered(
                lambda line: line.product_id and line.display_type not in ('line_section', 'line_note')
            )

            best_by_template = {}
            for line in lines:
                tmpl = line.product_id.product_tmpl_id.sudo()
                discount = line.discount if 'discount' in line._fields else 0.0
                discount = discount or 0.0
                current = best_by_template.get(tmpl.id)
                if not current or discount > current['discount']:
                    best_by_template[tmpl.id] = {
                        'template': tmpl,
                        'product': line.product_id.sudo(),
                        'discount': discount,
                    }

            for data in best_by_template.values():
                product_tmpl = data['template']
                discount = data['discount']
                product = data['product']

                existing = History.search([
                    ('product_tmpl_id', '=', product_tmpl.id),
                    ('move_id', '=', move.id),
                ], limit=1)
                values = {
                    'product_tmpl_id': product_tmpl.id,
                    'product_id': product.id,
                    'partner_id': move.partner_id.id or False,
                    'move_id': move.id,
                    'invoice_date': invoice_date,
                    'discount': discount,
                    'user_id': self.env.user.id,
                    'company_id': move.company_id.id or self.env.company.id,
                }
                if existing:
                    existing.write(values)
                else:
                    History.create(values)

                product_tmpl._pharmacy_recompute_last_purchase_discount()

    def _pharmacy_discount_sort_key(self, move):
        return (move.invoice_date or move.date or False, move.id)


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    last_purchase_discount_purchase_order_id = fields.Many2one(
        'purchase.order',
        string='Last Discount Purchase Order',
        readonly=True,
        groups='pharmacy.group_pharmacy_manager,pharmacy.group_pharmacy_pharmacist',
    )

    def _pharmacy_recompute_last_purchase_discount(self):
        """Recalculate after invoice post/cancel/reset to draft."""
        History = self.env['pharmacy.purchase.discount.history'].sudo()
        for product_tmpl in self.sudo():
            histories = History.search([
                ('product_tmpl_id', '=', product_tmpl.id),
            ]).filtered(lambda h: (
                h.move_id and h.move_id.state == 'posted' and h.move_id.move_type in ('in_invoice', 'in_refund')
            ) or (
                h.purchase_order_id and h.purchase_order_id.state in ('purchase', 'done')
            ))

            # Sort in Python to guarantee that records on the same day pick the
            # newest business event. A confirmed PO created after an older bill must
            # become the current latest discount. create_date/id are used as stable
            # tie-breakers for records sharing the same invoice/order date.
            def _history_sort_key(h):
                source_dt = False
                if h.purchase_order_id:
                    source_dt = h.purchase_order_id.date_approve or h.purchase_order_id.write_date or h.purchase_order_id.create_date
                elif h.move_id:
                    source_dt = h.move_id.write_date or h.move_id.create_date
                return (
                    h.invoice_date or fields.Date.to_date('1900-01-01'),
                    source_dt or h.create_date or fields.Datetime.to_datetime('1900-01-01 00:00:00'),
                    h.id or 0,
                )

            latest = histories.sorted(key=_history_sort_key, reverse=True)[:1]
            old_discount = product_tmpl.last_purchase_discount or 0.0
            old_move = product_tmpl.last_purchase_discount_move_id
            old_po = product_tmpl.last_purchase_discount_purchase_order_id

            if not latest:
                product_tmpl.write({
                    'last_purchase_discount': 0.0,
                    'last_purchase_discount_date': False,
                    'last_purchase_discount_supplier_id': False,
                    'last_purchase_discount_move_id': False,
                    'last_purchase_discount_purchase_order_id': False,
                })
                continue

            vals = {
                'last_purchase_discount': latest.discount or 0.0,
                'last_purchase_discount_date': latest.invoice_date,
                'last_purchase_discount_supplier_id': latest.partner_id.id or False,
                'last_purchase_discount_move_id': latest.move_id.id or False,
                'last_purchase_discount_purchase_order_id': latest.purchase_order_id.id or False,
            }
            product_tmpl.write(vals)

            if old_discount != (latest.discount or 0.0) or old_move != latest.move_id or old_po != latest.purchase_order_id:
                try:
                    product_tmpl.message_post(
                        body=_(
                            '<b>Last Purchase Discount Updated</b><br/>'
                            'Source Document: <b>%(invoice)s</b><br/>'
                            'Vendor: <b>%(vendor)s</b><br/>'
                            'Date: <b>%(date)s</b><br/>'
                            'Old Discount: <b>%(old).2f%%</b><br/>'
                            'New Discount: <b>%(new).2f%%</b>',
                            invoice=latest.move_id.name or latest.move_id.ref or latest.purchase_order_id.name or '/',
                            vendor=latest.partner_id.display_name or '-',
                            date=latest.invoice_date or '-',
                            old=old_discount,
                            new=latest.discount or 0.0,
                        ),
                        subtype_xmlid='mail.mt_note',
                    )
                except Exception:
                    _logger.exception('SC1-UC-01: Could not add chatter log for product.template %s', product_tmpl.id)


    @api.model
    def _pharmacy_recompute_last_purchase_discount_all(self):
        """Refresh stored latest discount values after module updates or logic fixes."""
        products = self.env['pharmacy.purchase.discount.history'].sudo().search([]).mapped('product_tmpl_id')
        if products:
            products._pharmacy_recompute_last_purchase_discount()
        return True
