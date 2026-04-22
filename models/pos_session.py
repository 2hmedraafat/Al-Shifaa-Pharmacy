from odoo import models


class PosSession(models.Model):
    _inherit = 'pos.session'

    def _loader_params_product_product(self):
        """
        إضافة is_scheduled_medicine للـ POS
        عشان الـ JS يعرف الدواء Scheduled ولا لأ
        """
        result = super()._loader_params_product_product()
        result['search_params']['fields'].append('is_scheduled_medicine')
        return result