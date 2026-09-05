"""Session 11: T-97 and T-98. The daily review, and why it survives contact
with a real inbox."""

from odoo import Command
from odoo.tests import tagged

from ..services.activity_service import MAX_ACTIVITIES_PER_USER_PER_DAY
from ..services.context import ExecutionContext, RunBudget
from ..services.enums import DenialReason
from .common import AIOperationsCommon


@tagged('post_install', '-at_install', 'ai_security')
class TestActivities(AIOperationsCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.service = cls.env['ai.operations.activity']
        cls.Activity = cls.env['mail.activity']

    def _ctx(self, profile=None):
        profile = profile or self.profile
        return ExecutionContext(
            env=self.env, profile=profile, execution_user=self.env.user,
            execution_mode='INTERACTIVE', trigger='CRON',
            company_ids=(self.company.id,), autonomy=2, tool_code='test',
            correlation_id='corr-activity', session_id='s', audit_id=0,
            policy_version='1.0.0', budget=RunBudget())

    def _create(self, reason='SHORTAGE', res_id=1, summary='330 ml short',
                escalate=False, ctx=None):
        return self.service.create_or_update(
            ctx or self._ctx(), 'res.partner', res_id, summary,
            '<p>Deterministic shortage 486,000</p>', reason, escalate=escalate)

    # -- T-98: deduplication -------------------------------------------------

    def test_t98_a_repeated_exception_updates_rather_than_duplicates(self):
        """The single most common way this class of system dies is becoming
        noise a user learns to ignore."""
        first = self._create()
        second = self._create(summary='330 ml still short')
        self.assertEqual(first, second)
        self.assertEqual(second.summary, '330 ml still short')
        self.assertEqual(second.ai_occurrence_count, 2)

    def test_the_dedup_key_has_somewhere_to_live(self):
        """Review finding H2: mail.activity ships no usable key field, so the
        kernel owns one."""
        self.assertIn('ai_dedup_key', self.Activity._fields)
        activity = self._create(reason='EXPIRY', res_id=2)
        self.assertEqual(
            activity.ai_dedup_key,
            '%s:res.partner:2:EXPIRY' % self.profile.code)

    def test_a_different_reason_is_a_different_activity(self):
        first = self._create(reason='SHORTAGE', res_id=3)
        second = self._create(reason='LATE_RECEIPT', res_id=3)
        self.assertNotEqual(first, second)

    def test_a_different_record_is_a_different_activity(self):
        self.assertNotEqual(self._create(res_id=10), self._create(res_id=11))

    # -- routing, and failing closed ------------------------------------------

    def test_the_routine_reviewer_gets_the_routine_work(self):
        activity = self._create(res_id=20)
        self.assertEqual(activity.user_id, self.reviewer)

    def test_t74e_an_escalated_item_goes_to_the_manager(self):
        activity = self._create(res_id=21, escalate=True)
        self.assertEqual(activity.user_id, self.escalation)

    def test_t74d_an_unresolvable_assignee_creates_nothing(self):
        """No fallback to Administrator, to the service user, to the record's
        creator, or to an arbitrary member of a group. An AI task on the wrong
        desk is worse than no task: it is silently absorbed."""
        profile = self._make_profile(code='noroute', active=False,
                                     default_review_user_id=False,
                                     default_escalation_user_id=False)
        before = self.Activity.search_count([])
        result = self._create(ctx=self._ctx(profile), res_id=30)
        self.assertIsNone(result)
        self.assertEqual(self.Activity.search_count([]), before)

    def test_an_unresolvable_assignee_is_audited(self):
        profile = self._make_profile(code='noroute2', active=False,
                                     default_review_user_id=False,
                                     default_escalation_user_id=False)
        self._create(ctx=self._ctx(profile), res_id=31)
        self.env.flush_all()
        row = self.env['ai.operations.audit.log'].search([
            ('correlation_id', '=', 'corr-activity'),
            ('denial_reason', '=', DenialReason.ASSIGNEE_UNRESOLVED.value)])
        self.assertTrue(row, "a silently missing activity must still be visible")

    def test_an_assignee_outside_the_company_scope_is_refused(self):
        """Refused earlier than the service, in fact: the profile constraint
        will not accept an out-of-scope routing user at all, so the service's
        own check is belt to those braces."""
        from odoo.exceptions import ValidationError
        with self.assertRaises(ValidationError):
            self._make_profile(code='crosscompany', active=False,
                               default_review_user_id=self.outsider.id,
                               default_escalation_user_id=self.outsider.id)

    # -- the volume ceiling B §8 stated and never specified --------------------

    def test_the_daily_ceiling_stops_a_flood(self):
        """Review finding H3: the specification names five per user per agent
        per day and gave it no field, no guard step and no test."""
        created = 0
        for index in range(MAX_ACTIVITIES_PER_USER_PER_DAY + 3):
            if self._create(reason='FLOOD', res_id=100 + index):
                created += 1
        self.assertEqual(created, MAX_ACTIVITIES_PER_USER_PER_DAY)

    def test_the_ceiling_is_per_agent_not_global(self):
        other = self._make_profile(code='otheragent')
        for index in range(MAX_ACTIVITIES_PER_USER_PER_DAY):
            self._create(reason='FLOOD2', res_id=200 + index)
        self.assertTrue(
            self._create(ctx=self._ctx(other), reason='FLOOD2', res_id=300),
            "one agent's noise must not silence another's")

    # -- T-97: four agents, four identities, no cross-contamination -----------

    def test_t97_each_agent_keeps_its_own_activities(self):
        agents = [self._make_profile(code='daily_%d' % index)
                  for index in range(4)]
        for index, agent in enumerate(agents):
            self._create(ctx=self._ctx(agent), reason='DAILY', res_id=400 + index)
        for index, agent in enumerate(agents):
            mine = self.Activity.search([('ai_profile_code', '=', agent.code)])
            self.assertEqual(len(mine), 1, agent.code)
            self.assertEqual(mine.ai_dedup_key,
                             '%s:res.partner:%d:DAILY' % (agent.code, 400 + index))

    def test_activities_are_marked_as_ai_generated(self):
        activity = self._create(res_id=500)
        self.assertTrue(activity.activity_type_id.ai_generated,
                        "a human must be able to filter this work from their own")
