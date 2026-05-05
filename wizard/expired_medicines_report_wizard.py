from calendar import monthrange
from datetime import date

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class PharmacyExpiredMedicinesReportWizard(models.TransientModel):
    _name = 'pharmacy.expired.medicines.report.wizard'
    _description = 'Expired Medicines Report Wizard'

    month = fields.Selection(
        selection=[
            ('1', 'January'),
            ('2', 'February'),
            ('3', 'March'),
            ('4', 'April'),
            ('5', 'May'),
            ('6', 'June'),
            ('7', 'July'),
            ('8', 'August'),
            ('9', 'September'),
            ('10', 'October'),
            ('11', 'November'),
            ('12', 'December'),
        ],
        string='Month',
        required=True,
        default=lambda self: str(fields.Date.context_today(self).month),
    )
    year = fields.Char(
        string='Year',
        required=True,
        default=lambda self: str(fields.Date.context_today(self).year),
    )
    branch_ids = fields.Many2many(
        'stock.location',
        'pharmacy_expired_report_location_rel',
        'wizard_id',
        'location_id',
        string='Expired Branches / Locations',
        domain="[('usage', '=', 'expired')]",
        required=True,
        help='Select one or more Expired locations only.',
    )

    date_from = fields.Date(string='From', compute='_compute_date_range')
    date_to = fields.Date(string='To', compute='_compute_date_range')

    @api.depends('month', 'year')
    def _compute_date_range(self):
        for wizard in self:
            if wizard.month and wizard.year:
                try:
                    year = int(wizard.year)
                    month = int(wizard.month)
                    last_day = monthrange(year, month)[1]
                    wizard.date_from = date(year, month, 1)
                    wizard.date_to = date(year, month, last_day)
                except (TypeError, ValueError):
                    wizard.date_from = False
                    wizard.date_to = False
            else:
                wizard.date_from = False
                wizard.date_to = False

    @api.constrains('year')
    def _check_year(self):
        for wizard in self:
            try:
                year = int(wizard.year)
            except (TypeError, ValueError):
                raise ValidationError(_('Please enter a valid year between 2000 and 2100.'))
            if year < 2000 or year > 2100:
                raise ValidationError(_('Please enter a valid year between 2000 and 2100.'))

    def action_print_pdf(self):
        self.ensure_one()
        if not self.date_from or not self.date_to:
            raise ValidationError(_('Please select a valid month and year.'))
        if not self.branch_ids:
            raise ValidationError(_('Please select at least one Expired location.'))

        data = {
            'wizard_id': self.id,
            'month': int(self.month),
            'year': int(self.year),
            'date_from': fields.Date.to_string(self.date_from),
            'date_to': fields.Date.to_string(self.date_to),
            'branch_ids': self.branch_ids.ids,
        }
        return self.env.ref('pharmacy.action_report_expired_medicines_per_branch').report_action(self, data=data)
