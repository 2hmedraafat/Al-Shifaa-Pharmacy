from odoo import models, fields, api, _
from odoo.exceptions import ValidationError


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    # -------------------------------------------------------
    # UC-06 — Scheduled Medicine
    # -------------------------------------------------------
    is_scheduled_medicine = fields.Boolean(
        string='Medicine is Scheduled',
        default=False,
        tracking=True,
        help='Check if this medicine is a controlled/scheduled substance.'
    )

    schedule_level = fields.Selection([
        ('1', 'Schedule I'),
        ('2', 'Schedule II'),
        ('3', 'Schedule III'),
        ('4', 'Schedule IV'),
        ('5', 'Schedule V'),
    ], string='Schedule Level', tracking=True)

    # -------------------------------------------------------
    # EAN-13 Check Digit Calculator
    # -------------------------------------------------------
    def _compute_ean13_check_digit(self, barcode_12):
        total = 0
        for i, digit in enumerate(barcode_12):
            if i % 2 == 0:
                total += int(digit) * 1
            else:
                total += int(digit) * 3
        check = (10 - (total % 10)) % 10
        return str(check)

    # -------------------------------------------------------
    # UC-03 — Barcode Format Validation
    # Supported: Internal Pharmacy Barcode, EAN-8, EAN-13, UPC-A (12), UPC-E (8), Code128
    # -------------------------------------------------------
    def _validate_barcode_format(self, barcode):
        barcode = barcode.strip()

        if not barcode:
            raise ValidationError(_('Barcode cannot be empty.'))

        # Internal Pharmacy Barcode
        # Format: 21 + 01 + 0001
        # Example: 21010001
        if barcode.isdigit() and len(barcode) == 8 and barcode.startswith('21'):
            return True

        # Code128 — alphanumeric, skip check digit validation
        if not barcode.isdigit():
            return True

        length = len(barcode)

        if length == 13:
            self._check_ean_digit(barcode, 13)
        elif length == 8:
            self._check_ean_digit(barcode, 8)
        elif length == 12:
            self._check_upc_digit(barcode)
        else:
            raise ValidationError(
                _('Barcode "%s" has unsupported format.\n'
                  'Accepted formats: Internal Pharmacy Barcode, EAN-8, EAN-13, UPC-A (12 digits), UPC-E (8 digits), Code128.')
                % barcode
            )
        return True

    def _check_ean_digit(self, barcode, length):
        digits = [int(d) for d in barcode]
        if length == 13:
            total = sum(d * (1 if i % 2 == 0 else 3) for i, d in enumerate(digits[:-1]))
        else:
            total = sum(d * (3 if i % 2 == 0 else 1) for i, d in enumerate(digits[:-1]))
        check = (10 - (total % 10)) % 10
        if check != digits[-1]:
            raise ValidationError(
                _('Barcode "%s" has an invalid check digit. Expected %d, got %d.\n'
                  'Please verify the barcode number.')
                % (barcode, check, digits[-1])
            )

    def _check_upc_digit(self, barcode):
        digits = [int(d) for d in barcode]
        total = sum(d * (3 if i % 2 == 0 else 1) for i, d in enumerate(digits[:-1]))
        check = (10 - (total % 10)) % 10
        if check != digits[-1]:
            raise ValidationError(
                _('UPC-A Barcode "%s" has an invalid check digit. Expected %d, got %d.\n'
                  'Please verify the barcode number.')
                % (barcode, check, digits[-1])
            )

    @api.constrains('barcode')
    def _check_barcode_format(self):
        for rec in self:
            if rec.barcode:
                rec._validate_barcode_format(rec.barcode)

    # -------------------------------------------------------
    # UC-03 — Generate Internal Barcode
    # Format: 21 + 01 + 0001
    # Example: 21010001
    # -------------------------------------------------------
    def action_generate_barcode(self):
        for product in self:
            sequence_value = self.env['ir.sequence'].next_by_code('pharmacy.barcode')
            if not sequence_value:
                raise ValidationError(
                    _('Barcode sequence "pharmacy.barcode" not found. '
                      'Please check your data configuration.')
                )

            sequence_digits = ''.join(filter(str.isdigit, sequence_value))
            sequence_digits = sequence_digits.zfill(4)[-4:]

            new_barcode = f'2101{sequence_digits}'
            product.barcode = new_barcode


class ProductProduct(models.Model):
    _inherit = 'product.product'

    is_scheduled_medicine = fields.Boolean(
        related='product_tmpl_id.is_scheduled_medicine',
        string='Medicine is Scheduled',
        store=True
    )