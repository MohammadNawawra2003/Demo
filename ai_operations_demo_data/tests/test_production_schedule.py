"""The production schedule, and the two things it must not disturb.

The schedule exists because the Manufacturing app was empty when the demo was
first reviewed. That is a presentation problem, but it is seeded into the same
database the agents read from, so most of what is asserted here is about
containment: the AI scenario's numbers must be exactly what they were before
the plant had a schedule.
"""

from odoo.tests import TransactionCase, tagged

from ..models.demo_setup import COMPANY, SEED_ORIGIN, SEED_COMPONENT
from ..models.production_schedule import (
    RESERVED_FOR_SCENARIO, SCHEDULE, SCHEDULE_ORIGIN)


@tagged('post_install', '-at_install', 'ai_security')
class TestProductionSchedule(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env['res.company'].search([('name', '=', COMPANY)], limit=1)
        cls.Production = cls.env['mrp.production'].with_context(active_test=False)

    def _scheduled(self):
        return self.Production.search(
            [('origin', 'like', SCHEDULE_ORIGIN + '/%')])

    # -- the plant looks like a plant -------------------------------------

    def test_every_scheduled_order_was_built(self):
        self.assertEqual(len(self._scheduled()), len(SCHEDULE),
                         "the Manufacturing list is short")

    def test_the_schedule_covers_all_four_states(self):
        """A list that is all drafts is not a plant that has been running."""
        states = set(self._scheduled().mapped('state'))
        for expected in ('draft', 'confirmed', 'progress', 'done'):
            self.assertIn(expected, states,
                          "no order reached %r; the workflow stalled" % expected)

    def test_every_order_reached_the_state_it_was_asked_for(self):
        wanted = {'%s/%03d' % (SCHEDULE_ORIGIN, sequence): state
                  for sequence, _code, _qty, state, _offset in SCHEDULE}
        actual = {order.origin: order.state for order in self._scheduled()}
        self.assertEqual(actual, wanted,
                         "an order stopped short of its state; the demo shows "
                         "a record whose state does not match its own moves")

    def test_the_schedule_belongs_to_naqaa(self):
        """The reason the list looked empty was a company filter, so this is
        the assertion that would have caught it."""
        self.assertTrue(self.company, "Naqaa is missing")
        for order in self._scheduled():
            self.assertEqual(order.company_id, self.company,
                             "%s is not a Naqaa order" % order.origin)

    def test_done_orders_actually_consumed_their_components(self):
        done = self._scheduled().filtered(lambda o: o.state == 'done')
        self.assertTrue(done, "nothing was produced")
        for order in done:
            self.assertTrue(order.move_raw_ids,
                            "%s has no components" % order.origin)
            self.assertTrue(
                all(move.state in ('done', 'cancel') for move in order.move_raw_ids),
                "%s is done but its components are not" % order.origin)

    # -- containment: the AI scenario must not have moved -----------------

    def test_the_schedule_never_makes_the_scenario_product(self):
        """FG-330 and its bottle carry the demo's own numbers.

        ``check_readiness`` and ``get_shortage_context`` both read live quants,
        so an order here that consumed or reserved PK-BTL-330 would change what
        the agents answer -- including the deterministic baseline DL-008 rules
        on. The plant makes its other five formats.
        """
        for order in self._scheduled():
            self.assertNotEqual(
                order.product_id.default_code, RESERVED_FOR_SCENARIO,
                "%s produces the scenario's own product" % order.origin)

    def test_the_scenario_component_still_has_no_stock(self):
        component = self.env['product.product'].search(
            [('default_code', '=', SEED_COMPONENT)], limit=1)
        self.assertTrue(component, "the demo component is missing")
        quants = self.env['stock.quant'].search([
            ('product_id', '=', component.id),
            ('location_id.usage', '=', 'internal')])
        self.assertFalse(
            sum(quants.mapped('quantity')),
            "the schedule put %s into stock; the shortage the demo is built "
            "on has been filled in" % SEED_COMPONENT)

    def test_the_scenario_order_is_still_the_only_one_of_its_kind(self):
        scenario = self.Production.search([('origin', '=', SEED_ORIGIN)])
        self.assertEqual(len(scenario), 1,
                         "the scenario order is no longer identifiable by "
                         "its origin")
        self.assertEqual(scenario.product_id.default_code, RESERVED_FOR_SCENARIO)
        self.assertEqual(scenario.state, 'draft',
                         "the scenario order was advanced out of draft")

    # -- re-running the builder ------------------------------------------

    def test_building_twice_schedules_nothing_twice(self):
        before = len(self._scheduled())
        self.env['ai.operations.demo.setup'].build_all()
        self.assertEqual(len(self._scheduled()), before,
                         "the schedule is not idempotent on upgrade")


@tagged('post_install', '-at_install', 'ai_security')
class TestTheReviewerCanSeeTheDemo(TransactionCase):
    """The demo was reported as broken twice, and neither report was a bug.

    Once because Manufacturing was empty under the wrong company, and once
    because an administrator is not an agent user and so had no way in. Both
    are configuration, and both belong to the demo module.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env['res.company'].search([('name', '=', COMPANY)], limit=1)
        cls.admin = cls.env.ref('base.user_admin')

    def test_the_administrator_can_reach_an_agent(self):
        group = self.env.ref('ai_operations.group_ai_user')
        self.assertIn(group, self.admin.group_ids,
                      "admin still has no way to open an agent")

    def test_the_administrator_lands_in_naqaa(self):
        self.assertIn(self.company, self.admin.company_ids,
                      "admin cannot switch to Naqaa at all")
        self.assertEqual(self.admin.company_id, self.company,
                         "admin still opens the database on another company, "
                         "where every seeded record is filtered out")

    def test_the_administrator_keeps_the_companies_they_had(self):
        """Access is added, never replaced."""
        others = self.admin.company_ids - self.company
        self.assertTrue(others, "the demo took away admin's own company")

    def test_the_demo_employees_land_in_naqaa(self):
        for login in ('noura.p', 'fahad.p', 'khalid.m'):
            user = self.env['res.users'].with_context(active_test=False).search(
                [('login', '=', login)], limit=1)
            self.assertTrue(user, "%s is missing" % login)
            self.assertEqual(user.company_id, self.company,
                             "%s does not open on Naqaa" % login)
