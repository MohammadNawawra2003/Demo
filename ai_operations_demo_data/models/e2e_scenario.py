"""The end-to-end demo scenario. Built for George, 2026-09-07.

George asked for a demo he can follow mechanically in a customer meeting: every
prompt written down, every expected answer known, no inventing questions in
front of a client. That needs a shape the seeded dataset does not have on its
own, for a reason worth writing down.

**Why the existing data cannot carry it.** Document A's production schedule
creates eighteen manufacturing orders that reserve their components, and it does
its job well: on a freshly built database `PK-BTL-600`, `PK-CAP-S`,
`PK-CTN-600` and `PK-FILM-SHR` are each 100% reserved and `PR-WATER-TRT` is
reserved beyond what is on hand. Free stock is zero. Any new manufacturing order
is therefore short of *everything*, which is not a story anyone can follow --
"the agent found five shortages" demonstrates nothing about judgement. Finished
goods have the opposite problem: over 300,000 cartons of FG-600 on hand, so no
plausible sales order ever fails to be fulfilled from stock and the
manufacturing half of the chain never triggers.

**What this builds instead.** One scenario product, its own sales orders, and a
deterministic top-up sized so that exactly ONE component is short:

* `FG-600-E2E` -- a 600 ml scenario SKU with no finished stock and the same bill
  of materials as `FG-600`, on Manufacture + Replenish-on-Order, so confirming
  the sales order creates the manufacturing order the way Odoo normally would.
* Component top-ups for everything the order needs EXCEPT bottles, plus 8,000
  bottles against a requirement of 12,000. `PK-BTL-600` is short by 4,000 and
  nothing else is short at all.
* `PK-BTL-600` is deliberately the shortage: it is the one component with two
  real vendors in Document A -- Jeddah Plastic Industries at 18 days against
  Riyadh PET Co. at 21 -- so `procurement.compare_suppliers` has an actual
  decision to show rather than a single row.

**Scenario B is the contrast.** A small order for the real `FG-600`, which has
ample stock, so the agent reports sufficiency and creates no work. Without it
the demo only ever shows an AI that generates tasks, which is the opposite of
the point.

Everything here carries ``SCENARIO_ORIGIN`` and is created idempotently, so the
fixture can be reset and rebuilt without touching one row of the historical
dataset. Nothing existing is deleted or reduced; the top-ups only add.
"""

import logging

from odoo import api, models

_logger = logging.getLogger(__name__)

#: Stamped on every record this file creates, so the whole scenario can be found
#: -- and reset -- with one domain.
SCENARIO_ORIGIN = 'AI-DEMO-E2E'

#: The two orders, named once so the top-up can find the shortage order's own
#: manufacturing order before measuring free stock.
SHORTAGE_ORIGIN = '%s/SHORTAGE' % SCENARIO_ORIGIN
SUFFICIENT_ORIGIN = '%s/SUFFICIENT' % SCENARIO_ORIGIN

#: The scenario SKU. Not a Document A product: it exists so the demo can run
#: repeatedly without disturbing the seeded FG-600 history.
SCENARIO_FG = 'FG-600-E2E'
SCENARIO_FG_NAME = 'Naqaa Still Water 600 ml x24 — Demo Scenario'

#: The real product the sufficiency contrast uses. It has six figures of stock.
CONTRAST_FG = 'FG-600'

#: Cartons on each order. 500 needs 12,000 bottles; 8,000 are provided.
SHORTAGE_QTY = 500
CONTRAST_QTY = 100

#: The component the demo is about, and its shortfall.
SHORT_COMPONENT = 'PK-BTL-600'
SHORT_COMPONENT_ONHAND = 8_000

#: Everything else the order needs, topped up past its requirement so that the
#: bottle is the only thing missing. PR-WATER-TRT is reserved beyond what is on
#: hand on a fresh build, which is why its figure is large.
COMPONENT_TOPUP = {
    'PK-CAP-S': 15_000,
    'PK-CTN-600': 1_000,
    'PK-FILM-SHR': 100,
    'PR-WATER-TRT': 80_000,
}

#: Who C1 sells to. Every named customer in Document A §7 -- Bin Dawood,
#: Carrefour, the camps -- belongs to the DISTRIBUTION company, because that is
#: the structure §3 describes: the plant manufactures and sells to distribution,
#: distribution sells to the market. Odoo enforces it too; a C1 order naming a
#: C2 customer is refused outright as a company crossover.
COMPANY = 'Naqaa Water Manufacturing Co.'
CUSTOMER_COMPANY = 'Naqaa Distribution Co.'
RAW_MATERIAL_LOCATION = 'RM/Stock'


class AIOperationsE2EScenario(models.AbstractModel):
    _name = 'ai.operations.e2e.scenario'
    _description = 'AI Operations End-to-End Demo Scenario (non-production)'

    # ------------------------------------------------------------------

    @api.model
    def build(self):
        """Idempotent. Safe to run on every upgrade."""
        company = self.env['res.company'].search([('name', '=', COMPANY)], limit=1)
        if not company:
            _logger.info("e2e scenario: %s absent, nothing to build", COMPANY)
            return False
        self = self.with_company(company)

        product = self._scenario_product(company)
        self._top_up_components(company)
        shortage = self._sales_order(
            product, SHORTAGE_QTY, SHORTAGE_ORIGIN, company)
        contrast = self._contrast_order(company)
        _logger.info(
            "e2e scenario: %s ready, shortage order %s, contrast order %s",
            product.default_code, shortage.name, contrast and contrast.name)
        return True

    # -- the scenario product ---------------------------------------------

    @api.model
    def _scenario_product(self, company):
        Product = self.env['product.product']
        existing = Product.with_context(active_test=False).search(
            [('default_code', '=', SCENARIO_FG)], limit=1)
        source = Product.search([('default_code', '=', CONTRAST_FG)], limit=1)
        if not source:
            raise ValueError(
                "%s is missing; alshayeb_demo_water has not been built."
                % CONTRAST_FG)
        if existing:
            # Repair rather than skip: a database built before the routes were
            # resolved by xmlid has the product on MTO alone.
            existing.route_ids = [(6, 0, self._scenario_routes().ids)]
            self._scenario_bom(existing, source, company)
            return existing

        product = Product.create({
            'name': SCENARIO_FG_NAME,
            'default_code': SCENARIO_FG,
            'is_storable': True,
            'uom_id': source.uom_id.id,
            'categ_id': source.categ_id.id,
            'list_price': source.list_price,
            'standard_price': source.standard_price,
            'company_id': False,
            'route_ids': [(6, 0, self._scenario_routes().ids)],
        })
        self._scenario_bom(product, source, company)
        return product

    @api.model
    def _scenario_routes(self):
        """Replenish on Order, and only that.

        MTO is what makes CONFIRMING the sales order create the manufacturing
        order. Without it the demo would need a human to create the MO by hand,
        which breaks the chain George wants to show -- sales demand producing
        production demand by itself.

        There is deliberately no Manufacture route here. Odoo ships it
        ``product_selectable=False``, and the domain on ``route_ids`` filters
        the field on READ as well as in the interface, so the route can be
        written and can never be read back: the row sits in
        ``stock_route_product`` and the ORM keeps returning MTO alone. What
        makes the product buildable is its bill of materials plus the
        warehouse's own manufacture rule, which is why the FG-600 this scenario
        is copied from carries no routes at all.

        Resolved by xmlid rather than by name, because ``stock.route.name`` is
        translatable and this demo installs Arabic. The stored value is
        ``{'en_US': 'Replenish on Order (MTO)', 'ar_001': 'تجديد المخزون عند
        الطلب (الإنتاج حسب الطلب)'}``, and a search for the English name under
        ``ar_001`` matches nothing at all -- which would leave the scenario
        product with no MTO, no manufacturing order, and no demo.
        """
        route = self.env.ref('stock.route_warehouse0_mto',
                             raise_if_not_found=False)
        if not route:
            raise ValueError(
                "stock.route_warehouse0_mto is missing; confirming the sales "
                "order would create no manufacturing order.")
        if not route.active:
            route.active = True
        return route

    @api.model
    def _scenario_bom(self, product, source, company):
        """Mirror FG-600's bill of materials onto the scenario product."""
        Bom = self.env['mrp.bom']
        if Bom.search([('product_tmpl_id', '=', product.product_tmpl_id.id)],
                      limit=1):
            return
        source_bom = Bom.search(
            [('product_tmpl_id', '=', source.product_tmpl_id.id)], limit=1)
        if not source_bom:
            raise ValueError("%s has no bill of materials to copy." % CONTRAST_FG)
        Bom.create({
            'product_tmpl_id': product.product_tmpl_id.id,
            'product_qty': source_bom.product_qty,
            'product_uom_id': source_bom.product_uom_id.id,
            'type': 'normal',
            'company_id': company.id,
            'bom_line_ids': [(0, 0, {
                'product_id': line.product_id.id,
                'product_qty': line.product_qty,
                'product_uom_id': line.product_uom_id.id,
            }) for line in source_bom.bom_line_ids],
        })

    # -- the one shortage, and nothing else --------------------------------

    @api.model
    def _top_up_components(self, company):
        """Bring free stock to a known figure for every component but one.

        Written as a floor rather than an addition: running twice must not keep
        adding stock, or the shortage the whole demo turns on would quietly
        disappear on the second upgrade.
        """
        location = self.env['stock.location'].search(
            [('complete_name', '=', RAW_MATERIAL_LOCATION)], limit=1)
        if not location:
            raise ValueError("%s is missing." % RAW_MATERIAL_LOCATION)

        held = self._scenario_reservations()
        targets = dict(COMPONENT_TOPUP)
        targets[SHORT_COMPONENT] = SHORT_COMPONENT_ONHAND
        for code, free_target in targets.items():
            product = self.env['product.product'].search(
                [('default_code', '=', code)], limit=1)
            if not product:
                _logger.warning("e2e scenario: component %s missing", code)
                continue
            self._set_free_quantity(
                product, location, free_target, held.get(product.id, 0.0))

    # -- putting the starting position back -------------------------------

    @api.model
    def _scenario_production(self):
        """The manufacturing order MTO created from the shortage sales order."""
        order = self.env['sale.order'].search(
            [('origin', '=', SHORTAGE_ORIGIN)], limit=1)
        if not order:
            return self.env['mrp.production']
        return self.env['mrp.production'].with_context(
            active_test=False).search([('origin', '=', order.name)], limit=1)

    @api.model
    def relevel(self):
        """Put component stock back to the figures the scenario starts from.

        ``build`` only ever tops UP, deliberately: it runs on every upgrade and
        must never remove stock a running demo depends on. That is the right
        rule for building and the wrong one for resetting, because a demo that
        was actually PERFORMED receives goods. Run #1 on staging bought 4,000
        bottles, took them through a lot number, ten quality checks and a
        two-step warehouse, and put them on the shelf -- which is the whole
        point of the receipt steps. Afterwards the order reserved all 12,000 it
        needed, the shortage was gone, and every later step of run #2 was about
        a problem that no longer existed. The reset could cancel the paperwork
        and could not un-receive the goods.

        So this levels rather than tops up, in both directions. It is also the
        general case: any component a presenter over-receives during a live
        demo has exactly this problem, not only the one the runbook names.

        The order is unreserved first. Stock that is reserved cannot be reduced,
        and its reservation is the scenario's own, so releasing it is not
        destroying anything -- ``action_assign`` puts it back at the end and the
        order returns to being short by precisely the documented 4,000.
        """
        company = self.env['res.company'].search([('name', '=', COMPANY)], limit=1)
        if not company:
            return False
        location = self.env['stock.location'].search(
            [('complete_name', '=', RAW_MATERIAL_LOCATION)], limit=1)
        if not location:
            return False

        production = self._scenario_production()
        if production and production.state not in ('done', 'cancel'):
            production.do_unreserve()

        targets = dict(COMPONENT_TOPUP)
        targets[SHORT_COMPONENT] = SHORT_COMPONENT_ONHAND
        levelled = {}
        for code, target in targets.items():
            product = self.env['product.product'].search(
                [('default_code', '=', code)], limit=1)
            if not product:
                continue
            moved = self._level_free_quantity(product, location, target)
            if moved:
                levelled[code] = moved

        if production and production.state not in ('done', 'cancel'):
            production.action_assign()
        _logger.info("e2e scenario: relevelled %s", levelled or 'nothing')
        return levelled

    @api.model
    def _level_free_quantity(self, product, location, free_target):
        """Move free stock to exactly ``free_target``, up or down.

        Surplus is taken from quants carrying a lot first. On a demo database
        those are what the run itself received -- the fixture's own baseline is
        untracked -- so the stock that goes is the stock the demo brought in,
        and the original quant is left alone. A quant is never taken below what
        is still reserved on it by somebody else.
        """
        Quant = self.env['stock.quant'].with_context(inventory_mode=True)
        quants = Quant.search([
            ('product_id', '=', product.id),
            ('location_id', 'child_of', location.id),
        ])
        on_hand = sum(quants.mapped('quantity'))
        reserved = sum(quants.mapped('reserved_quantity'))
        free = on_hand - reserved
        if free == free_target:
            return 0.0
        if free < free_target:
            self._set_free_quantity(product, location, free_target)
            return free_target - free

        surplus = free - free_target
        removed = 0.0
        for quant in quants.sorted(key=lambda q: (not q.lot_id, q.id)):
            if surplus <= 0:
                break
            removable = min(surplus, quant.quantity - quant.reserved_quantity)
            if removable <= 0:
                continue
            quant.with_context(inventory_mode=True).write({
                'inventory_quantity': quant.quantity - removable})
            quant.with_context(inventory_mode=True).action_apply_inventory()
            surplus -= removable
            removed += removable
        return -removed

    @api.model
    def _scenario_reservations(self):
        """What the scenario's own manufacturing order is already holding.

        ``build`` runs from an updatable data file, so it runs again on every
        upgrade. By the second run the order this fixture created is reserving
        the very stock the top-up is about to measure: free reads zero again, a
        second full top-up lands on top of the first, and the eight thousand
        bottles become sixteen thousand against a requirement of twelve. The
        order reserves in full and the one shortage the whole demo turns on is
        quietly gone.

        The scenario's own reservation is not competition for stock. It IS the
        scenario, so it is added back before the comparison.
        """
        order = self.env['sale.order'].search(
            [('origin', '=', SHORTAGE_ORIGIN)], limit=1)
        if not order:
            return {}
        productions = self.env['mrp.production'].with_context(
            active_test=False).search([('origin', '=', order.name)])
        held = {}
        for move in productions.move_raw_ids:
            if move.state in ('done', 'cancel'):
                continue
            held[move.product_id.id] = (
                held.get(move.product_id.id, 0.0) + move.quantity)
        return held

    @api.model
    def _set_free_quantity(self, product, location, free_target,
                           scenario_reserved=0.0):
        """Make ``free_target`` units available, counting existing reservations.

        Reserved stock is not available stock, and on a freshly built database
        almost all of this component stock is reserved by the seeded schedule.
        Topping up to an ON HAND figure would leave the scenario still short of
        everything, so the target is FREE quantity and the reservation is added
        back on top -- except the scenario's own, which
        ``_scenario_reservations`` measures and which must not count against
        the target.
        """
        quants = self.env['stock.quant'].with_context(
            inventory_mode=True).search([
                ('product_id', '=', product.id),
                ('location_id', 'child_of', location.id),
            ])
        on_hand = sum(quants.mapped('quantity'))
        reserved = sum(quants.mapped('reserved_quantity')) - scenario_reserved
        free = on_hand - reserved
        if free >= free_target:
            return
        needed = free_target - free
        quant = quants[:1]
        if not quant:
            quant = self.env['stock.quant'].with_context(
                inventory_mode=True).create({
                    'product_id': product.id,
                    'location_id': location.id,
                })
        quant.with_context(inventory_mode=True).write({
            'inventory_quantity': quant.quantity + needed,
        })
        quant.with_context(inventory_mode=True).action_apply_inventory()
        _logger.info(
            "e2e scenario: %s free stock %s -> %s",
            product.default_code, free, free_target)

    # -- the two orders -----------------------------------------------------

    @api.model
    def _customer(self):
        company = self.env['res.company'].search(
            [('name', '=', CUSTOMER_COMPANY)], limit=1)
        if not company:
            raise ValueError("Company %r is missing." % CUSTOMER_COMPANY)
        return company.partner_id

    @api.model
    def _sales_order(self, product, quantity, origin, company):
        Order = self.env['sale.order']
        existing = Order.search([('origin', '=', origin)], limit=1)
        if existing:
            return existing
        order = Order.create({
            'partner_id': self._customer().id,
            'company_id': company.id,
            'origin': origin,
            'order_line': [(0, 0, {
                'product_id': product.id,
                'product_uom_qty': quantity,
            })],
        })
        order.action_confirm()
        return order

    @api.model
    def _contrast_order(self, company):
        """Scenario B. Ordinary product, ample stock, no work created.

        Confirmed like the other one so the demo compares like with like: the
        difference the agent reports must come from the stock position, not from
        one order being a draft and the other not.
        """
        product = self.env['product.product'].search(
            [('default_code', '=', CONTRAST_FG)], limit=1)
        if not product:
            return False
        return self._sales_order(
            product, CONTRAST_QTY, SUFFICIENT_ORIGIN, company)
