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
    ], string='Status', default='open', tracking=True)

    notes = fields.Text(string='Notes')
    partner_id = fields.Many2one('res.partner', string='Patient Contact', readonly=True, copy=False)
    sale_order_id = fields.Many2one('sale.order', string='Sale Order', readonly=True, copy=False)
    invoice_id = fields.Many2one('account.move', string='Invoice', readonly=True, copy=False)

    @api.depends('qty_prescribed', 'qty_dispensed')
    def _compute_qty_remaining(self):
        for rec in self:
            rec.qty_remaining = rec.qty_prescribed - rec.qty_dispensed

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'pharmacy.prescription'
                ) or _('New')
        return super().create(vals_list)

    @api.constrains('qty_prescribed')
    def _check_qty_prescribed(self):
        for rec in self:
            if rec.qty_prescribed <= 0:
                raise ValidationError(
                    _('Prescribed quantity must be greater than 0.')
                )

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

    def _get_or_create_patient_partner(self):
        self.ensure_one()
        if self.partner_id:
            return self.partner_id

        partner = self.env['res.partner'].search([
            ('name', '=', self.patient_name),
            ('ref', '=', self.patient_id),
        ], limit=1)

        if not partner:
            partner = self.env['res.partner'].create({
                'name': self.patient_name,
                'ref': self.patient_id,
                'customer_rank': 1,
            })

        self.partner_id = partner.id
        return partner

    def _process_picking(self, picking):
        if not picking or picking.state in ('done', 'cancel'):
            return

        picking.action_assign()

        for move in picking.move_ids:
            qty_to_do = move.quantity if 'quantity' in move._fields else move.product_uom_qty
            for line in move.move_line_ids:
                if 'quantity' in line._fields:
                    line.quantity = qty_to_do
                elif 'qty_done' in line._fields:
                    line.qty_done = qty_to_do

        result = picking.button_validate()
        if isinstance(result, dict):
            model = result.get('res_model')
            res_id = result.get('res_id')
            if model and res_id and model in self.env:
                wizard = self.env[model].browse(res_id)
                if hasattr(wizard, 'process'):
                    wizard.process()
                elif hasattr(wizard, 'process_cancel_backorder'):
                    wizard.process_cancel_backorder()

    def action_create_invoice(self):
        for rec in self:
            if rec.invoice_id:
                raise ValidationError(_('Invoice already created for %s.') % rec.name)

            if rec.qty_dispensed <= 0:
                raise ValidationError(_('Dispense the prescription first before creating invoice.'))

            product = rec.product_id.product_variant_id
            if not product:
                raise ValidationError(_('Selected medicine has no product variant.'))

            partner = rec._get_or_create_patient_partner()

            sale_order = self.env['sale.order'].create({
                'partner_id': partner.id,
                'origin': rec.name,
                'note': rec.notes or '',
                'order_line': [(0, 0, {
                    'product_id': product.id,
                    'product_uom_qty': rec.qty_dispensed,
                    'price_unit': rec.product_id.list_price,
                    'name': product.display_name,
                })],
            })
            sale_order.action_confirm()

            for picking in sale_order.picking_ids.filtered(lambda p: p.state not in ('done', 'cancel')):
                rec._process_picking(picking)

            invoice = sale_order._create_invoices()
            if invoice and invoice.state == 'draft':
                invoice.action_post()

            rec.sale_order_id = sale_order.id
            rec.invoice_id = invoice.id if invoice else False

    def action_view_sale_order(self):
        self.ensure_one()
        if not self.sale_order_id:
            return False
        return {
            'type': 'ir.actions.act_window',
            'name': _('Sale Order'),
            'res_model': 'sale.order',
            'res_id': self.sale_order_id.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_view_invoice(self):
        self.ensure_one()
        if not self.invoice_id:
            return False
        return {
            'type': 'ir.actions.act_window',
            'name': _('Invoice'),
            'res_model': 'account.move',
            'res_id': self.invoice_id.id,
            'view_mode': 'form',
            'target': 'current',
        }
