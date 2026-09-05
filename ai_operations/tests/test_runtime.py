from odoo import Command
from odoo.exceptions import ValidationError
from odoo.tests import tagged
from odoo.tools import mute_logger

from ..services import provider as provider_module
from ..services import registry as registry_module
from ..services.context import RunBudget
from ..services.enums import (
    AutonomyLevel,
    Decision,
    DenialReason,
    ExecutionMode,
    ToolCategory,
    TriggerType,
)
from ..services.exceptions import (
    AIAccessDenied,
    AIBudgetExceeded,
    AIProviderError,
    AIProviderRegistrationError,
    NEUTRAL_DENIAL,
)
from ..services.provider import ai_provider
from ..services.registry import ai_tool
from ..services.schema import Int, Schema, Str
from .common import AIOperationsCommon


class NoInput(Schema):
    pass


class ScopeOutput(Schema):
    profile_code = Str()


class LeakyOutput(Schema):
    id = Int()
    api_key = Str()


@tagged('post_install', '-at_install', 'ai_security')
class TestRuntime(AIOperationsCommon):
    """Session 5. The provider layer, the loop, service users and budgets."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.runner = cls.env['ai.operations.execution']
        cls.security = cls.env['ai.operations.security']
        cls.Log = cls.env['ai.operations.audit.log']
        cls.Budget = cls.env['ai.operations.budget']
        cls.env['ai.operations.model.permission'].create({
            'profile_id': cls.profile.id,
            'model_id': cls.env['ir.model']._get('res.company').id,
            'perm_read': True,
        })

    # -- helpers ----------------------------------------------------------

    def _register(self, code, autonomy=AutonomyLevel.QUERY, output=ScopeOutput,
                  func=None):
        self.addCleanup(registry_module._REGISTRY.pop, code, None)
        body = func or (lambda ctx, params: {'profile_code': ctx.profile.code})

        @ai_tool(code=code, category=ToolCategory.READ, autonomy=autonomy,
                 models=['res.company'], input_schema=NoInput, output_schema=output)
        def _tool(ctx, params):
            """A tool registered by the runtime test suite."""
            return body(ctx, params)
        return _tool

    def _assign(self, code):
        Tool = self.env['ai.operations.tool']
        Tool._sync_from_registry()
        tool = Tool.search([('code', '=', code)], limit=1)
        tool.enabled = True
        self.env['ai.operations.tool.assignment'].create({
            'profile_id': self.profile.id, 'tool_id': tool.id})
        return tool

    def _call(self, code, params=None, mode=ExecutionMode.INTERACTIVE.value,
              budget=None):
        return self.runner.execute_tool(
            self.profile, code, params or {}, mode, TriggerType.CHAT.value,
            'sess-runtime', budget=budget)

    # ==================================================================
    # T-60 / T-61 -- autonomy is a ceiling against floors
    # ==================================================================

    def test_t60_level_two_agent_runs_a_prepare_tool(self):
        self._register('rt.prepare', autonomy=AutonomyLevel.PREPARE)
        self._assign('rt.prepare')
        self.profile.max_autonomy_level = '2'
        self.assertEqual(self._call('rt.prepare')['profile_code'], self.profile.code)

    def test_t61_level_one_agent_cannot_run_a_prepare_tool(self):
        self._register('rt.prepare1', autonomy=AutonomyLevel.PREPARE)
        self._assign('rt.prepare1')
        self.profile.max_autonomy_level = '1'
        with self.assertRaises(AIAccessDenied) as caught:
            self._call('rt.prepare1')
        self.assertEqual(caught.exception.reason, DenialReason.AUTONOMY_INSUFFICIENT)

    # ==================================================================
    # T-62 to T-64 -- the autonomous identity
    # ==================================================================

    def test_t62_autonomous_run_with_a_service_user(self):
        self.profile.write({'allow_autonomous': True,
                            'service_user_id': self.service_user.id})
        identity = self.security.resolve_identity(
            self.profile, ExecutionMode.AUTONOMOUS.value)
        self.assertEqual(identity, self.service_user)

    def test_t63_autonomous_run_without_a_service_user_aborts(self):
        with self.assertRaises(AIAccessDenied) as caught:
            self.security.resolve_identity(
                self.profile, ExecutionMode.AUTONOMOUS.value)
        self.assertEqual(caught.exception.reason, DenialReason.NO_SERVICE_USER)

    def test_t64_archived_service_user_aborts_with_no_fallback(self):
        self.profile.write({'allow_autonomous': True,
                            'service_user_id': self.service_user.id})
        self.service_user.active = False
        with self.assertRaises(AIAccessDenied) as caught:
            self.security.resolve_identity(
                self.profile, ExecutionMode.AUTONOMOUS.value)
        self.assertEqual(caught.exception.reason, DenialReason.NO_SERVICE_USER)
        self.assertNotEqual(caught.exception.reason, DenialReason.USER_ACL_DENIED)

    # ==================================================================
    # T-67 / T-68 -- run budgets
    # ==================================================================

    def test_t67_loop_exceeding_max_tool_calls_is_denied(self):
        self._register('rt.budget')
        self._assign('rt.budget')
        budget = RunBudget(max_tool_calls=2, max_write_ops=3)
        self._call('rt.budget', budget=budget)
        self._call('rt.budget', budget=budget)
        with self.assertRaises(AIAccessDenied) as caught:
            self._call('rt.budget', budget=budget)
        self.assertEqual(caught.exception.reason, DenialReason.BUDGET_EXCEEDED)

    def test_t68_run_exceeding_max_write_ops_is_denied(self):
        budget = RunBudget(max_tool_calls=12, max_write_ops=2)
        budget.consume_write()
        budget.consume_write()
        with self.assertRaises(AIBudgetExceeded):
            budget.consume_write()

    # ==================================================================
    # T-69 -- a service user carries no usable credential
    # ==================================================================

    def test_t69_service_user_with_an_api_key_is_refused(self):
        from datetime import datetime, timedelta
        user = self._make_user('ai.rt.svc', 'AI / Runtime Service')
        self.env['res.users.apikeys'].with_user(user)._generate(
            False, 'k', datetime.now() + timedelta(days=1))
        user.invalidate_recordset()
        self.assertTrue(user.api_key_ids, "premise: the key really exists")
        with self.assertRaises(ValidationError):
            user.is_ai_service_user = True

    def test_t69_service_user_with_a_password_is_refused(self):
        user = self._make_user('ai.rt.svc2', 'AI / Runtime Service 2')
        self.env.cr.execute(
            "UPDATE res_users SET password = 'a-real-hash' WHERE id = %s", (user.id,))
        user.invalidate_recordset()
        with self.assertRaises(ValidationError):
            user.is_ai_service_user = True

    def test_t69_service_user_cannot_authenticate(self):
        """The belt to those braces: no credential *and* no auth path."""
        from odoo.exceptions import AccessDenied
        user = self._make_user('ai.rt.svc3', 'AI / Runtime Service 3')
        user.is_ai_service_user = True
        with self.assertRaises(AccessDenied):
            user._check_credentials({'type': 'password', 'password': 'x'},
                                    {'interactive': False})

    def test_a_normal_user_still_authenticates_normally(self):
        """The override must not break login for everybody else."""
        from odoo.exceptions import AccessDenied
        user = self._make_user('ai.rt.normal', 'Normal User')
        with self.assertRaises(AccessDenied):
            # Wrong password: still AccessDenied, but from core, not from us.
            user._check_credentials({'type': 'password', 'password': 'wrong'},
                                    {'interactive': False})
        self.assertFalse(user.is_ai_service_user)

    # ==================================================================
    # T-70 -- the daily token ceiling
    # ==================================================================

    def test_t70_daily_token_ceiling_stops_the_run(self):
        self.profile.max_daily_tokens = 1000
        self.Budget.add_tokens(self.profile, 1000)
        with self.assertRaises(AIAccessDenied) as caught:
            self.security.check_token_ceiling(self.profile)
        self.assertEqual(caught.exception.reason, DenialReason.BUDGET_EXCEEDED)

    def test_the_ceiling_allows_a_run_under_budget(self):
        self.profile.max_daily_tokens = 1000
        self.Budget.add_tokens(self.profile, 999)
        self.assertIsNone(self.security.check_token_ceiling(self.profile))

    def test_zero_means_unlimited(self):
        self.profile.max_daily_tokens = 0
        self.Budget.add_tokens(self.profile, 10 ** 9)
        self.assertIsNone(self.security.check_token_ceiling(self.profile))

    def test_the_counter_lives_off_the_policy_record(self):
        """Finding B3 again: the runtime increments as the executing identity,
        so the counter must not live on the record carrying max_autonomy_level."""
        self.assertNotIn('tokens_date', self.profile._fields)
        self.assertTrue(self.profile._fields['tokens_today'].compute)
        self.Budget.add_tokens(self.profile, 42)
        self.profile.invalidate_recordset(['tokens_today'])
        self.assertEqual(self.profile.tokens_today, 42)

    def test_a_plain_agent_user_can_increment_the_counter(self):
        user = self._make_user('ai.rt.plain', 'Plain Agent User')
        user.write({'group_ids': [
            Command.link(self.env.ref('ai_operations.group_ai_user').id)]})
        self.Budget.with_user(user).add_tokens(self.profile, 5)
        self.assertEqual(self.Budget.tokens_used_today(self.profile), 5)

    @mute_logger('odoo.addons.base.models.ir_model')
    def test_that_user_still_cannot_touch_the_policy(self):
        from odoo.exceptions import AccessError
        user = self._make_user('ai.rt.plain2', 'Plain Agent User 2')
        user.write({'group_ids': [
            Command.link(self.env.ref('ai_operations.group_ai_user').id)]})
        with self.assertRaises(AccessError):
            self.profile.with_user(user).write({'max_autonomy_level': '2'})

    # ==================================================================
    # T-86 -- what the model is told about a denial
    # ==================================================================

    def test_t86_the_model_receives_a_fixed_neutral_string(self):
        self._register('rt.denied', autonomy=AutonomyLevel.PREPARE)
        self._assign('rt.denied')
        self.profile.max_autonomy_level = '1'
        try:
            self._call('rt.denied')
            self.fail("expected a denial")
        except AIAccessDenied as denial:
            self.assertEqual(str(denial), NEUTRAL_DENIAL)
            for leak in ('AUTONOMY_INSUFFICIENT', 'rt.denied', 'res.company'):
                self.assertNotIn(leak, str(denial))
            self.assertEqual(denial.reason, DenialReason.AUTONOMY_INSUFFICIENT)

    # ==================================================================
    # B3-b -- a denial written inside a rollback must still survive
    # ==================================================================

    def test_a_failure_inside_the_savepoint_is_still_audited(self):
        """Review finding B3-b, closed.

        Serialisation happens inside the savepoint that a failure rolls back, so
        the runtime audits *after* the rollback, in the outer transaction. If
        this regresses, a blocklist hit disappears along with the failure that
        caused it.
        """
        self._register('rt.leaks', output=LeakyOutput,
                       func=lambda ctx, params: {'id': 1, 'api_key': 'sk-live'})
        self._assign('rt.leaks')
        # NOT assertRaises: Odoo wraps it in a savepoint that rolls back, which
        # is precisely the behaviour this test exists to rule out.
        raised = False
        try:
            self._call('rt.leaks')
        except Exception:
            raised = True
        self.assertTrue(raised, "a blocklisted key must stop the call")
        self.env.flush_all()
        rows = self.Log.search([
            ('denial_reason', '=', DenialReason.BLOCKLIST_HIT.value),
            ('decision', '=', Decision.DENIED.value)])
        self.assertTrue(
            rows, "the blocklist hit must survive the savepoint rollback")
        self.assertEqual(rows[0].retention_class, 'SECURITY')

    # ==================================================================
    # The provider registry -- T-09, T-72, T-73, T-74a
    # ==================================================================

    def test_t09_runtime_provider_registration_is_refused(self):
        provider_module.freeze_provider_registry()
        self.addCleanup(setattr, provider_module, '_PROVIDERS_FROZEN', False)
        with self.assertRaises(AIProviderRegistrationError):
            @ai_provider(code='too_late', label='Too Late', models=(('m', 'M'),))
            class _Late:
                def complete(self): pass
                def get_models(self): pass
                def health_check(self): pass

    def test_a_provider_without_the_interface_is_refused(self):
        self.addCleanup(provider_module._PROVIDERS.pop, 'partial', None)
        with self.assertRaises(AIProviderRegistrationError):
            @ai_provider(code='partial', label='Partial', models=(('m', 'M'),))
            class _Partial:
                def complete(self): pass

    def test_a_provider_declaring_no_models_is_refused(self):
        self.addCleanup(provider_module._PROVIDERS.pop, 'empty', None)
        with self.assertRaises(AIProviderRegistrationError):
            @ai_provider(code='empty', label='Empty', models=())
            class _Empty:
                def complete(self): pass
                def get_models(self): pass
                def health_check(self): pass

    def test_t72_unknown_provider_code_is_refused(self):
        """Selection validation or the constraint, whichever fires first: both
        are the guard failing closed on an adapter that is not installed.

        A tuple cannot be passed to Odoo's assertRaises -- its override calls
        issubclass() on the argument.
        """
        with self.assertRaises(Exception) as caught:
            self.profile.provider_code = 'no_such_vendor'
        self.assertIsInstance(caught.exception, (ValidationError, ValueError))

    def test_t73_model_outside_the_adapters_declared_list_is_refused(self):
        self._install_null_adapter()
        self.profile.provider_code = 'null'
        with self.assertRaises(Exception) as caught:
            self.profile.model_code = 'not-a-declared-model'
        self.assertIsInstance(caught.exception, (ValidationError, ValueError))

    def test_t74a_get_models_makes_no_network_call(self):
        """Configuration must not depend on the vendor being reachable."""
        spec = self._install_null_adapter()
        self.assertEqual(list(spec.models), [('null-1', 'Null One')])

    def test_unknown_provider_lookup_raises_a_provider_error(self):
        with self.assertRaises(AIProviderError):
            provider_module.get_provider('nope')

    # -- the null adapter, and T-100 parity --------------------------------

    def _install_null_adapter(self):
        if provider_module.has_provider('null'):
            return provider_module.get_provider('null')
        self.addCleanup(provider_module._PROVIDERS.pop, 'null', None)

        @ai_provider(code='null', label='Null', models=(('null-1', 'Null One'),))
        class _Null:
            """A scripted test double: no vendor, no key, no network."""
            def complete(self, *args, **kwargs):
                return {'content': '', 'tool_calls': [], 'stop_reason': 'end_turn',
                        'usage': {'input_tokens': 1, 'output_tokens': 1}}
            def get_models(self):
                return [('null-1', 'Null One')]
            def health_check(self):
                return True, 'ok'
        return provider_module.get_provider('null')

    def test_t100_the_adapter_cannot_change_a_security_decision(self):
        """A provider may change how the LLM is called. It may never change
        security behaviour. Implementable in Phase 1 with one vendor, because
        the second adapter is a test double."""
        self._install_null_adapter()
        self._register('rt.parity', autonomy=AutonomyLevel.PREPARE)
        self._assign('rt.parity')
        self.profile.max_autonomy_level = '1'

        outcomes = []
        for code in (False, 'null'):
            self.profile.provider_code = code
            try:
                self._call('rt.parity')
                outcomes.append('ALLOWED')
            except AIAccessDenied as denial:
                outcomes.append(denial.reason)
        self.assertEqual(outcomes[0], outcomes[1],
                         "swapping the adapter changed a permission decision")
        self.assertEqual(outcomes[0], DenialReason.AUTONOMY_INSUFFICIENT)
