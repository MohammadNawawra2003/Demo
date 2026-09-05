from odoo import Command
from odoo.exceptions import AccessError
from odoo.tests import tagged
from odoo.tools import mute_logger

from ..services.context import ExecutionContext
from ..services.enums import AuditLevel, Decision, DenialReason, ExecutionMode
from ..services.exceptions import AIAccessDenied
from .common import AIOperationsCommon


@tagged('post_install', '-at_install', 'ai_security')
class TestGuard(AIOperationsCommon):
    """Document C 7, steps 1-19.

    The matrix in C 16.2 and 16.3 names purchase.order, account.move and
    hr.employee. The kernel depends on base and mail only and its suite must
    pass on a bare database (CI check 3), so those models do not exist here.
    The *semantics* are asserted against base models that carry the same shape:
    res.partner as a permitted model, res.currency as an unpermitted one, and
    res.company for the USER-versus-AGENT intersection, because core grants
    base.group_user read-only on it and group_erp_manager full access. The
    named-model assertions land in the tool-pack sessions, where those modules
    exist. See DEVIATIONS.md.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.security = cls.env['ai.operations.security']
        cls.Log = cls.env['ai.operations.audit.log']

        # The agent may read partners, and write companies.
        cls.perm_partner = cls.env['ai.operations.model.permission'].create({
            'profile_id': cls.profile.id,
            'model_id': cls.env['ir.model']._get('res.partner').id,
            'perm_read': True,
        })
        cls.perm_company = cls.env['ai.operations.model.permission'].create({
            'profile_id': cls.profile.id,
            'model_id': cls.env['ir.model']._get('res.company').id,
            'perm_read': True, 'perm_write': True,
        })

        # A user who may write res.company, and one who may not. Both hold
        # AI Operations / User, because the guard reads its own policy as the
        # executing identity -- sudo() is banned, so anyone running an agent
        # must be able to read the rules being enforced against them.
        ai_user = cls.env.ref('ai_operations.group_ai_user')
        cls.writer = cls._make_user('ai.guard.writer', 'May Write Companies')
        cls.writer.write({'group_ids': [
            Command.link(cls.env.ref('base.group_erp_manager').id),
            Command.link(ai_user.id)]})
        cls.reader = cls._make_user('ai.guard.reader', 'May Not Write Companies')
        cls.reader.write({'group_ids': [Command.link(ai_user.id)]})

    def _ctx(self, user=None, company_ids=None):
        user = user or self.env.user
        env = self.env(user=user, context={
            **self.env.context,
            'allowed_company_ids': list(company_ids or [self.company.id]),
        })
        return ExecutionContext(
            env=env, profile=self.profile.with_env(env), execution_user=user,
            execution_mode=ExecutionMode.INTERACTIVE.value, trigger='CHAT',
            company_ids=tuple(company_ids or [self.company.id]),
            autonomy=2, tool_code='test.guard', correlation_id='corr-test',
            session_id='sess-test', audit_id=0, policy_version='1.0.0')

    # ==================================================================
    # 16.2 -- model and record scope
    # ==================================================================

    def test_t10_permitted_model_is_allowed(self):
        self.assertIsNone(self.security.check_model(self.profile, 'res.partner', 'read'))

    def test_t11_unpermitted_model_is_denied(self):
        with self.assertRaises(AIAccessDenied) as caught:
            self.security.check_model(self.profile, 'res.currency', 'read')
        self.assertEqual(caught.exception.reason, DenialReason.MODEL_NOT_PERMITTED)

    def test_t12_second_unpermitted_model_is_denied(self):
        with self.assertRaises(AIAccessDenied) as caught:
            self.security.check_model(self.profile, 'ir.attachment', 'read')
        self.assertEqual(caught.exception.reason, DenialReason.MODEL_NOT_PERMITTED)

    def test_t13_model_with_no_permission_record_is_denied_by_default(self):
        """Default deny. Nothing is granted implicitly."""
        with self.assertRaises(AIAccessDenied) as caught:
            self.security.check_model(self.profile, 'res.groups', 'read')
        self.assertEqual(caught.exception.reason, DenialReason.MODEL_NOT_PERMITTED)

    def test_t14_operation_not_granted_on_a_permitted_model(self):
        """The agent may read partners. It may not write them."""
        with self.assertRaises(AIAccessDenied) as caught:
            self.security.check_model(self.profile, 'res.partner', 'write')
        self.assertEqual(caught.exception.reason, DenialReason.OPERATION_NOT_PERMITTED)

    def test_t15_record_outside_the_agent_domain(self):
        inside = self.env['res.partner'].create({'name': 'Supplier', 'ref': 'KEEP'})
        outside = self.env['res.partner'].create({'name': 'Other', 'ref': 'NOPE'})
        self.perm_partner.domain = "[('ref', '=', 'KEEP')]"

        ctx = self._ctx()
        self.assertTrue(ctx.check_records('res.partner', inside.ids))
        with self.assertRaises(AIAccessDenied) as caught:
            ctx.check_records('res.partner', outside.ids)
        self.assertEqual(caught.exception.reason, DenialReason.RECORD_OUT_OF_DOMAIN)

    def test_t16_max_records_caps_extraction(self):
        self.assertEqual(self.perm_partner.max_records, 200)
        self.perm_partner.max_records = 2
        self.assertEqual(
            self.security.max_records(self.profile, 'res.partner'), 2)

    def test_t18_hallucinated_record_id(self):
        ctx = self._ctx()
        with self.assertRaises(AIAccessDenied) as caught:
            ctx.check_records('res.partner', [999999999])
        self.assertEqual(caught.exception.reason, DenialReason.USER_ACL_DENIED)

    # ==================================================================
    # 16.3 -- the intersection: USER n AGENT
    # ==================================================================

    def test_t20_user_may_write_and_agent_may_write(self):
        """Both sides permit, so the call proceeds."""
        ctx = self._ctx(user=self.writer)
        self.assertTrue(ctx.check_records('res.company', self.company.ids, 'write'))

    @mute_logger('odoo.addons.base.models.ir_model')
    def test_t21_agent_may_write_but_user_may_not(self):
        """The agent layer subtracts. It can never add.

        This is the row that matters most in Document B 11: the agent is
        configured to allow the write, and the call still fails, because the
        human running it cannot do it either.
        """
        ctx = self._ctx(user=self.reader)
        with self.assertRaises(AIAccessDenied) as caught:
            ctx.check_records('res.company', self.company.ids, 'write')
        self.assertEqual(caught.exception.reason, DenialReason.USER_ACL_DENIED)

    def test_t22_user_may_write_but_agent_may_not(self):
        """The other direction of the same rule."""
        self.perm_company.perm_write = False
        ctx = self._ctx(user=self.writer)
        with self.assertRaises(AIAccessDenied) as caught:
            ctx.check_records('res.company', self.company.ids, 'write')
        self.assertEqual(caught.exception.reason, DenialReason.OPERATION_NOT_PERMITTED)

    def test_t23_neither_may_write(self):
        self.perm_company.perm_write = False
        ctx = self._ctx(user=self.reader)
        with self.assertRaises(AIAccessDenied):
            ctx.check_records('res.company', self.company.ids, 'write')

    @mute_logger('odoo.addons.base.models.ir_model')
    def test_t25_agent_capability_never_exceeds_user_capability(self):
        """Structural, not hopeful: for every operation the agent is granted,
        a user who lacks it is still refused."""
        ctx = self._ctx(user=self.reader)
        self.assertTrue(self.perm_company.perm_write, "premise: the agent allows it")
        with self.assertRaises(AIAccessDenied):
            ctx.check_records('res.company', self.company.ids, 'write')

    def test_company_out_of_scope(self):
        other = self.env['res.company'].create({'name': 'Outside Scope'})
        ctx = self._ctx(company_ids=[self.company.id])
        with self.assertRaises(AIAccessDenied) as caught:
            ctx.check_records('res.company', other.ids, 'read')
        self.assertEqual(caught.exception.reason, DenialReason.COMPANY_OUT_OF_SCOPE)

    def test_empty_company_intersection_is_denied(self):
        stranger = self._make_user('ai.guard.stranger', 'Other Co', company=self.other_company)
        with self.assertRaises(AIAccessDenied) as caught:
            self.security.resolve_companies(self.profile, stranger)
        self.assertEqual(caught.exception.reason, DenialReason.COMPANY_OUT_OF_SCOPE)

    # ==================================================================
    # Identity, autonomy, profile
    # ==================================================================

    def test_inactive_profile_is_denied(self):
        self.profile.write({
            'active': False,
            'default_review_user_id': False,
            'default_escalation_user_id': False,
        })
        with self.assertRaises(AIAccessDenied) as caught:
            self.security.check_profile(self.profile)
        self.assertEqual(caught.exception.reason, DenialReason.PROFILE_INACTIVE)

    def test_autonomous_run_without_a_service_user_aborts(self):
        with self.assertRaises(AIAccessDenied) as caught:
            self.security.resolve_identity(
                self.profile, ExecutionMode.AUTONOMOUS.value)
        self.assertEqual(caught.exception.reason, DenialReason.NO_SERVICE_USER)

    def test_archived_service_user_aborts_with_no_fallback(self):
        self.profile.write({
            'allow_autonomous': True,
            'service_user_id': self.service_user.id,
        })
        self.service_user.active = False
        with self.assertRaises(AIAccessDenied) as caught:
            self.security.resolve_identity(
                self.profile, ExecutionMode.AUTONOMOUS.value)
        self.assertEqual(caught.exception.reason, DenialReason.NO_SERVICE_USER)

    # ==================================================================
    # 16.7 -- T-71, the audit level
    # ==================================================================

    def test_t71_audit_level_cannot_suppress_a_row(self):
        """Only the verbosity fields are emptied. The row is always written,
        because the per-run counters read from this table."""
        audit = self.env['ai.operations.audit']
        self.profile.audit_level = AuditLevel.BASIC.value

        before = self.Log.search_count([('correlation_id', '=', 'corr-verbosity')])
        audit.record_decision(
            'corr-verbosity', Decision.ALLOWED, profile=self.profile,
            tool_code='test.tool', input_args={'secret': 1},
            records_accessed='1,2,3')
        rows = self.Log.search([('correlation_id', '=', 'corr-verbosity')])

        self.assertEqual(len(rows), before + 1, "the row must still be written")
        self.assertFalse(rows.input_args)
        self.assertFalse(rows.records_accessed)

    def test_a_denial_is_never_trimmed(self):
        audit = self.env['ai.operations.audit']
        self.profile.audit_level = AuditLevel.BASIC.value
        audit.record_decision(
            'corr-denial', Decision.DENIED, profile=self.profile,
            reason=DenialReason.MODEL_NOT_PERMITTED, detail='account.move',
            tool_code='test.tool', input_args={'model': 'account.move'})
        row = self.Log.search([('correlation_id', '=', 'corr-denial')], limit=1)
        self.assertTrue(row.input_args, "a denial keeps its evidence")
        self.assertEqual(row.denial_reason, DenialReason.MODEL_NOT_PERMITTED.value)

    # ==================================================================
    # The audit log itself -- finding B3
    # ==================================================================

    def test_audit_log_is_append_only(self):
        row = self.Log.create({
            'event_type': 'OPEN', 'correlation_id': 'corr-immutable',
            'tool_code': 'test.tool',
        })
        with self.assertRaises(AccessError):
            row.write({'tool_code': 'rewritten'})
        with self.assertRaises(AccessError):
            row.unlink()

    def test_a_denial_is_audited_before_it_propagates(self):
        """The property T-80 depends on: nothing escapes unlogged."""
        audit = self.env['ai.operations.audit']
        audit.open_entry(
            tool_code='test.tool', profile=self.profile, user=self.env.user,
            execution_mode=ExecutionMode.INTERACTIVE.value, trigger='CHAT',
            session_id='s', correlation_id='corr-order')
        audit.record_decision(
            'corr-order', Decision.DENIED, profile=self.profile,
            reason=DenialReason.MODEL_NOT_PERMITTED, tool_code='test.tool')
        events = audit.call_events('corr-order')
        self.assertEqual(events[0].event_type, 'OPEN')
        self.assertEqual(events[1].decision, Decision.DENIED.value)

    def test_denial_rows_are_retained_as_security(self):
        """Retention is a property of the event, never of the profile."""
        row = self.Log.create({
            'event_type': 'DECISION', 'correlation_id': 'corr-retention',
            'decision': Decision.DENIED.value,
        })
        self.assertEqual(row.retention_class, 'SECURITY')

    def test_ordinary_reads_are_operational(self):
        row = self.Log.create({
            'event_type': 'DECISION', 'correlation_id': 'corr-op',
            'decision': Decision.ALLOWED.value,
        })
        self.assertEqual(row.retention_class, 'OPERATIONAL')

    @mute_logger('odoo.addons.base.models.ir_model')
    def test_a_user_sees_only_their_own_audit_entries(self):
        mine = self.Log.create({
            'event_type': 'OPEN', 'correlation_id': 'corr-mine',
            'user_id': self.reader.id,
        })
        theirs = self.Log.create({
            'event_type': 'OPEN', 'correlation_id': 'corr-theirs',
            'user_id': self.writer.id,
        })
        self.reader.write({'group_ids': [
            Command.link(self.env.ref('ai_operations.group_ai_user').id)]})
        visible = self.Log.with_user(self.reader).search([
            ('correlation_id', 'in', ['corr-mine', 'corr-theirs'])])
        self.assertIn(mine, visible)
        self.assertNotIn(theirs, visible)

    @mute_logger('odoo.addons.base.models.ir_model')
    def test_a_user_without_the_ai_group_gets_a_neutral_denial(self):
        """Discovered by building this: the guard reads its own policy as the
        executing identity, so a user without AI Operations / User makes Odoo
        raise AccessError -- whose message names a model. The runner hands a
        tool's exception text back to the LLM, so that must never escape as
        itself."""
        outsider = self._make_user('ai.guard.outsider', 'No AI Group')
        ctx = self._ctx(user=outsider)
        with self.assertRaises(AIAccessDenied) as caught:
            ctx.check_records('res.partner', [1])
        self.assertEqual(caught.exception.reason, DenialReason.MODEL_NOT_PERMITTED)
        self.assertNotIn('ai.operations', str(caught.exception))

    def test_the_auditor_sees_everyone(self):
        self.Log.create({
            'event_type': 'OPEN', 'correlation_id': 'corr-audited',
            'user_id': self.writer.id,
        })
        auditor = self._make_user('ai.guard.auditor', 'Guard Auditor')
        auditor.write({'group_ids': [
            Command.link(self.env.ref('ai_operations.group_ai_auditor').id)]})
        visible = self.Log.with_user(auditor).search([
            ('correlation_id', '=', 'corr-audited')])
        self.assertTrue(visible)
