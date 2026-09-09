"""Procurement Intelligence. Document B §5.1.

**If Odoo can compute it, Odoo computes it and the tool returns the computed
value.** The LLM never recalculates a quantity the ERP already knows. Where a
tool produces a number Odoo did not — a recommended purchase quantity — that
number is presented alongside its deterministic input, never instead of it.
"""

import datetime

from odoo import fields

from odoo.addons.ai_operations.services.enums import AutonomyLevel, ToolCategory
from odoo.addons.ai_operations.services.handoff_service import (
    record_idempotency_key,
)
from odoo.addons.ai_operations.services.registry import ai_tool
from odoo.addons.ai_operations.tools import (
    activity_mixin, product_mixin, production_mixin,
)

from . import schemas
from odoo.addons.ai_operations.services.schema import (
    Bool, Float, Int, Schema, Str,
)


# ======================================================================
# Read
# ======================================================================

@ai_tool(
    code='procurement.find_product',
    category=ToolCategory.READ,
    autonomy=AutonomyLevel.QUERY,
    models=['product.product'],
    input_schema=schemas.FindProductInput,
    output_schema=schemas.FindProductOutput,
    max_results=10,
)
def find_product(ctx, params):
    """Resolve a product code or name to the internal id the other tools need.

    Every other tool here takes a numeric ``product_id``. Call this first: a
    code like "PK-BTL-330" is not an id, and guessing one reaches a record that
    either does not exist or is not yours, which is refused.
    """
    return product_mixin.find_product(ctx, params)


@ai_tool(
    code='procurement.find_production',
    category=ToolCategory.READ,
    autonomy=AutonomyLevel.QUERY,
    models=['mrp.production', 'product.product'],
    input_schema=schemas.FindProductionInput,
    output_schema=schemas.FindProductionOutput,
    max_results=10,
)
def find_production(ctx, params):
    """Resolve a manufacturing order reference to the id the other tools need.

    Call this before any tool that takes a ``production_id``. A reference like
    "RM/MO/00002" is not an id, and reading the digits out of it reaches a
    different order entirely -- which is exactly what happened before this
    existed.
    """
    return production_mixin.find_production(ctx, params)


@ai_tool(
    code='procurement.get_shortage_context',
    category=ToolCategory.READ,
    autonomy=AutonomyLevel.QUERY,
    models=['product.product', 'stock.quant', 'stock.move',
            'stock.warehouse.orderpoint', 'mrp.production'],
    input_schema=schemas.ShortageContextInput,
    output_schema=schemas.ShortageContextOutput,
)
def get_shortage_context(ctx, params):
    """Current stock position for a product: on hand, reserved, available,
    incoming, and the reorder configuration. Use it before recommending any
    purchase quantity; the shortage it returns is the deterministic figure Odoo
    computed, and your recommendation must be shown against it.

    Pass ``production_id`` when the question is about a specific manufacturing
    order. Without it the shortage is measured against the reorder point across
    the company, which is the right answer to "are we below our minimum" and the
    WRONG one to "is this order short": free stock can be zero because every
    unit is reserved by other orders, and a company with no reorder point
    configured reports a shortage of zero no matter how short the order is.
    Recommending a purchase against that figure tells the reader the
    deterministic shortage is nil while ordering thousands, which is exactly the
    contradiction Document B 6.3 exists to prevent.

    ``shortage_basis`` says which of the two was measured, so the figure is
    never presented without its meaning, and the two sets are never returned
    together: given a ``production_id`` this reports the order's numbers and
    nothing else. Returning both made the model read them as a contradiction --
    it raised an activity about "a conflict between the reported shortage and
    the deterministic shortage" instead of drafting the order it was asked for.
    """
    product = ctx.model('product.product').browse(params['product_id'])
    ctx.check_records('product.product', product.ids)

    quants = ctx.model('stock.quant').search([
        ('product_id', '=', product.id),
        ('location_id.usage', '=', 'internal'),
    ])
    on_hand = sum(quants.mapped('quantity'))
    reserved = sum(quants.mapped('reserved_quantity'))

    incoming = sum(ctx.model('stock.move').search([
        ('product_id', '=', product.id),
        ('state', 'not in', ('done', 'cancel')),
        ('location_dest_id.usage', '=', 'internal'),
    ]).mapped('product_uom_qty'))

    orderpoint = ctx.model('stock.warehouse.orderpoint').search(
        [('product_id', '=', product.id)], limit=1)
    minimum = orderpoint.product_min_qty if orderpoint else 0.0
    maximum = orderpoint.product_max_qty if orderpoint else 0.0

    available = on_hand - reserved
    shortage = max(0.0, minimum - (available + incoming))
    basis = 'reorder_point'
    order_required = 0.0
    order_reserved = 0.0

    production_id = params.get('production_id')
    if production_id:
        production = ctx.model('mrp.production').browse(production_id)
        ctx.check_records('mrp.production', production.ids)
        lines = production.move_raw_ids.filtered(
            lambda move: move.product_id.id == product.id
            and move.state not in ('done', 'cancel'))
        order_required = sum(lines.mapped('product_uom_qty'))
        # `quantity` on a move that is not done is what Odoo has managed to
        # reserve for it, which is the half of the figure the reorder point
        # cannot see.
        order_reserved = sum(lines.mapped('quantity'))
        shortage = max(0.0, order_required - order_reserved)
        basis = 'manufacturing_order'

    result = {
        'product_id': product.id,
        'product_name': product.display_name,
        'uom': product.uom_id.name,
        'shortage': shortage,
        'shortage_basis': basis,
    }
    if production_id:
        # Order-scoped: only this order's numbers. Returning the company-wide
        # position alongside them made the model treat the two as contradictory
        # and escalate rather than act -- see the docstring.
        result['order_required'] = order_required
        result['order_reserved'] = order_reserved
        return result
    result.update({
        'on_hand': on_hand,
        'reserved': reserved,
        'available': available,
        'incoming': incoming,
        'reorder_min': minimum,
        'reorder_max': maximum,
    })
    return result


@ai_tool(
    code='procurement.get_open_pos',
    category=ToolCategory.READ,
    autonomy=AutonomyLevel.QUERY,
    models=['purchase.order', 'purchase.order.line', 'res.partner'],
    input_schema=schemas.OpenPosInput,
    output_schema=schemas.OpenPosOutput,
)
def get_open_pos(ctx, params):
    """Open and overdue purchase orders, for a product or a vendor. An overdue
    order is often the real cause of a shortage, so check here before proposing
    a new one.
    """
    domain = [('state', 'in', ('draft', 'sent', 'purchase'))]
    if params.get('partner_id'):
        domain.append(('partner_id', '=', params['partner_id']))
    orders = ctx.model('purchase.order').search(domain, limit=50)
    if params.get('product_id'):
        orders = orders.filtered(
            lambda o: params['product_id'] in o.order_line.mapped('product_id').ids)

    today = datetime.date.today()
    rows, overdue = [], 0
    for order in orders:
        expected = order.date_planned.date() if order.date_planned else None
        days_late = (today - expected).days if expected and expected < today else 0
        if days_late > 0 and order.state == 'purchase':
            overdue += 1
        rows.append({
            'id': order.id,
            'reference': order.name,
            'vendor': order.partner_id.name,
            'state': order.state,
            'expected_date': expected.isoformat() if expected else '',
            'days_late': days_late,
            'quantity': sum(order.order_line.mapped('product_qty')),
        })
    return {'orders': rows, 'overdue_count': overdue}


@ai_tool(
    code='procurement.compare_suppliers',
    category=ToolCategory.READ,
    autonomy=AutonomyLevel.ANALYZE,
    models=['product.product', 'product.supplierinfo', 'res.partner'],
    input_schema=schemas.CompareSuppliersInput,
    output_schema=schemas.CompareSuppliersOutput,
)
def compare_suppliers(ctx, params):
    """Price, lead time and minimum order quantity for every approved vendor of
    a product. Compare them; the trade-off between a cheaper long-lead import
    and a dearer local supplier is a judgement, so show your reasoning.
    """
    product = ctx.model('product.product').browse(params['product_id'])
    ctx.check_records('product.product', product.ids)

    offers = ctx.model('product.supplierinfo').search(
        [('product_tmpl_id', '=', product.product_tmpl_id.id)])
    return {
        'product_id': product.id,
        'offers': [{
            'partner_id': offer.partner_id.id,
            'vendor': offer.partner_id.name,
            'ref': offer.partner_id.ref or '',
            'price': offer.price,
            'lead_days': offer.delay,
            'min_qty': offer.min_qty,
        } for offer in offers],
    }


@ai_tool(
    code='procurement.get_forecast_demand',
    category=ToolCategory.READ,
    autonomy=AutonomyLevel.ANALYZE,
    models=['product.product', 'stock.move'],
    input_schema=schemas.ForecastInput,
    output_schema=schemas.ForecastOutput,
)
def get_forecast_demand(ctx, params):
    """Odoo's own forecast requirement over a horizon.

    This is the deterministic number. If you adjust it — for the Hijri calendar
    drift, say — present both figures separately and label them. Never silently
    replace one with the other.
    """
    product = ctx.model('product.product').browse(params['product_id'])
    ctx.check_records('product.product', product.ids)
    horizon = params.get('horizon_days') or 30
    horizon_end = datetime.date.today() + datetime.timedelta(days=horizon)

    outgoing = ctx.model('stock.move').search([
        ('product_id', '=', product.id),
        ('state', 'not in', ('done', 'cancel')),
        ('location_dest_id.usage', 'in', ('customer', 'production')),
    ])
    demand = sum(
        move.product_uom_qty for move in outgoing
        if not move.date or move.date.date() <= horizon_end)

    return {
        'product_id': product.id,
        'horizon_days': horizon,
        'deterministic_forecast': demand,
        'basis': "Odoo forecasted outgoing moves within the horizon",
    }


@ai_tool(
    code='procurement.get_price_history',
    category=ToolCategory.READ,
    autonomy=AutonomyLevel.ANALYZE,
    models=['product.product', 'purchase.order', 'purchase.order.line'],
    input_schema=schemas.PriceHistoryInput,
    output_schema=schemas.PriceHistoryOutput,
)
def get_price_history(ctx, params):
    """Purchase price movement for a product over a period."""
    product = ctx.model('product.product').browse(params['product_id'])
    ctx.check_records('product.product', product.ids)
    months = params.get('months') or 12
    since = datetime.date.today() - datetime.timedelta(days=months * 31)

    lines = ctx.model('purchase.order.line').search([
        ('product_id', '=', product.id),
        ('order_id.state', 'in', ('purchase', 'done')),
    ], limit=100, order='id desc')

    points = []
    for line in lines:
        ordered = line.order_id.date_order
        if ordered and ordered.date() < since:
            continue
        points.append({
            'date': ordered.date().isoformat() if ordered else '',
            'price': line.price_unit,
            'vendor': line.order_id.partner_id.name,
        })
    return {'product_id': product.id, 'points': points}


# ======================================================================
# Draft write
# ======================================================================

@ai_tool(
    code='procurement.prepare_draft_rfq',
    category=ToolCategory.DRAFT_WRITE,
    autonomy=AutonomyLevel.PREPARE,
    models=['purchase.order', 'purchase.order.line', 'product.product',
            'res.partner'],
    actions=[('purchase.order', 'CREATE_DRAFT')],
    input_schema=schemas.PrepareDraftRfqInput,
    output_schema=schemas.DraftRfqOutput,
    idempotent=True,
    max_results=1,
)
def prepare_draft_rfq(ctx, params):
    """Prepare a draft purchase order for a human to review. It never confirms.

    Pass the deterministic shortage alongside your recommended quantity. Routine
    consolidation above the shortage is legitimate purchasing behaviour, but it
    is bounded: beyond the routine bound the draft is still created and stamped
    for manager approval, and beyond the hard ceiling it is refused outright.
    The same request run twice produces one order: the key is derived from the
    business facts, so replay protection does not depend on you repeating
    anything.
    """
    Purchase = ctx.model('purchase.order')

    product = ctx.model('product.product').browse(params['product_id'])
    partner = ctx.model('res.partner').browse(params['partner_id'])
    ctx.check_records('product.product', product.ids)
    ctx.check_records('res.partner', partner.ids)

    # Document D 13:
    #   {profile_code}:{company_id}:{purpose}:{product_ref}:{location_ref}:{date}
    #
    # Built here, from the business facts, and never taken from the model. The
    # model cannot produce this shape -- it knows neither the company id nor the
    # profile code -- and when it was asked for free text it invented a
    # different value every turn, which is how one request produced two draft
    # orders.
    #
    # The vendor sits in the location slot: for a purchase the counterparty is
    # what scopes the request. The date is the delivery date when one is given,
    # otherwise today, so a replay within the day returns the first order while
    # tomorrow's genuine reorder is its own request.
    #
    # Quantity is deliberately NOT part of the key. The contract does not put it
    # there, and replay protection is about the same intent arriving twice, not
    # about the number matching to the unit.
    key = record_idempotency_key(
        ctx.profile.code,
        ctx.company_ids[0] if ctx.company_ids else 0,
        'draft_rfq',
        product.default_code or product.id,
        partner.id,
        params.get('required_date') or fields.Date.context_today(Purchase),
    )

    existing = Purchase.search([('ai_idempotency_key', '=', key)], limit=1)
    if existing:
        return _render_rfq(existing, idempotent_hit=True)

    deterministic = params['deterministic_shortage']
    recommended = params['recommended_quantity']

    # Steps 16 and 17: the ceiling denies, the routine bound escalates.
    variance, approval_required = ctx.check_variance(
        deterministic, recommended,
        model_name='purchase.order', action_code='CREATE_DRAFT')

    ctx.consume_write()
    order = Purchase.create({
        'partner_id': partner.id,
        'ai_idempotency_key': key,
        'ai_approval_required': approval_required,
        'ai_deterministic_qty': deterministic,
        'ai_variance_pct': variance,
        # No price_unit. purchase.order.line.price_unit is a stored compute
        # (_compute_price_unit_and_date_planned_and_name) that prices the line
        # from the VENDOR via _select_seller, which is the same figure
        # compare_suppliers reports. Passing a value overrides that compute, and
        # what was being passed was product.standard_price -- our AVCO cost, not
        # the vendor's quote, and company-dependent besides, so it read 0.0 for
        # any company it had not been written on. That is how an RFQ came out at
        # 0.00 while the vendor comparison had just said 0.0550.
        #
        # One number, one source. If Odoo cannot price the line, that is a real
        # answer -- no vendor price on file -- and it belongs in front of the
        # human who confirms the order, not papered over with a cost figure.
        'order_line': [(0, 0, {
            'product_id': product.id,
            'product_qty': recommended,
        })],
    })
    return _render_rfq(order, idempotent_hit=False)


def _render_rfq(order, idempotent_hit):
    """Serialised by hand into the declared shape. Never a recordset."""
    return {
        'purchase_order_id': order.id,
        'reference': order.name,
        'vendor': {'id': order.partner_id.id, 'name': order.partner_id.name},
        'required_date': order.date_planned.date().isoformat() if order.date_planned else '',
        'lines': [{
            'product_id': line.product_id.id,
            'product_name': line.product_id.display_name,
            'quantity': line.product_qty,
            'uom': line.product_uom_id.name if 'product_uom_id' in line._fields
                   else line.product_id.uom_id.name,
            'price_unit': line.price_unit,
        } for line in order.order_line],
        'deterministic_shortage': order.ai_deterministic_qty,
        'recommended_quantity': sum(order.order_line.mapped('product_qty')),
        'variance_pct': order.ai_variance_pct,
        'approval_required': order.ai_approval_required,
        'idempotent_hit': idempotent_hit,
    }


# -- Document B §5.1, the four tools this pack never had -------------------

class UpdateDraftInput(Schema):
    order_id = Int(min=1)
    quantity = Float(min=0.0)
    deterministic_shortage = Float(min=0.0)


class UpdateDraftOutput(Schema):
    order_id = Int()
    reference = Str()
    state = Str()
    quantity = Float()
    deterministic_shortage = Float()
    variance_pct = Float()
    approval_required = Bool()


class AcceptHandoffInput(Schema):
    handoff_id = Int(min=1)


class AcceptHandoffOutput(Schema):
    handoff_id = Int()
    reference = Str()
    state = Str()
    handoff_type = Str()
    product_id = Int()
    qty_shortage = Float()


class CompleteHandoffInput(Schema):
    handoff_id = Int(min=1)
    result_ref = Str(max_length=64)


class CompleteHandoffOutput(Schema):
    handoff_id = Int()
    reference = Str()
    state = Str()
    result_ref = Str()


@ai_tool(
    code='procurement.update_draft_rfq',
    category=ToolCategory.DRAFT_WRITE,
    autonomy=AutonomyLevel.PREPARE,
    models=['purchase.order', 'purchase.order.line'],
    input_schema=UpdateDraftInput,
    output_schema=UpdateDraftOutput,
)
def update_draft_rfq(ctx, params):
    """Amend a DRAFT purchase order, within §6.3's bounds.

    ⚠ This is the tool the model permission's `state_restriction` exists for.
    Until it was written nothing amended an existing order, so §4.1's "write:
    draft only" had never been exercised — and it turned out the restriction was
    declared and never read. The guard enforces it now, in `check_records`,
    before this function is reached: a confirmed order is refused with
    STATE_NOT_PERMITTED rather than quietly amended.

    The bound behaves as §6.3 says: above +20% the amendment still happens and
    is stamped for a manager, above +100% it is refused.
    """
    order = ctx.model('purchase.order').browse(params['order_id'])
    # Step 10b denies here if the order has left draft.
    ctx.check_records('purchase.order', order.ids, operation='write')
    ctx.security.check_action(ctx, 'purchase.order', 'UPDATE_DRAFT', records=order)

    variance, approval_required = ctx.security.check_bound(
        ctx, params['deterministic_shortage'], params['quantity'],
        model_name='purchase.order', action_code='UPDATE_DRAFT',
        category_ref=order.order_line[:1].product_id.categ_id.name or None)

    line = order.order_line[:1]
    if line:
        line.product_qty = params['quantity']
    order.ai_approval_required = approval_required
    return {
        'order_id': order.id,
        'reference': order.name,
        'state': order.state,
        'quantity': params['quantity'],
        'deterministic_shortage': params['deterministic_shortage'],
        'variance_pct': variance,
        'approval_required': approval_required,
    }


@ai_tool(
    code='procurement.find_handoff',
    category=ToolCategory.READ,
    autonomy=AutonomyLevel.QUERY,
    models=['ai.operations.handoff'],
    input_schema=schemas.FindHandoffInput,
    output_schema=schemas.FindHandoffOutput,
    max_results=10,
)
def find_handoff(ctx, params):
    """Resolve a handoff reference to the id ``accept_handoff`` needs.

    ``accept_handoff`` and ``complete_handoff`` take a numeric id. A person
    reads "AIH/2026/00027" off a list and types that, because it is what the
    screen shows -- so without this the reference cannot be used at all, and
    the alternatives are both bad: guess an integer out of the digits, which
    lands on somebody else's handoff, or decline. Both happened.

    Only handoffs addressed to the caller's own profile are returned. That is
    not a convenience: the receiver scope is what stops one agent enumerating
    another's queue, and it is the same boundary ``_for_receiver`` enforces on
    accept.
    """
    handoff_ref = params['handoff_ref']
    handoffs = ctx.model('ai.operations.handoff').search([
        ('to_profile_id', '=', ctx.profile.id),
        ('name', '=ilike', handoff_ref),
    ], limit=10)
    ctx.check_records('ai.operations.handoff', handoffs.ids)
    return {
        'handoffs': [{
            'id': handoff.id,
            'reference': handoff.name,
            'type_code': handoff.type_id.code or '',
            'from_profile': handoff.from_profile_id.code or '',
            'state': handoff.state,
            'priority': handoff.priority or '',
        } for handoff in handoffs],
    }


@ai_tool(
    code='procurement.accept_handoff',
    category=ToolCategory.HANDOFF,
    autonomy=AutonomyLevel.PREPARE,
    models=['ai.operations.handoff'],
    input_schema=AcceptHandoffInput,
    output_schema=AcceptHandoffOutput,
)
def accept_handoff(ctx, params):
    """Claim work from this agent's own queue. §6.1.

    ⚠ Accepting tells the agent *what to work on*; it grants nothing. The
    payload's `product_id` is a number, and reading that product still needs the
    profile's own permission — a handoff naming a model Procurement may not read
    leaves it exactly as unable to read it.
    """
    ctx.check_records('ai.operations.handoff', [params['handoff_id']])
    # The service takes an id, not a recordset: it re-resolves the handoff
    # through _for_receiver, which is what refuses work from another agent's
    # queue. Passing the record would skip that.
    accepted = ctx.env['ai.operations.handoff.service'].accept(
        ctx, params['handoff_id'])
    payload = accepted.payload or {}
    return {
        'handoff_id': accepted.id,
        'reference': accepted.name,
        'state': accepted.state,
        'handoff_type': accepted.type_id.code,
        'product_id': int(payload.get('product_id') or 0),
        'qty_shortage': float(payload.get('qty_shortage')
                              or payload.get('qty_suggested') or 0.0),
    }


@ai_tool(
    code='procurement.complete_handoff',
    category=ToolCategory.HANDOFF,
    autonomy=AutonomyLevel.PREPARE,
    models=['ai.operations.handoff'],
    input_schema=CompleteHandoffInput,
    output_schema=CompleteHandoffOutput,
)
def complete_handoff(ctx, params):
    """Close a handoff with the reference of what was produced. §6.4."""
    ctx.check_records('ai.operations.handoff', [params['handoff_id']])
    done = ctx.env['ai.operations.handoff.service'].complete(
        ctx, params['handoff_id'],
        result_model='purchase.order', result_res_id=0)
    return {
        'handoff_id': done.id,
        'reference': done.name,
        'state': done.state,
        'result_ref': params['result_ref'],
    }


@ai_tool(
    code='procurement.create_review_activity',
    category=ToolCategory.DRAFT_WRITE,
    autonomy=AutonomyLevel.PREPARE,
    models=['mail.activity', 'purchase.order'],
    input_schema=activity_mixin.ReviewActivityInput,
    output_schema=activity_mixin.ReviewActivityOutput,
)
def create_review_activity(ctx, params):
    """Put the draft on a human's desk. §7 steps 21 and 22.

    The activity is what makes the cascade end somewhere a person looks. Above
    the routine bound the caller passes `escalate`, and §12 swaps the routine
    reviewer for the escalation user — same type, same content, same dedup key.
    """
    return activity_mixin.create_review_activity(ctx, params, 'purchase.order')
