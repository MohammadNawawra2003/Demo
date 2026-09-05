"""Session 8 STOP gate: the cascade tools return correct deterministic values.

The point of these is not that the tools run. It is that the numbers they return
are **Odoo's numbers** — the shortage a tool reports is the one the ERP computed,
because the whole division of labour in Document B §2 collapses if the tool
quietly does its own arithmetic.
"""

from odoo import Command
from odoo.tests import TransactionCase, tagged

from odoo.addons.ai_operations.services.context import ExecutionContext, RunBudget
from odoo.addons.ai_operations.services.enums import DenialReason
from odoo.addons.ai_operations.services.exceptions import AIAccessDenied
from odoo.addons.ai_operations.services.registry import get_tool


@tagged('post_install', '-at_install', 'ai_security')
class TestProcurementTools(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env['res.company'].create({'name': 'Naqaa Proc Test'})
        cls.env.user.write({
            'company_ids': [Command.link(cls.company.id)],
            'group_ids': [
                Command.link(cls.env.ref('ai_operations.group_ai_user').id)]})

        # The pack ships the profile INACTIVE, because an active one needs a
        # company scope and routing users that no policy pack can know. Fetch it
        # with active_test=False and complete it, which is what a deployment does.
        cls.profile = cls.env['ai.operations.agent.profile'].with_context(
            active_test=False).search([('code', '=', 'procurement')], limit=1)
        assert cls.profile, "the procurement policy pack did not load"
        cls.reviewer = cls.env['res.users'].create({
            'name': 'Noura', 'login': 'proc.noura',
            'company_id': cls.company.id,
            'company_ids': [Command.set([cls.company.id])]})
        cls.manager = cls.env['res.users'].create({
            'name': 'Ahmed', 'login': 'proc.ahmed',
            'company_id': cls.company.id,
            'company_ids': [Command.set([cls.company.id])]})
        cls.profile.write({
            'company_ids': [Command.set([cls.company.id])],
            'default_review_user_id': cls.reviewer.id,
            'default_escalation_user_id': cls.manager.id,
            'active': True})

        cls.bottle = cls.env['product.product'].create({
            'name': 'Empty PET bottle 330 ml', 'default_code': 'T-PK-BTL-330',
            'is_storable': True, 'standard_price': 0.055, 'purchase_ok': True})
        cls.vendor = cls.env['res.partner'].create({
            'name': 'Jeddah Plastic (test)', 'ref': 'T-SUP-JPI', 'supplier_rank': 1})
        cls.env['product.supplierinfo'].create({
            'partner_id': cls.vendor.id,
            'product_tmpl_id': cls.bottle.product_tmpl_id.id,
            'price': 0.055, 'delay': 18})
        cls.env['product.supplierinfo'].create({
            'partner_id': cls.env['res.partner'].create({
                'name': 'Ningbo Cap (test)', 'ref': 'T-SUP-NCI',
                'supplier_rank': 1}).id,
            'product_tmpl_id': cls.bottle.product_tmpl_id.id,
            'price': 0.043, 'delay': 55, 'min_qty': 5_000_000})

        cls.warehouse = cls.env['stock.warehouse'].search(
            [('company_id', '=', cls.company.id)], limit=1)
        cls.env['stock.quant'].create({
            'product_id': cls.bottle.id,
            'location_id': cls.warehouse.lot_stock_id.id,
            'quantity': 120_000})
        cls.env['stock.warehouse.orderpoint'].create({
            'product_id': cls.bottle.id,
            'warehouse_id': cls.warehouse.id,
            'location_id': cls.warehouse.lot_stock_id.id,
            'product_min_qty': 486_000, 'product_max_qty': 972_000,
            'company_id': cls.company.id})

    def _ctx(self):
        env = self.env(user=self.env.user, context={
            **self.env.context, 'allowed_company_ids': [self.company.id]})
        return ExecutionContext(
            env=env, profile=self.profile.with_env(env),
            execution_user=self.env.user, execution_mode='INTERACTIVE',
            trigger='CHAT', company_ids=(self.company.id,), autonomy=2,
            tool_code='test', correlation_id='corr-proc', session_id='s',
            audit_id=0, policy_version='1.0.0', budget=RunBudget())

    def _run(self, code, params):
        spec = get_tool(code)
        return spec.func(self._ctx(), spec.input_schema.validate(params))

    # -- the deterministic shortage ----------------------------------------

    def test_shortage_context_returns_odoos_numbers(self):
        result = self._run('procurement.get_shortage_context',
                           {'product_id': self.bottle.id})
        self.assertEqual(result['on_hand'], 120_000)
        self.assertEqual(result['reorder_min'], 486_000)
        # 486,000 required against 120,000 available and nothing incoming.
        self.assertEqual(result['shortage'], 366_000)

    def test_the_shortage_moves_when_the_stock_does(self):
        """If this ever stops tracking the quants, the tool has started doing
        its own arithmetic."""
        self.env['stock.quant'].create({
            'product_id': self.bottle.id,
            'location_id': self.warehouse.lot_stock_id.id, 'quantity': 66_000})
        result = self._run('procurement.get_shortage_context',
                           {'product_id': self.bottle.id})
        self.assertEqual(result['on_hand'], 186_000)
        self.assertEqual(result['shortage'], 300_000)

    def test_supplier_comparison_shows_the_real_trade_off(self):
        """§9's planted tension: cheaper import against a 37-day lead gap."""
        result = self._run('procurement.compare_suppliers',
                           {'product_id': self.bottle.id})
        self.assertEqual(len(result['offers']), 2)
        cheapest = min(result['offers'], key=lambda o: o['price'])
        fastest = min(result['offers'], key=lambda o: o['lead_days'])
        self.assertNotEqual(cheapest['partner_id'], fastest['partner_id'],
                            "the decision must not be obvious")
        self.assertGreaterEqual(cheapest['min_qty'], 5_000_000)

    def test_no_vendor_output_carries_bank_or_tax_details(self):
        """Not filtered. The schema declares four keys, so nothing else exists."""
        result = self._run('procurement.compare_suppliers',
                           {'product_id': self.bottle.id})
        for offer in result['offers']:
            self.assertEqual(set(offer),
                             {'partner_id', 'vendor', 'ref', 'price',
                              'lead_days', 'min_qty'})

    # -- the draft, and both bounds ----------------------------------------

    def _prepare(self, recommended, deterministic=366_000, key='k1'):
        return self._run('procurement.prepare_draft_rfq', {
            'product_id': self.bottle.id, 'partner_id': self.vendor.id,
            'recommended_quantity': recommended,
            'deterministic_shortage': deterministic,
            'idempotency_key': key})

    def test_a_draft_within_the_routine_bound_is_not_escalated(self):
        result = self._prepare(400_000, key='within')     # +9.3%
        self.assertFalse(result['approval_required'])
        self.assertLess(result['variance_pct'], 20.0)

    def test_a_draft_above_the_routine_bound_is_created_and_escalated(self):
        """T-37's shape. A breach ESCALATES; it does not deny.

        A denial would leave nothing on a human's desk and make the agent's
        judgement invisible. The escalation preserves both the decision and the
        evidence for it.
        """
        result = self._prepare(620_000, deterministic=486_000, key='escalated')
        self.assertTrue(result['approval_required'])
        self.assertAlmostEqual(result['variance_pct'], 27.57, places=1)
        self.assertTrue(result['purchase_order_id'], "the draft must exist")

    def test_the_hard_ceiling_denies_and_writes_nothing(self):
        """T-39. The only bound that denies."""
        before = self.env['purchase.order'].search_count([])
        with self.assertRaises(AIAccessDenied) as caught:
            self._prepare(1_200_000, deterministic=486_000, key='over')
        self.assertEqual(caught.exception.reason, DenialReason.BOUND_EXCEEDED)
        self.assertEqual(self.env['purchase.order'].search_count([]), before)

    def test_the_draft_shows_both_numbers_never_one(self):
        """Document B §6.3: the deterministic value and the recommendation are
        separate fields, always. The tool may not merge them."""
        result = self._prepare(620_000, deterministic=486_000, key='bothnums')
        self.assertEqual(result['deterministic_shortage'], 486_000)
        self.assertEqual(result['recommended_quantity'], 620_000)
        self.assertNotEqual(result['deterministic_shortage'],
                            result['recommended_quantity'])

    def test_the_draft_is_a_draft(self):
        result = self._prepare(400_000, key='isdraft')
        order = self.env['purchase.order'].browse(result['purchase_order_id'])
        self.assertEqual(order.state, 'draft')

    def test_running_twice_with_one_key_produces_one_order(self):
        """T-92 in miniature."""
        first = self._prepare(400_000, key='same-key')
        second = self._prepare(400_000, key='same-key')
        self.assertEqual(first['purchase_order_id'], second['purchase_order_id'])
        self.assertTrue(second['idempotent_hit'])
        self.assertFalse(first['idempotent_hit'])

    # -- the policy pack itself ---------------------------------------------

    def test_the_policy_pack_survives_the_kernels_own_validator(self):
        """Review finding B2: Document D §13's sample does not.

        Every domain here is literal and every state restriction names its
        field, because the constraints run on install and the pack would not
        have loaded otherwise. This test states the intent so a future edit
        cannot quietly reintroduce the sample.
        """
        for permission in self.profile.model_permission_ids:
            if permission.state_restriction:
                self.assertIn('=', permission.state_restriction)
            if permission.domain:
                self.assertNotIn('allowed_company_ids', permission.domain)

    def test_confirming_a_purchase_order_is_not_a_permitted_action(self):
        """T-31: absence is the mechanism."""
        confirm = self.env['ai.operations.action.permission'].search([
            ('profile_id', '=', self.profile.id),
            ('action_code', 'in', ('CONFIRM', 'button_confirm'))])
        self.assertFalse(confirm)

    def test_no_tool_in_this_pack_can_confirm_anything(self):
        from odoo.addons.ai_operations.services.registry import all_tools
        for code, spec in all_tools().items():
            if not code.startswith('procurement.'):
                continue
            for _model, action in spec.actions:
                self.assertNotIn(action, ('CONFIRM', 'VALIDATE', 'POST'))
