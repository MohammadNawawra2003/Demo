"""Accounting Intelligence, read-only. Post-freeze owner decision, 2026-09-07.

This agent shipped as a roster entry with no tools and no scope, because
Document B §1 put Finance outside Phase 1. George asked for it twice, most
recently after trying the staging demo himself, so it becomes operational --
read-only, and no further.

What it may do: report. Four aggregates, each through a fixed output schema.

What it may not do, and has no permission or tool for:

* post a journal entry
* validate or register a payment
* create, alter or reverse any accounting entry
* change a reconciliation
* change a tax
* change bank data

Those are not omissions to be filled in later by configuration. The profile
holds ``perm_read`` and nothing else on the two models it can see, and
``max_autonomy_level`` is 0 (QUERY), so guard step 15 refuses any action needing
more even if a permission were added by mistake. ``test_accounting_roster.py``
asserts each prohibition individually.

Note the models this pack does NOT permit: ``account.move.line``,
``account.payment``, ``account.journal``, ``account.tax`` and
``res.partner.bank``. A ledger, a payment run and a bank account have no path
into any schema here.
"""

from odoo.addons.ai_operations.services.enums import AutonomyLevel, ToolCategory
from odoo.addons.ai_operations.services.registry import ai_tool
from odoo.addons.ai_operations.services.schema import (
    Float, Int, List, Nested, Schema, Str,
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
