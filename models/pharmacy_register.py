from odoo import models, fields, api, _
from odoo.exceptions import ValidationError, AccessError


class PharmacyControlledRegister(models.Model):
    _name = 'pharmacy.controlled.register'
    _description = 'Controlled Substances Register (Narcotics)'
    _rec_name = 'name'
    _order = 'date desc'

    name = fields.Char(
        string='Register Reference',
        required=True,
        copy=False,
        readonly=True,
        default=lambda self: _('New')
    )
    date = fields.Datetime(
        string='Date & Time',
        required=True,
        readonly=True,
        default=fields.Datetime.now
    )
    patient_name = fields.Char(
        string='Patient Name',
        required=True,
        readonly=True
    )
    patient_id_number = fields.Char(
        string='Patient ID',
        required=True,
        readonly=True
    )
    product_id = fields.Many2one(
        'product.template',
        string='Medicine',
        required=True,
        readonly=True
    )
    schedule_level = fields.Selection([
        ('1', 'Schedule I'),
        ('2', 'Schedule II'),
        ('3', 'Schedule III'),
        ('4', 'Schedule IV'),
        ('5', 'Schedule V'),
    ], string='Schedule Level', readonly=True)
    lot_number = fields.Char(
        string='Lot / Batch Number',
        readonly=True
    )
    qty_dispensed = fields.Float(
        string='Quantity Dispensed',
        required=True,
        readonly=True
    )
    pharmacist_id = fields.Many2one(
        'res.users',
        string='Dispensing Pharmacist',
        required=True,
        readonly=True,
        default=lambda self: self.env.user
    )
    rx_id = fields.Many2one(
        'pharmacy.prescription',
        string='Prescription (Rx)',
        readonly=True
    )
    rx_reference = fields.Char(
        string='Rx Reference',
        readonly=True
    )
    notes = fields.Text(
        string='Notes',
        readonly=True
    )

    # -------------------------------------------------------
    # Auto-generate Register reference
    # -------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'pharmacy.controlled.register'
                ) or _('New')
        return super().create(vals_list)

    # -------------
    # IMMUTABLE — 
    # -------------
    def write(self, vals):
        raise AccessError(
            _('Controlled Substances Register entries are immutable. '
              'No modifications are allowed.')
        )

    def unlink(self):
        raise AccessError(
            _('Controlled Substances Register entries cannot be deleted. '
              'This is a permanent regulatory record.')
        )