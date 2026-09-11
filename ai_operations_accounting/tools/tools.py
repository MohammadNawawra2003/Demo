"""Accounting Intelligence. Reports, and drafts -- never posts.

Read-only by the owner's decision of 2026-09-07. On 2026-09-11 the owner asked
for it to record a supplier's bill from a picture and to prepare a journal entry
when one is needed (decision-log DL-010), so it now DRAFTS both, at Level 2
(Prepare) -- the ceiling every operational agent works at.

What it may do: report through four aggregates; look up a vendor and an account
code; prepare a draft vendor bill or a draft journal entry, which a person then
reviews and confirms.

What it may not do, and has no permission or tool for:

* post, confirm or reverse any entry
* validate or register a payment
* change a reconciliation
* change a tax -- a bill line's tax comes from its account, as configured
* change bank data

``account.move.line``, ``account.payment``, ``account.journal``,
``account.tax`` and ``res.partner.bank`` still hold no permission on any
profile. A draft's lines are written through ``account.move``, as the person
who asked, never by reaching into the ledger. ``test_accounting_roster.py``
asserts each prohibition individually; ``test_accounting_drafts.py`` the
drafting itself.
"""

from odoo.addons.ai_operations.services.enums import AutonomyLevel, ToolCategory
from odoo.addons.ai_operations.services.handoff_service import (
    record_idempotency_key,
)
from odoo.addons.ai_operations.services.registry import ai_tool
from odoo.addons.ai_operations.services.schema import (
    Bool, Date, Float, Int, List, Nested, Schema, Str,
)

MAX_ROWS = 50

#: Standard ageing buckets, in days. The last is open-ended.
BUCKETS = ((0, 30), (31, 60), (61, 90), (91, None))


class EmptyInput(Schema):
    pass


class LimitInput(Schema):
    limit = Int(min=1, max=MAX_ROWS, required=False, default=20)


class MonthsInput(Schema):
    months = Int(min=1, max=24, required=False, default=6)


class AgeingOutput(Schema):
    currency = Str()
    buckets = List(Nested({
        'label': Str(),
        'amount': Float(),
        'count': Int(),
    }), max_items=8)
    total = Float()
    total_overdue = Float()


class OpenInvoicesOutput(Schema):
    currency = Str()
    invoices = List(Nested({
        'reference': Str(),
        'partner': Str(),
        'invoice_date': Str(),
        'due_date': Str(),
        'amount_total': Float(),
        'amount_residual': Float(),
        'days_overdue': Int(),
    }), max_items=MAX_ROWS)
    count = Int()
    total_residual = Float()


class RevenueOutput(Schema):
    currency = Str()
    periods = List(Nested({
        'period': Str(),
        'invoiced': Float(),
        'credited': Float(),
        'net': Float(),
    }), max_items=24)
    net_total = Float()


def _today(ctx):
    return ctx.env.cr.now().date()


def _open_moves(ctx, move_type):
    return ctx.model('account.move').search([
        ('move_type', '=', move_type),
        ('state', '=', 'posted'),
        ('payment_state', 'in', ('not_paid', 'partial')),
    ], limit=5000)


def _bucket_label(low, high):
    return '%s+ days' % low if high is None else '%s-%s days' % (low, high)


def _ageing(ctx, move_type):
    today = _today(ctx)
    rows = [{'label': _bucket_label(low, high), 'amount': 0.0, 'count': 0}
            for low, high in BUCKETS]
    total = overdue = 0.0
    for move in _open_moves(ctx, move_type):
        residual = abs(move.amount_residual)
        total += residual
        due = move.invoice_date_due
        age = (today - due).days if due else 0
        if age > 0:
            overdue += residual
        for index, (low, high) in enumerate(BUCKETS):
            if age >= low and (high is None or age <= high):
                rows[index]['amount'] += residual
                rows[index]['count'] += 1
                break
    for row in rows:
        row['amount'] = round(row['amount'], 2)
    return {
        'currency': ctx.env.company.currency_id.name,
        'buckets': rows,
        'total': round(total, 2),
        'total_overdue': round(overdue, 2),
    }


@ai_tool(
    code='accounting.get_receivable_ageing',
    category=ToolCategory.READ,
    autonomy=AutonomyLevel.QUERY,
    models=['account.move'],
    input_schema=EmptyInput,
    output_schema=AgeingOutput,
)
def get_receivable_ageing(ctx, params):
    """Customer money owed, bucketed by how overdue it is. Amounts and counts
    only -- no invoice list and no ledger."""
    return _ageing(ctx, 'out_invoice')


@ai_tool(
    code='accounting.get_payable_ageing',
    category=ToolCategory.READ,
    autonomy=AutonomyLevel.QUERY,
    models=['account.move'],
    input_schema=EmptyInput,
    output_schema=AgeingOutput,
)
def get_payable_ageing(ctx, params):
    """Vendor money owed, bucketed the same way."""
    return _ageing(ctx, 'in_invoice')


@ai_tool(
    code='accounting.get_open_invoices',
    category=ToolCategory.READ,
    autonomy=AutonomyLevel.QUERY,
    models=['account.move', 'res.partner'],
    input_schema=LimitInput,
    output_schema=OpenInvoicesOutput,
)
def get_open_invoices(ctx, params):
    """Unpaid customer invoices, most overdue first. Reporting only: this tool
    cannot register a payment, and there is no permission behind it that
    would let anything else here do so."""
    today = _today(ctx)
    rows = []
    for move in _open_moves(ctx, 'out_invoice'):
        due = move.invoice_date_due
        rows.append({
            'reference': move.name,
            'partner': move.partner_id.display_name or '',
            'invoice_date': str(move.invoice_date or ''),
            'due_date': str(due or ''),
            'amount_total': round(abs(move.amount_total), 2),
            'amount_residual': round(abs(move.amount_residual), 2),
            'days_overdue': max((today - due).days, 0) if due else 0,
        })
    rows.sort(key=lambda row: row['days_overdue'], reverse=True)
    total = round(sum(row['amount_residual'] for row in rows), 2)
    rows = rows[:params.get('limit') or 20]
    return {
        'currency': ctx.env.company.currency_id.name,
        'invoices': rows,
        'count': len(rows),
        'total_residual': total,
    }


@ai_tool(
    code='accounting.get_revenue_by_period',
    category=ToolCategory.READ,
    autonomy=AutonomyLevel.QUERY,
    models=['account.move'],
    input_schema=MonthsInput,
    output_schema=RevenueOutput,
)
def get_revenue_by_period(ctx, params):
    """Invoiced revenue by month, net of credit notes. Computed from posted
    customer invoices; it is a reporting figure, not a statutory one."""
    today = _today(ctx)
    months = params.get('months') or 6
    # First day of the month `months - 1` back, so the current month counts.
    year, month = today.year, today.month - (months - 1)
    while month <= 0:
        month += 12
        year -= 1
    start = today.replace(year=year, month=month, day=1)

    periods = {}
    moves = ctx.model('account.move').search([
        ('move_type', 'in', ('out_invoice', 'out_refund')),
        ('state', '=', 'posted'),
        ('invoice_date', '>=', start),
    ], limit=5000)
    for move in moves:
        if not move.invoice_date:
            continue
        key = move.invoice_date.strftime('%Y-%m')
        row = periods.setdefault(
            key, {'period': key, 'invoiced': 0.0, 'credited': 0.0, 'net': 0.0})
        amount = abs(move.amount_untaxed)
        if move.move_type == 'out_refund':
            row['credited'] += amount
        else:
            row['invoiced'] += amount

    rows = []
    for key in sorted(periods):
        row = periods[key]
        row['net'] = round(row['invoiced'] - row['credited'], 2)
        row['invoiced'] = round(row['invoiced'], 2)
        row['credited'] = round(row['credited'], 2)
        rows.append(row)
    return {
        'currency': ctx.env.company.currency_id.name,
        'periods': rows,
        'net_total': round(sum(row['net'] for row in rows), 2),
    }


# ======================================================================
# Drafting -- owner decision 2026-09-11, DL-010
# ======================================================================

#: Lookups are for choosing a record, not for browsing the books.
MAX_LOOKUP = 20
MAX_LINES = 20

#: The one action both drafting tools perform. The pack's permission for it
#: carries the amount ceiling the operator sets on the agent form.
DRAFT_MODEL, DRAFT_ACTION = 'account.move', 'CREATE_DRAFT'

_UNKNOWN_ACCOUNTS = ('No account with code %s in this company. Call '
                     'accounting.find_accounts and use a code it returns.')


class FindPartnersInput(Schema):
    search_text = Str(max_length=64, description='Part of the name or internal reference.')
    limit = Int(min=1, max=MAX_LOOKUP, required=False, default=10)


class FindPartnersOutput(Schema):
    partners = List(Nested({
        'id': Int(),
        'name': Str(),
        'ref': Str(),
        'is_company': Bool(),
    }), max_items=MAX_LOOKUP)
    count = Int()


class FindAccountsInput(Schema):
    search_text = Str(max_length=64, required=False, default='',
                      description='Start of the code, or part of the name.')
    limit = Int(min=1, max=MAX_LOOKUP, required=False, default=MAX_LOOKUP)


class FindAccountsOutput(Schema):
    accounts = List(Nested({
        'code': Str(),
        'name': Str(),
        'account_type': Str(),
    }), max_items=MAX_LOOKUP)
    count = Int()


class PrepareDraftBillInput(Schema):
    partner_id = Int(min=1, description='Vendor id from accounting.find_partners.')
    bill_reference = Str(max_length=64, description="The vendor's own bill number.")
    bill_date = Date()
    due_date = Date(required=False)
    lines = List(Nested({
        'description': Str(max_length=256),
        'account_code': Str(max_length=32),
        'amount': Float(min=0.01, description='Amount BEFORE tax.'),
    }), max_items=MAX_LINES)


class DraftBillOutput(Schema):
    ok = Bool()
    problem = Str()
    move_id = Int()
    reference = Str()
    vendor = Nested({'id': Int(), 'name': Str()})
    bill_reference = Str()
    bill_date = Str()
    currency = Str()
    amount_untaxed = Float()
    amount_tax = Float()
    amount_total = Float()
    state = Str()
    lines = List(Nested({
        'description': Str(),
        'account_code': Str(),
        'account_name': Str(),
        'amount': Float(),
    }), max_items=MAX_LINES)
    idempotent_hit = Bool()


class PrepareDraftEntryInput(Schema):
    reference = Str(max_length=64, description='What the entry is for.')
    entry_date = Date()
    lines = List(Nested({
        'account_code': Str(max_length=32),
        'label': Str(max_length=256),
        'debit_amount': Float(min=0.0, required=False, default=0.0),
        'credit_amount': Float(min=0.0, required=False, default=0.0),
        'partner_id': Int(min=1, required=False),
    }), max_items=MAX_LINES)


class DraftEntryOutput(Schema):
    ok = Bool()
    problem = Str()
    move_id = Int()
    reference = Str()
    entry_reference = Str()
    entry_date = Str()
    currency = Str()
    total_debit = Float()
    total_credit = Float()
    state = Str()
    lines = List(Nested({
        'label': Str(),
        'account_code': Str(),
        'account_name': Str(),
        'debit_amount': Float(),
        'credit_amount': Float(),
    }), max_items=MAX_LINES)
    idempotent_hit = Bool()


def _company_id(ctx):
    return ctx.company_ids[0] if ctx.company_ids else 0


def _resolve_accounts(ctx, codes):
    """``({code: account}, [unknown codes])`` in the run's company.

    The model names accounts by code, the way a chart is read; an account id is
    not something it should carry between turns.
    """
    wanted = sorted(set(codes))
    found = ctx.model('account.account').search([('code', 'in', wanted)])
    ctx.check_records('account.account', found.ids)
    by_code = {account.code: account for account in found}
    return by_code, [code for code in wanted if code not in by_code]


# A fixable input comes back as ok=False and a sentence, not as an exception.
# Anything a tool raises reaches the model as the neutral denial string, which
# is right for a refusal and useless for "that account code does not exist":
# the model cannot correct what it is not told.

def _empty_bill(problem):
    return {
        'ok': False, 'problem': problem, 'move_id': 0, 'reference': '',
        'vendor': {'id': 0, 'name': ''}, 'bill_reference': '', 'bill_date': '',
        'currency': '', 'amount_untaxed': 0.0, 'amount_tax': 0.0,
        'amount_total': 0.0, 'state': '', 'lines': [], 'idempotent_hit': False,
    }


def _empty_entry(problem):
    return {
        'ok': False, 'problem': problem, 'move_id': 0, 'reference': '',
        'entry_reference': '', 'entry_date': '', 'currency': '',
        'total_debit': 0.0, 'total_credit': 0.0, 'state': '', 'lines': [],
        'idempotent_hit': False,
    }


@ai_tool(
    code='accounting.find_partners',
    category=ToolCategory.READ,
    autonomy=AutonomyLevel.QUERY,
    models=['res.partner'],
    input_schema=FindPartnersInput,
    output_schema=FindPartnersOutput,
    max_results=MAX_LOOKUP,
)
def find_partners(ctx, params):
    """Find a vendor or customer by name or internal reference, to get the id a
    draft needs. It never creates a contact: when the vendor is not found, tell
    the user it has to be created first rather than picking a similar one."""
    query = params['search_text'].strip()
    partners = ctx.model('res.partner').search(
        ['|', ('name', 'ilike', query), ('ref', 'ilike', query)],
        limit=params.get('limit') or 10)
    rows = [{
        'id': partner.id,
        'name': partner.name or '',
        'ref': partner.ref or '',
        'is_company': bool(partner.is_company),
    } for partner in partners]
    return {'partners': rows, 'count': len(rows)}


@ai_tool(
    code='accounting.find_accounts',
    category=ToolCategory.READ,
    autonomy=AutonomyLevel.QUERY,
    models=['account.account'],
    input_schema=FindAccountsInput,
    output_schema=FindAccountsOutput,
    max_results=MAX_LOOKUP,
)
def find_accounts(ctx, params):
    """List chart-of-accounts entries whose code starts with, or whose name
    contains, the search text -- "rent", "expense", "6". Use a returned code on a
    bill or journal line; never invent one."""
    query = (params.get('search_text') or '').strip()
    domain = ['|', ('code', '=like', query + '%'), ('name', 'ilike', query)] \
        if query else []
    accounts = ctx.model('account.account').search(
        domain, limit=params.get('limit') or MAX_LOOKUP)
    rows = [{
        'code': account.code or '',
        'name': account.name or '',
        'account_type': account.account_type or '',
    } for account in accounts]
    return {'accounts': rows, 'count': len(rows)}


@ai_tool(
    code='accounting.prepare_draft_vendor_bill',
    category=ToolCategory.DRAFT_WRITE,
    autonomy=AutonomyLevel.PREPARE,
    models=['account.move', 'res.partner', 'account.account'],
    actions=[(DRAFT_MODEL, DRAFT_ACTION)],
    input_schema=PrepareDraftBillInput,
    output_schema=DraftBillOutput,
    idempotent=True,
    max_results=1,
)
def prepare_draft_vendor_bill(ctx, params):
    """Prepare a DRAFT vendor bill for an accountant to review and confirm. It
    never posts.

    Use it to record a supplier's bill, for example one the user attached as an
    image. Pass the vendor id from accounting.find_partners, the vendor's own
    bill number, the bill date, and one line per charge with its amount BEFORE
    tax and an account code from accounting.find_accounts. Do not pass tax:
    Odoo applies the tax configured on the account. Compare the amount_total
    returned with the document and tell the user if they differ. The same
    vendor, bill number and date return the existing draft, never a second one.
    If ok is false, read problem, correct the input and call again.
    """
    Move = ctx.model('account.move')
    partner = ctx.model('res.partner').browse(params['partner_id'])
    ctx.check_records('res.partner', partner.ids)
    lines = params['lines']

    # AUTHORISE FIRST, THEN LOOK -- procurement.prepare_draft_rfq explains why
    # the replay guard may never be reachable by an unauthorised caller. No
    # amount yet: the ceiling is in company currency, and only the created bill
    # knows its currency and its tax, so it is asked below on Odoo's figure.
    ctx.check_create(DRAFT_MODEL, action_code=DRAFT_ACTION)

    if not lines:
        return _empty_bill('A bill needs at least one line.')
    accounts, unknown = _resolve_accounts(
        ctx, [line['account_code'] for line in lines])
    if unknown:
        return _empty_bill(_UNKNOWN_ACCOUNTS % ', '.join(unknown))

    key = record_idempotency_key(
        ctx.profile.code, _company_id(ctx), 'vendor_bill',
        params['bill_reference'], partner.id, params['bill_date'])
    existing = Move.search([('ai_idempotency_key', '=', key)], limit=1)
    if existing:
        return _render_bill(existing, idempotent_hit=True)

    values = {
        'move_type': 'in_invoice',
        'partner_id': partner.id,
        'ref': params['bill_reference'],
        'invoice_date': params['bill_date'],
        'ai_idempotency_key': key,
        # No tax_ids. Odoo derives a bill line's tax from its account
        # (account.move.line._get_computed_taxes), so the tax is the one the
        # accountant configured -- and account.tax stays outside this pack.
        'invoice_line_ids': [(0, 0, {
            'name': line['description'],
            'account_id': accounts[line['account_code']].id,
            'quantity': 1,
            'price_unit': line['amount'],
        }) for line in lines],
    }
    if params.get('due_date'):
        values['invoice_date_due'] = params['due_date']
    ctx.consume_write()
    bill = Move.create(values)
    # Total with tax, in COMPANY currency: a bill takes its journal's currency,
    # and a USD bill measured in USD would pass a SAR ceiling at a third of its
    # size. Raising here rolls the bill back: every tool runs inside the
    # executor's savepoint (execution.py, step 20).
    ctx.security.check_action(
        ctx, DRAFT_MODEL, DRAFT_ACTION, amount=abs(bill.amount_total_signed))
    return _render_bill(bill, idempotent_hit=False)


def _render_bill(bill, idempotent_hit):
    """Serialised by hand into the declared shape. Never a recordset."""
    return {
        'ok': True,
        'problem': '',
        'move_id': bill.id,
        'reference': bill.display_name,
        'vendor': {'id': bill.partner_id.id, 'name': bill.partner_id.name or ''},
        'bill_reference': bill.ref or '',
        'bill_date': str(bill.invoice_date or ''),
        'currency': bill.currency_id.name,
        'amount_untaxed': round(bill.amount_untaxed, 2),
        'amount_tax': round(bill.amount_tax, 2),
        'amount_total': round(bill.amount_total, 2),
        'state': bill.state,
        'lines': [{
            'description': line.name or '',
            'account_code': line.account_id.code or '',
            'account_name': line.account_id.name or '',
            'amount': round(line.price_subtotal, 2),
        } for line in bill.invoice_line_ids],
        'idempotent_hit': idempotent_hit,
    }


@ai_tool(
    code='accounting.prepare_draft_journal_entry',
    category=ToolCategory.DRAFT_WRITE,
    autonomy=AutonomyLevel.PREPARE,
    models=['account.move', 'res.partner', 'account.account'],
    actions=[(DRAFT_MODEL, DRAFT_ACTION)],
    input_schema=PrepareDraftEntryInput,
    output_schema=DraftEntryOutput,
    idempotent=True,
    max_results=1,
)
def prepare_draft_journal_entry(ctx, params):
    """Prepare a DRAFT journal entry for an accountant to review and confirm. It
    never posts.

    For accruals, reclassifications and other adjustments. Every line takes an
    account code from accounting.find_accounts and either a debit_amount or a
    credit_amount, never both; total debits must equal total credits. For a
    supplier's bill use accounting.prepare_draft_vendor_bill instead, so that
    the tax and the payable are Odoo's. The same reference and date return the
    existing draft. If ok is false, read problem, correct the input and call
    again.
    """
    Move = ctx.model('account.move')
    lines = params['lines']
    debit = round(sum(line.get('debit_amount') or 0.0 for line in lines), 2)
    credit = round(sum(line.get('credit_amount') or 0.0 for line in lines), 2)

    # AUTHORISE FIRST. An entry carries no tax, so its debits are its size.
    ctx.check_create(DRAFT_MODEL, action_code=DRAFT_ACTION, amount=debit)

    problem = _entry_problem(lines, debit, credit)
    if problem:
        return _empty_entry(problem)
    accounts, unknown = _resolve_accounts(
        ctx, [line['account_code'] for line in lines])
    if unknown:
        return _empty_entry(_UNKNOWN_ACCOUNTS % ', '.join(unknown))
    partner_ids = sorted({line['partner_id'] for line in lines
                          if line.get('partner_id')})
    if partner_ids:
        ctx.check_records('res.partner', partner_ids)

    key = record_idempotency_key(
        ctx.profile.code, _company_id(ctx), 'journal_entry',
        params['reference'], 'entry', params['entry_date'])
    existing = Move.search([('ai_idempotency_key', '=', key)], limit=1)
    if existing:
        return _render_entry(existing, idempotent_hit=True)

    ctx.consume_write()
    entry = Move.create({
        'move_type': 'entry',
        'ref': params['reference'],
        'date': params['entry_date'],
        'ai_idempotency_key': key,
        'line_ids': [(0, 0, {
            'name': line['label'],
            'account_id': accounts[line['account_code']].id,
            'debit': line.get('debit_amount') or 0.0,
            'credit': line.get('credit_amount') or 0.0,
            'partner_id': line.get('partner_id') or False,
        }) for line in lines],
    })
    return _render_entry(entry, idempotent_hit=False)


def _entry_problem(lines, debit, credit):
    if len(lines) < 2:
        return 'A journal entry needs at least two lines.'
    for index, line in enumerate(lines, start=1):
        if bool(line.get('debit_amount')) == bool(line.get('credit_amount')):
            return ('Line %d must carry a debit_amount or a credit_amount: '
                    'one of them, not both and not neither.' % index)
    if debit != credit:
        return ('The entry does not balance: debits %.2f, credits %.2f.'
                % (debit, credit))
    return ''


def _render_entry(entry, idempotent_hit):
    """Serialised by hand into the declared shape. Never a recordset."""
    lines = entry.line_ids
    return {
        'ok': True,
        'problem': '',
        'move_id': entry.id,
        'reference': entry.display_name,
        'entry_reference': entry.ref or '',
        'entry_date': str(entry.date or ''),
        'currency': entry.currency_id.name,
        'total_debit': round(sum(lines.mapped('debit')), 2),
        'total_credit': round(sum(lines.mapped('credit')), 2),
        'state': entry.state,
        'lines': [{
            'label': line.name or '',
            'account_code': line.account_id.code or '',
            'account_name': line.account_id.name or '',
            'debit_amount': round(line.debit, 2),
            'credit_amount': round(line.credit, 2),
        } for line in lines],
        'idempotent_hit': idempotent_hit,
    }
