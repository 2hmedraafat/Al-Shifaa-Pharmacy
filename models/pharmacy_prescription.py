from odoo import models, fields, api, _
from odoo.exceptions import ValidationError


class PharmacyPrescription(models.Model):
    _name = 'pharmacy.prescription'
    _description = 'Pharmacy Prescription (Rx)'
    _rec_name = 'name'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date desc'

    name = fields.Char(
        string='Prescription Reference',
        required=True,
        copy=False,
        readonly=True,
        default=lambda self: _('New')
    )
    date = fields.Date(
        string='Prescription Date',
        required=True,
        default=fields.Date.today
    )
    patient_name = fields.Char(
        string='Patient Name',
        required=True
    )
    patient_id = fields.Char(
        string='Patient ID',
        required=True
    )
    doctor_name = fields.Char(
        string='Doctor Name',
        required=True
    )
    product_id = fields.Many2one(
        'product.template',
        string='Medicine',
        required=True,
        domain=[('is_scheduled_medicine', '=', True)]
    )
    schedule_level = fields.Selection(
        related='product_id.schedule_level',
        string='Schedule Level',
        readonly=True
    )
    qty_prescribed = fields.Float(
        string='Prescribed Quantity',
        required=True,
        default=1.0
    )
    qty_dispensed = fields.Float(
        string='Dispensed Quantity',
        readonly=True,
        default=0.0
    )
    qty_remaining = fields.Float(
        string='Remaining Quantity',
        compute='_compute_qty_remaining',
        store=True
    )
    state = fields.Selection([
        ('open', 'Open'),
        ('partial', 'Partially Dispensed'),
        ('done', 'Fully Dispensed'),
        ('cancelled', 'Cancelled'),
    ], string='Status', default='open')

    notes = fields.Text(string='Notes')

    # -------------------------------------------------------
    # Compute remaining quantity
    # -------------------------------------------------------
    @api.depends('qty_prescribed', 'qty_dispensed')
    def _compute_qty_remaining(self):
        for rec in self:
            rec.qty_remaining = rec.qty_prescribed - rec.qty_dispensed

    # -------------------------------------------------------
    # Auto-generate Rx reference on creation
    # -------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'pharmacy.prescription'
                ) or _('New')
        return super().create(vals_list)

    # -------------------------------------------------------
    # Validate qty_prescribed > 0
    # -------------------------------------------------------
    @api.constrains('qty_prescribed')
    def _check_qty_prescribed(self):
        for rec in self:
            if rec.qty_prescribed <= 0:
                raise ValidationError(
                    _('Prescribed quantity must be greater than 0.')
                )

    # -------------------------------------------------------
    # Dispense method — called from POS/Sale
    # -------------------------------------------------------
    def action_dispense(self, qty):
        self.ensure_one()

        if self.state in ('done', 'cancelled'):
            raise ValidationError(
                _('Prescription %s is already %s.') % (self.name, self.state)
            )

        if qty <= 0:
            raise ValidationError(
                _('Dispensed quantity must be greater than 0.')
            )

        if qty > self.qty_remaining:
            raise ValidationError(
                _('Cannot dispense %s units. Only %s remaining on Rx %s.')
                % (qty, self.qty_remaining, self.name)
            )

        self.qty_dispensed += qty

        if self.qty_remaining <= 0:
            self.state = 'done'
        else:
            self.state = 'partial'

        # -------------------------------------------------------
        # Auto-create Controlled Substances Register entry
        # -------------------------------------------------------
        if self.product_id.is_scheduled_medicine:
            self.env['pharmacy.controlled.register'].create({
                'patient_name': self.patient_name,
                'patient_id_number': self.patient_id,
                'product_id': self.product_id.id,
                'schedule_level': self.schedule_level,
                'lot_number': self.product_id.default_code or '',
                'qty_dispensed': qty,
                'pharmacist_id': self.env.user.id,
                'rx_id': self.id,
                'rx_reference': self.name,
                'notes': self.notes or '',
            })

    # -------------------------------------------------------
    # Buttons for UI testing
    # -------------------------------------------------------
    def action_dispense_one(self):
        for rec in self:
            if rec.qty_remaining <= 0:
                raise ValidationError(_('There is no remaining quantity to dispense.'))
            rec.action_dispense(1)

    def action_dispense_all(self):
        for rec in self:
            if rec.qty_remaining <= 0:
                raise ValidationError(_('There is no remaining quantity to dispense.'))
            rec.action_dispense(rec.qty_remaining)