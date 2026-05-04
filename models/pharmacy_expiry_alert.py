from collections import defaultdict

from odoo import api, fields, models, _
from odoo.tools import html_escape


class StockLotExpiredDetection(models.Model):
    _inherit = 'stock.lot'

    @api.model
    def _pharmacy_get_expiry_thresholds(self):
        ICP = self.env['ir.config_parameter'].sudo()
        warning_days = int(ICP.get_param('pharmacy.expiry_warning_days', 30) or 30)
        critical_days = int(ICP.get_param('pharmacy.expiry_critical_days', 7) or 7)
        if warning_days < 1:
            warning_days = 30
        if critical_days < 1:
            critical_days = 7
        if critical_days > warning_days:
            critical_days = warning_days
        return warning_days, critical_days

    @api.model
    def _pharmacy_get_expired_lot_quants(self):
        """Return positive internal quants for expired medicine lots only.

        SC2-UC-04 is detection-only: we scan internal locations and notify managers.
        We do not create transfers, scrap moves, or change stock quantities.
        """
        today = fields.Date.context_today(self)
        return self.env['stock.quant'].sudo().search([
            ('lot_id', '!=', False),
            ('quantity', '>', 0),
            ('location_id.usage', '=', 'internal'),
            ('product_id.product_tmpl_id.classification', '=', 'medicine'),
            ('lot_id.expiration_date', '!=', False),
            ('lot_id.expiration_date', '<', today),
        ], order='location_id, product_id, lot_id')

    @api.model
    def _pharmacy_get_near_expiry_lot_quants(self):
        """Return positive internal quants for non-expired medicine lots within warning threshold.

        SC2-UC-03 only creates near-expiry/critical warning activities.
        Expired lots stay handled by SC2-UC-04 action_detect_expired_lots_notify_inventory_manager().
        """
        today = fields.Date.context_today(self)
        warning_days, critical_days = self._pharmacy_get_expiry_thresholds()
        warning_limit = fields.Date.add(today, days=warning_days)
        return self.env['stock.quant'].sudo().search([
            ('lot_id', '!=', False),
            ('quantity', '>', 0),
            ('location_id.usage', '=', 'internal'),
            ('product_id.product_tmpl_id.classification', '=', 'medicine'),
            ('lot_id.expiration_date', '!=', False),
            ('lot_id.expiration_date', '>=', today),
            ('lot_id.expiration_date', '<=', warning_limit),
        ], order='location_id, product_id, lot_id')

    @api.model
    def _pharmacy_get_inventory_manager_users(self):
        """Use Odoo Inventory Manager group as the recipient group."""
        inventory_group = self.env.ref('stock.group_stock_manager', raise_if_not_found=False)
        users = inventory_group.users if inventory_group else self.env['res.users']
        users = users.filtered(lambda user: user.active and not user.share)
        if not users:
            admin = self.env.ref('base.user_admin', raise_if_not_found=False)
            users = admin if admin else self.env['res.users']
        return users

    @api.model
    def _pharmacy_expired_medicines_url(self):
        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url', '')
        action = self.env.ref('pharmacy.action_pharmacy_expired_medicines', raise_if_not_found=False)
        if action:
            return f'{base_url}/web#action={action.id}&model=stock.quant&view_type=list'
        return f'{base_url}/web#model=stock.quant&view_type=list'

    @api.model
    def _pharmacy_expiry_dashboard_url(self):
        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url', '')
        action = self.env.ref('pharmacy.action_pharmacy_expiry_dashboard_server', raise_if_not_found=False)
        if action:
            return f'{base_url}/web#action={action.id}'
        return f'{base_url}/web#model=pharmacy.expiry.dashboard&view_type=form'

    @api.model
    def action_create_near_expiry_activities(self):
        """Create/update warning activities for SC2-UC-03 near-expiry alerts only.

        This method deliberately excludes expired lots, so SC2-UC-04 remains responsible
        for expired lot detection and expired medicine notifications.
        """
        quants = self._pharmacy_get_near_expiry_lot_quants()
        if not quants:
            return True

        today = fields.Date.context_today(self)
        warning_days, critical_days = self._pharmacy_get_expiry_thresholds()
        critical_limit = fields.Date.add(today, days=critical_days)

        lots_data = defaultdict(lambda: {
            'qty': 0.0,
            'locations': set(),
            'product': False,
            'expiry': False,
            'state': 'near',
        })
        for quant in quants:
            lot = quant.lot_id
            expiry_date = fields.Date.to_date(lot.expiration_date)
            lots_data[lot]['qty'] += quant.quantity
            lots_data[lot]['locations'].add(quant.location_id.display_name)
            lots_data[lot]['product'] = quant.product_id.display_name
            lots_data[lot]['expiry'] = expiry_date
            lots_data[lot]['state'] = 'critical' if expiry_date <= critical_limit else 'near'

        Activity = self.env['mail.activity'].sudo()
        model = self.env['ir.model'].sudo()._get('stock.lot')
        activity_type = (
            self.env.ref('mail.mail_activity_data_warning', raise_if_not_found=False)
            or self.env.ref('mail.mail_activity_data_todo')
        )
        users = self._pharmacy_get_inventory_manager_users()
        dashboard_url = self._pharmacy_expiry_dashboard_url()

        critical_summary = _('Critical Expiry Medicine Lot Alert')
        near_summary = _('Near-Expiry Medicine Lot Alert')
        managed_summaries = [critical_summary, near_summary]

        for lot, data in lots_data.items():
            is_critical = data['state'] == 'critical'
            summary = critical_summary if is_critical else near_summary
            alert_label = _('Critical') if is_critical else _('Near Expiry')
            threshold_days = critical_days if is_critical else warning_days
            locations = ', '.join(sorted(data['locations']))
            note = _(
                '%(alert_label)s medicine lot alert.<br/>'
                '<b>Product:</b> %(product)s<br/>'
                '<b>Lot:</b> %(lot)s<br/>'
                '<b>Expiry Date:</b> %(expiry)s<br/>'
                '<b>Internal Quantity:</b> %(qty)s<br/>'
                '<b>Internal Location(s):</b> %(locations)s<br/>'
                '<b>Configured Threshold:</b> %(threshold_days)s days<br/><br/>'
                '<a href="%(url)s">Open Expiry Alerts Dashboard</a><br/><br/>'
                'Warning only: no automatic transfer or stock movement was created.',
                alert_label=alert_label,
                product=html_escape(data['product'] or ''),
                lot=html_escape(lot.name or ''),
                expiry=data['expiry'],
                qty=data['qty'],
                locations=html_escape(locations),
                threshold_days=threshold_days,
                url=dashboard_url,
            )

            for user in users:
                existing = Activity.search([
                    ('res_model_id', '=', model.id),
                    ('res_id', '=', lot.id),
                    ('user_id', '=', user.id),
                    ('activity_type_id', '=', activity_type.id),
                    ('summary', 'in', managed_summaries),
                ], limit=1)
                values = {
                    'summary': summary,
                    'note': note,
                    'date_deadline': today,
                }
                if existing:
                    existing.write(values)
                    continue

                Activity.create(dict(values, **{
                    'res_model_id': model.id,
                    'res_id': lot.id,
                    'user_id': user.id,
                    'activity_type_id': activity_type.id,
                }))
        return True

    @api.model
    def action_detect_expired_lots_notify_inventory_manager(self):
        """Nightly expired lot detector for SC2-UC-04.

        - Scans Internal locations only.
        - Detects expired medicine lots with available quantity.
        - Notifies Inventory Managers with a direct link to Expired Medicines.
        - Does not auto-transfer, scrap, reserve, or modify stock.
        """
        quants = self._pharmacy_get_expired_lot_quants()
        if not quants:
            return True

        lots_data = defaultdict(lambda: {'qty': 0.0, 'locations': set(), 'product': False, 'expiry': False})
        for quant in quants:
            lot = quant.lot_id
            lots_data[lot]['qty'] += quant.quantity
            lots_data[lot]['locations'].add(quant.location_id.display_name)
            lots_data[lot]['product'] = quant.product_id.display_name
            lots_data[lot]['expiry'] = fields.Date.to_date(lot.expiration_date)

        Activity = self.env['mail.activity'].sudo()
        model = self.env['ir.model'].sudo()._get('stock.lot')
        activity_type = (
            self.env.ref('mail.mail_activity_data_warning', raise_if_not_found=False)
            or self.env.ref('mail.mail_activity_data_todo')
        )
        users = self._pharmacy_get_inventory_manager_users()
        expired_page_url = self._pharmacy_expired_medicines_url()
        today = fields.Date.context_today(self)

        for lot, data in lots_data.items():
            summary = _('Expired Medicine Lot Detected')
            locations = ', '.join(sorted(data['locations']))
            note = _(
                'Expired medicine lot detected.<br/>'
                '<b>Product:</b> %(product)s<br/>'
                '<b>Lot:</b> %(lot)s<br/>'
                '<b>Expiry Date:</b> %(expiry)s<br/>'
                '<b>Internal Quantity:</b> %(qty)s<br/>'
                '<b>Internal Location(s):</b> %(locations)s<br/><br/>'
                '<a href="%(url)s">Open Expired Medicines page</a><br/><br/>'
                'Detection only: no automatic transfer or stock movement was created.',
                product=html_escape(data['product'] or ''),
                lot=html_escape(lot.name or ''),
                expiry=data['expiry'],
                qty=data['qty'],
                locations=html_escape(locations),
                url=expired_page_url,
            )

            for user in users:
                existing = Activity.search([
                    ('res_model_id', '=', model.id),
                    ('res_id', '=', lot.id),
                    ('user_id', '=', user.id),
                    ('activity_type_id', '=', activity_type.id),
                    ('summary', '=', summary),
                ], limit=1)
                if existing:
                    existing.write({
                        'note': note,
                        'date_deadline': today,
                    })
                    continue

                Activity.create({
                    'res_model_id': model.id,
                    'res_id': lot.id,
                    'user_id': user.id,
                    'activity_type_id': activity_type.id,
                    'summary': summary,
                    'note': note,
                    'date_deadline': today,
                })
        return True

    # Backward compatibility with the old cron name if it still exists in DB.
    @api.model
    def action_create_expiry_activities(self):
        return self.action_detect_expired_lots_notify_inventory_manager()
