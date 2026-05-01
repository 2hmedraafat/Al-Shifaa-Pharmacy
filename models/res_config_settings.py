from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    pharmacy_expiry_warning_days = fields.Integer(
        string='Near-Expiry Warning Days',
        config_parameter='pharmacy.expiry_warning_days',
        default=30,
        help='Products/lots expiring within this number of days appear as near-expiry.',
    )
    pharmacy_expiry_critical_days = fields.Integer(
        string='Critical Expiry Days',
        config_parameter='pharmacy.expiry_critical_days',
        default=7,
        help='Products/lots expiring within this number of days appear as critical.',
    )

    @api.constrains('pharmacy_expiry_warning_days', 'pharmacy_expiry_critical_days')
    def _check_pharmacy_expiry_thresholds(self):
        for rec in self:
            if rec.pharmacy_expiry_warning_days <= 0:
                raise ValidationError(_('Near-Expiry Warning Days must be greater than 0.'))
            if rec.pharmacy_expiry_critical_days <= 0:
                raise ValidationError(_('Critical Expiry Days must be greater than 0.'))
            if rec.pharmacy_expiry_critical_days > rec.pharmacy_expiry_warning_days:
                raise ValidationError(_('Critical Expiry Days must be less than or equal to Near-Expiry Warning Days.'))
