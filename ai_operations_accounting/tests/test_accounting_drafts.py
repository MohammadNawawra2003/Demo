"""The Accountant drafts a bill and a journal entry. Nothing here posts. DL-010.

Every tool runs as a REAL accountant, never as the superuser this suite
otherwise runs as: uid 1 bypasses ir.model.access, so a test asserting that
something is *permitted* proves nothing while it runs as uid 1 (05_progress,
2026-09-08).
"""

import inspect

from odoo import SUPERUSER_ID, Command
from odoo.tests import tagged

from odoo.addons.account.tests.common import AccountTestInvoicingCommon
from odoo.addons.ai_operations.services.context import ExecutionContext, RunBudget
from odoo.addons.ai_operations.services.enums import Decision, DenialReason
from odoo.addons.ai_operations.services.exceptions import AIAccessDenied
from odoo.addons.ai_operations.services.registry import get_tool

from ..tools import tools as pack

BILL = 'accounting.prepare_draft_vendor_bill'
ENTRY = 'accounting.prepare_draft_journal_entry'
BILL_REF = 'NQ-RNT-2026-09-001'
ENTRY_REF = 'Accrued rent September 2026'


@tagged('post_install', '-at_install', 'ai_security')
class TestAccountingDrafts(AccountTestInvoicingCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.company_data['company']
        cls.expense = cls.company_data['default_account_expense']
        # A bill line takes its tax from its account. This is the accountant's
        # configuration the tool relies on, never a tax the model chooses.
        cls.expense.tax_ids = [Command.set(cls.tax_purchase_a.ids)]
        cls.accrual = cls.env['account.account'].create({
            'code': 'T219990', 'name': 'Accrued Rent (test)',
            'account_type': 'liability_current'})
        cls.vendor = cls.env['res.partner'].create({
            'name': 'Riyadh Landlord (test)', 'supplier_rank': 1})
        cls.accountant = cls._person('acct.omar', 'account.group_account_manager')
        cls.clerk = cls._person('acct.clerk', None)

        # Configuring the agent is an administrator's act, and the fixture user
        # lives in its own company, where record rules hide a profile the demo
        # scoped to Naqaa. So configure as uid 1 -- what every other suite here
        # does -- and run the TOOLS as the real people above.
        admin = cls.env(user=SUPERUSER_ID)
        cls.profile = admin['ai.operations.agent.profile'].with_context(
            active_test=False).search([('code', '=', 'accounting')], limit=1)
        assert cls.profile, "the accounting policy pack did not load"
        cls.profile.write({
            'company_ids': [Command.set([cls.company.id])],
            'user_ids': [Command.set([cls.accountant.id, cls.clerk.id])],
            'default_review_user_id': cls.accountant.id,
            'default_escalation_user_id': cls.accountant.id,
            'allow_interactive': True,
            'active': True})
        # Tools materialise disabled; a deployment enables them.
        Tool = admin['ai.operations.tool'].with_context(active_test=False)
        Tool._sync_from_registry()
        Tool.search([('code', '=like', 'accounting.%')]).write({'enabled': True})
        admin['ai.operations.tool.assignment'].search(
            [('profile_id', '=', cls.profile.id)]).write({'enabled': True})
        cls.draft_action = admin.ref(
            'ai_operations_accounting.action_create_draft_move')

    @classmethod
    def _person(cls, login, group_xmlid):
        groups = [cls.env.ref('base.group_user'),
                  cls.env.ref('ai_operations.group_ai_user')]
        if group_xmlid:
            groups.append(cls.env.ref(group_xmlid))
        return cls.env['res.users'].create({
            'name': login, 'login': login,
            'company_id': cls.company.id,
            'company_ids': [Command.set([cls.company.id])],
            'group_ids': [Command.set([group.id for group in groups])]})

    def _ctx(self, user=None, autonomy=2):
        user = user or self.accountant
        env = self.env(user=user, context={
            **self.env.context, 'allowed_company_ids': [self.company.id]})
        return ExecutionContext(
            env=env, profile=self.profile.with_env(env),
            execution_user=user, execution_mode='INTERACTIVE', trigger='CHAT',
            company_ids=(self.company.id,), autonomy=autonomy,
            tool_code='test', correlation_id='corr-acct', session_id='s',
            audit_id=0, policy_version='1.2.0',
            budget=RunBudget(max_tool_calls=8, max_write_ops=2))

    def _run(self, code, params, **ctx_kwargs):
        spec = get_tool(code)
        return spec.func(self._ctx(**ctx_kwargs), spec.input_schema.validate(params))

    def _bill(self, lines=None):
        return {
            'partner_id': self.vendor.id,
            'bill_reference': BILL_REF,
            'bill_date': '2026-09-30',
            'lines': lines or [{'description': 'Shop rent, September 2026',
                                'account_code': self.expense.code,
                                'amount': 1000.0}],
        }

    def _entry(self, lines=None):
        return {
            'reference': ENTRY_REF,
            'entry_date': '2026-09-30',
            'lines': lines or [
                {'account_code': self.expense.code, 'label': 'Rent accrual',
                 'debit_amount': 300.0},
                {'account_code': self.accrual.code, 'label': 'Rent accrual',
                 'credit_amount': 300.0},
            ],
        }

    def _moves(self, ref):
        return self.env['account.move'].search(
            [('ref', '=', ref), ('company_id', '=', self.company.id)])

    # -- the vendor bill ---------------------------------------------------

    def test_a_bill_is_drafted_as_the_person_with_odoos_tax(self):
        result = self._run(BILL, self._bill())
        self.assertTrue(result['ok'], result['problem'])
        bill = self.env['account.move'].browse(result['move_id'])
        self.assertEqual(bill.state, 'draft', "an agent posted a bill")
        self.assertEqual(bill.move_type, 'in_invoice')
        self.assertEqual(bill.partner_id, self.vendor)
        self.assertEqual(bill.ref, BILL_REF)
        self.assertEqual(bill.create_uid, self.accountant,
                         "the draft must be the person's, made with their rights")
        self.assertAlmostEqual(result['amount_untaxed'], 1000.0)
        self.assertGreater(result['amount_tax'], 0.0,
                           "the account's tax was not applied")
        self.assertAlmostEqual(result['amount_total'],
                               result['amount_untaxed'] + result['amount_tax'])

    def test_the_same_bill_twice_is_one_draft(self):
        first = self._run(BILL, self._bill())
        second = self._run(BILL, self._bill())
        self.assertFalse(first['idempotent_hit'])
        self.assertTrue(second['idempotent_hit'])
        self.assertEqual(first['move_id'], second['move_id'])
        self.assertEqual(len(self._moves(BILL_REF)), 1)

    def test_an_unknown_account_is_named_and_nothing_is_written(self):
        result = self._run(BILL, self._bill(lines=[
            {'description': 'Rent', 'account_code': 'NOPE999', 'amount': 10.0}]))
        self.assertFalse(result['ok'])
        self.assertIn('NOPE999', result['problem'])
        self.assertFalse(self._moves(BILL_REF))

    def test_a_bill_above_the_ceiling_leaves_nothing_behind(self):
        self.draft_action.max_amount = 500.0
        with self.assertRaises(AIAccessDenied) as refusal:
            # The executor runs every tool inside a savepoint; so does this.
            with self.env.cr.savepoint():
                self._run(BILL, self._bill())
        self.assertEqual(refusal.exception.reason, DenialReason.ACTION_NOT_PERMITTED)
        self.assertFalse(self._moves(BILL_REF))

    def test_an_existing_draft_is_not_handed_to_someone_who_could_not_make_it(self):
        """Authorise first, then look: a replay may not skip the person's ACL."""
        self._run(BILL, self._bill())
        with self.assertRaises(AIAccessDenied) as refusal:
            self._run(BILL, self._bill(), user=self.clerk)
        self.assertEqual(refusal.exception.reason, DenialReason.USER_ACL_DENIED)

    def test_the_ceiling_is_on_the_total_with_tax(self):
        """1,000 before tax passes a 1,001 ceiling; 1,000 plus tax does not."""
        self.draft_action.max_amount = 1001.0
        with self.assertRaises(AIAccessDenied):
            # The executor runs every tool inside a savepoint; so does this.
            with self.env.cr.savepoint():
                self._run(BILL, self._bill())
        self.assertFalse(self._moves(BILL_REF))

    def test_a_person_without_billing_rights_is_refused(self):
        with self.assertRaises(AIAccessDenied) as refusal:
            self._run(BILL, self._bill(), user=self.clerk)
        self.assertEqual(refusal.exception.reason, DenialReason.USER_ACL_DENIED)

    def test_query_autonomy_cannot_draft(self):
        with self.assertRaises(AIAccessDenied) as refusal:
            self._run(BILL, self._bill(), autonomy=0)
        self.assertEqual(refusal.exception.reason,
                         DenialReason.AUTONOMY_INSUFFICIENT)

    # -- through the executor, as a chat turn runs it -------------------------

    def _through_the_executor(self, correlation_id):
        runner = self.env['ai.operations.execution'].with_user(
            self.accountant).with_context(allowed_company_ids=[self.company.id])
        return runner.execute_tool(
            self.profile.with_env(runner.env), BILL, self._bill(),
            'INTERACTIVE', 'CHAT', 'sess-acct', correlation_id=correlation_id,
            budget=RunBudget(max_tool_calls=8, max_write_ops=2))

    def _audit(self, correlation_id):
        return self.env(user=SUPERUSER_ID)['ai.operations.audit.log'].search(
            [('correlation_id', '=', correlation_id)])

    def test_through_the_executor_a_drafted_bill_is_audited_as_a_write(self):
        result = self._through_the_executor('corr-bill-ok')
        self.assertTrue(result['ok'], result['problem'])
        self.assertTrue(
            self._audit('corr-bill-ok').filtered('values_after'),
            "a drafted bill left no WRITE row: move_id is not in WRITE_ID_KEYS")

    def test_through_the_executor_the_ceiling_rolls_the_bill_back(self):
        """DL-010's claim, proved on the real path: guard, savepoint, audit.

        Deliberately NOT ``assertRaises``: Odoo's wraps its block in a savepoint
        and rolls it back, which would erase the bill -- and the audit rows --
        whatever the executor did. Here the only rollback is the executor's.
        """
        self.draft_action.max_amount = 1001.0
        try:
            self._through_the_executor('corr-bill-over')
        except AIAccessDenied as denial:
            self.assertEqual(denial.reason, DenialReason.ACTION_NOT_PERMITTED)
        else:
            self.fail("a bill above the ceiling was drafted")
        self.assertFalse(self._moves(BILL_REF), "a refused bill survived")
        denied = self._audit('corr-bill-over').filtered(
            lambda row: row.decision == Decision.DENIED.value)
        self.assertTrue(denied, "the refusal was not audited")
        self.assertEqual(denied[:1].denial_reason,
                         DenialReason.ACTION_NOT_PERMITTED.value)

    # -- the journal entry -------------------------------------------------

    def test_a_balanced_entry_is_drafted_and_never_posted(self):
        result = self._run(ENTRY, self._entry())
        self.assertTrue(result['ok'], result['problem'])
        entry = self.env['account.move'].browse(result['move_id'])
        self.assertEqual(entry.state, 'draft', "an agent posted an entry")
        self.assertEqual(entry.move_type, 'entry')
        self.assertEqual(len(entry.line_ids), 2)
        self.assertAlmostEqual(result['total_debit'], 300.0)
        self.assertAlmostEqual(result['total_credit'], 300.0)

    def test_an_unbalanced_entry_is_refused_by_name(self):
        result = self._run(ENTRY, self._entry(lines=[
            {'account_code': self.expense.code, 'label': 'x', 'debit_amount': 300.0},
            {'account_code': self.accrual.code, 'label': 'x', 'credit_amount': 250.0},
        ]))
        self.assertFalse(result['ok'])
        self.assertIn('does not balance', result['problem'])
        self.assertFalse(self._moves(ENTRY_REF))

    def test_a_line_with_both_sides_is_refused(self):
        result = self._run(ENTRY, self._entry(lines=[
            {'account_code': self.expense.code, 'label': 'x',
             'debit_amount': 300.0, 'credit_amount': 300.0},
            {'account_code': self.accrual.code, 'label': 'x', 'credit_amount': 300.0},
        ]))
        self.assertFalse(result['ok'])
        self.assertIn('Line 1', result['problem'])

    def test_the_entry_ceiling_is_on_its_debits(self):
        self.draft_action.max_amount = 100.0
        with self.assertRaises(AIAccessDenied):
            self._run(ENTRY, self._entry())
        self.assertFalse(self._moves(ENTRY_REF))

    # -- lookups, and what no tool may do ---------------------------------

    def test_find_accounts_returns_a_code_the_drafts_accept(self):
        result = self._run('accounting.find_accounts',
                           {'search_text': self.expense.code})
        self.assertIn(self.expense.code, [row['code'] for row in result['accounts']])

    def test_find_partners_finds_the_vendor_by_name(self):
        result = self._run('accounting.find_partners',
                           {'search_text': 'Riyadh Landlord'})
        self.assertIn(self.vendor.id, [row['id'] for row in result['partners']])

    def test_no_tool_in_the_pack_posts_or_pays(self):
        source = inspect.getsource(pack)
        for call in ('.action_post(', '._post(', '.action_register_payment('):
            self.assertNotIn(call, source, "a tool in the pack calls %s" % call)
