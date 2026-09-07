"""The Accountant agent exists and can do nothing. Both halves matter.

The owner asked for this agent after seeing the roster. Document B puts Finance
out of Phase 1, and the isolation proofs the platform is sold on are built on
accounting being unreachable. So these tests hold the line in both directions:
the profile is there and configured, and it has no way to read a ledger.
"""

from odoo.addons.ai_operations.services.registry import all_tools
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install', 'ai_security')
class TestAccountingRoster(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.profile = cls.env['ai.operations.agent.profile'].with_context(
            active_test=False).search([('code', '=', 'accounting')], limit=1)

    def test_the_agent_is_on_the_roster(self):
        self.assertTrue(self.profile, "the Accountant agent is missing")
        self.assertEqual(self.profile.name, 'Accounting Intelligence')

    def test_it_holds_no_tools(self):
        assignments = self.env['ai.operations.tool.assignment'].search(
            [('profile_id', '=', self.profile.id)])
        self.assertFalse(assignments, "the Phase 2 agent has been given tools")
        self.assertFalse(
            [code for code in all_tools() if code.startswith('accounting.')],
            "an accounting tool has been registered")

    def test_it_holds_no_model_permission_at_all(self):
        """Absence is the mechanism: the guard denies anything not listed."""
        permissions = self.env['ai.operations.model.permission'].search(
            [('profile_id', '=', self.profile.id)])
        self.assertFalse(permissions,
                         "the Phase 2 agent has been given scope")

    def test_t34_no_agent_anywhere_can_reach_a_ledger(self):
        """Document B §11 rows 1, 2 and 4, and §15's acceptance. This is the
        property the whole platform is demonstrated on, and adding a finance
        agent is the obvious way to lose it by accident."""
        forbidden = {'account.move', 'account.move.line', 'account.payment',
                     'account.journal'}
        for profile in self.env['ai.operations.agent.profile'].with_context(
                active_test=False).search([]):
            granted = set(self.env['ai.operations.model.permission'].search(
                [('profile_id', '=', profile.id)]).mapped('model_name'))
            self.assertFalse(
                granted & forbidden,
                "%s can reach %s" % (profile.code, granted & forbidden))

    def test_it_cannot_be_activated_without_a_deliberate_act(self):
        """An active profile needs a service user, routing users and company
        scope. None is configured, so activation fails closed rather than
        quietly producing an agent with no boundaries."""
        self.assertFalse(self.profile.active)
        self.assertFalse(self.profile.service_user_id)
