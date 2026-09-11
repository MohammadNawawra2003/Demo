"""The Accountant reports and drafts, and posts nothing. All three halves matter.

George made this agent operational, read-only, on 2026-09-07. On 2026-09-11 the
owner asked for it to record a supplier's bill from a picture and to prepare a
journal entry when one is needed (DL-010), so it now drafts both -- Level 2,
Prepare, the ceiling the operational agents work at. These tests hold the new
line:

1. the only thing it may write is a DRAFT ``account.move``, through one action
   that carries an amount ceiling;
2. nothing posts, pays, reconciles, taxes or banks -- the ledger machinery stays
   out of every profile's reach;
3. the four OPERATIONAL agents still cannot read accounting at all, which is
   what Document B §11 rows 1, 2 and 4 and §13's X-04 actually test.

The drafting itself is exercised in ``test_accounting_drafts.py``.
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

READ_TOOLS = {
    'accounting.get_receivable_ageing',
    'accounting.get_payable_ageing',
    'accounting.get_open_invoices',
    'accounting.get_revenue_by_period',
    'accounting.find_partners',
    'accounting.find_accounts',
}
DRAFT_TOOLS = {
    'accounting.prepare_draft_vendor_bill',
    'accounting.prepare_draft_journal_entry',
}


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

    def test_it_holds_its_eight_tools(self):
        codes = {code for code in all_tools() if code.startswith('accounting.')}
        self.assertEqual(codes, READ_TOOLS | DRAFT_TOOLS)
        assigned = self.env['ai.operations.tool.assignment'].search(
            [('profile_id', '=', self.profile.id)])
        self.assertEqual(
            set(assigned.mapped('tool_id.code')), codes,
            "the pack registered tools it never assigned; guard step 4 would "
            "deny every one of them")

    # -- and can write exactly one thing -----------------------------------

    def test_reads_are_reads_and_only_the_two_drafts_write(self):
        for code in READ_TOOLS:
            spec = get_tool(code)
            self.assertEqual(spec.category, ToolCategory.READ.value,
                             "%s is not a READ tool" % code)
            self.assertEqual(spec.autonomy, int(AutonomyLevel.QUERY),
                             "%s needs more than QUERY autonomy" % code)
            self.assertFalse(spec.actions, "%s performs an action" % code)
        for code in DRAFT_TOOLS:
            spec = get_tool(code)
            self.assertEqual(spec.category, ToolCategory.DRAFT_WRITE.value)
            self.assertEqual(spec.autonomy, int(AutonomyLevel.PREPARE))
            self.assertEqual(spec.actions, (('account.move', 'CREATE_DRAFT'),),
                             "%s does more than draft an account.move" % code)

    def test_the_only_write_is_creating_an_account_move(self):
        permissions = self._permissions(self.profile)
        for permission in permissions:
            for field in ('perm_write', 'perm_unlink'):
                self.assertFalse(permission[field], "accounting holds %s on %s"
                                 % (field, permission.model_name))
            if permission.model_name != 'account.move':
                self.assertFalse(permission.perm_create,
                                 "accounting may create %s" % permission.model_name)
        move = permissions.filtered(lambda p: p.model_name == 'account.move')
        self.assertTrue(move.perm_create,
                        "the Accountant cannot create the drafts its tools make")

    def test_the_one_action_is_create_draft_with_a_ceiling(self):
        actions = self.env['ai.operations.action.permission'].search(
            [('profile_id', '=', self.profile.id)])
        self.assertEqual(
            {(action.model_name, action.action_code) for action in actions},
            {('account.move', 'CREATE_DRAFT')})
        for action in actions:
            self.assertEqual(int(action.autonomy_required), 2)
            self.assertGreater(action.max_amount, 0,
                               "a drafting action with no amount ceiling")

    def test_autonomy_is_prepare_and_no_higher(self):
        self.assertEqual(self.profile.max_autonomy_level, '2')

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

    def test_only_the_accountant_creates_and_nobody_edits_an_entry(self):
        """account.move: two agents read it, one drafts it, none edits or
        deletes one."""
        for profile in self.Profile.search([]):
            for permission in self._permissions(profile).filtered(
                    lambda p: p.model_name == 'account.move'):
                for field in ('perm_write', 'perm_unlink'):
                    self.assertFalse(permission[field], "%s holds %s on account.move"
                                     % (profile.code, field))
                if profile.code != 'accounting':
                    self.assertFalse(permission.perm_create,
                                     "%s may create account.move" % profile.code)

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

        The service user stays read-only after DL-010, on purpose: a draft is
        made as the PERSON who asked, with their own rights, and the service
        user only ever runs the unattended cron -- which may report, not write.
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
            "the Accountant's service user can write accounting; drafts are "
            "made as the person, so the service user stays read-only")


@tagged('post_install', '-at_install', 'ai_security')
class TestAccountantSystemPrompt(TransactionCase):
    """The description IS the system prompt, so its wording is behaviour.

    ``build_system_prompt`` returns ``profile.description`` verbatim. An earlier
    wording ended "it holds no permission on any of the models those actions
    need", and on staging the agent dropped the qualifier: three times in seven
    runs it answered that it had no permission to use accounting tools and
    called nothing at all, while holding four assigned and enabled tools.
    Configuration was correct every time. The sentence was not.
    """

    def _accounting(self):
        return self.env['ai.operations.agent.profile'].with_context(
            active_test=False).search([('code', '=', 'accounting')], limit=1)

    def test_the_prompt_does_not_deny_holding_permissions(self):
        description = (self._accounting().description or '').lower()
        self.assertTrue(description, "the accountant has no system prompt")
        for phrase in ('holds no permission', 'no permission on any',
                       'without permissions', 'no write capability'):
            self.assertNotIn(
                phrase, description,
                "the system prompt denies a capability the agent now holds")

    def test_the_prompt_names_what_it_can_do(self):
        description = (self._accounting().description or '').lower()
        for capability in ('receivable', 'payable', 'invoice', 'revenue',
                           'vendor bill', 'journal entry', 'draft'):
            self.assertIn(
                capability, description,
                "the prompt must lead with what the agent CAN do")

    def test_the_restriction_is_scoped_to_posting(self):
        description = (self._accounting().description or '').lower()
        self.assertIn('cannot post', description,
                      "the prompt must say a draft waits for a person")
