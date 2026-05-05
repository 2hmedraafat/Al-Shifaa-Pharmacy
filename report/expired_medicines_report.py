from collections import defaultdict
from datetime import datetime, time
from math import floor

from odoo import api, fields, models, _


class ReportExpiredMedicinesPerBranch(models.AbstractModel):
    _name = 'report.pharmacy.report_expired_medicines_per_branch'
    _description = 'Expired Medicines Report per Branch'

    @api.model
    def _get_report_values(self, docids, data=None):
        data = data or {}
        wizard = None
        if data.get('wizard_id'):
            wizard = self.env['pharmacy.expired.medicines.report.wizard'].browse(data['wizard_id']).exists()

        date_from = fields.Date.to_date(data.get('date_from'))
        date_to = fields.Date.to_date(data.get('date_to'))
        branches = self.env['stock.location'].browse(data.get('branch_ids') or []).exists()

        lines, totals = self._get_expired_lines(date_from, date_to, branches)
        generated_at = fields.Datetime.context_timestamp(self, fields.Datetime.now())

        return {
            'doc_ids': docids,
            'doc_model': 'pharmacy.expired.medicines.report.wizard',
            'docs': wizard,
            'data': data,
            'lines': lines,
            'totals': totals,
            'date_from': date_from,
            'date_to': date_to,
            'branches': branches,
            'branch_names': ', '.join(branches.mapped('display_name')) if branches else '',
            'company': self.env.company,
            'generated_at': generated_at,
        }

    @api.model
    def _get_expired_lines(self, date_from, date_to, branches):
        Quant = self.env['stock.quant'].sudo()
        date_from_dt = fields.Datetime.to_string(datetime.combine(date_from, time.min))
        date_to_dt = fields.Datetime.to_string(datetime.combine(date_to, time.max))

        domain = [
            ('lot_id', '!=', False),
            ('quantity', '>', 0),
            ('location_id.usage', '=', 'expired'),
            ('product_id.product_tmpl_id.classification', '=', 'medicine'),
            ('lot_id.expiration_date', '!=', False),
            ('lot_id.expiration_date', '>=', date_from_dt),
            ('lot_id.expiration_date', '<=', date_to_dt),
        ]
        if branches:
            domain.append(('location_id', 'child_of', branches.ids))

        quants = Quant.search(domain, order='location_id, product_id, lot_id')

        grouped = defaultdict(lambda: {
            'branch': '',
            'barcode': '',
            'product': '',
            'lot': '',
            'expiry_date': False,
            'expiry_mm_yyyy': '',
            'raw_qty': 0.0,
            'box_qty': 0.0,
            'unit_qty': 0.0,
            'units_per_box': 1,
            'box_price': 0.0,
            'unit_price': 0.0,
            'total_value': 0.0,
        })

        for quant in quants:
            product = quant.product_id
            tmpl = product.product_tmpl_id
            expiry_date = fields.Date.to_date(quant.lot_id.expiration_date)
            key = (quant.location_id.id, product.id, quant.lot_id.id)
            line = grouped[key]
            line['branch'] = quant.location_id.display_name
            line['barcode'] = product.barcode or tmpl.barcode or ''
            line['product'] = product.display_name
            line['lot'] = quant.lot_id.name
            line['expiry_date'] = expiry_date
            line['expiry_mm_yyyy'] = expiry_date.strftime('%m/%Y') if expiry_date else ''
            line['raw_qty'] += quant.quantity
            line['units_per_box'] = max(int(getattr(tmpl, 'units_per_package', 1) or 1), 1)
            line['box_price'] = self._get_box_price(product, tmpl)

        for line in grouped.values():
            self._fill_qty_and_value(line)

        lines = sorted(grouped.values(), key=lambda row: (row['branch'], row['product'], row['lot']))
        totals = {
            'box_qty': sum(line['box_qty'] for line in lines),
            'unit_qty': sum(line['unit_qty'] for line in lines),
            'total_value': sum(line['total_value'] for line in lines),
        }
        return lines, totals

    @api.model
    def _get_box_price(self, product, tmpl):
        # Financial report should value expired stock using purchase/cost data, not sale price.
        price = product.standard_price or tmpl.standard_price or 0.0
        units_per_box = max(int(getattr(tmpl, 'units_per_package', 1) or 1), 1)
        if getattr(tmpl, 'sell_as', False) == 'unit' and units_per_box > 1:
            return price * units_per_box
        return price

    @api.model
    def _fill_qty_and_value(self, line):
        raw_qty = line['raw_qty'] or 0.0
        units_per_box = max(int(line['units_per_box'] or 1), 1)
        box_price = line['box_price'] or 0.0
        unit_price = box_price / units_per_box if units_per_box else box_price

        if units_per_box > 1:
            box_qty = floor(raw_qty / units_per_box)
            unit_qty = raw_qty - (box_qty * units_per_box)
            if box_qty == 0 and raw_qty >= 1:
                unit_qty = raw_qty
        else:
            box_qty = raw_qty
            unit_qty = 0.0

        line['box_qty'] = box_qty
        line['unit_qty'] = unit_qty
        line['unit_price'] = unit_price
        line['total_value'] = (box_qty * box_price) + (unit_qty * unit_price)
