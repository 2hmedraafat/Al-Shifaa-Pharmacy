from odoo import models, fields, api, _
import logging

_logger = logging.getLogger(__name__)


class StockMove(models.Model):
    _inherit = 'stock.move'

    def _action_done(self, cancel_backorder=False):
        """
        UC-08: Auto-log cost history every time a supplier receipt is validated.
        """
        res = super()._action_done(cancel_backorder=cancel_backorder)

        incoming_moves = self.filtered(
            lambda m: m.picking_id.picking_type_code == 'incoming' and m.state == 'done'
        )

        for move in incoming_moves:
            tmpl = move.product_id.product_tmpl_id

            variants = tmpl.product_variant_ids
            total_value = sum(
                v.standard_price * v.qty_available
                for v in variants if v.qty_available > 0
            )
            total_qty = sum(v.qty_available for v in variants if v.qty_available > 0)
            avg_cost = (total_value / total_qty) if total_qty > 0 else move.product_id.standard_price

           
            self.env['pharmacy.cost.history'].sudo().create({
                'product_tmpl_id': tmpl.id,
                'date': fields.Datetime.now(),
                'cost': avg_cost,
                'qty_received': move.quantity,
                'unit_purchase_price': move.price_unit if hasattr(move, 'price_unit') else 0.0,
                'picking_id': move.picking_id.id if move.picking_id else False,
                'purchase_order_id': (
                    move.purchase_line_id.order_id.id
                    if hasattr(move, 'purchase_line_id') and move.purchase_line_id
                    else False
                ),
                'note': _('Auto-logged on receipt validation'),
            })

            try:
                currency = tmpl.currency_id or tmpl.env.company.currency_id
                tmpl.message_post(
                    body=_(
                        '<b>Avg. Purchase Cost Updated</b><br/>'
                        'New Avg. Cost: <b>%(cost).3f %(currency)s</b><br/>'
                        'Qty Received: <b>%(qty).3f</b><br/>'
                        'Source: %(picking)s',
                        cost=avg_cost,
                        currency=currency.symbol or '',
                        qty=move.quantity,
                        picking=move.picking_id.name if move.picking_id else _('Manual'),
                    ),
                    subtype_xmlid='mail.mt_note',
                )
            except Exception as e:
                _logger.warning('UC-08: Could not post chatter message: %s', e)

        return res
