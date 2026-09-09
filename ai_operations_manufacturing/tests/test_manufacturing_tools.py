"""Session 8: check_readiness is the cascade's origin, so its number is the one
that travels. Everything downstream quotes it."""

from odoo import Command
from odoo.tests import TransactionCase, tagged

from odoo.addons.ai_operations.services.context import ExecutionContext, RunBudget
from odoo.addons.ai_operations.services.registry import all_tools, get_tool


@tagged('post_install', '-at_install', 'ai_security')
class TestManufacturingTools(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env['res.company'].create({'name': 'Naqaa Mfg Test'})
        cls.env.user.write({
            'company_ids': [Command.link(cls.company.id)],
            'group_ids': [
                Command.link(cls.env.ref('ai_operations.group_ai_user').id)]})
        cls.profile = cls.env['ai.operations.agent.profile'].with_context(
            active_test=False).search([('code', '=', 'manufacturing')], limit=1)
        assert cls.profile, "the manufacturing policy pack did not load"
        cls.reviewer = cls.env['res.users'].create({
            'name': 'Yousef', 'login': 'mfg.yousef',
            'company_id': cls.company.id,
            'company_ids': [Command.set([cls.company.id])]})
        cls.manager = cls.env['res.users'].create({
            'name': 'Khalid', 'login': 'mfg.khalid',
            'company_id': cls.company.id,
            'company_ids': [Command.set([cls.company.id])]})
        cls.profile.write({
            'company_ids': [Command.set([cls.company.id])],
            'default_review_user_id': cls.reviewer.id,
            'default_escalation_user_id': cls.manager.id,
            'active': True})

        cls.finished = cls.env['product.product'].create({
            'name': 'Naqaa 330 ml (test)', 'default_code': 'T-FG-330',
            'is_storable': True})
        cls.bottle = cls.env['product.product'].create({
            'name': 'Bottle 330 (test)', 'default_code': 'T-BTL-330',
            'is_storable': True})
        cls.cap = cls.env['product.product'].create({
            'name': 'Cap S (test)', 'default_code': 'T-CAP-S',
            'is_storable': True})

        cls.bom = cls.env['mrp.bom'].create({
            'product_tmpl_id': cls.finished.product_tmpl_id.id,
            'product_qty': 1, 'company_id': cls.company.id,
            'bom_line_ids': [
                (0, 0, {'product_id': cls.bottle.id, 'product_qty': 40}),
                (0, 0, {'product_id': cls.cap.id, 'product_qty': 40}),
            ]})

        warehouse = cls.env['stock.warehouse'].search(
            [('company_id', '=', cls.company.id)], limit=1)
        # Caps are plentiful; bottles are short. One component short of two is
        # AT RISK, which is exactly the S-01 shape.
        cls.env['stock.quant'].create({
            'product_id': cls.cap.id,
            'location_id': warehouse.lot_stock_id.id, 'quantity': 1_000_000})
        cls.env['stock.quant'].create({
            'product_id': cls.bottle.id,
            'location_id': warehouse.lot_stock_id.id, 'quantity': 100})

        cls.production = cls.env['mrp.production'].with_company(cls.company).create({
            'product_id': cls.finished.id,
            'product_qty': 1000,
            'bom_id': cls.bom.id,
            'company_id': cls.company.id,
        })

    def _ctx(self):
        env = self.env(user=self.env.user, context={
            **self.env.context, 'allowed_company_ids': [self.company.id]})
        return ExecutionContext(
            env=env, profile=self.profile.with_env(env),
            execution_user=self.env.user, execution_mode='INTERACTIVE',
            trigger='CHAT', company_ids=(self.company.id,), autonomy=2,
            tool_code='test', correlation_id='corr-mfg', session_id='s',
            audit_id=0, policy_version='1.0.0', budget=RunBudget())

    def _run(self, code, params):
        spec = get_tool(code)
        return spec.func(self._ctx(), spec.input_schema.validate(params))

    def test_readiness_reports_the_component_gap(self):
        result = self._run('manufacturing.check_readiness',
                           {'production_id': self.production.id})
        self.assertEqual(result['production_id'], self.production.id)
        self.assertGreaterEqual(result['short_component_count'], 1)
        shortages = {c['product_id']: c['shortage'] for c in result['components']}
        self.assertGreater(shortages.get(self.bottle.id, 0), 0)

    def test_one_component_short_of_several_is_at_risk_not_blocked(self):
        """The S-01 shape: the line can still be planned, and that is what makes
        it worth a human's attention rather than an alarm."""
        result = self._run('manufacturing.check_readiness',
                           {'production_id': self.production.id})
        self.assertEqual(result['status'], 'AT RISK')

    def test_the_gap_tracks_the_stock(self):
        warehouse = self.env['stock.warehouse'].search(
            [('company_id', '=', self.company.id)], limit=1)
        before = self._run('manufacturing.check_readiness',
                           {'production_id': self.production.id})
        self.env['stock.quant'].create({
            'product_id': self.bottle.id,
            'location_id': warehouse.lot_stock_id.id, 'quantity': 500_000})
        after = self._run('manufacturing.check_readiness',
                          {'production_id': self.production.id})
        self.assertLess(after['short_component_count'],
                        before['short_component_count'] + 1)
        self.assertEqual(after['status'], 'READY')

    # -- what actually crosses to the next department -------------------------

    def _raise(self, **overrides):
        params = {
            'production_id': self.production.id,
            'product_id': self.bottle.id,
            # The shape from the field: the agent could not resolve a product id
            # or a quantity, so it supplied its own and said so in its reply.
            'qty_required': 12000.0,
            'qty_available': 0.0,
            'qty_shortage': 12000.0,
        }
        params.update(overrides)
        return self._run('manufacturing.raise_handoff', params)

    def test_the_payload_carries_the_orders_figures_not_the_models(self):
        """check_readiness's docstring is the rule: "the shortage figure you
        pass onward must be this one". Until now nothing enforced it, and a
        handoff reached Procurement describing a shortage that did not exist."""
        readiness = self._run('manufacturing.check_readiness',
                              {'production_id': self.production.id})
        measured = next(line for line in readiness['components']
                        if line['product_id'] == self.bottle.id)

        result = self._raise()
        payload = self.env['ai.operations.handoff'].browse(
            result['handoff_id']).payload

        self.assertEqual(payload['qty_required'], measured['required'])
        self.assertEqual(payload['qty_available'], measured['available'])
        self.assertEqual(payload['qty_shortage'], measured['shortage'])
        self.assertNotEqual(payload['qty_shortage'], 12000.0,
                            "the model's own number reached the next department")
        self.assertEqual(result['qty_shortage'], measured['shortage'])

    def test_a_product_that_is_not_a_component_is_refused(self):
        """A fabricated id is a perfectly readable record; it is simply the
        wrong one, so no permission check would ever have caught it."""
        from odoo.addons.ai_operations.services.enums import DenialReason
        from odoo.addons.ai_operations.services.exceptions import AIAccessDenied

        with self.assertRaises(AIAccessDenied) as caught:
            self._raise(product_id=self.finished.id)
        self.assertEqual(caught.exception.reason,
                         DenialReason.RECORD_OUT_OF_DOMAIN)

    def test_the_pack_can_resolve_a_product_code_to_an_id(self):
        """The gap that produced the guess: Procurement had find_product and
        Manufacturing had nothing, so a code like T-BTL-330 was unreachable."""
        result = self._run('manufacturing.find_product',
                           {'product_ref': 'T-BTL-330'})
        self.assertEqual([row['id'] for row in result['products']],
                         [self.bottle.id])

    def test_bom_explosion_returns_what_odoo_computed(self):
        result = self._run('manufacturing.get_bom_explosion',
                           {'product_id': self.finished.id, 'quantity': 10})
        required = {c['product_id']: c['required'] for c in result['components']}
        self.assertEqual(required[self.bottle.id], 400)
        self.assertEqual(required[self.cap.id], 400)

    def test_open_manufacturing_orders_are_listed(self):
        result = self._run('manufacturing.get_open_mos', {'days_ahead': 365})
        self.assertGreaterEqual(result['count'], 1)

    def test_posting_a_note_changes_no_state(self):
        """It may assess and report. It may not advance anything."""
        state_before = self.production.state
        result = self._run('manufacturing.post_readiness_note', {
            'production_id': self.production.id,
            'note': 'AT RISK — 1 component short'})
        self.assertTrue(result['message_id'])
        self.assertEqual(self.production.state, state_before)

    def test_no_output_schema_in_this_pack_declares_a_cost_field(self):
        """Document B §4.3 denies all cost fields, and the enforcement is that
        no schema ever names one."""
        banned = {'cost', 'price', 'price_unit', 'standard_price', 'value',
                  'amount', 'margin'}
        for code, spec in all_tools().items():
            if not code.startswith('manufacturing.'):
                continue
            leaked = spec.output_schema.field_names() & banned
            self.assertFalse(leaked, "%s emits %s" % (code, leaked))

    def test_t33_no_tool_in_this_pack_can_change_a_production_state(self):
        for code, spec in all_tools().items():
            if not code.startswith('manufacturing.'):
                continue
            for model, action in spec.actions:
                self.assertNotEqual(model, 'mrp.production',
                                    "%s writes to mrp.production" % code)
