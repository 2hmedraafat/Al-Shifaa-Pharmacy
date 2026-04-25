from odoo import fields, models, tools


class PharmacyCommissionReport(models.Model):
    _name = 'pharmacy.commission.report'
    _description = 'Commission Report'
    _auto = False
    _rec_name = 'sale_order_id'
    _order = 'sale_order_id desc, id desc'

    sale_order_id = fields.Many2one('sale.order', string='Sale Order', readonly=True)
    customer_id = fields.Many2one('res.partner', string='Customer', readonly=True)
    salesperson_id = fields.Many2one('res.users', string='Salesperson', readonly=True)
    product_id = fields.Many2one('product.product', string='Product', readonly=True)
    product_uom_qty = fields.Float(string='Qty', readonly=True)
    price_unit = fields.Float(string='Unit Price', readonly=True)
    price_subtotal = fields.Monetary(string='Subtotal', readonly=True)
    commission_amount = fields.Monetary(string='Commission', readonly=True)
    currency_id = fields.Many2one('res.currency', string='Currency', readonly=True)
    order_state = fields.Selection(
        selection=[
            ('draft', 'Quotation'),
            ('sent', 'Quotation Sent'),
            ('sale', 'Sales Order'),
            ('done', 'Locked'),
            ('cancel', 'Cancelled'),
        ],
        string='Status',
        readonly=True,
    )

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute(f"""
            CREATE OR REPLACE VIEW {self._table} AS (
                SELECT
                    sol.id AS id,
                    sol.order_id AS sale_order_id,
                    so.partner_id AS customer_id,
                    so.user_id AS salesperson_id,
                    sol.product_id AS product_id,
                    sol.product_uom_qty AS product_uom_qty,
                    sol.price_unit AS price_unit,
                    sol.price_subtotal AS price_subtotal,
                    sol.commission_amount AS commission_amount,
                    so.currency_id AS currency_id,
                    so.state AS order_state
                FROM sale_order_line sol
                JOIN sale_order so ON so.id = sol.order_id
                WHERE sol.display_type IS NULL
                  AND sol.product_id IS NOT NULL
                  AND so.state != 'cancel'
            )
        """)
