from odoo import Command
from odoo.exceptions import ValidationError
from odoo.tests import tagged

from .common import AIOperationsCommon


@tagged('post_install', '-at_install', 'ai_security')
class TestAgentProfile(AIOperationsCommon):

    def test_valid_profile_is_creatable(self):
        profile = self._make_profile(code='inventory', name='Inventory Intelligence')
        self.assertTrue(profile.active)
        self.assertEqual(profile.max_autonomy_level, '2')
        self.assertEqual(profile.audit_level, 'STANDARD')
        self.assertEqual(profile.policy_version, '1.0.0')
        self.assertEqual(profile.max_tool_calls, 12)
        self.assertEqual(profile.max_write_ops, 3)
        self.assertEqual(profile.max_daily_tokens, 2000000)

    def test_t66_autonomy_above_phase1_ceiling_raises(self):
        """Phase 1 permits no agent above level 2."""
        with self.assertRaises(ValidationError):
            self._make_profile(code='too_autonomous', max_autonomy_level='3')

    def test_t66_autonomy_level_four_raises(self):
        with self.assertRaises(ValidationError):
            self._make_profile(code='way_too_autonomous', max_autonomy_level='4')

    def test_autonomous_without_service_user_raises(self):
        """It must never fall back to the administrator or to sudo()."""
        with self.assertRaises(ValidationError):
            self._make_profile(code='headless', allow_autonomous=True)

    def test_t65_service_user_in_group_system_raises(self):
        """An agent may never run as administrator."""
        with self.assertRaises(ValidationError):
            self._make_profile(
                code='root_agent',
                allow_autonomous=True,
                service_user_id=self.system_user.id,
            )

    def test_autonomous_with_service_user_is_allowed(self):
        profile = self._make_profile(
            code='autonomous_ok',
            allow_autonomous=True,
            service_user_id=self.service_user.id,
        )
        self.assertEqual(profile.service_user_id, self.service_user)

    def test_t74b_active_profile_without_reviewer_raises(self):
        with self.assertRaises(ValidationError):
            self._make_profile(code='no_reviewer', default_review_user_id=False)

    def test_t74b_active_profile_without_escalation_user_raises(self):
        with self.assertRaises(ValidationError):
            self._make_profile(code='no_escalation', default_escalation_user_id=False)

    def test_t74b_active_profile_without_company_scope_raises(self):
        with self.assertRaises(ValidationError):
            self._make_profile(code='no_company', company_ids=[Command.clear()])

    def test_t74c_escalation_user_may_not_be_the_service_user(self):
        """An activity addressed to the agent itself is a task nobody owns."""
        with self.assertRaises(ValidationError):
            self._make_profile(
                code='self_escalating',
                allow_autonomous=True,
                service_user_id=self.service_user.id,
                default_escalation_user_id=self.service_user.id,
            )

    def test_t74c_escalation_user_may_not_be_an_administrator(self):
        with self.assertRaises(ValidationError):
            self._make_profile(
                code='escalates_to_root',
                default_escalation_user_id=self.system_user.id,
            )

    def test_t74c_review_user_may_not_be_an_administrator(self):
        with self.assertRaises(ValidationError):
            self._make_profile(
                code='reviewed_by_root',
                default_review_user_id=self.system_user.id,
            )

    def test_routing_user_outside_company_scope_raises(self):
        """Fail closed: routing may never resolve outside the effective scope."""
        with self.assertRaises(ValidationError):
            self._make_profile(
                code='cross_company_routing',
                default_review_user_id=self.outsider.id,
            )

    def test_profile_code_is_unique(self):
        from psycopg2 import IntegrityError

        from odoo.tools import mute_logger
        with self.assertRaises(IntegrityError), mute_logger('odoo.sql_db'):
            self._make_profile(code='procurement', name='Duplicate Code')
            self.env.flush_all()

    def test_archived_profile_escapes_the_activation_constraints(self):
        """The requirement is on activation, not on existence."""
        profile = self._make_profile(code='draft_profile', active=False,
                                     default_review_user_id=False,
                                     default_escalation_user_id=False)
        self.assertFalse(profile.active)

        with self.assertRaises(ValidationError):
            profile.active = True
