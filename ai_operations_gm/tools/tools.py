"""General Manager Intelligence. Post-freeze owner decision, 2026-09-07.

George asked for an agent for the company president: one that answers questions
across departments instead of making him open four chatbots and stitch the
answers together himself.

The whole pack is READ. There is no write tool, no handoff, no activity, no
draft of anything -- ``max_autonomy_level`` is QUERY and every tool here is
``ToolCategory.READ``. An executive view is exactly where a write capability
would be least noticed and most dangerous, so there isn't one.

Two design rules, both from Document C:

* **Aggregates, not access.** Every tool returns a narrow, capped shape. The
  output schema is the leakage defence (§5.4), so the schema is what to read
  when asking what a General Manager can see. ``get_financial_headlines``
  returns six numbers; there is no per-invoice, per-partner or per-line variant
  of it, deliberately, and no ``account.move.line`` permission behind it.
* **Subtraction only.** ``EFFECTIVE = USER ∩ AGENT ∩ TOOL ∩ ACTION ∩ COMPANY``.
  The profile narrows whoever runs it and can never widen them, so a GM user
  without accounting rights gets nothing from the finance tool even though the
  profile permits the model. Tested, not assumed.
"""

from odoo.addons.ai_operations.services.enums import AutonomyLevel, ToolCategory
from odoo.addons.ai_operations.services.registry import ai_tool
from odoo.addons.ai_operations.services.schema import (
    Float, Int, List, Nested, Schema, Str,
)

#: One cap for every list this pack returns. A General Manager asking "what is
#: wrong today" wants the headline, not four hundred rows, and an unbounded list
#: is how a read tool turns into an export.
MAX_ROWS = 25


class EmptyInput(Schema):
    pass


class LimitInput(Schema):
    limit = Int(min=1, max=MAX_ROWS, required=False, default=10)


class OperationalSummaryOutput(Schema):
    open_sales_orders = Int()
    sales_orders_at_risk = Int()
    open_purchase_orders = Int()
    late_purchase_orders = Int()
    open_manufacturing_orders = Int()
    blocked_manufacturing_orders = Int()
    products_below_reorder = Int()
    open_quality_issues = Int()
    headline = Str()


class StockExceptionsOutput(Schema):
    products = List(Nested({
        'product_name': Str(),
        'on_hand': Float(),
        'reorder_min': Float(),
        'shortfall': Float(),
    }), max_items=MAX_ROWS)
    count = Int()


class BlockedProductionOutput(Schema):
    orders = List(Nested({
        'reference': Str(),
        'product_name': Str(),
        'quantity': Float(),
        'state': Str(),
        'availability': Str(),
        'blocking_component': Str(),
    }), max_items=MAX_ROWS)
    count = Int()


class LateProcurementOutput(Schema):
    orders = List(Nested({
        'reference': Str(),
        'vendor': Str(),
        'state': Str(),
        'expected': Str(),
        'days_late': Int(),
    }), max_items=MAX_ROWS)
    count = Int()


class QualityIssuesOutput(Schema):
    issues = List(Nested({
        'reference': Str(),
        'product_name': Str(),
        'stage': Str(),
    }), max_items=MAX_ROWS)
    count = Int()


class FinancialHeadlinesOutput(Schema):
    """Six numbers. There is no per-invoice or per-partner variant of this."""
    currency = Str()
    receivable_outstanding = Float()
    receivable_overdue = Float()
    receivable_overdue_count = Int()
    payable_outstanding = Float()
    payable_overdue = Float()
    payable_overdue_count = Int()


def _today(ctx):
    return ctx.env.cr.now().date()


def _open_mo_domain():
    return [('state', 'in', ('confirmed', 'progress', 'to_close'))]


# -- the cross-department headline ---------------------------------------


@ai_tool(
    code='gm.get_operational_summary',
    category=ToolCategory.READ,
    autonomy=AutonomyLevel.QUERY,
    models=['sale.order', 'purchase.order', 'mrp.production',
            'stock.warehouse.orderpoint', 'stock.quant', 'quality.alert'],
    input_schema=EmptyInput,
    output_schema=OperationalSummaryOutput,
)
def get_operational_summary(ctx, params):
    """One count per department: what is open, and how much of it is in
    trouble. The starting point for any management question -- use the more
    specific tools to explain a number that looks wrong."""
    today = _today(ctx)

    sale_orders = ctx.model('sale.order').search([('state', '=', 'sale')])
    at_risk = sum(
        1 for order in sale_orders
        if any(line.product_uom_qty > line.qty_delivered
               for line in order.order_line)
        and order.commitment_date and order.commitment_date.date() < today)

    purchase_orders = ctx.model('purchase.order').search(
        [('state', 'in', ('draft', 'sent', 'purchase'))])
    late_pos = sum(
        1 for order in purchase_orders
        if order.date_planned and order.date_planned.date() < today)

    productions = ctx.model('mrp.production').search(_open_mo_domain())
    blocked = sum(1 for mo in productions
                  if mo.reservation_state != 'assigned')

    below = len(_below_reorder_rows(ctx, MAX_ROWS))
    quality_issues = len(_open_quality_rows(ctx, MAX_ROWS))

    return {
        'open_sales_orders': len(sale_orders),
        'sales_orders_at_risk': at_risk,
        'open_purchase_orders': len(purchase_orders),
        'late_purchase_orders': late_pos,
        'open_manufacturing_orders': len(productions),
        'blocked_manufacturing_orders': blocked,
        'products_below_reorder': below,
        'open_quality_issues': quality_issues,
        'headline': _headline(at_risk, blocked, late_pos, below,
                              quality_issues),
    }


def _headline(at_risk, blocked, late_pos, below, quality_issues):
    parts = []
    if blocked:
        parts.append('%s manufacturing order(s) cannot be started' % blocked)
    if at_risk:
        parts.append('%s customer order(s) past their commitment date' % at_risk)
    if late_pos:
        parts.append('%s purchase order(s) late' % late_pos)
    if below:
        parts.append('%s product(s) below reorder point' % below)
    if quality_issues:
        parts.append('%s open quality issue(s)' % quality_issues)
    return '; '.join(parts) or 'No exceptions across the five departments.'


# -- the explanations behind each number ---------------------------------


def _below_reorder_rows(ctx, limit):
    rows = []
    for orderpoint in ctx.model('stock.warehouse.orderpoint').search(
            [], limit=200):
        on_hand = sum(ctx.model('stock.quant').search([
            ('product_id', '=', orderpoint.product_id.id),
            ('location_id.usage', '=', 'internal'),
        ]).mapped('quantity'))
        if on_hand >= orderpoint.product_min_qty:
            continue
        rows.append({
            'product_name': orderpoint.product_id.display_name,
            'on_hand': on_hand,
            'reorder_min': orderpoint.product_min_qty,
            'shortfall': orderpoint.product_min_qty - on_hand,
        })
        if len(rows) >= limit:
            break
    return rows


@ai_tool(
    code='gm.get_stock_exceptions',
    category=ToolCategory.READ,
    autonomy=AutonomyLevel.QUERY,
    models=['stock.warehouse.orderpoint', 'stock.quant', 'product.product'],
    input_schema=LimitInput,
    output_schema=StockExceptionsOutput,
)
def get_stock_exceptions(ctx, params):
    """Products below their required stock level, worst shortfall first.
    Quantities only -- no cost and no selling price."""
    rows = _below_reorder_rows(ctx, params.get('limit') or 10)
    rows.sort(key=lambda row: row['shortfall'], reverse=True)
    return {'products': rows, 'count': len(rows)}


@ai_tool(
    code='gm.get_blocked_production',
    category=ToolCategory.READ,
    autonomy=AutonomyLevel.QUERY,
    models=['mrp.production', 'stock.move', 'product.product'],
    input_schema=LimitInput,
    output_schema=BlockedProductionOutput,
)
def get_blocked_production(ctx, params):
    """Manufacturing orders that cannot start, and the component holding each
    one up. This is the question a General Manager actually asks: not "what is
    blocked" but "blocked on what"."""
    rows = []
    for mo in ctx.model('mrp.production').search(
            _open_mo_domain(), limit=200):
        if mo.reservation_state == 'assigned':
            continue
        short = [move.product_id.display_name for move in mo.move_raw_ids
                 if move.forecast_availability < move.product_uom_qty]
        rows.append({
            'reference': mo.name,
            'product_name': mo.product_id.display_name,
            'quantity': mo.product_qty,
            'state': mo.state,
            'availability': mo.reservation_state or 'none',
            'blocking_component': ', '.join(short[:3]) or 'not determined',
        })
        if len(rows) >= (params.get('limit') or 10):
            break
    return {'orders': rows, 'count': len(rows)}


@ai_tool(
    code='gm.get_late_procurement',
    category=ToolCategory.READ,
    autonomy=AutonomyLevel.QUERY,
    models=['purchase.order', 'res.partner'],
    input_schema=LimitInput,
    output_schema=LateProcurementOutput,
)
def get_late_procurement(ctx, params):
    """Requests for quotation and purchase orders past their expected date,
    latest first. A late RFQ is the one nobody has acted on yet."""
    today = _today(ctx)
    rows = []
    for order in ctx.model('purchase.order').search(
            [('state', 'in', ('draft', 'sent', 'purchase'))], limit=200):
        if not order.date_planned or order.date_planned.date() >= today:
            continue
        rows.append({
            'reference': order.name,
            'vendor': order.partner_id.display_name,
            'state': order.state,
            'expected': str(order.date_planned.date()),
            'days_late': (today - order.date_planned.date()).days,
        })
    rows.sort(key=lambda row: row['days_late'], reverse=True)
    rows = rows[:params.get('limit') or 10]
    return {'orders': rows, 'count': len(rows)}


def _open_quality_rows(ctx, limit):
    rows = []
    for alert in ctx.model('quality.alert').search([], limit=200):
        stage = alert.stage_id
        if getattr(stage, 'done', False):
            continue
        rows.append({
            'reference': alert.display_name,
            'product_name': alert.product_id.display_name or '',
            'stage': stage.display_name or '',
        })
        if len(rows) >= limit:
            break
    return rows


@ai_tool(
    code='gm.get_open_quality_issues',
    category=ToolCategory.READ,
    autonomy=AutonomyLevel.QUERY,
    models=['quality.alert', 'product.product'],
    input_schema=LimitInput,
    output_schema=QualityIssuesOutput,
)
def get_open_quality_issues(ctx, params):
    """Quality alerts not yet in a closing stage."""
    rows = _open_quality_rows(ctx, params.get('limit') or 10)
    return {'issues': rows, 'count': len(rows)}


# -- finance, as six numbers ---------------------------------------------


@ai_tool(
    code='gm.get_financial_headlines',
    category=ToolCategory.READ,
    autonomy=AutonomyLevel.QUERY,
    models=['account.move'],
    input_schema=EmptyInput,
    output_schema=FinancialHeadlinesOutput,
)
def get_financial_headlines(ctx, params):
    """Total receivable and payable outstanding, and how much of each is
    overdue. Totals only: this tool has no per-invoice, per-partner or
    per-journal-line form, and the General Manager holds no permission on
    account.move.line, so there is no path from here to a ledger."""
    today = _today(ctx)
    company = ctx.env.company
    totals = {'out_invoice': [0.0, 0.0, 0], 'in_invoice': [0.0, 0.0, 0]}

    moves = ctx.model('account.move').search([
        ('move_type', 'in', ('out_invoice', 'in_invoice')),
        ('state', '=', 'posted'),
        ('payment_state', 'in', ('not_paid', 'partial')),
    ], limit=5000)
    for move in moves:
        bucket = totals[move.move_type]
        residual = abs(move.amount_residual)
        bucket[0] += residual
        due = move.invoice_date_due
        if due and due < today:
            bucket[1] += residual
            bucket[2] += 1

    receivable, payable = totals['out_invoice'], totals['in_invoice']
    return {
        'currency': company.currency_id.name,
        'receivable_outstanding': round(receivable[0], 2),
        'receivable_overdue': round(receivable[1], 2),
        'receivable_overdue_count': receivable[2],
        'payable_outstanding': round(payable[0], 2),
        'payable_overdue': round(payable[1], 2),
        'payable_overdue_count': payable[2],
    }
