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
        # `key` is now the required_date, because the idempotency key is derived
        # rather than supplied: two calls that must stay distinct need different
        # business facts, not different labels.
        return self._run('procurement.prepare_draft_rfq', {
            'product_id': self.bottle.id, 'partner_id': self.vendor.id,
            'recommended_quantity': recommended,
            'deterministic_shortage': deterministic,
            'required_date': '2026-%02d-%02d' % (
                (abs(hash(key)) % 12) + 1, (abs(hash(key)) % 27) + 1)})

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

    # -- no computed basis at all ------------------------------------------

    def test_a_proposal_against_a_zero_baseline_is_escalated(self):
        """George's ruling, 2026-09-06.

        Odoo computing a shortage of 0 is not the same as an agent proposing
        nothing. There is nothing to measure the recommendation against, so a
        human decides. The bound escalates; it does not deny.
        """
        result = self._prepare(100_000, deterministic=0, key='zerobase')
        self.assertTrue(result['approval_required'],
                        "a recommendation with no computed basis was waved through")
        self.assertTrue(result['purchase_order_id'], "the draft must still exist")

    def test_a_zero_baseline_escalation_is_still_only_a_draft(self):
        """Escalating must not creep past Level 2."""
        result = self._prepare(100_000, deterministic=0, key='zerodraft')
        order = self.env['purchase.order'].browse(result['purchase_order_id'])
        self.assertEqual(order.state, 'draft')
        self.assertTrue(order.ai_approval_required,
                        "the escalation was not stamped on the record")

    def test_a_zero_baseline_with_nothing_proposed_is_not_escalated(self):
        """Nothing recommended against nothing computed is not a judgement
        call, and must not land on a manager's desk."""
        result = self._prepare(0, deterministic=0, key='zerozero')
        self.assertFalse(result['approval_required'],
                         "an empty proposal was escalated for no reason")

    def test_a_zero_baseline_never_denies(self):
        """Only the ceiling denies, and a missing baseline is not a ceiling
        breach -- there is no percentage to breach it with."""
        before = self.env['purchase.order'].search_count([])
        result = self._prepare(5_000_000, deterministic=0, key='zerohuge')
        self.assertTrue(result['approval_required'])
        self.assertEqual(self.env['purchase.order'].search_count([]), before + 1,
                         "a zero baseline turned into a denial")

    def test_the_escalation_is_recorded_in_the_audit(self):
        self._prepare(100_000, deterministic=0, key='zeroaudit')
        self.env.flush_all()
        row = self.env['ai.operations.audit.log'].search(
            [('event_type', '=', 'VARIANCE')], order='id desc', limit=1)
        self.assertTrue(row, "no variance event was audited")
        self.assertTrue(row.approval_required,
                        "the audit does not show the escalation")

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


@tagged('post_install', '-at_install', 'ai_security')
class TestDraftRfqIdempotency(TestProcurementTools):
    """Replay protection must be a property of the system, not of the model.

    P00004 and P00009 are the same business request and both exist, because the
    key was a free-text parameter the LLM invented -- and it invented a
    different one every time: ``PK-BTL-330-JPI-100000-req1`` then
    ``PK-BTL-330-JPI-100000-shortage-2024``.

    Document D §13 pins the composition:
    ``{profile_code}:{company_id}:{purpose}:{product_ref}:{location_ref}:{date}``
    -- which the model cannot produce, because it does not know the company id
    or the profile code.
    """

    def _prepare_intent(self, quantity=400_000, partner=None, required_date=None,
                        deterministic=366_000):
        params = {
            'product_id': self.bottle.id,
            'partner_id': (partner or self.vendor).id,
            'recommended_quantity': quantity,
            'deterministic_shortage': deterministic,
        }
        if required_date:
            params['required_date'] = required_date
        return self._run('procurement.prepare_draft_rfq', params)

    def test_the_model_cannot_supply_the_key(self):
        """The whole defect in one assertion."""
        from ..tools import schemas
        self.assertNotIn('idempotency_key',
                         schemas.PrepareDraftRfqInput.field_names(),
                         "the LLM is still inventing replay-safety keys")

    def test_the_same_intent_replayed_produces_one_order(self):
        Purchase = self.env['purchase.order']
        before = Purchase.search([])
        first = self._prepare_intent()
        second = self._prepare_intent()          # a separate run, same intent

        self.assertEqual(len(Purchase.search([]) - before), 1,
                         "the same request created a second order")
        self.assertTrue(second['idempotent_hit'])
        self.assertEqual(second['purchase_order_id'], first['purchase_order_id'],
                         "the replay did not return the original order")

    def test_a_different_required_date_is_a_different_request(self):
        Purchase = self.env['purchase.order']
        before = Purchase.search([])
        self._prepare_intent(required_date='2026-09-24')
        self._prepare_intent(required_date='2026-10-24')
        self.assertEqual(len(Purchase.search([]) - before), 2,
                         "two different delivery dates collapsed into one order")

    def test_a_different_vendor_is_a_different_request(self):
        other = self.env['res.partner'].create(
            {'name': 'Other vendor (test)', 'supplier_rank': 1})
        self.env['product.supplierinfo'].create({
            'partner_id': other.id,
            'product_tmpl_id': self.bottle.product_tmpl_id.id,
            'price': 0.06, 'delay': 10})
        Purchase = self.env['purchase.order']
        before = Purchase.search([])

        self._prepare_intent()
        self._prepare_intent(partner=other)

        self.assertEqual(len(Purchase.search([]) - before), 2,
                         "two vendors collapsed into one order")

    def test_the_key_is_composed_the_way_the_contract_says(self):
        from odoo.addons.ai_operations.services.handoff_service import (
            record_idempotency_key,
        )
        key = record_idempotency_key(
            'procurement', self.company.id, 'draft_rfq', 'T-PK-BTL-330',
            self.vendor.id, '2026-09-24')
        self.assertEqual(key.split(':')[0], 'procurement')
        self.assertEqual(key.split(':')[1], str(self.company.id))
        self.assertEqual(len(key.split(':')), 6)

    def test_two_companies_do_not_collide_on_the_same_purpose(self):
        """T-74. The company is inside the key, not only on the constraint."""
        from odoo.addons.ai_operations.services.handoff_service import (
            record_idempotency_key,
        )
        args = ('procurement', None, 'draft_rfq', 'T-PK-BTL-330', 1, '2026-09-24')
        first = record_idempotency_key('procurement', 11, *args[2:])
        second = record_idempotency_key('procurement', 22, *args[2:])
        self.assertNotEqual(first, second)

    def test_the_order_carries_the_derived_key(self):
        result = self._prepare_intent()
        order = self.env['purchase.order'].browse(result['purchase_order_id'])
        self.assertTrue(order.ai_idempotency_key)
        self.assertTrue(order.ai_idempotency_key.startswith('procurement:'),
                        "the stored key is not the namespaced one")
        self.assertEqual(order.state, 'draft')
