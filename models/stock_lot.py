from calendar import monthrange
from datetime import datetime, time

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


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
                _set_all_lot_dates_on_record(record, expiry_value)

    def _inverse_pharmacy_expiry_month_year(self):
        for record in self:
            if record.pharmacy_expiry_month_year:
                expiry_value = _month_year_to_field_value(record, record.pharmacy_expiry_month_year, 'expiration_date')
                _set_all_lot_dates_on_record(record, expiry_value)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            month_year = vals.pop('pharmacy_expiry_month_year', False)
            if month_year:
                expiry_value = _month_year_to_field_value(self, month_year, 'expiration_date')
                _set_all_lot_dates_on_vals(self, vals, expiry_value)
            elif vals.get('expiration_date'):
                expiry_value = _normalize_to_month_last_day(self, 'expiration_date', vals['expiration_date'])
                _set_all_lot_dates_on_vals(self, vals, expiry_value)
        return super().create(vals_list)

    def write(self, vals):
        vals = dict(vals)
        month_year = vals.pop('pharmacy_expiry_month_year', False)
        if month_year:
            expiry_value = _month_year_to_field_value(self, month_year, 'expiration_date')
            _set_all_lot_dates_on_vals(self, vals, expiry_value)
        elif vals.get('expiration_date'):
            expiry_value = _normalize_to_month_last_day(self, 'expiration_date', vals['expiration_date'])
            _set_all_lot_dates_on_vals(self, vals, expiry_value)
        return super().write(vals)


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
                record.expiration_date = _month_year_to_field_value(record, record.pharmacy_expiry_month_year, 'expiration_date')

    def _inverse_pharmacy_expiry_month_year(self):
        for record in self:
            if record.pharmacy_expiry_month_year:
                record.expiration_date = _month_year_to_field_value(record, record.pharmacy_expiry_month_year, 'expiration_date')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            month_year = vals.pop('pharmacy_expiry_month_year', False)
            if month_year:
                vals['expiration_date'] = _month_year_to_field_value(self, month_year, 'expiration_date')
            elif vals.get('expiration_date'):
                vals['expiration_date'] = _normalize_to_month_last_day(self, 'expiration_date', vals['expiration_date'])
        return super().create(vals_list)

    def write(self, vals):
        vals = dict(vals)
        month_year = vals.pop('pharmacy_expiry_month_year', False)
        if month_year:
            vals['expiration_date'] = _month_year_to_field_value(self, month_year, 'expiration_date')
        elif vals.get('expiration_date'):
            vals['expiration_date'] = _normalize_to_month_last_day(self, 'expiration_date', vals['expiration_date'])
        return super().write(vals)
