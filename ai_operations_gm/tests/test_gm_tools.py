"""General Manager Intelligence. Post-freeze owner decision, 2026-09-07.

The GM agent is the one most likely to acquire a capability nobody intended:
it is the executive view, so "just let it also..." is the natural next request.
Most of this file exists to make that impossible to do quietly.

The last test is the one that matters. Document C's invariant is
``EFFECTIVE = USER ∩ AGENT ∩ TOOL ∩ ACTION ∩ COMPANY`` -- the profile
*subtracts* from the person running it. A profile permission on
``account.move`` is therefore not a grant of anything: a general manager whose
own Odoo user cannot read invoices still gets nothing. That is asserted against
a real user with real groups, not argued from the design.
"""

from odoo import Command
from odoo.addons.ai_operations.services.context import ExecutionContext, RunBudget
from odoo.addons.ai_operations.services.enums import AutonomyLevel, ToolCategory
from odoo.addons.ai_operations.services.registry import all_tools, get_tool
from odoo.exceptions import AccessError
from odoo.tests import TransactionCase, tagged

GM_TOOLS = {
    'gm.get_operational_summary',
    'gm.get_stock_exceptions',
    'gm.get_blocked_production',
    'gm.get_late_procurement',
    'gm.get_open_quality_issues',
    'gm.get_financial_headlines',
}


@tagged('post_install', '-at_install', 'ai_security')
class TestGeneralManagerTools(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Profile = cls.env['ai.operations.agent.profile'].with_context(
            active_test=False)
        cls.profile = cls.Profile.search([('code', '=', 'gm')], limit=1)

    def _permissions(self, profile=None):
        return self.env['ai.operations.model.permission'].search(
            [('profile_id', '=', (profile or self.profile).id)])

    def _manager(self, login, name, group_xmlids):
        """A user inside the profile's own company.

        Company matters and is easy to get wrong: the guard reads its own
        policy as the executing identity, so a user created in the default
        company sees none of the profile's permission rows and every tool
        denies with MODEL_NOT_PERMITTED. That failure looks exactly like the
        one this file is trying to prove and means something entirely
        different, so the fixture pins the company rather than inheriting it.
        """
        company = self.profile.company_ids[:1] or self.env.company
        return self.env['res.users'].create({
            'name': name,
            'login': login,
            'company_id': company.id,
            'company_ids': [Command.set(company.ids)],
            'group_ids': [Command.set(
                [self.env.ref(xmlid).id for xmlid in group_xmlids])],
        })

    def _ctx(self, user=None):
        user = user or self.env.user
        company = self.profile.company_ids[:1] or user.company_id
        env = self.env(user=user, context={
            **self.env.context, 'allowed_company_ids': company.ids})
        return ExecutionContext(
            env=env, profile=self.profile.with_env(env),
            execution_user=user, execution_mode='INTERACTIVE',
            trigger='CHAT', company_ids=tuple(company.ids), autonomy=0,
            tool_code='test', correlation_id='corr-gm', session_id='s',
            audit_id=0, policy_version='1.0.0', budget=RunBudget())

    def _run(self, code, params=None, user=None):
        spec = get_tool(code)
        return spec.func(self._ctx(user), spec.input_schema.validate(params or {}))

    # -- the pack is what it says it is ------------------------------------

    def test_the_agent_is_on_the_roster(self):
        self.assertTrue(self.profile, "the General Manager agent is missing")
        self.assertEqual(self.profile.name, 'General Manager Intelligence')

    def test_it_registers_and_assigns_exactly_its_six_tools(self):
        self.assertEqual(
            {code for code in all_tools() if code.startswith('gm.')}, GM_TOOLS)
        assigned = self.env['ai.operations.tool.assignment'].search(
            [('profile_id', '=', self.profile.id)])
        self.assertEqual(
            set(assigned.mapped('tool_id.code')), GM_TOOLS,
            "a registered tool was never assigned; guard step 4 would deny it")

    # -- read-only, by construction ----------------------------------------

    def test_every_tool_is_read_and_query(self):
        for code in GM_TOOLS:
            spec = get_tool(code)
            self.assertEqual(spec.category, ToolCategory.READ.value,
                             "%s is not a READ tool" % code)
            self.assertEqual(spec.autonomy, int(AutonomyLevel.QUERY),
                             "%s needs more than QUERY autonomy" % code)

    def test_the_profile_holds_no_write_permission_of_any_kind(self):
        for permission in self._permissions():
            for field in ('perm_create', 'perm_write', 'perm_unlink'):
                self.assertFalse(
                    permission[field],
                    "gm holds %s on %s" % (field, permission.model_name))

    def test_the_profile_holds_no_action_permission(self):
        actions = self.env['ai.operations.action.permission'].search(
            [('profile_id', '=', self.profile.id)])
        self.assertFalse(actions, "the read-only executive agent can act: %s"
                                  % actions.mapped('action_code'))

    def test_autonomy_is_pinned_at_query(self):
        self.assertEqual(self.profile.max_autonomy_level, '0')

    def test_it_has_no_handoff_and_no_activity(self):
        """Two capabilities every operational pack has and this one must not:
        a handoff creates work, an activity lands on a desk. Both are writes."""
        granted = set(self._permissions().mapped('model_name'))
        self.assertFalse(
            granted & {'ai.operations.handoff', 'mail.activity', 'mail.message'},
            "the executive agent can create work")

    def test_the_finance_surface_is_totals_only(self):
        """The output schema is the leakage defence (§5.4), so it is what is
        asserted. Six numbers and a currency -- no partner, no invoice, no
        line, no account."""
        fields = get_tool('gm.get_financial_headlines').output_schema.field_names()
        self.assertEqual(fields, {
            'currency', 'receivable_outstanding', 'receivable_overdue',
            'receivable_overdue_count', 'payable_outstanding',
            'payable_overdue', 'payable_overdue_count'})

    # -- and it subtracts, never adds --------------------------------------

    def test_a_manager_without_accounting_rights_gets_nothing(self):
        """The invariant, against a real user.

        The profile permits ``account.move``. This user does not. The
        intersection is empty, so the ORM refuses under the executing identity
        -- which the runner records as USER_ACL_DENIED and reports to the model
        as the neutral string. The agent permission granted nothing.
        """
        manager = self._manager('gm.no.accounting', 'GM Without Accounting', [
            'base.group_user',
            'ai_operations.group_ai_user',
        ])
        self.assertFalse(
            manager._has_group('account.group_account_readonly'),
            "the fixture user can read accounting; the test proves nothing")
        with self.assertRaises(AccessError):
            self._run('gm.get_financial_headlines', user=manager)

    def test_the_same_manager_still_gets_operational_answers(self):
        """Non-vacuity for the test above: the refusal is about accounting
        rights, not about the user being unable to run the agent at all."""
        manager = self._manager('gm.stock.only', 'GM With Stock Only', [
            'base.group_user',
            'ai_operations.group_ai_user',
            'stock.group_stock_user',
        ])
        result = self._run('gm.get_stock_exceptions', {'limit': 5}, user=manager)
        self.assertIn('products', result)
        self.assertIsInstance(result['count'], int)
