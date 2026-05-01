from dateutil.relativedelta import relativedelta

from odoo import api, fields, models, _


class StockLotExpiryActivities(models.Model):
    _inherit = 'stock.lot'

    @api.model
    def _pharmacy_get_thresholds(self):
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
    def action_create_expiry_activities(self):
        today = fields.Date.context_today(self)
        warning_days, critical_days = self._pharmacy_get_thresholds()
        warning_limit = today + relativedelta(days=warning_days)
        critical_limit = today + relativedelta(days=critical_days)

        Activity = self.env['mail.activity'].sudo()
        lot_model = self.env['ir.model'].sudo()._get('stock.lot')
        activity_type = self.env.ref('mail.mail_activity_data_warning', raise_if_not_found=False) or self.env.ref('mail.mail_activity_data_todo')

        manager_group = self.env.ref('pharmacy.group_pharmacy_manager', raise_if_not_found=False)
        manager_users = manager_group.users if manager_group else self.env['res.users']
        manager_users = manager_users.filtered(lambda user: user.active)
        if not manager_users:
            manager_users = self.env.ref('base.user_admin')

        lots = self.sudo().search([
            ('expiration_date', '!=', False),
            ('product_qty', '>', 0),
            ('product_id.product_tmpl_id.classification', '=', 'medicine'),
            ('expiration_date', '<=', warning_limit),
        ], order='expiration_date asc')

        for lot in lots:
            expiry_date = fields.Date.to_date(lot.expiration_date)
            if expiry_date < today:
                level = _('Expired')
                deadline = today
            elif expiry_date <= critical_limit:
                level = _('Critical Expiry')
                deadline = today
            else:
                level = _('Near Expiry')
                deadline = expiry_date

            summary = _('Pharmacy Expiry Alert: %s') % level
            note = _(
                'Lot %(lot)s for product %(product)s expires on %(date)s. Current lot quantity: %(qty)s.',
                lot=lot.name,
                product=lot.product_id.display_name,
                date=expiry_date,
                qty=lot.product_qty,
            )

            for user in manager_users:
                existing = Activity.search([
                    ('res_model_id', '=', lot_model.id),
                    ('res_id', '=', lot.id),
                    ('user_id', '=', user.id),
                    ('activity_type_id', '=', activity_type.id),
                    ('summary', '=', summary),
                ], limit=1)
                if existing:
                    continue
                Activity.create({
                    'res_model_id': lot_model.id,
                    'res_id': lot.id,
                    'user_id': user.id,
                    'activity_type_id': activity_type.id,
                    'summary': summary,
                    'note': note,
                    'date_deadline': deadline,
                })
        return True
