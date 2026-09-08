"""The one property the whole A-to-Z demo rests on: exactly one shortage.

The scenario fixture exists to give George a demo he can follow mechanically,
and its entire premise is that the manufacturing order is short of ``PK-BTL-600``
and short of nothing else. An agent that reports five shortages demonstrates
nothing about judgement, and an agent that reports none has no story at all.

That property is not static. ``build()`` runs from an updatable data file on
every upgrade, so it has to survive being run again on a database where it has
already run -- which is also exactly what the owner's item I asks for: build the
demo, reset it, and run it a second time from the runbook alone.

The fixture shipped in c6f4ec8 with no tests, and the second run silently filled
the shortage in. The top-up measures free stock as ``on_hand - reserved`` and the
scenario's own manufacturing order is holding a reservation by then, so free
reads zero again and a second full top-up lands on top of the first. Eight
thousand bottles plus eight thousand covers the twelve thousand the order needs,
the order reserves in full, and the demo quietly becomes a story about an agent
that finds nothing wrong.
"""

from odoo.tests import TransactionCase, tagged

from ..models.demo_setup import COMPANY
from ..models.e2e_scenario import (
    CONTRAST_FG, SCENARIO_FG, SCENARIO_ORIGIN, SHORTAGE_ORIGIN, SHORTAGE_QTY,
    SHORT_COMPONENT, SHORT_COMPONENT_ONHAND, SUFFICIENT_ORIGIN)


@tagged('post_install', '-at_install', 'ai_security')
class TestE2EScenario(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env['res.company'].search(
            [('name', '=', COMPANY)], limit=1)
        cls.Scenario = cls.env['ai.operations.e2e.scenario']

    # -- helpers ----------------------------------------------------------

    def _order(self, origin):
        return self.env['sale.order'].search([('origin', '=', origin)], limit=1)

    def _production(self):
        """The manufacturing order MTO created from the shortage sales order."""
        order = self._order(SHORTAGE_ORIGIN)
        self.assertTrue(order, "the shortage sales order is missing")
        return self.env['mrp.production'].with_context(active_test=False).search(
            [('origin', '=', order.name)], limit=1)

    def _unreserved(self, production):
        """Component moves the order could not fully reserve."""
        return [move.product_id.default_code
                for move in production.move_raw_ids
                if move.state != 'assigned']

    # -- the premise ------------------------------------------------------

    def test_the_scenario_is_short_of_the_bottle_and_nothing_else(self):
        production = self._production()
        self.assertTrue(production, "MTO created no manufacturing order")
        self.assertEqual(
            self._unreserved(production), [SHORT_COMPONENT],
            "the demo turns on exactly one shortage; this order is short of "
            "%s" % (self._unreserved(production) or 'nothing at all'))

    def test_the_bottle_shortfall_is_the_documented_figure(self):
        production = self._production()
        move = production.move_raw_ids.filtered(
            lambda m: m.product_id.default_code == SHORT_COMPONENT)
        self.assertTrue(move, "the order does not consume %s" % SHORT_COMPONENT)
        self.assertEqual(
            move.product_uom_qty - SHORT_COMPONENT_ONHAND, 4_000,
            "the runbook quotes a shortfall of 4,000 bottles against a "
            "requirement of %s" % move.product_uom_qty)

    def test_the_contrast_order_needs_no_work(self):
        """Scenario B: ample stock, so the agent reports sufficiency."""
        order = self._order(SUFFICIENT_ORIGIN)
        self.assertTrue(order, "the sufficiency sales order is missing")
        self.assertEqual(order.order_line.product_id.default_code, CONTRAST_FG)
        self.assertFalse(
            self.env['mrp.production'].search([('origin', '=', order.name)]),
            "the contrast order created production work; it exists precisely "
            "to show the agent creating none")

    # -- and it survives a second run --------------------------------------

    def test_building_twice_does_not_fill_the_shortage_in(self):
        """Item I builds the demo, resets it, and runs it again.

        ``build()`` also re-runs by itself on every upgrade, so this is the
        ordinary path rather than an exotic one.
        """
        production = self._production()
        before = self._unreserved(production)

        self.Scenario.build()
        production.invalidate_recordset()

        self.assertEqual(
            self._unreserved(production), before,
            "a second build changed what the order is short of: %s -> %s"
            % (before, self._unreserved(production)))
        self.assertEqual(
            self._unreserved(production), [SHORT_COMPONENT],
            "the second build filled the shortage in and the demo has no "
            "story left")

    def test_building_twice_creates_no_second_order(self):
        names = self.env['sale.order'].search(
            [('origin', 'like', SCENARIO_ORIGIN + '%')]).mapped('name')
        self.Scenario.build()
        self.assertEqual(
            self.env['sale.order'].search(
                [('origin', 'like', SCENARIO_ORIGIN + '%')]).mapped('name'),
            names, "a second build duplicated the scenario orders")

    def test_building_twice_adds_no_stock(self):
        """The floor in ``_set_free_quantity`` is the thing under test."""
        product = self.env['product.product'].search(
            [('default_code', '=', SHORT_COMPONENT)], limit=1)
        location = self.env['stock.location'].search(
            [('complete_name', '=', 'RM/Stock')], limit=1)
        domain = [('product_id', '=', product.id),
                  ('location_id', 'child_of', location.id)]
        before = sum(self.env['stock.quant'].search(domain).mapped('quantity'))

        self.Scenario.build()

        self.assertEqual(
            sum(self.env['stock.quant'].search(domain).mapped('quantity')),
            before,
            "the second build topped %s up again; free stock was measured "
            "against the scenario's own reservation" % SHORT_COMPONENT)

    # -- the product itself -------------------------------------------------

    def test_the_scenario_product_is_built_to_order(self):
        """Without MTO a human has to create the manufacturing order by hand,
        and the demo stops showing demand producing production demand.

        Asserted by xmlid, not by name: the demo installs Arabic and
        ``stock.route.name`` is translatable, so the English string is not what
        a reader of this database sees.
        """
        product = self.env['product.product'].search(
            [('default_code', '=', SCENARIO_FG)], limit=1)
        self.assertTrue(product, "the scenario product is missing")
        self.assertIn(
            self.env.ref('stock.route_warehouse0_mto'), product.route_ids,
            "the scenario product is not made to order; confirming the sales "
            "order will create no manufacturing order")

    def test_the_shortage_order_is_confirmed(self):
        order = self._order(SHORTAGE_ORIGIN)
        self.assertEqual(order.state, 'sale')
        self.assertEqual(order.order_line.product_uom_qty, SHORTAGE_QTY)
