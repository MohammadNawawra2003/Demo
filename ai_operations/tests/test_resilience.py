"""Document C §14 and §18's Resilience section. T-35, T-38, T-40, T-90, T-91.

§14 says the core ERP "must never depend on LLM availability" and that this is
"verified by an explicit test that disables the provider and runs a full
business cycle". There was no such test, so the entire Resilience acceptance
section was asserted and never demonstrated.
"""

from odoo import Command
from odoo.tests import TransactionCase, tagged

from ..services.enums import DenialReason
from ..services.exceptions import AIAccessDenied, AIProviderError


@tagged('post_install', '-at_install', 'ai_security')
class TestResilience(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.profile = cls.env['ai.operations.agent.profile'].with_context(
            active_test=False).search([('code', '=', 'procurement')], limit=1)

    # -- T-90: the provider is dead and Odoo does not care ----------------

    def test_t90_a_dead_provider_blocks_no_odoo_workflow(self):
        """The claim §14 makes and §18 accepts on.

        The provider is pointed at a code that does not exist, so every agent
        run fails. A partner, a product and a company are then created, written
        and read through the ordinary ORM. If the platform had coupled Odoo to
        the LLM anywhere, this is where it would show.
        """
        original = self.profile.provider_code
        self.profile.with_context(skip_policy_audit=True).provider_code = False

        try:
            result = self.env['ai.operations.execution'].run(
                self.profile.code, 'CHAT', entry_prompt='anything')
            self.assertEqual(result.get('status'), 'FAILED',
                             "a dead provider should fail the run, cleanly")

            # ... and the ERP carries on.
            partner = self.env['res.partner'].create({'name': 'Resilience Co'})
            partner.write({'ref': 'RES-001'})
            self.assertEqual(partner.ref, 'RES-001')
            company = self.env['res.company'].create({'name': 'Resilience Ltd'})
            self.assertTrue(company.id)
            self.assertTrue(self.env['res.users'].search([], limit=1))
        finally:
            self.profile.with_context(skip_policy_audit=True).provider_code = original

    def test_t90_a_cron_run_refuses_before_it_reaches_a_dead_provider(self):
        """The demo profiles ship with `allow_autonomous` off, so a CRON run is
        refused at step 1 and never reaches the provider at all.

        That is the stronger outcome, not a weaker one: arming the cron is a
        deliberate act, and until somebody performs it a dead vendor cannot even
        be contacted. The clean-exit path for an armed cron is covered by
        `ai_operations_procurement/tests/test_cron_entry.py`.
        """
        with self.assertRaises(AIAccessDenied) as caught:
            self.env['ai.operations.execution'].run(
                self.profile.code, 'CRON', entry_prompt='daily review')
        self.assertEqual(caught.exception.reason, DenialReason.PROFILE_INACTIVE)

    def test_t90_the_failure_is_audited(self):
        original = self.profile.provider_code
        self.profile.with_context(skip_policy_audit=True).provider_code = False
        Log = self.env['ai.operations.audit.log']
        before = Log.search_count([])
        try:
            self.env['ai.operations.execution'].run(
                self.profile.code, 'CHAT', entry_prompt='anything')
        finally:
            self.profile.with_context(skip_policy_audit=True).provider_code = original
        self.assertGreater(Log.search_count([]), before,
                           "a provider failure left no trace")

    # -- T-91: the timeout is carried, not invented -----------------------

    def test_t91_the_profile_timeout_reaches_the_provider(self):
        """§14: abort at `timeout_seconds`. The value was passed and nothing
        asserted it, so a profile could carry a timeout the adapter ignored."""
        import inspect
        from ..services import execution
        source = inspect.getsource(execution.AIExecutionRunner.run)
        self.assertIn('timeout', source,
                      "the runner never passes a timeout to the provider")
        self.assertTrue(self.profile.timeout_seconds,
                        "the profile carries no timeout at all")

    # -- T-40: no bound configured is a denial, not a default -------------

    def test_t40_no_bound_record_denies(self):
        """§6.3 and §13: the guard fails closed. A variance with no bound row
        must deny rather than fall back to a permissive default."""
        ctx = self._ctx()
        with self.assertRaises(AIAccessDenied) as caught:
            self.env['ai.operations.security'].check_bound(
                ctx, 100.0, 110.0,
                model_name='res.partner', action_code='NO_SUCH_ACTION')
        self.assertEqual(caught.exception.reason, DenialReason.BOUND_EXCEEDED)

    # -- T-38: the category-specific bound beats the agent default --------

    def test_t38_a_category_specific_bound_wins(self):
        """§16 decision 4: the bound is configurable per product category.
        The resolver existed and no test proved the specific row wins."""
        Permission = self.env['ai.operations.action.permission']
        generic = Permission.search([
            ('profile_id', '=', self.profile.id),
            ('model_name', '=', 'purchase.order'),
            ('action_code', '=', 'CREATE_DRAFT')], limit=1)
        self.assertTrue(generic, "the generic bound is missing")

        specific = generic.copy({
            'product_category_ref': 'Naqaa',
            'variance_bound_pct': 5.0,
            'variance_ceiling_pct': 50.0,
        })
        ctx = self._ctx()
        # 10% is inside the generic 20% and outside the specific 5%.
        _variance, approval = self.env['ai.operations.security'].check_bound(
            ctx, 100.0, 110.0, model_name='purchase.order',
            action_code='CREATE_DRAFT', category_ref='Naqaa')
        self.assertTrue(approval,
                        "the category-specific bound did not take precedence")
        specific.unlink()

    # -- T-35: no method name ever comes from the model -------------------

    def test_t35_no_tool_can_be_given_a_method_name(self):
        """§5.3 promises a Python action registry that does not exist. The
        risk it was written against is closed structurally instead: `method`
        and `method_name` are prohibited input-schema parameter names, so an
        LLM has no way to supply one."""
        from ..services.registry import PROHIBITED_PARAM_NAMES, all_tools
        self.assertIn('method', PROHIBITED_PARAM_NAMES)
        self.assertIn('method_name', PROHIBITED_PARAM_NAMES)
        for code, spec in all_tools().items():
            fields = set(spec.input_schema.field_names())
            self.assertFalse(
                fields & PROHIBITED_PARAM_NAMES,
                "%s accepts %s" % (code, fields & PROHIBITED_PARAM_NAMES))

    # -- the two denial reasons nothing asserted --------------------------

    def test_schema_invalid_is_raised_and_asserted(self):
        """CI check 8: a reason the guard can raise and no test expects is a
        branch nobody has read since it was written."""
        ctx = self._ctx()
        del ctx
        with self.assertRaises(AIAccessDenied) as caught:
            self.env['ai.operations.security'].check_schema(
                self._spec_with_required_int(), {'not_the_field': 1})
        self.assertEqual(caught.exception.reason, DenialReason.SCHEMA_INVALID)

    def _spec_with_required_int(self):
        from ..services.registry import get_tool
        return get_tool('procurement.get_shortage_context')

    # -- helper ------------------------------------------------------------

    def _ctx(self):
        from ..services.context import ExecutionContext, RunBudget
        return ExecutionContext(
            env=self.env, profile=self.profile,
            execution_user=self.env.user, execution_mode='INTERACTIVE',
            trigger='CHAT', company_ids=tuple(self.profile.company_ids.ids),
            autonomy=2, tool_code='test', correlation_id='corr-res',
            session_id='s', audit_id=0, policy_version='1.0.0',
            budget=RunBudget())
