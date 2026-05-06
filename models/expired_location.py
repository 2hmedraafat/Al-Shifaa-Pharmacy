from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


class StockLocation(models.Model):
    _inherit = 'stock.location'

    usage = fields.Selection(
        selection_add=[('expired', 'Expired')],
        ondelete={'expired': 'set default'},
    )

    is_expired_location = fields.Boolean(
        string='Expired Product Location',
        compute='_compute_is_expired_location',
        store=True,
        index=True,
        help='Technical safety flag. Stock here is excluded from POS, sales availability, forecasting, and reorder rules.',
    )

    @api.depends('usage')
    def _compute_is_expired_location(self):
        for location in self:
            location.is_expired_location = location.usage == 'expired'

    @api.constrains('usage')
    def _check_expired_location_is_not_scrap_or_replenishment(self):
        for location in self:
            if location.usage == 'expired' and getattr(location, 'scrap_location', False):
                raise ValidationError(_('Expired locations cannot be configured as Scrap Locations.'))
            if location.usage == 'expired' and getattr(location, 'replenish_location', False):
                raise ValidationError(_('Expired locations cannot be configured as Replenishment Locations.'))


class StockQuant(models.Model):
    _inherit = 'stock.quant'

    pharmacy_lot_expiration_date = fields.Datetime(
        string='Expiration Date',
        related='lot_id.expiration_date',
        readonly=True,
        store=False,
    )
    pharmacy_expired_transfer_qty = fields.Float(
        string='Available to Transfer',
        compute='_compute_pharmacy_expired_transfer_qty',
        search='_search_pharmacy_expired_transfer_qty',
        digits='Product Unit of Measure',
        help='Quantity that can be transferred to Expired Medicines location. Reserved quantity is excluded.',
    )

    @api.depends('quantity', 'reserved_quantity')
    def _compute_pharmacy_expired_transfer_qty(self):
        for quant in self:
            quant.pharmacy_expired_transfer_qty = max((quant.quantity or 0.0) - (quant.reserved_quantity or 0.0), 0.0)


    @api.model
    def _search_pharmacy_expired_transfer_qty(self, operator, value):
        quants = self.search([])

        def _match(qty):
            if operator == '>':
                return qty > value
            if operator == '>=':
                return qty >= value
            if operator == '<':
                return qty < value
            if operator == '<=':
                return qty <= value
            if operator == '=':
                return qty == value
            if operator == '!=':
                return qty != value
            if operator in ('in', 'not in'):
                matched = qty in value
                return matched if operator == 'in' else not matched
            return False

        matched_ids = [
            quant.id for quant in quants
            if _match(max((quant.quantity or 0.0) - (quant.reserved_quantity or 0.0), 0.0))
        ]
        return [('id', 'in', matched_ids or [0])]

    @api.model
    def _pharmacy_expired_quant_domain(self):
        today = fields.Date.context_today(self)
        return [
            ('lot_id', '!=', False),
            ('quantity', '>', 0),
            ('location_id.usage', '=', 'internal'),
            ('location_id.is_expired_location', '=', False),
            ('product_id.product_tmpl_id.classification', '=', 'medicine'),
            ('lot_id.expiration_date', '!=', False),
            ('lot_id.expiration_date', '<', today),
        ]

    @api.model
    def _pharmacy_get_expired_destination_location(self):
        location = self.env.ref('pharmacy.stock_location_expired_medicines', raise_if_not_found=False)
        if not location:
            location = self.env['stock.location'].sudo().search([
                ('usage', '=', 'expired'),
                ('is_expired_location', '=', True),
            ], limit=1)
        if not location:
            raise UserError(_(
                'Expired Medicines location was not found. Please create one location with Location Type = Expired first.'
            ))
        return location.sudo()

    @api.model
    def _pharmacy_get_internal_picking_type(self, company):
        domain = [('code', '=', 'internal')]
        if company:
            domain = ['|', ('company_id', '=', company.id), ('company_id', '=', False)] + domain
        picking_type = self.env['stock.picking.type'].sudo().search(domain, limit=1)
        if not picking_type:
            raise UserError(_('No Internal Transfer operation type was found.'))
        return picking_type


    def _pharmacy_force_validate_expired_picking(self, picking):
        """Validate the generated Internal Transfer without leaving it in Ready.

        Odoo can return an Immediate Transfer or Backorder wizard from button_validate()
        depending on stock settings/version. UC-05 needs one-click transfer, so we process
        those wizards automatically and fall back to _action_done() only for our generated
        expired-medicines picking.
        """
        picking = picking.sudo()
        ctx = {
            'skip_immediate': True,
            'skip_immediate_transfer': True,
            'skip_backorder': True,
            'cancel_backorder': True,
        }
        result = picking.with_context(**ctx).button_validate()

        if isinstance(result, dict) and picking.state != 'done':
            res_model = result.get('res_model')
            res_id = result.get('res_id')
            context = result.get('context') or {}
            if res_model == 'stock.immediate.transfer':
                wizard = self.env[res_model].sudo().with_context(context).browse(res_id) if res_id else False
                if wizard:
                    wizard.process()
            elif res_model == 'stock.backorder.confirmation':
                wizard = self.env[res_model].sudo().with_context(context).browse(res_id) if res_id else False
                if wizard:
                    if hasattr(wizard, 'process_cancel_backorder'):
                        wizard.process_cancel_backorder()
                    else:
                        wizard.process()

        if picking.state != 'done':
            # Last safety fallback for Odoo 18 custom stock flows. The picking is already
            # created by this method only, with exact done quantities and picked lines.
            picking.with_context(cancel_backorder=True)._action_done()

        if picking.state != 'done':
            raise UserError(_(
                'The expired medicines transfer was created but could not be auto-validated. '
                'Please open transfer %(name)s and validate it manually.',
                name=picking.name,
            ))

    def action_pharmacy_transfer_to_expired_location(self):
        """Bulk transfer selected expired medicine quants to the Expired location.

        This is SC2-UC-05 only. It creates real stock.picking records and validates them.
        Existing UC-03/UC-04 alert jobs remain detection/notification only.
        """
        selected_quants = self.sudo().filtered_domain(self._pharmacy_expired_quant_domain())
        if not selected_quants:
            raise UserError(_(
                'No transferable expired medicine stock was found. Select expired medicine lots that are still in normal Internal locations.'
            ))

        reserved_quants = selected_quants.filtered(lambda q: (q.reserved_quantity or 0.0) > 0.0)
        if reserved_quants:
            names = ', '.join(reserved_quants[:5].mapped(lambda q: '%s / %s' % (q.product_id.display_name, q.lot_id.name)))
            if len(reserved_quants) > 5:
                names += ', ...'
            raise UserError(_(
                'Some selected expired lots are reserved and cannot be auto-transferred safely.\n'
                'Please unreserve them first, then try again.\n\n%s'
            ) % names)

        destination = self._pharmacy_get_expired_destination_location()
        StockPicking = self.env['stock.picking'].sudo()
        StockMoveLine = self.env['stock.move.line'].sudo()
        created_pickings = self.env['stock.picking'].sudo()

        quants_by_location_company = {}
        for quant in selected_quants:
            qty = quant.pharmacy_expired_transfer_qty
            if qty <= 0:
                continue
            key = (quant.location_id.id, quant.company_id.id or self.env.company.id)
            quants_by_location_company.setdefault(key, self.env['stock.quant'].sudo())
            quants_by_location_company[key] |= quant

        for (source_location_id, company_id), quants in quants_by_location_company.items():
            source_location = self.env['stock.location'].sudo().browse(source_location_id)
            company = self.env['res.company'].sudo().browse(company_id) if company_id else self.env.company
            picking_type = self._pharmacy_get_internal_picking_type(company)

            picking = StockPicking.create({
                'picking_type_id': picking_type.id,
                'location_id': source_location.id,
                'location_dest_id': destination.id,
                'company_id': company.id,
                'origin': _('Pharmacy Expired Medicines Bulk Transfer'),
                'pharmacy_expired_transfer_reason': _('Auto-validated bulk transfer from Expired Medicines page.'),
                'move_ids_without_package': [
                    (0, 0, {
                        'name': '%s / %s' % (quant.product_id.display_name, quant.lot_id.name),
                        'product_id': quant.product_id.id,
                        'product_uom_qty': quant.pharmacy_expired_transfer_qty,
                        'product_uom': quant.product_id.uom_id.id,
                        'location_id': source_location.id,
                        'location_dest_id': destination.id,
                        'company_id': company.id,
                    })
                    for quant in quants
                ],
            })

            picking.action_confirm()
            picking.action_assign()

            for move, quant in zip(picking.move_ids_without_package, quants):
                move.move_line_ids.unlink()
                line_values = {
                    'picking_id': picking.id,
                    'move_id': move.id,
                    'product_id': quant.product_id.id,
                    'lot_id': quant.lot_id.id,
                    'location_id': source_location.id,
                    'location_dest_id': destination.id,
                    'company_id': company.id,
                }
                if 'product_uom_id' in StockMoveLine._fields:
                    line_values['product_uom_id'] = quant.product_id.uom_id.id
                elif 'product_uom' in StockMoveLine._fields:
                    line_values['product_uom'] = quant.product_id.uom_id.id

                done_qty_field = 'quantity' if 'quantity' in StockMoveLine._fields else 'qty_done'
                line_values[done_qty_field] = quant.pharmacy_expired_transfer_qty

                # Odoo 18 may require detailed-operation lines to be marked as picked
                # before auto-validation. Keep this conditional so older versions are safe.
                if 'picked' in StockMoveLine._fields:
                    line_values['picked'] = True

                StockMoveLine.create(line_values)

            self._pharmacy_force_validate_expired_picking(picking)
            created_pickings |= picking

        if not created_pickings:
            raise UserError(_('No available expired quantity could be transferred.'))

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Expired Medicines Transferred'),
                'message': _('%s internal transfer(s) were validated to the Expired Medicines location.') % len(created_pickings),
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},
            },
        }


class ProductProduct(models.Model):
    _inherit = 'product.product'

    pharmacy_saleable_qty = fields.Float(
        string='Saleable Qty (Excluding Expired Stock)',
        compute='_compute_pharmacy_saleable_qty',
        search='_search_pharmacy_saleable_qty',
        digits='Product Unit of Measure',
        help='Available quantity in normal internal locations only. Expired locations and expired lots are always excluded.',
    )

    def _pharmacy_saleable_quant_domain(self):
        # Patient-safety rule for POS/Sales:
        # saleable stock = normal internal locations only + non-expired lots only.
        # This prevents products with expired lots still sitting in WH/Stock from being sold.
        today = fields.Date.context_today(self)
        return [
            ('product_id', 'in', self.ids),
            ('location_id.usage', '=', 'internal'),
            ('location_id.is_expired_location', '=', False),
            '|',
                ('lot_id', '=', False),
                ('lot_id.expiration_date', '>=', today),
        ]

    def _pharmacy_get_saleable_qty_map(self):
        products = self.exists()
        result = {product.id: 0.0 for product in products}
        if not products:
            return result

        groups = self.env['stock.quant'].sudo().read_group(
            products._pharmacy_saleable_quant_domain(),
            ['quantity:sum', 'reserved_quantity:sum'],
            ['product_id'],
        )
        for group in groups:
            product_id = group['product_id'][0]
            qty = (group.get('quantity') or 0.0) - (group.get('reserved_quantity') or 0.0)
            result[product_id] = max(qty, 0.0)
        return result

    @api.depends_context('company', 'warehouse')
    def _compute_pharmacy_saleable_qty(self):
        qty_map = self._pharmacy_get_saleable_qty_map()
        for product in self:
            product.pharmacy_saleable_qty = qty_map.get(product.id, 0.0)

    @api.model
    def _load_pos_data_fields(self, config_id):
        """Odoo 18 POS loader: make saleable qty available in the POS product cache.

        Without this, POS receives the product without pharmacy_saleable_qty,
        so the JS safety limit treats it as unknown and cannot block extra clicks.
        """
        fields_list = super()._load_pos_data_fields(config_id)
        if 'pharmacy_saleable_qty' not in fields_list:
            fields_list.append('pharmacy_saleable_qty')
        return fields_list

    @api.model
    def _search_pharmacy_saleable_qty(self, operator, value):
        products = self.search([])
        qty_map = products._pharmacy_get_saleable_qty_map()

        def _match(qty):
            if operator == '>':
                return qty > value
            if operator == '>=':
                return qty >= value
            if operator == '<':
                return qty < value
            if operator == '<=':
                return qty <= value
            if operator == '=':
                return qty == value
            if operator == '!=':
                return qty != value
            if operator in ('in', 'not in'):
                matched = qty in value
                return matched if operator == 'in' else not matched
            return False

        matched_ids = [product_id for product_id, qty in qty_map.items() if _match(qty)]
        return [('id', 'in', matched_ids or [0])]


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    pharmacy_saleable_qty = fields.Float(
        string='Saleable Qty (Excluding Expired Stock)',
        compute='_compute_pharmacy_template_saleable_qty',
        search='_search_pharmacy_template_saleable_qty',
        digits='Product Unit of Measure',
        help='Total saleable quantity of all variants excluding Expired locations and expired lots.',
    )

    @api.depends('product_variant_ids.pharmacy_saleable_qty')
    def _compute_pharmacy_template_saleable_qty(self):
        for template in self:
            template.pharmacy_saleable_qty = sum(template.product_variant_ids.mapped('pharmacy_saleable_qty'))

    @api.model
    def _search_pharmacy_template_saleable_qty(self, operator, value):
        product_domain = [('pharmacy_saleable_qty', operator, value)]
        products = self.env['product.product'].search(product_domain)
        return [('id', 'in', products.mapped('product_tmpl_id').ids or [0])]


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    def _pharmacy_check_no_expired_stock_used(self):
        """Patient safety gate: SO confirmation can only use normal internal stock."""
        errors = []
        for order in self:
            for line in order.order_line.filtered(lambda l: l.product_id and l.product_id.type != 'service'):
                product = line.product_id
                requested_qty = line.product_uom._compute_quantity(
                    line.product_uom_qty,
                    product.uom_id,
                    rounding_method='HALF-UP',
                ) if line.product_uom else line.product_uom_qty
                saleable_qty = product.pharmacy_saleable_qty
                if requested_qty > saleable_qty:
                    errors.append(_(
                        '%(product)s: requested %(requested).2f %(uom)s, saleable %(saleable).2f %(uom)s. '
                        'Expired stock is excluded for patient safety.',
                        product=product.display_name,
                        requested=requested_qty,
                        saleable=saleable_qty,
                        uom=product.uom_id.display_name,
                    ))
        if errors:
            raise ValidationError(_('Cannot confirm this Sale Order because available stock exists only in normal saleable locations.\n\n%s') % '\n'.join(errors))

    def action_confirm(self):
        self._pharmacy_check_no_expired_stock_used()
        return super().action_confirm()


class StockLocationPharmacySc2Uc01(models.Model):
    _inherit = 'stock.location'

    def unlink(self):
        expired_locations = self.filtered(lambda loc: loc.usage == 'expired' or loc.is_expired_location)
        if expired_locations:
            raise UserError(_(
                'Expired locations cannot be deleted while they exist. Archive the location instead, or move/write off its stock first.'
            ))
        return super().unlink()


class StockPickingPharmacySc2Uc01(models.Model):
    _inherit = 'stock.picking'

    pharmacy_expired_transfer_reason = fields.Text(
        string='Expired Transfer Reason',
        copy=False,
        help='Mandatory reason/note when transferring stock into an Expired location.',
    )

    pharmacy_is_destination_expired_location = fields.Boolean(
        string='Destination Is Expired Location',
        compute='_compute_pharmacy_is_destination_expired_location',
    )

    @api.depends('location_dest_id', 'location_dest_id.usage', 'location_dest_id.is_expired_location')
    def _compute_pharmacy_is_destination_expired_location(self):
        for picking in self:
            dest = picking.location_dest_id
            picking.pharmacy_is_destination_expired_location = bool(
                dest and (dest.usage == 'expired' or dest.is_expired_location)
            )

    def _pharmacy_is_expired_or_scrap_location(self, location):
        return bool(location and (location.usage == 'expired' or location.is_expired_location or location.scrap_location))

    def _pharmacy_check_expired_location_transfer_rules(self):
        for picking in self:
            src_expired = picking.location_id.usage == 'expired' or picking.location_id.is_expired_location
            dest_expired = picking.location_dest_id.usage == 'expired' or picking.location_dest_id.is_expired_location

            if dest_expired and not (picking.pharmacy_expired_transfer_reason or '').strip():
                raise UserError(_(
                    'Expired Transfer Reason is required before moving stock into an Expired location.'
                ))

            if src_expired and not self._pharmacy_is_expired_or_scrap_location(picking.location_dest_id):
                raise UserError(_(
                    'Stock cannot be transferred out of an Expired location to a normal Internal or Customer location. '
                    'You can only transfer it to another Expired location or to a Scrap location.'
                ))

    def _pharmacy_get_first_incoming_move_invalid_expiry(self):
        """Return first receipt move that needs expiry-date correction.

        This covers both cases from the Detailed Operations popup:
        1) Lot/Serial entered but Expiration Date is empty.
        2) Expiration Date is already expired.

        Returning the move lets button_validate reopen the same details popup
        instead of forcing the user to delete the receipt line and create it again.
        """
        StockMoveLine = self.env['stock.move.line']
        qty_field = 'quantity' if 'quantity' in StockMoveLine._fields else 'qty_done'
        today = fields.Date.context_today(self)

        def _line_expiry_date(line):
            expiry_value = False
            if 'expiration_date' in line._fields:
                expiry_value = line.expiration_date
            if not expiry_value and line.lot_id and 'expiration_date' in line.lot_id._fields:
                expiry_value = line.lot_id.expiration_date
            if not expiry_value:
                return False
            expiry_dt = fields.Datetime.to_datetime(expiry_value)
            return expiry_dt.date() if expiry_dt else fields.Date.to_date(expiry_value)

        for picking in self:
            if picking.picking_type_code != 'incoming':
                continue

            for move in picking.move_ids.exists():
                product = move.product_id
                if not product or product.tracking == 'none':
                    continue

                move_lines = move.move_line_ids.exists()
                if not move_lines:
                    continue

                for line in move_lines:
                    qty = 0.0
                    if qty_field in line._fields:
                        qty = line[qty_field] or 0.0
                    elif 'qty_done' in line._fields:
                        qty = line.qty_done or 0.0

                    has_lot = bool(line.lot_id) or bool(getattr(line, 'lot_name', False))
                    if qty <= 0 and not has_lot:
                        continue

                    expiry_date = _line_expiry_date(line)

                    # Lot exists but no expiry: reopen popup so user can fill it.
                    if has_lot and not expiry_date:
                        return move

                    # Existing receipt line has an already-expired month/year:
                    # reopen popup instead of leaving the user stuck at Validate.
                    if expiry_date and expiry_date < today:
                        return move

        return self.env['stock.move']

    def _pharmacy_get_first_incoming_move_missing_expiry(self):
        # Backward-compatible alias used by older helper calls.
        return self._pharmacy_get_first_incoming_move_invalid_expiry()

    def _pharmacy_open_missing_expiry_move_action(self, move):
        return {
            'type': 'ir.actions.act_window',
            'name': _('Correct Expiration Date'),
            'res_model': 'stock.move',
            'res_id': move.id,
            'view_mode': 'form',
            'target': 'new',
            'context': dict(
                self.env.context,
                pharmacy_missing_expiry_warning=True,
            ),
        }

    def _pharmacy_check_incoming_lot_expiry_required(self):
        missing_move = self._pharmacy_get_first_incoming_move_missing_expiry()
        if missing_move:
            raise UserError(_('Expiration Date is required for received lot/serial numbers.'))

    def action_confirm(self):
        self._pharmacy_check_expired_location_transfer_rules()
        return super().action_confirm()

    def button_validate(self):
        self._pharmacy_check_expired_location_transfer_rules()
        missing_move = self._pharmacy_get_first_incoming_move_missing_expiry()
        if missing_move:
            return self._pharmacy_open_missing_expiry_move_action(missing_move)
        result = super().button_validate()
        for picking in self.filtered(lambda p: p.state == 'done' and (
            p.location_id.usage == 'expired' or p.location_dest_id.usage == 'expired'
            or p.location_id.is_expired_location or p.location_dest_id.is_expired_location
        )):
            direction = _('to Expired location') if (picking.location_dest_id.usage == 'expired' or picking.location_dest_id.is_expired_location) else _('from Expired location')
            picking.message_post(body=_(
                'Expired stock movement validated %(direction)s by %(user)s.<br/>Source: %(src)s<br/>Destination: %(dest)s<br/>Reason: %(reason)s',
                direction=direction,
                user=self.env.user.display_name,
                src=picking.location_id.display_name,
                dest=picking.location_dest_id.display_name,
                reason=picking.pharmacy_expired_transfer_reason or '-',
            ))
        return result
