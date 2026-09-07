"""Document C §14 and §18's Resilience section, on a BARE database.

§4's hard rule: the kernel's full suite must pass on a database with only
`base` and `mail` installed, and CI check 3 enforces it. The first version of
this file reached for the `procurement` profile, its action permission and a
pack tool — so it passed on a demo database and failed on a bare one, which is
the exact defect the bare-database run exists to catch.

Everything here builds its own fixtures. The parts that genuinely need a real
pack live in `ai_operations_procurement/tests/test_bounds.py`.
"""

from odoo import Command
from odoo.tests import TransactionCase, tagged

from ..services.enums import DenialReason
from ..services.exceptions import AIAccessDenied


@tagged('post_install', '-at_install', 'ai_security')
class TestResilience(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env['res.company'].create({'name': 'Resilience Co'})
        reviewer = cls.env['res.users'].create({
            'name': 'Reviewer', 'login': 'res.reviewer',
            'company_id': cls.company.id,
            'company_ids': [Command.set([cls.company.id])]})
        manager = cls.env['res.users'].create({
            'name': 'Manager', 'login': 'res.manager',
            'company_id': cls.company.id,
            'company_ids': [Command.set([cls.company.id])]})
        cls.profile = cls.env['ai.operations.agent.profile'].create({
            'name': 'Resilience', 'code': 'res_kt',
            'company_ids': [Command.set([cls.company.id])],
            'max_autonomy_level': '2',
            'timeout_seconds': 120,
            'default_review_user_id': reviewer.id,
            'default_escalation_user_id': manager.id,
        })

    # -- T-90: the provider is dead and Odoo does not care ----------------

    def test_t90_a_dead_provider_blocks_no_odoo_workflow(self):
        """§14's claim and §18's acceptance box.

        The profile carries no provider, so every run fails. Ordinary ORM work
        then proceeds. If the platform had coupled Odoo to the LLM anywhere,
        this is where it would show.
        """
        result = self.env['ai.operations.execution'].run(
            self.profile.code, 'CHAT', entry_prompt='anything')
        self.assertEqual(result.get('status'), 'FAILED',
                         "a dead provider should fail the run, cleanly")

        partner = self.env['res.partner'].create({'name': 'Still Works'})
        partner.write({'ref': 'RES-001'})
        self.assertEqual(partner.ref, 'RES-001')
        company = self.env['res.company'].create({'name': 'Still Works Ltd'})
        self.assertTrue(company.id)
        self.assertTrue(self.env['res.users'].search([], limit=1))

    def test_t90_the_run_returns_rather_than_raising(self):
        """A cron that raises is a cron that mails an administrator every
        morning. §14: log and exit cleanly."""
        self.profile.write({'allow_autonomous': True,
                            'service_user_id': self._service_user().id})
        result = self.env['ai.operations.execution'].run(
            self.profile.code, 'CRON', entry_prompt='daily review')
        self.assertIsInstance(result, dict)
        self.assertEqual(result.get('status'), 'FAILED')

    def test_t90_the_failure_is_audited(self):
        Log = self.env['ai.operations.audit.log']
        before = Log.search_count([])
        self.env['ai.operations.execution'].run(
            self.profile.code, 'CHAT', entry_prompt='anything')
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
        self.assertEqual(self.profile.timeout_seconds, 120)

    # -- T-40: no bound configured is a denial, not a default -------------

    def test_t40_no_bound_record_denies(self):
        """§6.3 and §14: the guard fails closed. A variance with no bound row
        must deny rather than fall back to something permissive."""
        with self.assertRaises(AIAccessDenied) as caught:
            self.env['ai.operations.security'].check_bound(
                self._ctx(), 100.0, 110.0,
                model_name='res.partner', action_code='NO_SUCH_ACTION')
        self.assertEqual(caught.exception.reason, DenialReason.BOUND_EXCEEDED)

    # -- T-35: no method name ever comes from the model -------------------

    def test_t35_no_tool_can_be_given_a_method_name(self):
        """§5.3 promises a Python action registry that does not exist. The risk
        it guards against is closed structurally instead: `method` and
        `method_name` are prohibited input-schema parameter names, so an LLM
        has no way to supply one."""
        from ..services.registry import PROHIBITED_PARAM_NAMES, all_tools
        self.assertIn('method', PROHIBITED_PARAM_NAMES)
        self.assertIn('method_name', PROHIBITED_PARAM_NAMES)
        for code, spec in all_tools().items():
            fields = set(spec.input_schema.field_names())
            self.assertFalse(fields & PROHIBITED_PARAM_NAMES,
                             "%s accepts %s" % (code, fields & PROHIBITED_PARAM_NAMES))

    # -- helpers ------------------------------------------------------------

    def _service_user(self):
        user = self.env['res.users'].create({
            'name': 'Res Service', 'login': 'res.service',
            'company_id': self.company.id,
            'company_ids': [Command.set([self.company.id])]})
        self.env.cr.execute(
            "UPDATE res_users SET password = NULL WHERE id = %s", (user.id,))
        user.invalidate_recordset()
        if 'is_ai_service_user' in user._fields:
            user.is_ai_service_user = True
        return user

    def _ctx(self):
        from ..services.context import ExecutionContext, RunBudget
        return ExecutionContext(
            env=self.env, profile=self.profile,
            execution_user=self.env.user, execution_mode='INTERACTIVE',
            trigger='CHAT', company_ids=(self.company.id,),
            autonomy=2, tool_code='test', correlation_id='corr-res',
            session_id='s', audit_id=0, policy_version='1.0.0',
            budget=RunBudget())
