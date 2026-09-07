"""The Naqaa production schedule: the manufacturing orders a running plant has.

Why this exists
---------------
``alshayeb_demo_water`` seeds master data only, and Session 7's history
generator -- the thing that would produce eighteen months of transactions -- is
deliberately not run on install: it is far too expensive for a trial build
capped at 1 GB. The consequence was visible the moment the demo was reviewed:
*Manufacturing -> Operations -> Manufacturing Orders* read "No manufacturing
order found", because the only order in the database was the single draft the
AI scenario needs.

This module seeds a small, fixed schedule instead -- eighteen orders spread
across Draft, Confirmed, In Progress and Done -- so the Manufacturing app looks
like a plant that has been running, without generating a history.

What it deliberately does NOT touch
-----------------------------------
**No order here makes FG-330.** That is not an oversight and it is not
cosmetic. The AI demo scenario is built on FG-330 and its 330 ml bottle:
``check_readiness`` reports the bottle shortage, ``get_shortage_context``
computes the deterministic baseline that DL-008 rules on, and both read live
``stock.quant`` rows. An order here that consumed or reserved PK-BTL-330 would
move those numbers and silently change what the agents answer. The plant makes
its five other formats; the 330 ml line is the one the demo talks about.

Everything is keyed on its own ``origin``, one per order, so the builder is
idempotent per record and re-running it on upgrade creates nothing twice.
"""

import logging

from datetime import timedelta

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

#: Origin prefix for the schedule. Deliberately NOT ``SEED_ORIGIN``: that one is
#: matched with ``search([('origin', '=', SEED_ORIGIN)], limit=1)`` to make the
#: AI scenario records idempotent, so a second record carrying it would make the
#: first one answer for all of them.
SCHEDULE_ORIGIN = 'NAQAA-SCHED'

#: The finished product the AI scenario owns. Nothing here may make it.
RESERVED_FOR_SCENARIO = 'FG-330'

#: The manufacturing warehouse. 'Production Floor' is where the plant builds;
#: naming it explicitly also gives ``manufacturing.raise_handoff`` a warehouse to
#: derive from ``picking_type_id.warehouse_id`` rather than a company default.
SCHEDULE_WAREHOUSE = 'WIP'

#: How much of an In Progress order has actually been produced. Below 1.0, or
#: ``_compute_state`` reads the order as To Close rather than In Progress.
PROGRESS_FRACTION = 0.4

#: sequence, finished product, cartons, target state, days from today.
#:
#: Volumes are one line-day or so each, against the annual carton figures in
#: ``alshayeb_demo_water``'s blueprint (FG-600 is 3.0M cartons/yr over ~350 run
#: days). Dates straddle today so that ``manufacturing.get_open_mos``, whose
#: default horizon is 14 days, sees a realistic subset rather than all or none.
SCHEDULE = [
    (1, 'FG-600', 9_600, 'done', -21),
    (2, 'FG-1500', 6_400, 'done', -18),
    (3, 'FG-200', 11_200, 'done', -14),
    (4, 'FG-5000', 3_200, 'done', -10),
    (5, 'FG-12000', 1_800, 'done', -7),
    (6, 'FG-600', 9_600, 'progress', -2),
    (7, 'FG-200', 8_400, 'progress', -1),
    (8, 'FG-1500', 5_200, 'progress', 0),
    (9, 'FG-600', 10_800, 'confirmed', 1),
    (10, 'FG-5000', 3_600, 'confirmed', 2),
    (11, 'FG-200', 9_600, 'confirmed', 4),
    (12, 'FG-1500', 6_000, 'confirmed', 6),
    (13, 'FG-12000', 2_100, 'confirmed', 8),
    (14, 'FG-600', 11_400, 'draft', 11),
    (15, 'FG-200', 10_400, 'draft', 14),
    (16, 'FG-1500', 6_800, 'draft', 18),
    (17, 'FG-5000', 4_000, 'draft', 21),
    (18, 'FG-12000', 2_400, 'draft', 25),
]


class AIOperationsDemoProductionSchedule(models.AbstractModel):
    """Extends the demo builder with a manufacturing schedule."""

    _inherit = 'ai.operations.demo.setup'

    # ------------------------------------------------------------------

    @api.model
    def _seed_production_schedule(self, company):
        """Build every order in SCHEDULE that is not already there.

        One order failing must not take the install down with it: a demo whose
        Manufacturing list is short is a great deal better than a module that
        will not install. The state each order actually reached is asserted by
        the tests, which is where a regression should surface.
        """
        Production = self.env['mrp.production'].with_company(company)
        picking_type = self._schedule_picking_type(company)
        today = fields.Datetime.now()
        built = Production.browse()

        for sequence, code, cartons, target, offset in SCHEDULE:
            if code == RESERVED_FOR_SCENARIO:
                raise ValueError(
                    "%s belongs to the AI scenario; the schedule may not "
                    "produce it." % RESERVED_FOR_SCENARIO)
            origin = '%s/%03d' % (SCHEDULE_ORIGIN, sequence)
            existing = Production.search([('origin', '=', origin)], limit=1)
            if existing:
                built |= existing
                continue

            finished = self._product(code)
            values = {
                'product_id': finished.id,
                'product_qty': cartons,
                'company_id': company.id,
                'origin': origin,
                'date_start': today + timedelta(days=offset),
            }
            bom = self.env['mrp.bom'].search(
                [('product_tmpl_id', '=', finished.product_tmpl_id.id),
                 ('company_id', '=', company.id)], limit=1)
            if bom:
                values['bom_id'] = bom.id
            if picking_type:
                values['picking_type_id'] = picking_type.id

            production = Production.create(values)
            try:
                self._advance_production(production, target)
            except Exception:            # noqa: BLE001 - demo data, never fatal
                _logger.exception(
                    "ai_operations_demo_data: %s stopped at %r, wanted %r",
                    origin, production.state, target)
            built |= production

        _logger.info("ai_operations_demo_data: %d manufacturing order(s) scheduled",
                     len(built))
        return built

    @api.model
    def _schedule_picking_type(self, company):
        warehouse = self.env['stock.warehouse'].search(
            [('code', '=', SCHEDULE_WAREHOUSE), ('company_id', '=', company.id)],
            limit=1)
        return warehouse.manu_type_id

    # -- driving an order to its state, through Odoo's own buttons --------

    @api.model
    def _advance_production(self, production, target):
        """Walk the real workflow. Nothing here writes ``state`` directly.

        ``mrp.production.state`` is a stored compute over the moves and the
        produced quantity, so a demo that assigned it would produce orders whose
        state does not match their own stock moves -- which is exactly the kind
        of record that makes a demo fall apart when someone opens it.
        """
        if target == 'draft':
            return

        production.action_confirm()
        if target == 'confirmed':
            return

        # Confirmed is the last state that needs no stock. Beyond it the order
        # has to actually consume something, so put the components on the floor.
        self._stage_components(production)
        production.action_assign()

        if target == 'progress':
            production.qty_producing = production.product_qty * PROGRESS_FRACTION
            production._set_qty_producing()
            return

        production.button_mark_done()

    @api.model
    def _stage_components(self, production):
        """Opening stock for exactly what this order consumes.

        ``_update_available_quantity`` rather than an inventory adjustment: the
        adjustment would post a stock move per component per order, and this
        database lives on a 1 GB trial build. The quantity is what the order's
        own raw moves ask for, so the reservation that follows is exact and
        ``button_mark_done`` raises no consumption wizard.
        """
        Quant = self.env['stock.quant'].with_company(production.company_id)
        location = production.location_src_id
        for move in production.move_raw_ids:
            required = move.product_uom_qty
            if required <= 0:
                continue
            product = move.product_id
            lot = None
            if product.tracking != 'none':
                lot = self._demo_lot(product, production.company_id)
            Quant._update_available_quantity(
                product, location, required, lot_id=lot)

    @api.model
    def _demo_lot(self, product, company):
        """One lot per tracked component, reused across the schedule.

        A lot per order would be more faithful, and would also multiply the
        ``stock.lot`` rows by the number of orders for no demonstrative gain.
        """
        name = '%s/DEMO' % (product.default_code or product.id)
        Lot = self.env['stock.lot'].with_company(company)
        lot = Lot.search([('name', '=', name), ('product_id', '=', product.id),
                          ('company_id', '=', company.id)], limit=1)
        if lot:
            return lot
        return Lot.create({
            'name': name,
            'product_id': product.id,
            'company_id': company.id,
        })
