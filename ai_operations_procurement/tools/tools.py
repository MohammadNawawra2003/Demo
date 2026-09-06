"""Procurement Intelligence. Document B §5.1.

**If Odoo can compute it, Odoo computes it and the tool returns the computed
value.** The LLM never recalculates a quantity the ERP already knows. Where a
tool produces a number Odoo did not — a recommended purchase quantity — that
number is presented alongside its deterministic input, never instead of it.
"""

import datetime

from odoo.addons.ai_operations.services.enums import AutonomyLevel, ToolCategory
from odoo.addons.ai_operations.services.registry import ai_tool

from . import schemas


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
    Product = ctx.model('product.product')
    product_ref = params['product_ref']
    products = Product.search(
        ['|', ('default_code', '=ilike', product_ref),
         ('name', 'ilike', product_ref)],
        limit=10)
    ctx.check_records('product.product', products.ids)
    return {
        'products': [{
            'id': product.id,
            'code': product.default_code or '',
            'name': product.display_name,
            'uom': product.uom_id.name or '',
        } for product in products],
    }


@ai_tool(
    code='procurement.get_shortage_context',
    category=ToolCategory.READ,
    autonomy=AutonomyLevel.QUERY,
    models=['product.product', 'stock.quant', 'stock.move',
            'stock.warehouse.orderpoint'],
    input_schema=schemas.ShortageContextInput,
    output_schema=schemas.ShortageContextOutput,
)
def get_shortage_context(ctx, params):
    """Current stock position for a product: on hand, reserved, available,
    incoming, and the reorder configuration. Use it before recommending any
    purchase quantity; the shortage it returns is the deterministic figure Odoo
    computed, and your recommendation must be shown against it.
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

    return {
        'product_id': product.id,
        'product_name': product.display_name,
        'uom': product.uom_id.name,
        'on_hand': on_hand,
        'reserved': reserved,
        'available': available,
        'incoming': incoming,
        'reorder_min': minimum,
        'reorder_max': maximum,
        'shortage': shortage,
    }


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
    An idempotency key is mandatory, so running twice produces one order.
    """
    Purchase = ctx.model('purchase.order')
    key = params['idempotency_key']

    existing = Purchase.search([('ai_idempotency_key', '=', key)], limit=1)
    if existing:
        return _render_rfq(existing, idempotent_hit=True)

    product = ctx.model('product.product').browse(params['product_id'])
    partner = ctx.model('res.partner').browse(params['partner_id'])
    ctx.check_records('product.product', product.ids)
    ctx.check_records('res.partner', partner.ids)

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
