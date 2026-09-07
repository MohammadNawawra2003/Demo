"""The bound and schema tests that genuinely need a real pack. T-38, SCHEMA_INVALID.

These moved out of the kernel suite. Document C §4 requires the kernel's full
suite to pass on a database with only `base` and `mail`, and these three need a
real profile, a real action permission and a real registered tool — so they
belong here, where those exist.
"""

from odoo.addons.ai_operations.services.context import ExecutionContext, RunBudget
from odoo.addons.ai_operations.services.enums import DenialReason
from odoo.addons.ai_operations.services.exceptions import AIAccessDenied
from odoo.addons.ai_operations.services.registry import get_tool
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install', 'ai_security')
class TestBounds(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.profile = cls.env['ai.operations.agent.profile'].with_context(
            active_test=False).search([('code', '=', 'procurement')], limit=1)
        cls.skip_all = not cls.profile

    def setUp(self):
        super().setUp()
        if self.skip_all:
            self.skipTest('procurement profile not configured')

    def _ctx(self):
        companies = self.profile.company_ids.ids or self.env.companies.ids
        env = self.env(user=self.env.user, context={
            **self.env.context, 'allowed_company_ids': companies})
        return ExecutionContext(
            env=env, profile=self.profile.with_env(env),
            execution_user=self.env.user, execution_mode='INTERACTIVE',
            trigger='CHAT', company_ids=tuple(companies), autonomy=2,
            tool_code='test', correlation_id='corr-bounds', session_id='s',
            audit_id=0, policy_version='1.0.0', budget=RunBudget())

    def test_t38_a_category_specific_bound_wins(self):
        """§16 decision 4: the bound is configurable per product category.

        The resolver existed and nothing proved the specific row beats the
        agent default, so a category bound could have been silently ignored.
        """
        Permission = self.env['ai.operations.action.permission']
        generic = Permission.search([
            ('profile_id', '=', self.profile.id),
            ('model_name', '=', 'purchase.order'),
            ('action_code', '=', 'CREATE_DRAFT')], limit=1)
        self.assertTrue(generic, "the generic bound is missing")
        self.assertEqual(generic.variance_bound_pct, 20.0)

        specific = generic.copy({
            'product_category_ref': 'Naqaa',
            'variance_bound_pct': 5.0,
            'variance_ceiling_pct': 50.0,
        })
        # 10% is inside the generic 20% and outside the specific 5%.
        _variance, approval = self.env['ai.operations.security'].check_bound(
            self._ctx(), 100.0, 110.0, model_name='purchase.order',
            action_code='CREATE_DRAFT', category_ref='Naqaa')
        self.assertTrue(approval,
                        "the category-specific bound did not take precedence")

        _variance, no_approval = self.env['ai.operations.security'].check_bound(
            self._ctx(), 100.0, 110.0, model_name='purchase.order',
            action_code='CREATE_DRAFT')
        self.assertFalse(no_approval,
                         "the agent default should still allow 10%")
        specific.unlink()

    def test_schema_invalid_is_raised_and_asserted(self):
        """CI check 8: a reason the guard can raise and no test expects is a
        branch nobody has read since it was written."""
        spec = get_tool('procurement.get_shortage_context')
        with self.assertRaises(AIAccessDenied) as caught:
            self.env['ai.operations.security'].check_schema(
                spec, {'not_a_declared_field': 1})
        self.assertEqual(caught.exception.reason, DenialReason.SCHEMA_INVALID)

    def test_t91_the_profile_timeout_reaches_the_provider(self):
        self.assertTrue(self.profile.timeout_seconds,
                        "the profile carries no timeout at all")
