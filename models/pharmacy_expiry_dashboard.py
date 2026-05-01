from dateutil.relativedelta import relativedelta

from odoo import api, fields, models, _


class PharmacyExpiryDashboard(models.TransientModel):
    _name = 'pharmacy.expiry.dashboard'
    _description = 'Pharmacy Expiry Dashboard'

    name = fields.Char(default='Expiry Alerts Dashboard')
    warning_days = fields.Integer(compute='_compute_dashboard_data')
    critical_days = fields.Integer(compute='_compute_dashboard_data')
    expired_lot_count = fields.Integer(compute='_compute_dashboard_data')
    critical_lot_count = fields.Integer(compute='_compute_dashboard_data')
    near_lot_count = fields.Integer(compute='_compute_dashboard_data')
    total_alert_lot_count = fields.Integer(compute='_compute_dashboard_data')

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

    def _base_lot_domain(self):
        internal_lot_ids = self.env['stock.quant'].sudo().search([
            ('lot_id', '!=', False),
            ('quantity', '>', 0),
            ('location_id.usage', '=', 'internal'),
            ('product_id.product_tmpl_id.classification', '=', 'medicine'),
        ]).mapped('lot_id').ids
        return [
            ('id', 'in', internal_lot_ids),
            ('expiration_date', '!=', False),
            ('product_id.product_tmpl_id.classification', '=', 'medicine'),
        ]

    def _expiry_domains(self):
        today = fields.Date.context_today(self)
        warning_days, critical_days = self._pharmacy_get_thresholds()
        critical_limit = today + relativedelta(days=critical_days)
        warning_limit = today + relativedelta(days=warning_days)
        base = self._base_lot_domain()
        return {
            'expired': base + [('expiration_date', '<', today)],
            'critical': base + [('expiration_date', '>=', today), ('expiration_date', '<=', critical_limit)],
            'near': base + [('expiration_date', '>', critical_limit), ('expiration_date', '<=', warning_limit)],
            'all': base + [('expiration_date', '<=', warning_limit)],
        }

    @api.depends_context('uid')
    def _compute_dashboard_data(self):
        domains = self._expiry_domains()
        warning_days, critical_days = self._pharmacy_get_thresholds()
        Lot = self.env['stock.lot'].sudo()
        for rec in self:
            rec.warning_days = warning_days
            rec.critical_days = critical_days
            rec.expired_lot_count = Lot.search_count(domains['expired'])
            rec.critical_lot_count = Lot.search_count(domains['critical'])
            rec.near_lot_count = Lot.search_count(domains['near'])
            rec.total_alert_lot_count = Lot.search_count(domains['all'])

    @api.model
    def action_open_dashboard(self):
        dashboard = self.create({})
        return {
            'type': 'ir.actions.act_window',
            'name': _('Expiry Alerts Dashboard'),
            'res_model': 'pharmacy.expiry.dashboard',
            'view_mode': 'form',
            'res_id': dashboard.id,
            'target': 'current',
        }

    def _open_lots(self, title, domain_key):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': title,
            'res_model': 'stock.lot',
            'view_mode': 'list,form',
            'domain': self._expiry_domains()[domain_key],
            'context': {'search_default_group_by_product': 1},
        }

    def action_open_expired_lots(self):
        return self._open_lots(_('Expired Lots'), 'expired')

    def action_open_critical_lots(self):
        return self._open_lots(_('Critical Expiry Lots'), 'critical')

    def action_open_near_lots(self):
        return self._open_lots(_('Near-Expiry Lots'), 'near')

    def action_open_all_alert_lots(self):
        return self._open_lots(_('All Expiry Alert Lots'), 'all')
