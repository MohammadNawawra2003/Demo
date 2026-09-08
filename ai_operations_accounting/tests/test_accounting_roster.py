"""The Accountant agent reports, and can change nothing. Both halves matter.

George asked for this agent twice, and on 2026-09-07 -- after trying the staging
demo himself -- asked for it to actually work. It became operational as a
read-only reporting agent. These tests hold the new line.

The previous version of this file asserted that no profile anywhere could reach
``account.move``. That assertion is now wrong by decision, not by accident, so
it is replaced rather than deleted: the property that mattered underneath it was
never "nobody reads accounting", it was

1. no agent can *write* accounting, and
2. the four OPERATIONAL agents still cannot read it, which is what Document B
   §11 rows 1, 2 and 4 and §13's X-04 actually test.

Both are asserted below, individually, per prohibited capability.
"""

from odoo.addons.ai_operations.services.enums import AutonomyLevel, ToolCategory
from odoo.addons.ai_operations.services.registry import all_tools, get_tool
from odoo.tests import TransactionCase, tagged

#: The models that posting, paying, reconciling, taxing and banking need. No
#: profile may hold any permission on these -- not read, and certainly not write.
LEDGER_MACHINERY = {
    'account.move.line', 'account.payment', 'account.journal', 'account.tax',
    'account.full.reconcile', 'account.partial.reconcile', 'res.partner.bank',
    'account.bank.statement', 'account.bank.statement.line',
}

#: Agents whose refusal of financial data is a Phase 1 acceptance criterion.
OPERATIONAL_AGENTS = ('procurement', 'inventory', 'manufacturing', 'quality')


@tagged('post_install', '-at_install', 'ai_security')
class TestAccountingRoster(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Profile = cls.env['ai.operations.agent.profile'].with_context(
            active_test=False)
        cls.profile = cls.Profile.search([('code', '=', 'accounting')], limit=1)

    def _permissions(self, profile):
        return self.env['ai.operations.model.permission'].search(
            [('profile_id', '=', profile.id)])

    # -- the agent exists and works ----------------------------------------

    def test_the_agent_is_on_the_roster(self):
        self.assertTrue(self.profile, "the Accountant agent is missing")
        self.assertEqual(self.profile.name, 'Accounting Intelligence')

    def test_it_holds_its_four_read_tools(self):
        codes = {code for code in all_tools() if code.startswith('accounting.')}
        self.assertEqual(codes, {
            'accounting.get_receivable_ageing',
            'accounting.get_payable_ageing',
            'accounting.get_open_invoices',
            'accounting.get_revenue_by_period',
        })
        assigned = self.env['ai.operations.tool.assignment'].search(
            [('profile_id', '=', self.profile.id)])
        self.assertEqual(
            set(assigned.mapped('tool_id.code')), codes,
            "the pack registered tools it never assigned; guard step 4 would "
            "deny every one of them")

    # -- and can change nothing --------------------------------------------

    def test_every_accounting_tool_is_read_only(self):
        for code in (c for c in all_tools() if c.startswith('accounting.')):
            spec = get_tool(code)
            self.assertEqual(
                spec.category, ToolCategory.READ.value,
                "%s is not a READ tool" % code)
            self.assertEqual(
                spec.autonomy, int(AutonomyLevel.QUERY),
                "%s needs more than QUERY autonomy" % code)

    def test_the_profile_holds_no_write_permission_of_any_kind(self):
        for permission in self._permissions(self.profile):
            for field in ('perm_create', 'perm_write', 'perm_unlink'):
                self.assertFalse(
                    permission[field],
                    "accounting holds %s on %s"
                    % (field, permission.model_name))

    def test_the_profile_holds_no_action_permission(self):
        """No action permission means guard step 15 has nothing to allow."""
        actions = self.env['ai.operations.action.permission'].search(
            [('profile_id', '=', self.profile.id)])
        self.assertFalse(
            actions, "accounting can perform actions: %s"
                     % actions.mapped('action_code'))

    def test_autonomy_is_pinned_at_query(self):
        self.assertEqual(self.profile.max_autonomy_level, '0')

    def test_no_profile_anywhere_can_touch_the_ledger_machinery(self):
        """Posting, paying, reconciling, taxes and bank data.

        Each is prohibited by the absence of the model it needs, so this is the
        single assertion that covers all five prohibitions George named.
        """
        for profile in self.Profile.search([]):
            granted = set(self._permissions(profile).mapped('model_name'))
            trespass = granted & LEDGER_MACHINERY
            self.assertFalse(
                trespass, "%s can reach %s" % (profile.code, sorted(trespass)))

    def test_no_profile_anywhere_can_write_an_accounting_entry(self):
        """account.move itself: readable by two agents now, writable by none."""
        for profile in self.Profile.search([]):
            for permission in self._permissions(profile).filtered(
                    lambda p: p.model_name == 'account.move'):
                for field in ('perm_create', 'perm_write', 'perm_unlink'):
                    self.assertFalse(
                        permission[field],
                        "%s holds %s on account.move"
                        % (profile.code, field))

    # -- the isolation rows Document B is sold on --------------------------

    def test_t34_the_operational_agents_still_cannot_read_accounting(self):
        """Document B §11 rows 1, 2 and 4, and §13's X-04.

        Widening Accountant is exactly the change that would lose this by
        accident, so it is asserted against the named four rather than against
        "every profile" -- which is what made the old version of this test
        block the owner's decision instead of protecting the property.
        """
        for code in OPERATIONAL_AGENTS:
            profile = self.Profile.search([('code', '=', code)], limit=1)
            if not profile:
                continue    # that pack is not installed in this database
            granted = set(self._permissions(profile).mapped('model_name'))
            trespass = {name for name in granted if name.startswith('account.')}
            self.assertFalse(
                trespass,
                "%s can reach %s; Document B §11's refusal rows no longer hold"
                % (code, sorted(trespass)))

    def test_activation_carries_its_boundaries(self):
        """An active profile must carry the identity it runs as.

        This asserted ``not active`` until the agent became operational. That
        was never the property worth holding -- the pack still ships the profile
        inactive, and the demo module activates it, so asserting on the flag
        just recorded which module happened to run last. What matters is that an
        ACTIVE profile has a service user and a company scope, so it can never
        run as an unbounded identity.
        """
        if not self.profile.active:
            self.assertFalse(
                self.profile.service_user_id,
                "an inactive profile is carrying a service user")
            return
        self.assertTrue(
            self.profile.service_user_id,
            "the Accountant is active with no service user to execute as")
        self.assertTrue(
            self.profile.company_ids,
            "the Accountant is active with no company scope")
        self.assertFalse(
            self.profile.service_user_id._has_group(
                'account.group_account_user'),
            "the Accountant's service user can write accounting; read-only "
            "means group_account_readonly and nothing above it")


@tagged('post_install', '-at_install', 'ai_security')
class TestAccountantSystemPrompt(TransactionCase):
    """The description IS the system prompt, so its wording is behaviour.

    ``build_system_prompt`` returns ``profile.description`` verbatim. The
    original ended "it holds no permission on any of the models those actions
    need", and on staging the agent dropped the qualifier: three times in seven
    runs it answered that it had no permission to use accounting tools and
    called nothing at all, while holding four assigned and enabled tools.
    Configuration was correct every time. The sentence was not.

    The General Manager is read-only in the same way, says "no WRITE capability
    of any kind", and has never refused.
    """

    def _accounting(self):
        return self.env['ai.operations.agent.profile'].with_context(
            active_test=False).search([('code', '=', 'accounting')], limit=1)

    def test_the_prompt_does_not_deny_holding_permissions(self):
        description = (self._accounting().description or '').lower()
        self.assertTrue(description, "the accountant has no system prompt")
        for phrase in ('holds no permission', 'no permission on any',
                       'without permissions'):
            self.assertNotIn(
                phrase, description,
                "the system prompt tells the model it holds no permissions, "
                "which it reads as 'do not call your tools'")

    def test_the_prompt_names_what_it_can_do(self):
        description = (self._accounting().description or '').lower()
        for capability in ('receivable', 'payable', 'invoice', 'revenue'):
            self.assertIn(
                capability, description,
                "a read-only agent's prompt must lead with what it CAN do")

    def test_the_restriction_is_scoped_to_writing(self):
        description = (self._accounting().description or '').lower()
        self.assertIn('write', description,
                      "the restriction must name writing, not permissions")
