"""Session 10 STOP gate: T-96, the recall runs end to end.

The claim this demo is sold on is that the trace is Odoo's, not the model's. So
these assert against real ``stock.move.line`` genealogy: if the chain were faked,
trace_forward would walk nothing and the headline would be a slide.
"""

from odoo import Command
from odoo.tests import TransactionCase, tagged

from odoo.addons.ai_operations.services.context import ExecutionContext, RunBudget
from odoo.addons.ai_operations.services.enums import DenialReason
from odoo.addons.ai_operations.services.exceptions import AIAccessDenied
from odoo.addons.ai_operations.services.registry import all_tools, get_tool


@tagged('post_install', '-at_install', 'ai_security')
class TestRecall(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env['res.company'].search(
            [('name', '=', 'Naqaa Water Manufacturing Co.')], limit=1)
        if not cls.company:
            cls.skip_all = True
            return
        cls.env.user.write({
            'company_ids': [Command.link(cls.company.id)],
            'group_ids': [
                Command.link(cls.env.ref('ai_operations.group_ai_user').id)]})
        cls.env['alshayeb.demo.history'].generate(scale=0.01)

        cls.profile = cls.env['ai.operations.agent.profile'].with_context(
            active_test=False).search([('code', '=', 'quality')], limit=1)
        reviewer = cls.env['res.users'].create({
            'name': 'Rania', 'login': 'q.rania',
            'company_id': cls.company.id,
            'company_ids': [Command.set([cls.company.id])]})
        manager = cls.env['res.users'].create({
            'name': 'Huda', 'login': 'q.huda',
            'company_id': cls.company.id,
            'company_ids': [Command.set([cls.company.id])]})
        cls.profile.write({
            'company_ids': [Command.set([cls.company.id])],
            'default_review_user_id': reviewer.id,
            'default_escalation_user_id': manager.id,
            'active': True})

    def setUp(self):
        super().setUp()
        if getattr(self, 'skip_all', False):
            self.skipTest('demo company not installed')

    def _ctx(self):
        env = self.env(user=self.env.user, context={
            **self.env.context, 'allowed_company_ids': [self.company.id]})
        return ExecutionContext(
            env=env, profile=self.profile.with_env(env),
            execution_user=self.env.user, execution_mode='INTERACTIVE',
            trigger='CHAT', company_ids=(self.company.id,), autonomy=2,
            tool_code='test', correlation_id='corr-recall', session_id='s',
            audit_id=0, policy_version='1.0.0', budget=RunBudget())

    def _run(self, code, params):
        spec = get_tool(code)
        return spec.func(self._ctx(), spec.input_schema.validate(params))

    # -- T-96: the trace ----------------------------------------------------

    def test_the_bromate_batch_traces_forward_to_finished_lots(self):
        result = self._run('quality.trace_forward', {'lot_name': 'WT-260819-02'})
        self.assertGreaterEqual(
            result['finished_lot_count'], 4,
            "the batch fed four finished lots across two lines")

    def test_the_trace_reaches_customers(self):
        result = self._run('quality.trace_forward', {'lot_name': 'WT-260819-02'})
        self.assertGreater(result['customer_count'], 0)
        self.assertTrue(result['shipments'])

    def test_the_trace_walks_real_odoo_genealogy(self):
        """If the chain were faked, this would find nothing. Odoo's genealogy
        follows lot links on stock.move.line."""
        lot = self.env['stock.lot'].search([('name', '=', 'WT-260819-02')], limit=1)
        lines = self.env['stock.move.line'].search([('lot_id', '=', lot.id)])
        self.assertTrue(lines, "no move line consumes the affected batch")

    def test_it_reports_who_received_product_and_never_what_it_was_worth(self):
        """The sharp edge, asserted. Quality reads customer identity and never
        customer value; there is no schema field for an amount."""
        result = self._run('quality.trace_forward', {'lot_name': 'WT-260819-02'})
        for shipment in result['shipments']:
            self.assertEqual(set(shipment),
                             {'lot_name', 'customer', 'customer_ref', 'quantity'})
            self.assertNotIn('amount', shipment)
            self.assertNotIn('value', shipment)

    def test_no_quality_output_schema_declares_a_monetary_field(self):
        banned = {'amount', 'value', 'price', 'cost', 'total', 'revenue',
                  'price_unit', 'amount_total'}
        for code, spec in all_tools().items():
            if not code.startswith('quality.'):
                continue
            leaked = spec.output_schema.field_names() & banned
            self.assertFalse(leaked, "%s emits %s" % (code, leaked))

    def test_financial_exposure_is_refused_at_the_guard(self):
        """When the QA manager asks what it was worth, the correct behaviour is
        a scope refusal. That refusal is a selling point, not a limitation."""
        with self.assertRaises(AIAccessDenied) as caught:
            self._ctx().security.check_model(self.profile, 'account.move', 'read')
        self.assertEqual(caught.exception.reason, DenialReason.MODEL_NOT_PERMITTED)

    # -- the backward half --------------------------------------------------

    def test_a_finished_lot_traces_back_to_the_batch_that_made_it(self):
        forward = self._run('quality.trace_forward', {'lot_name': 'WT-260819-02'})
        self.assertTrue(forward['finished_lots'])
        finished_name = forward['finished_lots'][0]['lot_name']
        backward = self._run('quality.trace_backward', {'lot_name': finished_name})
        traced = [row['lot_name'] for row in backward['consumed_lots']]
        self.assertIn('WT-260819-02', traced)

    # -- disposition ---------------------------------------------------------

    def test_lot_disposition_reports_where_stock_still_sits(self):
        result = self._run('quality.get_lot_disposition',
                           {'lot_name': 'WT-260819-02'})
        self.assertEqual(result['lot_name'], 'WT-260819-02')
        self.assertIsInstance(result['total_on_hand'], float)

    def test_an_unknown_lot_returns_empty_rather_than_raising(self):
        result = self._run('quality.trace_forward', {'lot_name': 'NO-SUCH-LOT'})
        self.assertEqual(result['finished_lot_count'], 0)

    # -- no state changes ----------------------------------------------------

    def test_no_quality_tool_moves_stock(self):
        """The agent proposes a hold; a human executes it."""
        for code, spec in all_tools().items():
            if not code.startswith('quality.'):
                continue
            for model, _action in spec.actions:
                self.assertNotIn(model, ('stock.quant', 'stock.move',
                                         'stock.picking'))
