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

    pharmacy_max_product_suggestions = fields.Integer(
        string='Max Related Products per List',
        config_parameter='pharmacy.max_product_suggestions',
        default=10,
        help='Maximum similar products and maximum complementary products allowed per product.',
    )
    pharmacy_pos_expiry_indicator_enabled = fields.Boolean(
        string='POS Expiry Indicator Enabled',
        config_parameter='pharmacy.pos_expiry_indicator_enabled',
        default=True,
        help='Show the red/orange expiry clock indicator on POS product tiles.',
    )

    @api.constrains('pharmacy_max_product_suggestions')
    def _check_pharmacy_max_product_suggestions(self):
        for rec in self:
            if rec.pharmacy_max_product_suggestions <= 0:
                raise ValidationError(_('Max Related Products per List must be greater than 0.'))

    @api.constrains('pharmacy_expiry_warning_days', 'pharmacy_expiry_critical_days')
    def _check_pharmacy_expiry_thresholds(self):
        for rec in self:
            if rec.pharmacy_expiry_warning_days <= 0:
                raise ValidationError(_('Near-Expiry Warning Days must be greater than 0.'))
            if rec.pharmacy_expiry_critical_days <= 0:
                raise ValidationError(_('Critical Expiry Days must be greater than 0.'))
            if rec.pharmacy_expiry_critical_days > rec.pharmacy_expiry_warning_days:
                raise ValidationError(_('Critical Expiry Days must be less than or equal to Near-Expiry Warning Days.'))
