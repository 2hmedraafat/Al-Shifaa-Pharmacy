from odoo import models


class PosSession(models.Model):
    _inherit = 'pos.session'

    def _loader_params_product_product(self):
        """Load pharmacy fields used by POS custom barcode rules."""
        result = super()._loader_params_product_product()
        fields = result['search_params']['fields']
        for field_name in ['barcode', 'display_name', 'is_scheduled_medicine', 'product_tmpl_id', 'pharmacy_expiry_alert_state', 'pharmacy_nearest_expiry_date']:
            if field_name not in fields:
                fields.append(field_name)
        return result
