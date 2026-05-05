from calendar import monthrange
from datetime import datetime, time

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError
from odoo.tools.float_utils import float_compare


EXPIRY_FIELDS = ('expiration_date', 'use_date', 'removal_date', 'alert_date')


def _parse_month_year(value):
    value = (value or '').strip()
    if not value:
        return False, False, False

    parts = value.split('/')
    if len(parts) != 2 or len(parts[0]) != 2 or len(parts[1]) != 4:
        raise ValidationError(_('Expiration Date must be in MM/YYYY format, for example 04/2028.'))

    try:
        month = int(parts[0])
        year = int(parts[1])
    except ValueError:
        raise ValidationError(_('Expiration Date must be in MM/YYYY format, for example 04/2028.'))

    if month < 1 or month > 12:
        raise ValidationError(_('Expiration month must be between 01 and 12.'))

    return year, month, monthrange(year, month)[1]


def _date_to_month_year(value):
    if not value:
        return False
    expiry_dt = fields.Datetime.to_datetime(value)
    if not expiry_dt:
        return False
    return f'{expiry_dt.month:02d}/{expiry_dt.year:04d}'


def _month_year_to_field_value(record, value, field_name='expiration_date'):
    year, month, last_day = _parse_month_year(value)
    if not year:
        return False

    expiry_date = fields.Date.to_date(f'{year:04d}-{month:02d}-{last_day:02d}')
    field = record._fields.get(field_name)
    if field and field.type == 'datetime':
        # Midday avoids timezone conversion moving the value to the previous day.
        return fields.Datetime.to_string(datetime.combine(expiry_date, time(12, 0, 0)))
    return fields.Date.to_string(expiry_date)


def _normalize_to_month_last_day(record, field_name, value):
    if not value or field_name not in record._fields:
        return value

    field = record._fields[field_name]
    if field.type == 'datetime':
        expiry_dt = fields.Datetime.to_datetime(value)
        if not expiry_dt:
            return value
        last_day = monthrange(expiry_dt.year, expiry_dt.month)[1]
        expiry_dt = expiry_dt.replace(day=last_day, hour=12, minute=0, second=0, microsecond=0)
        return fields.Datetime.to_string(expiry_dt)

    if field.type == 'date':
        expiry_date = fields.Date.to_date(value)
        if not expiry_date:
            return value
        last_day = monthrange(expiry_date.year, expiry_date.month)[1]
        expiry_date = expiry_date.replace(day=last_day)
        return fields.Date.to_string(expiry_date)

    return value



def _is_incoming_receipt_record(record, vals=None):
    """Return True when the move line belongs to an incoming receipt."""
    vals = vals or {}
    picking = False
    if vals.get('picking_id'):
        picking = record.env['stock.picking'].browse(vals['picking_id'])
    elif vals.get('move_id'):
        move = record.env['stock.move'].browse(vals['move_id'])
        picking = move.picking_id
    else:
        picking = getattr(record, 'picking_id', False) or getattr(getattr(record, 'move_id', False), 'picking_id', False)
    return bool(picking and picking.picking_type_code == 'incoming')


def _validate_not_expired_on_incoming_receipt(record, expiry_value, vals=None):
    """Block receiving products with an already expired month/year."""
    if not expiry_value or not _is_incoming_receipt_record(record, vals=vals):
        return
    expiry_dt = fields.Datetime.to_datetime(expiry_value)
    if not expiry_dt:
        expiry_date = fields.Date.to_date(expiry_value)
    else:
        expiry_date = expiry_dt.date()
    today = fields.Date.context_today(record)
    if expiry_date and expiry_date < today:
        raise ValidationError(_(
            'Expired products cannot be received. Please enter an expiry month/year that is not already expired.'
        ))



def _validate_not_expired_month_year(record, expiry_value):
    """Block saving an already expired expiry month/year on lot forms."""
    if not expiry_value or record.env.context.get('pharmacy_allow_past_expiry'):
        return
    expiry_dt = fields.Datetime.to_datetime(expiry_value)
    expiry_date = expiry_dt.date() if expiry_dt else fields.Date.to_date(expiry_value)
    today = fields.Date.context_today(record)
    if expiry_date and expiry_date < today:
        raise ValidationError(_(
            'Expired date is not allowed. Please enter a current or future expiry month/year.'
        ))



def _validate_required_expiry_on_incoming_receipt_line(record, vals=None):
    """Block saving an incoming receipt detailed-operation line when a lot is set without expiry.

    Placeholder remaining lines created by the module are allowed while lot/expiry are both empty.
    Once the user types a Lot/Serial Number, Expiration Date becomes mandatory immediately.
    """
    vals = vals or {}
    if not _is_incoming_receipt_record(record, vals=vals):
        return

    product = False
    if vals.get('product_id'):
        product = record.env['product.product'].browse(vals['product_id'])
    else:
        product = getattr(record, 'product_id', False)
    if not product or product.tracking == 'none':
        return

    lot_id = vals.get('lot_id') if 'lot_id' in vals else getattr(record, 'lot_id', False).id if getattr(record, 'lot_id', False) else False
    lot_name = vals.get('lot_name') if 'lot_name' in vals else (getattr(record, 'lot_name', False) if 'lot_name' in record._fields else False)
    expiry = vals.get('expiration_date') if 'expiration_date' in vals else (getattr(record, 'expiration_date', False) if 'expiration_date' in record._fields else False)

    if (lot_id or lot_name) and not expiry:
        raise ValidationError(_(
            'Expiration Date is required for received lot/serial numbers.'
        ))

def _set_all_lot_dates_on_vals(record, vals, expiry_value):
    """Fill all product_expiry lot dates with the same month-end value."""
    for field_name in EXPIRY_FIELDS:
        if field_name in record._fields:
            vals[field_name] = _normalize_to_month_last_day(record, field_name, expiry_value)
    return vals


def _set_all_lot_dates_on_record(record, expiry_value):
    """Used by onchange/inverse so the Dates tab changes immediately in the form."""
    for field_name in EXPIRY_FIELDS:
        if field_name in record._fields:
            record[field_name] = _normalize_to_month_last_day(record, field_name, expiry_value)


class StockLot(models.Model):
    _inherit = 'stock.lot'

    pharmacy_expiry_month_year = fields.Char(
        string='Expiry Month/Year',
        compute='_compute_pharmacy_expiry_month_year',
        inverse='_inverse_pharmacy_expiry_month_year',
        readonly=False,
        help='Enter expiry date as MM/YYYY. It will be stored as the last day of the selected month.',
    )

    @api.depends('expiration_date')
    def _compute_pharmacy_expiry_month_year(self):
        for record in self:
            record.pharmacy_expiry_month_year = _date_to_month_year(record.expiration_date)

    @api.onchange('pharmacy_expiry_month_year')
    def _onchange_pharmacy_expiry_month_year(self):
        for record in self:
            if record.pharmacy_expiry_month_year:
                expiry_value = _month_year_to_field_value(record, record.pharmacy_expiry_month_year, 'expiration_date')
                _validate_not_expired_month_year(record, expiry_value)
                _set_all_lot_dates_on_record(record, expiry_value)

    def _inverse_pharmacy_expiry_month_year(self):
        for record in self:
            if record.pharmacy_expiry_month_year:
                expiry_value = _month_year_to_field_value(record, record.pharmacy_expiry_month_year, 'expiration_date')
                _validate_not_expired_month_year(record, expiry_value)
                _set_all_lot_dates_on_record(record, expiry_value)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            month_year = vals.pop('pharmacy_expiry_month_year', False)
            if month_year:
                expiry_value = _month_year_to_field_value(self, month_year, 'expiration_date')
                _validate_not_expired_month_year(self, expiry_value)
                _set_all_lot_dates_on_vals(self, vals, expiry_value)
            elif vals.get('expiration_date'):
                expiry_value = _normalize_to_month_last_day(self, 'expiration_date', vals['expiration_date'])
                _validate_not_expired_month_year(self, expiry_value)
                _set_all_lot_dates_on_vals(self, vals, expiry_value)
        return super().create(vals_list)

    def write(self, vals):
        vals = dict(vals)
        month_year = vals.pop('pharmacy_expiry_month_year', False)
        if month_year:
            expiry_value = _month_year_to_field_value(self, month_year, 'expiration_date')
            for record in self:
                _validate_not_expired_month_year(record, expiry_value)
            _set_all_lot_dates_on_vals(self, vals, expiry_value)
        elif vals.get('expiration_date'):
            expiry_value = _normalize_to_month_last_day(self, 'expiration_date', vals['expiration_date'])
            for record in self:
                _validate_not_expired_month_year(record, expiry_value)
            _set_all_lot_dates_on_vals(self, vals, expiry_value)
        return super().write(vals)




class StockMove(models.Model):
    _inherit = 'stock.move'

    def _pharmacy_get_move_line_qty_field(self):
        StockMoveLine = self.env['stock.move.line']
        return 'quantity' if 'quantity' in StockMoveLine._fields else 'qty_done'

    def _pharmacy_prepare_remaining_receipt_lines_onchange(self):
        """Add/update the remaining lot line immediately in the Detailed Operations popup.

        This is UI-only. The write/create hooks below stay as a safety net when the popup is
        saved from Odoo in a way that bypasses onchange.
        """
        qty_field = self._pharmacy_get_move_line_qty_field()
        StockMoveLine = self.env['stock.move.line']

        for move in self:
            picking = move.picking_id
            if not picking or picking.picking_type_code != 'incoming':
                continue
            if move.state in ('done', 'cancel'):
                continue
            if not move.product_id or move.product_id.tracking == 'none':
                continue

            demand = move.product_uom_qty or 0.0
            rounding = move.product_uom.rounding or move.product_id.uom_id.rounding or 0.01
            if float_compare(demand, 0.0, precision_rounding=rounding) <= 0:
                continue

            lines = move.move_line_ids
            placeholder_lines = lines.filtered(lambda line: line._pharmacy_is_placeholder_receipt_line())
            real_lines = lines - placeholder_lines
            real_qty = sum(real_lines.mapped(qty_field))
            remaining = demand - real_qty

            if float_compare(remaining, 0.0, precision_rounding=rounding) <= 0:
                if placeholder_lines:
                    move.move_line_ids -= placeholder_lines
                continue

            if placeholder_lines:
                keep_line = placeholder_lines[0]
                keep_line[qty_field] = remaining
                extra_lines = placeholder_lines - keep_line
                if extra_lines:
                    move.move_line_ids -= extra_lines
                continue

            vals = {
                'picking_id': picking.id,
                'move_id': move.id,
                'product_id': move.product_id.id,
                'location_id': move.location_id.id,
                'location_dest_id': move.location_dest_id.id,
                'company_id': move.company_id.id or picking.company_id.id,
                qty_field: remaining,
            }
            if 'product_uom_id' in StockMoveLine._fields:
                vals['product_uom_id'] = move.product_uom.id
            elif 'product_uom' in StockMoveLine._fields:
                vals['product_uom'] = move.product_uom.id
            move.move_line_ids += StockMoveLine.new(vals)

    @api.onchange('move_line_ids', 'move_line_ids.quantity', 'move_line_ids.lot_id', 'move_line_ids.lot_name', 'move_line_ids.expiration_date')
    def _onchange_pharmacy_auto_remaining_receipt_lines(self):
        self._pharmacy_prepare_remaining_receipt_lines_onchange()

    def _pharmacy_auto_add_remaining_receipt_lines_for_moves(self):
        """Ensure incoming tracked receipt details always show one blank line for remaining qty.

        Example: Demand 20, entered lots total 7 -> create/update one blank line with qty 13.
        This runs from stock.move.write too because the Detailed Operations popup saves the
        stock.move with one2many commands, not always stock.move.line.write directly.
        """
        if self.env.context.get('pharmacy_skip_auto_remaining_receipt_line'):
            return

        qty_field = self._pharmacy_get_move_line_qty_field()
        StockMoveLine = self.env['stock.move.line'].with_context(pharmacy_skip_auto_remaining_receipt_line=True)

        for move in self.exists():
            picking = move.picking_id
            if not picking or picking.picking_type_code != 'incoming':
                continue
            if move.state in ('done', 'cancel'):
                continue
            if not move.product_id or move.product_id.tracking == 'none':
                continue

            demand = move.product_uom_qty or 0.0
            rounding = move.product_uom.rounding or move.product_id.uom_id.rounding or 0.01
            if float_compare(demand, 0.0, precision_rounding=rounding) <= 0:
                continue

            lines = move.move_line_ids.exists()
            placeholder_lines = lines.filtered(lambda line: line._pharmacy_is_placeholder_receipt_line())
            real_lines = lines - placeholder_lines
            real_qty = sum(real_lines.mapped(qty_field))
            remaining = demand - real_qty

            if float_compare(remaining, 0.0, precision_rounding=rounding) <= 0:
                if placeholder_lines:
                    placeholder_lines.with_context(pharmacy_skip_auto_remaining_receipt_line=True).unlink()
                continue

            if placeholder_lines:
                keep_line = placeholder_lines[0]
                extra_lines = placeholder_lines - keep_line
                if extra_lines:
                    extra_lines.with_context(pharmacy_skip_auto_remaining_receipt_line=True).unlink()
                keep_line.with_context(pharmacy_skip_auto_remaining_receipt_line=True).write({qty_field: remaining})
                continue

            vals = {
                'picking_id': picking.id,
                'move_id': move.id,
                'product_id': move.product_id.id,
                'location_id': move.location_id.id,
                'location_dest_id': move.location_dest_id.id,
                'company_id': move.company_id.id or picking.company_id.id,
                qty_field: remaining,
            }
            if 'product_uom_id' in StockMoveLine._fields:
                vals['product_uom_id'] = move.product_uom.id
            elif 'product_uom' in StockMoveLine._fields:
                vals['product_uom'] = move.product_uom.id
            StockMoveLine.create(vals)

    def _pharmacy_validate_receipt_move_line_commands_have_expiry(self, vals):
        """Block the Detailed Operations popup Save when user typed a lot without expiry.

        Odoo saves that popup by writing one2many commands on stock.move, so the
        stock.move.line create/write constraint does not always give the user an
        early error. This check runs before super().write(), keeping the popup open
        so the pharmacist can immediately fill the missing Expiration Date.
        """
        commands = vals.get('move_line_ids') or []
        if not commands:
            return

        qty_field = self._pharmacy_get_move_line_qty_field()
        for move in self:
            picking = move.picking_id
            if not picking or picking.picking_type_code != 'incoming':
                continue
            product = move.product_id
            if not product or product.tracking == 'none':
                continue

            for command in commands:
                if not isinstance(command, (list, tuple)) or len(command) < 3:
                    continue
                cmd = command[0]
                line_id = command[1]
                line_vals = command[2] or {}
                if cmd not in (0, 1) or not isinstance(line_vals, dict):
                    continue

                existing_line = self.env['stock.move.line'].browse(line_id) if cmd == 1 and line_id else self.env['stock.move.line']

                has_lot = bool(line_vals.get('lot_id'))
                has_lot_name = bool(line_vals.get('lot_name'))
                if existing_line:
                    has_lot = has_lot or bool(existing_line.lot_id)
                    has_lot_name = has_lot_name or bool(getattr(existing_line, 'lot_name', False))

                # Placeholder auto-remaining lines are intentionally blank.
                if not has_lot and not has_lot_name:
                    continue

                expiry = False
                if 'pharmacy_expiry_month_year' in line_vals:
                    expiry = line_vals.get('pharmacy_expiry_month_year')
                if not expiry and 'expiration_date' in line_vals:
                    expiry = line_vals.get('expiration_date')
                if not expiry and existing_line:
                    expiry = getattr(existing_line, 'expiration_date', False) if 'expiration_date' in existing_line._fields else False
                    if not expiry and existing_line.lot_id and 'expiration_date' in existing_line.lot_id._fields:
                        expiry = existing_line.lot_id.expiration_date

                if not expiry:
                    raise ValidationError(_(
                        'Expiration Date is required for received lot/serial numbers.'
                    ))

    def write(self, vals):
        if 'move_line_ids' in vals:
            self._pharmacy_validate_receipt_move_line_commands_have_expiry(vals)
        res = super().write(vals)
        if not self.env.context.get('pharmacy_skip_auto_remaining_receipt_line') and (
            'move_line_ids' in vals or 'product_uom_qty' in vals or 'quantity' in vals or 'qty_done' in vals
        ):
            self._pharmacy_auto_add_remaining_receipt_lines_for_moves()
        return res

class StockMoveLine(models.Model):
    _inherit = 'stock.move.line'

    pharmacy_expiry_month_year = fields.Char(
        string='Expiry Month/Year',
        compute='_compute_pharmacy_expiry_month_year',
        inverse='_inverse_pharmacy_expiry_month_year',
        readonly=False,
        help='Enter expiry date as MM/YYYY. It will be stored as the last day of the selected month.',
    )

    @api.depends('expiration_date')
    def _compute_pharmacy_expiry_month_year(self):
        for record in self:
            record.pharmacy_expiry_month_year = _date_to_month_year(record.expiration_date)

    @api.onchange('pharmacy_expiry_month_year')
    def _onchange_pharmacy_expiry_month_year(self):
        for record in self:
            if record.pharmacy_expiry_month_year:
                expiry_value = _month_year_to_field_value(record, record.pharmacy_expiry_month_year, 'expiration_date')
                _validate_not_expired_on_incoming_receipt(record, expiry_value)
                record.expiration_date = expiry_value

    def _inverse_pharmacy_expiry_month_year(self):
        for record in self:
            if record.pharmacy_expiry_month_year:
                expiry_value = _month_year_to_field_value(record, record.pharmacy_expiry_month_year, 'expiration_date')
                _validate_not_expired_on_incoming_receipt(record, expiry_value)
                record.expiration_date = expiry_value

    def _pharmacy_get_done_qty_field(self):
        return 'quantity' if 'quantity' in self._fields else 'qty_done'

    def _pharmacy_is_placeholder_receipt_line(self):
        """A blank auto-created remaining line that still needs lot/expiry data."""
        self.ensure_one()
        has_lot = bool(self.lot_id)
        has_lot_name = bool(getattr(self, 'lot_name', False)) if 'lot_name' in self._fields else False
        has_expiry = bool(getattr(self, 'expiration_date', False)) if 'expiration_date' in self._fields else False
        return not has_lot and not has_lot_name and not has_expiry

    def _pharmacy_auto_add_remaining_receipt_lines(self):
        if self.env.context.get('pharmacy_skip_auto_remaining_receipt_line'):
            return
        self.mapped('move_id').exists()._pharmacy_auto_add_remaining_receipt_lines_for_moves()

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            month_year = vals.pop('pharmacy_expiry_month_year', False)
            if month_year:
                vals['expiration_date'] = _month_year_to_field_value(self, month_year, 'expiration_date')
            elif vals.get('expiration_date'):
                vals['expiration_date'] = _normalize_to_month_last_day(self, 'expiration_date', vals['expiration_date'])
            _validate_not_expired_on_incoming_receipt(self, vals.get('expiration_date'), vals=vals)
            _validate_required_expiry_on_incoming_receipt_line(self, vals=vals)
        records = super().create(vals_list)
        records._pharmacy_auto_add_remaining_receipt_lines()
        return records

    def write(self, vals):
        vals = dict(vals)
        month_year = vals.pop('pharmacy_expiry_month_year', False)
        if month_year:
            vals['expiration_date'] = _month_year_to_field_value(self, month_year, 'expiration_date')
        elif vals.get('expiration_date'):
            vals['expiration_date'] = _normalize_to_month_last_day(self, 'expiration_date', vals['expiration_date'])
        for record in self:
            if vals.get('expiration_date'):
                _validate_not_expired_on_incoming_receipt(record, vals['expiration_date'], vals=vals)
            _validate_required_expiry_on_incoming_receipt_line(record, vals=vals)
        res = super().write(vals)
        self._pharmacy_auto_add_remaining_receipt_lines()
        return res
