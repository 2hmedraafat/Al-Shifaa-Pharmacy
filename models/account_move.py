import logging

from odoo import models, _

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

    def _pharmacy_update_last_purchase_discount(self):
        """SC1-UC-01: Save latest Vendor Bill discount on product.template."""
        for move in self.sudo():
            if move.move_type not in ('in_invoice', 'in_refund'):
                continue
            if move.state != 'posted':
                continue

            invoice_date = move.invoice_date or move.date

            # IMPORTANT:
            # In Odoo 18 normal invoice product lines may have display_type = 'product'.
            # So we only exclude real section/note lines, not every line with display_type.
            lines = move.invoice_line_ids.filtered(
                lambda line: line.product_id
                and line.display_type not in ('line_section', 'line_note')
            )

            for line in lines:
                product_tmpl = line.product_id.product_tmpl_id.sudo()
                if not product_tmpl:
                    continue

                discount = line.discount if 'discount' in line._fields else 0.0
                discount = discount or 0.0

                # Update only with the newest supplier invoice date.
                if product_tmpl.last_purchase_discount_date and invoice_date:
                    if product_tmpl.last_purchase_discount_date > invoice_date:
                        continue

                old_discount = product_tmpl.last_purchase_discount or 0.0

                product_tmpl.write({
                    'last_purchase_discount': discount,
                    'last_purchase_discount_date': invoice_date,
                    'last_purchase_discount_supplier_id': move.partner_id.id or False,
                    'last_purchase_discount_move_id': move.id,
                })

                try:
                    product_tmpl.message_post(
                        body=_(
                            '<b>Last Purchase Discount Updated</b><br/>'
                            'Supplier Invoice: <b>%(invoice)s</b><br/>'
                            'Vendor: <b>%(vendor)s</b><br/>'
                            'Old Discount: <b>%(old).2f%%</b><br/>'
                            'New Discount: <b>%(new).2f%%</b>',
                            invoice=move.name or move.ref or '/',
                            vendor=move.partner_id.display_name or '-',
                            old=old_discount,
                            new=discount,
                        ),
                        subtype_xmlid='mail.mt_note',
                    )
                except Exception:
                    _logger.exception(
                        'SC1-UC-01: Could not add chatter log for product.template %s',
                        product_tmpl.id,
                    )

                _logger.info(
                    'SC1-UC-01: updated product.template %s from vendor bill %s with discount %s',
                    product_tmpl.id,
                    move.name or move.id,
                    discount,
                )
