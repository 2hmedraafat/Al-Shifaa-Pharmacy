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
        string='Saleable Qty (Excluding Expired Locations)',
        compute='_compute_pharmacy_saleable_qty',
        search='_search_pharmacy_saleable_qty',
        digits='Product Unit of Measure',
        help='Available quantity in normal internal locations only. Expired locations are always excluded.',
    )

    def _pharmacy_saleable_quant_domain(self):
        return [
            ('product_id', 'in', self.ids),
            ('location_id.usage', '=', 'internal'),
            ('location_id.is_expired_location', '=', False),
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
        string='Saleable Qty (Excluding Expired Locations)',
        compute='_compute_pharmacy_template_saleable_qty',
        search='_search_pharmacy_template_saleable_qty',
        digits='Product Unit of Measure',
        help='Total saleable quantity of all variants excluding Expired locations.',
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
                        'Expired-location stock is excluded for patient safety.',
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
