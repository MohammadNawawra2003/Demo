"""Which Naqaa employee may see, and use, which agent.

George opened the chat selector as Noura Al-Harbi -- a procurement clerk -- and
it listed Accounting, General Manager, Inventory, Manufacturing, Procurement and
Quality. Nothing leaked: the guard still refused whatever her own ACLs refused.
But every agent being offered to everybody made "which employees may use this
agent?" a question with no answer, and made the selector actively misleading.

This is the acceptance matrix for the fix, on the real demo configuration rather
than on synthetic fixtures. It asserts BOTH halves, because they fail
independently and only one of them is visible:

  * what each employee is OFFERED  -- ai_widget_profiles' domain
  * what each employee may EXECUTE -- guard step 8b, via check_eligibility

Visibility is not execution security. An agent missing from a dropdown is still
reachable by RPC, by a channel bound before eligibility existed, and by any
caller who passes the id directly -- which is why the guard is asserted
separately here rather than assumed to follow from the selector.
"""

from odoo.tests import TransactionCase, tagged

from ..models.demo_setup import AGENT_USERS


@tagged('post_install', '-at_install', 'ai_security')
class TestDemoAgentEligibilityMatrix(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Profile = cls.env['ai.operations.agent.profile']
        cls.security = cls.env['ai.operations.security']

    def _user(self, login):
        user = self.env['res.users'].with_context(active_test=False).search(
            [('login', '=', login)], limit=1)
        self.assertTrue(user, "demo user %s is missing" % login)
        return user

    def _profile(self, code):
        profile = self.Profile.with_context(active_test=False).search(
            [('code', '=', code)], limit=1)
        self.assertTrue(profile, "agent profile %s is missing" % code)
        return profile

    # -- the assignment itself ---------------------------------------------

    def test_every_agent_names_its_employees(self):
        for code, logins in AGENT_USERS.items():
            profile = self._profile(code)
            self.assertEqual(
                sorted(profile.user_ids.mapped('login')), sorted(logins),
                "agent %s is assigned to the wrong people" % code)

    # -- what each employee is OFFERED -------------------------------------

    def test_each_employee_is_offered_only_their_own_agents(self):
        """The screenshot George sent, inverted into an assertion."""
        for code, logins in AGENT_USERS.items():
            for login in logins:
                user = self._user(login)
                offered = {p['code'] for p
                           in self.Profile.with_user(user).ai_widget_profiles()}
                expected = {c for c, ls in AGENT_USERS.items()
                            if login in ls}
                self.assertEqual(
                    offered, expected,
                    "%s was offered %s but should have %s"
                    % (login, sorted(offered), sorted(expected)))

    def test_noura_is_not_offered_the_accountant(self):
        """Named explicitly because it is the report, not just an instance."""
        offered = {p['code'] for p in self.Profile.with_user(
            self._user('noura.p')).ai_widget_profiles()}
        self.assertEqual(offered, {'procurement'})
        self.assertNotIn('accounting', offered)

    # -- what each employee may EXECUTE ------------------------------------

    def test_each_employee_may_execute_only_their_own_agents(self):
        from odoo.addons.ai_operations.services.enums import DenialReason
        from odoo.addons.ai_operations.services.exceptions import AIAccessDenied

        for code in AGENT_USERS:
            profile = self._profile(code)
            for other_code, logins in AGENT_USERS.items():
                for login in logins:
                    user = self._user(login)
                    if login in AGENT_USERS[code]:
                        self.security.check_eligibility(profile, user)
                        continue
                    with self.assertRaises(AIAccessDenied) as caught:
                        self.security.check_eligibility(profile, user)
                    self.assertEqual(
                        caught.exception.reason,
                        DenialReason.PROFILE_NOT_ELIGIBLE,
                        "%s could execute %s" % (login, code))

    def test_fahad_keeps_the_procurement_agent(self):
        """The refusal scene depends on him REACHING the guard.

        fahad.p is read-only on purchase, so the request that succeeds for
        noura.p is refused for him at the USER term -- the sharpest thing in the
        demo. Hiding the agent from him would replace a demonstrated boundary
        with an empty dropdown, so he is eligible on purpose and denied later,
        on his own ACLs.
        """
        self.security.check_eligibility(
            self._profile('procurement'), self._user('fahad.p'))

    # -- the administrator -------------------------------------------------

    def test_the_administrator_can_still_configure_and_test_every_agent(self):
        admin = self.env.ref('base.user_admin')
        for code in AGENT_USERS:
            profile = self._profile(code)
            self.security.check_eligibility(profile, admin)
            self.assertTrue(
                self.Profile.with_user(admin).search(
                    [('id', '=', profile.id)]),
                "the administrator lost sight of agent %s" % code)
