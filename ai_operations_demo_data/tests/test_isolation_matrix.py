"""The isolation ids that had no test at all. T-77, T-82, and STATE_NOT_PERMITTED.

These need Naqaa, because they are about two real companies and a real
intercompany document rather than about synthetic fixtures.
"""

from odoo.addons.ai_operations.services.enums import DenialReason
from odoo.addons.ai_operations.services.exceptions import AIAccessDenied
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install', 'ai_security')
class TestIsolationMatrix(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Profile = cls.env['ai.operations.agent.profile'].with_context(
            active_test=False)
        cls.inventory = cls.Profile.search([('code', '=', 'inventory')], limit=1)
        cls.procurement = cls.Profile.search([('code', '=', 'procurement')], limit=1)
        cls.c1 = cls.env['res.company'].search(
            [('name', '=', 'Naqaa Water Manufacturing Co.')], limit=1)
        cls.c2 = cls.env['res.company'].search(
            [('name', '=', 'Naqaa Distribution Co.')], limit=1)

    def test_t77_c1_cost_is_unreachable_through_the_intercompany_document(self):
        """Document C §16.8 T-77, and Document B's "hardest security test".

        The X-01 fixture exists — a real transfer-priced sale from C1 to C2 —
        and nothing ever tried to walk it. The point is that the link is a
        genuine business document: following it is exactly what an agent
        looking for a margin would do, and the cost still has to be out of
        reach at the end of it.
        """
        order = self.env['sale.order'].with_context(active_test=False).search(
            [('origin', '=', 'DEMO:X-01')], limit=1)
        self.assertTrue(order, "the intercompany document is missing")
        self.assertEqual(order.company_id, self.c1)

        # The Inventory agent spans both companies and is the one that could
        # plausibly reach across. It still cannot read a value.
        for model in ('sale.order', 'sale.order.line', 'stock.valuation.layer',
                      'account.move'):
            with self.assertRaises(AIAccessDenied) as caught:
                self.env['ai.operations.security'].check_model(
                    self.inventory, model, 'read')
            self.assertEqual(caught.exception.reason,
                             DenialReason.MODEL_NOT_PERMITTED,
                             "%s is reachable" % model)

    def test_t77_the_two_numbers_really_do_differ(self):
        """The refusal only means something because there is something to
        refuse: C1's cost and C2's price are materially different."""
        contrast = self.env['alshayeb.demo.builder'].x01_contrast()
        self.assertGreater(contrast['transfer_price'],
                           contrast['production_cost'])

    def test_t82_an_agent_instructed_to_use_a_handoff_for_finance_is_refused(self):
        """§16.9 T-82. The declared schema is the boundary, so an instruction
        to smuggle a value through a handoff fails at write time rather than
        being filtered into something harmless."""
        service = self.env['ai.operations.handoff.service']
        manufacturing = self.Profile.search(
            [('code', '=', 'manufacturing')], limit=1)
        ctx = self._ctx(profile=manufacturing)
        with self.assertRaises(Exception) as caught:
            service.raise_handoff(
                ctx, 'MATERIAL_SHORTAGE',
                payload={'product_id': 1, 'qty_required': 1.0,
                         'qty_available': 0.0, 'qty_shortage': 1.0,
                         'uom_id': 1, 'required_date': '', 'origin_ref': 'x',
                         'warehouse_id': 1, 'priority': '2',
                         'net_profit': 123456.0},
                idempotency_key='t82')
        message = (str(caught.exception) + ' '
                   + str(getattr(caught.exception, 'detail', ''))).lower()
        self.assertIn('net_profit', message,
                      "the undeclared field was not named in the refusal")

    def test_state_not_permitted_is_raised_on_a_confirmed_order(self):
        """The 19th denial reason, asserted rather than merely declared.

        Document B §4.1 grants procurement write on `purchase.order` DRAFT ONLY.
        That restriction was decorative until it was enforced; this is the test
        that fails if it ever stops being.
        """
        confirmed = self.env['purchase.order'].search(
            [('state', 'in', ('purchase', 'done'))], limit=1)
        if not confirmed:
            self.skipTest('no confirmed purchase order in the demo data')
        ctx = self._ctx()
        with self.assertRaises(AIAccessDenied) as caught:
            self.env['ai.operations.security'].check_records(
                ctx, 'purchase.order', confirmed.ids, operation='write')
        self.assertEqual(caught.exception.reason,
                         DenialReason.STATE_NOT_PERMITTED)

    def _ctx(self, profile=None):
        from odoo.addons.ai_operations.services.context import (
            ExecutionContext, RunBudget,
        )
        profile = profile or self.procurement
        env = self.env(user=self.env.user, context={
            **self.env.context, 'allowed_company_ids': [self.c1.id]})
        return ExecutionContext(
            env=env, profile=profile.with_env(env),
            execution_user=self.env.user, execution_mode='INTERACTIVE',
            trigger='CHAT', company_ids=(self.c1.id,), autonomy=2,
            tool_code='test', correlation_id='corr-iso', session_id='s',
            audit_id=0, policy_version='1.0.0', budget=RunBudget())
