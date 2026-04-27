from odoo import models, fields


class SaleScheduledMedicineConfirmWizard(models.TransientModel):
    _name = 'sale.scheduled.medicine.confirm.wizard'
    _description = 'Confirm Scheduled Medicine Sale'

    sale_order_id = fields.Many2one(
        'sale.order',
        string='Sale Order',
        required=True,
        readonly=True,
        ondelete='cascade',
    )
    message = fields.Char(
        string='Message',
        default='Pharmacist Authentication Required',
        readonly=True,
    )
    medicine_names = fields.Text(
        string='Scheduled Medicines',
        readonly=True,
    )

    def action_confirm(self):
        self.ensure_one()
        return self.sale_order_id.with_context(
            skip_scheduled_medicine_confirm=True
        ).action_confirm()

    def action_cancel(self):
        return {'type': 'ir.actions.act_window_close'}
