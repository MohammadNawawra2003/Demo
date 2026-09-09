from odoo import Command
from odoo.exceptions import AccessError
from odoo.tests import tagged

from ..services.enums import DenialReason, ExecutionMode
from ..services.exceptions import AIAccessDenied
from .common import AIOperationsCommon


@tagged('post_install', '-at_install', 'ai_security')
class TestAgentEligibility(AIOperationsCommon):
    """Who may use which agent -- the term the intersection never had.

    Until this shipped, any holder of AI Operations / User was offered every
    active profile whose company scope overlapped their own. The guard still
    refused whatever the user's own ACLs refused, so nothing leaked; but being
    offered an agent you may not use is not a boundary, and an administrator had
    no way to answer "which employees may use this agent?" at all.

    Two independent mechanisms, tested separately here because they fail in
    different ways: a record rule scopes DISCOVERY (and a rule cannot see a
    direct call), and guard step 8b scopes EXECUTION (and the guard is never
    consulted by a dropdown).
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.security = cls.env['ai.operations.security']
        cls.ai_user_group = cls.env.ref('ai_operations.group_ai_user')

        cls.eligible = cls._make_user('ai.test.eligible', 'Eligible Employee')
        cls.ineligible = cls._make_user('ai.test.ineligible', 'Other Department')
        for user in (cls.eligible, cls.ineligible):
            user.write({'group_ids': [Command.link(cls.ai_user_group.id)]})

        cls.profile.write({'user_ids': [Command.link(cls.eligible.id)]})

    # -- the guard: step 8b ------------------------------------------------

    def test_a_listed_user_is_eligible(self):
        self.security.check_eligibility(self.profile, self.eligible)

    def test_an_unlisted_user_is_refused(self):
        with self.assertRaises(AIAccessDenied) as caught:
            self.security.check_eligibility(self.profile, self.ineligible)
        self.assertEqual(caught.exception.reason,
                         DenialReason.PROFILE_NOT_ELIGIBLE)

    def test_the_service_user_is_eligible_without_being_listed(self):
        """An autonomous run has no human to assign."""
        self.profile.write({
            'service_user_id': self.service_user.id,
            'user_ids': [Command.set([self.eligible.id])],
        })
        self.assertNotIn(self.service_user, self.profile.user_ids)
        self.security.check_eligibility(self.profile, self.service_user)

    def test_a_security_admin_is_eligible_without_being_listed(self):
        """Whoever configures the agent has to be able to test it."""
        admin = self._make_user('ai.test.secadmin', 'Security Administrator')
        admin.write({'group_ids': [Command.link(
            self.env.ref('ai_operations.group_ai_security_admin').id)]})
        self.assertNotIn(admin, self.profile.user_ids)
        self.security.check_eligibility(self.profile, admin)

    def test_an_empty_allowed_users_list_refuses_everybody(self):
        """Fails closed, like every other term of the intersection.

        Empty must not mean "everyone". A profile whose eligibility was never
        configured is a profile nobody has been granted, and reading it the
        other way would silently restore exactly the behaviour this replaces.
        """
        self.profile.write({'user_ids': [Command.clear()]})
        with self.assertRaises(AIAccessDenied) as caught:
            self.security.check_eligibility(self.profile, self.eligible)
        self.assertEqual(caught.exception.reason,
                         DenialReason.PROFILE_NOT_ELIGIBLE)

    def test_eligibility_is_not_read_as_records(self):
        """The ids, never the recordset.

        Instantiating an x2many filters it on ``active``, which fetches the
        rows and can raise AccessError for a narrow executing user -- a crash
        no permission check catches. That is what company_ids did to every
        Inventory call, and eligibility must not repeat it. Driving the check
        AS the narrow user is what makes this a real assertion.
        """
        narrow = self.security.with_user(self.eligible)
        narrow.check_eligibility(self.profile.with_user(self.eligible),
                                 self.eligible)

    # -- the door: opening a conversation ----------------------------------

    def test_an_assigned_user_can_open_a_chat(self):
        self.profile.write({
            'partner_id': self.env['res.partner'].create(
                {'name': 'Eligible Agent'}).id,
        })
        action = self.profile.with_user(self.eligible).action_open_chat()
        self.assertTrue(action['params']['channel_id'])

    def test_an_unassigned_user_cannot_open_a_chat(self):
        """Not being offered an agent is not the same as not being able to
        open one. The id is whatever the caller passes, so the door checks."""
        self.profile.write({
            'partner_id': self.env['res.partner'].create(
                {'name': 'Eligible Agent 2'}).id,
        })
        with self.assertRaises(AccessError):
            self.profile.with_user(self.ineligible).action_open_chat()

    def test_a_security_admin_can_open_any_chat(self):
        self.profile.write({
            'partner_id': self.env['res.partner'].create(
                {'name': 'Eligible Agent 3'}).id,
        })
        admin = self._make_user('ai.test.secadmin2', 'Security Administrator 2')
        admin.write({'group_ids': [Command.link(
            self.env.ref('ai_operations.group_ai_security_admin').id)]})
        action = self.profile.with_user(admin).action_open_chat()
        self.assertTrue(action['params']['channel_id'])

    # -- eligibility is not a record rule, on purpose ----------------------

    def test_a_user_may_still_read_a_profile_they_do_not_own(self):
        """Deliberate, and the reason a record rule was removed.

        Scoping READ on the profile table broke the kernel's own mechanics:
        raising a handoff reads the RECEIVING profile's code, and a rule turned
        that into AccessError -- a crash in the middle of the demo's flagship
        path rather than a refusal. Routing users, audit rows and handoffs all
        reference profiles their reader was never assigned.

        The consequence is honest and small: an AI user can read another
        agent's configuration. They cannot open it, and they cannot run it.
        """
        self.assertTrue(self.profile.with_user(self.ineligible).name)

    def test_raising_a_handoff_may_read_the_receiving_profile(self):
        """The regression this replaced a record rule to avoid."""
        receiver = self._make_profile(name='Receiving Agent', code='kt_recv')
        self.assertTrue(
            receiver.with_user(self.eligible).code,
            "an agent could not read the profile it hands work to")

    # -- eligibility only ever subtracts -----------------------------------

    def test_being_eligible_grants_nothing_else(self):
        """The other four terms are untouched.

        The point of the whole change is that it narrows. An eligible user must
        still be refused a model the profile was never granted, and with the
        reason that names the real cause.
        """
        with self.assertRaises(AIAccessDenied) as caught:
            self.security.check_model(self.profile, 'res.currency', 'read')
        self.assertEqual(caught.exception.reason,
                         DenialReason.MODEL_NOT_PERMITTED)

    def test_an_out_of_company_user_still_hears_about_the_company(self):
        """Ordering: company is checked first, and keeps reporting itself.

        The outsider is not on the allowed list either, so both terms would
        refuse. Company is the coarser boundary and the more useful answer, and
        an audit trail that renamed every existing company denial overnight
        would be a worse trail.
        """
        with self.assertRaises(AIAccessDenied) as caught:
            self.security.resolve_companies(self.profile, self.outsider)
        self.assertEqual(caught.exception.reason,
                         DenialReason.COMPANY_OUT_OF_SCOPE)

    def test_autonomous_identity_resolution_is_unchanged(self):
        self.profile.write({
            'allow_autonomous': True,
            'service_user_id': self.service_user.id,
        })
        identity = self.security.resolve_identity(
            self.profile, ExecutionMode.AUTONOMOUS.value)
        self.assertEqual(identity, self.service_user)
