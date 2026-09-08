"""Inventory Intelligence. Document B §4.2, §5.2 and §11 rows 5 and 11.

This pack shipped with an **empty** tests directory, which is how §11 row 5 --
the multi-company value isolation that Document B calls "the sharpest
multi-company test" -- had no automated proof of any kind.

Inventory is the only Phase 1 agent spanning both companies. Quantities cross
the boundary; values do not. That sentence is the whole reason this agent
exists, so most of what is below is about what it must refuse.
"""

from odoo import Command
from odoo.addons.ai_operations.services.context import ExecutionContext, RunBudget
from odoo.addons.ai_operations.services.exceptions import AIAccessDenied
from odoo.addons.ai_operations.services.enums import DenialReason
from odoo.addons.ai_operations.services.registry import get_tool, all_tools
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install', 'ai_security')
class TestInventoryTools(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.c1 = cls.env['res.company'].search(
            [('name', '=', 'Naqaa Water Manufacturing Co.')], limit=1)
        cls.c2 = cls.env['res.company'].search(
            [('name', '=', 'Naqaa Distribution Co.')], limit=1)
        cls.skip_all = not (cls.c1 and cls.c2)
        if cls.skip_all:
            return
        cls.profile = cls.env['ai.operations.agent.profile'].with_context(
            active_test=False).search([('code', '=', 'inventory')], limit=1)

    def setUp(self):
        super().setUp()
        if self.skip_all:
            self.skipTest('demo company not installed')

    def _ctx(self, companies=None):
        companies = companies or (self.c1.id, self.c2.id)
        env = self.env(user=self.env.user, context={
            **self.env.context, 'allowed_company_ids': list(companies)})
        return ExecutionContext(
            env=env, profile=self.profile.with_env(env),
            execution_user=self.env.user, execution_mode='INTERACTIVE',
            trigger='CHAT', company_ids=tuple(companies), autonomy=2,
            tool_code='test', correlation_id='corr-inv', session_id='s',
            audit_id=0, policy_version='1.0.0', budget=RunBudget())

    def _run(self, code, params, companies=None):
        spec = get_tool(code)
        return spec.func(self._ctx(companies), spec.input_schema.validate(params))

    def _product(self, code):
        return self.env['product.product'].with_context(active_test=False).search(
            [('default_code', '=', code)], limit=1)

    # -- §5.2 the catalogue works -----------------------------------------

    def test_stock_position_reports_quantities_by_location(self):
        result = self._run('inventory.get_stock_position',
                           {'product_id': self._product('PK-BTL-330').id})
        self.assertIn('total_on_hand', result)
        self.assertIn('by_location', result)

    def test_the_forecast_is_odoos_number(self):
        """§16 decision 2: the deterministic forecast is the native figure."""
        result = self._run('inventory.get_forecast',
                           {'product_id': self._product('PK-BTL-330').id,
                            'horizon_days': 30})
        self.assertEqual(
            result['forecasted'],
            result['on_hand'] + result['incoming'] - result['outgoing'],
            "the forecast is not the arithmetic of its own inputs")
        self.assertIn('Odoo', result['basis'])

    def test_below_reorder_finds_the_seeded_shortage(self):
        result = self._run('inventory.get_below_reorder', {'limit': 50})
        self.assertIn('products', result)

    def test_late_transfers_returns_only_overdue_ones(self):
        result = self._run('inventory.get_late_transfers', {'limit': 20})
        for row in result['transfers']:
            self.assertGreaterEqual(row['days_late'], 0)
            self.assertNotIn(row['state'], ('done', 'cancel'))

    def test_discrepancies_report_the_gap_seeded_by_s08(self):
        result = self._run('inventory.get_stock_discrepancies', {'limit': 50})
        for row in result['discrepancies']:
            self.assertAlmostEqual(
                row['difference'],
                row['counted_quantity'] - row['system_quantity'], places=2)

    def test_expiring_lots_are_inside_the_window(self):
        result = self._run('inventory.get_expiring_lots', {'days': 90})
        self.assertIn('lots', result)

    # -- §11 row 5: the sharpest multi-company test -----------------------

    def test_row5_no_inventory_output_schema_can_carry_a_value(self):
        """Document B §4.2: "Quantities cross the company boundary; values do
        not." Enforced structurally -- there is no field to put a value in."""
        money = {'cost', 'price', 'value', 'amount', 'standard_price',
                 'list_price', 'valuation', 'total'}
        for code, spec in all_tools().items():
            if not code.startswith('inventory.'):
                continue
            for field in spec.output_schema.field_names():
                self.assertNotIn(
                    field.lower(), money,
                    "%s can emit %s" % (code, field))

    def test_t76_row5_the_agent_cannot_reach_c1_production_cost(self):
        """The literal §11 row 5: Inventory spans C1 and C2 and is refused the
        one thing that would let it compare them."""
        with self.assertRaises(AIAccessDenied) as caught:
            self.env['ai.operations.security'].check_model(
                self.profile, 'stock.valuation.layer', 'read')
        self.assertEqual(caught.exception.reason,
                         DenialReason.MODEL_NOT_PERMITTED)

    def test_row5_accounting_is_refused_in_both_companies(self):
        for model in ('account.move', 'account.move.line', 'product.pricelist'):
            with self.assertRaises(AIAccessDenied):
                self.env['ai.operations.security'].check_model(
                    self.profile, model, 'read')

    def test_t75_row5_it_really_does_span_both_companies(self):
        """The other half: the refusal is only interesting because the agent
        genuinely sees both companies' stock."""
        self.assertGreaterEqual(len(self.profile.company_ids), 2,
                                "inventory is not scoped to both companies")

    # -- §4.2: no writes to any stock model -------------------------------

    def test_no_inventory_tool_writes_stock(self):
        for code, spec in all_tools().items():
            if not code.startswith('inventory.'):
                continue
            category = getattr(spec.category, 'value', spec.category)
            if category == 'HANDOFF' or 'activity' in code:
                continue
            self.assertEqual(
                category, 'READ', "%s is not read-only" % code)

    def test_t32_validating_a_picking_is_not_a_permitted_action(self):
        with self.assertRaises(AIAccessDenied) as caught:
            self.env['ai.operations.security'].check_action(
                self._ctx(), 'stock.picking', 'button_validate')
        self.assertEqual(caught.exception.reason,
                         DenialReason.ACTION_NOT_PERMITTED)

    # -- §6.2 the replenishment handoff ------------------------------------

    def test_the_replenishment_handoff_reaches_procurement(self):
        result = self._run('inventory.raise_handoff', {
            'product_id': self._product('PK-BTL-330').id,
            'qty_suggested': 100000.0,
            'reason_code': 'BELOW_REORDER'})
        self.assertEqual(result['to_profile'], 'procurement')
        self.assertFalse(result['idempotent_hit'])

    def test_row13_one_shortage_seen_twice_is_one_item_of_work(self):
        """§11 row 13 and §6.5, with the REAL packs rather than test doubles.

        Manufacturing raises MATERIAL_SHORTAGE and Inventory raises
        REPLENISHMENT_REQUEST for the same product, warehouse and date. Two
        different types, one receiver -- and because §6.5 scopes uniqueness to
        `(to_profile_id, idempotency_key)` rather than to the type, Procurement
        sees **one** item of work. A type-scoped rule would have let both
        through and Procurement would buy the same bottles twice.

        This is the row the kernel could only prove with synthetic profiles
        until Inventory had a handoff tool and a type of its own.
        """
        product = self._product('PK-BTL-330')
        warehouse = self.env['stock.warehouse'].search(
            [('code', '=', 'RM'), ('company_id', '=', self.c1.id)], limit=1)
        Handoff = self.env['ai.operations.handoff']
        before = Handoff.search([])

        inventory_result = self._run('inventory.raise_handoff', {
            'product_id': product.id, 'qty_suggested': 486000.0,
            'warehouse_id': warehouse.id, 'reason_code': 'BELOW_REORDER'})

        # The same shortage, noticed by Manufacturing, through its own tool.
        manufacturing = self.env['ai.operations.agent.profile'].with_context(
            active_test=False).search([('code', '=', 'manufacturing')], limit=1)
        production = self.env['mrp.production'].search(
            [('origin', '=', 'AI-DEMO')], limit=1)
        self.assertTrue(production, "the scenario order is missing")

        env = self.env(user=self.env.user, context={
            **self.env.context, 'allowed_company_ids': [self.c1.id]})
        mfg_ctx = ExecutionContext(
            env=env, profile=manufacturing.with_env(env),
            execution_user=self.env.user, execution_mode='INTERACTIVE',
            trigger='CHAT', company_ids=(self.c1.id,), autonomy=2,
            tool_code='test', correlation_id='corr-mfg', session_id='s',
            audit_id=0, policy_version='1.0.0', budget=RunBudget())
        spec = get_tool('manufacturing.raise_handoff')
        manufacturing_result = spec.func(mfg_ctx, spec.input_schema.validate({
            'production_id': production.id,
            'product_id': product.id,
            'qty_required': 486000.0,
            'qty_available': 0.0,
            'qty_shortage': 486000.0,
            'warehouse_id': warehouse.id}))

        created = Handoff.search([]) - before
        self.assertEqual(
            len(created), 1,
            "two agents noticing one shortage produced %s items of work"
            % len(created))
        self.assertEqual(manufacturing_result['handoff_id'],
                         inventory_result['handoff_id'],
                         "the second raise did not return the first handoff")
        self.assertTrue(manufacturing_result['idempotent_hit'],
                        "the collision was not recorded as an idempotent hit")


@tagged('post_install', '-at_install', 'ai_security')
class TestOrderComponents(TestInventoryTools):
    """The question an inventory controller actually asks.

    Every other tool in this pack is scoped to a product, and George's own
    acceptance prompt names a manufacturing order: "check the raw materials
    required and whether we have enough". On staging run #2 the agent could only
    answer that it had no tool able to connect an order number to its
    components, and no rewording could get past that -- the profile held
    mrp.production read permission the whole time, and nothing exposed it.
    """

    def _order(self):
        production = self.env['mrp.production'].search(
            [('origin', '=', 'AI-DEMO')], limit=1)
        self.assertTrue(production, "the scenario order is missing")
        return production

    def test_it_reports_every_component_of_the_order(self):
        production = self._order()
        result = self._run('inventory.check_order_components',
                           {'production_id': production.id})
        self.assertEqual(result['production_id'], production.id)
        self.assertEqual(result['reference'], production.name)
        self.assertEqual(
            len(result['components']),
            len(production.move_raw_ids.filtered(
                lambda m: m.state not in ('done', 'cancel'))),
            "a component was dropped from the answer")

    def test_a_short_component_is_reported_as_short(self):
        production = self._order()
        result = self._run('inventory.check_order_components',
                           {'production_id': production.id})
        for row in result['components']:
            self.assertEqual(
                row['sufficient'], row['shortage'] <= 0.0,
                "%s reports sufficient=%s with a shortage of %s"
                % (row['product_code'], row['sufficient'], row['shortage']))
        self.assertEqual(
            result['short_count'],
            len([r for r in result['components'] if not r['sufficient']]))
        self.assertEqual(result['ready'], result['short_count'] == 0)

    def test_it_declares_no_value_field(self):
        """Quantities cross the company boundary here; values never do."""
        result = self._run('inventory.check_order_components',
                           {'production_id': self._order().id})
        for row in result['components']:
            for forbidden in ('price', 'cost', 'value', 'amount'):
                self.assertFalse(
                    [k for k in row if forbidden in k],
                    "a value field reached an inventory output: %s" % row)
