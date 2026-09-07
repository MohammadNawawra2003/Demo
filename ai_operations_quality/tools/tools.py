"""Quality Intelligence. Document B §5.4 and §9.

**The sharp edge.** Quality needs cross-company lot trace to do its job: a recall
must follow product into the branches and out to customers. So it reads customer
*identity* and never customer *value*. It can tell you eleven customers received
an affected lot; it cannot tell you what those shipments were worth. That figure
needs `account.move`, which is outside Quality's scope in every direction — and
the refusal is a selling point, not a limitation. It is the moment a prospect
understands the difference between this and a chatbot with database access.
"""

import datetime

from odoo.addons.ai_operations.services.enums import AutonomyLevel, ToolCategory
from odoo.addons.ai_operations.services.handoff_service import (
    handoff_idempotency_key,
)
from odoo.addons.ai_operations.services.registry import ai_tool
from odoo.addons.ai_operations.tools import activity_mixin
from odoo.addons.ai_operations.services.schema import (
    Bool,
    Float,
    Int,
    List,
    Nested,
    Schema,
    Str,
)


class LotInput(Schema):
    lot_name = Str(max_length=64)


class TraceForwardOutput(Schema):
    lot_name = Str()
    product_name = Str()
    finished_lots = List(Nested({
        'lot_id': Int(),
        'lot_name': Str(),
        'product_name': Str(),
        'quantity_produced': Float(),
    }), max_items=100)
    shipments = List(Nested({
        'lot_name': Str(),
        # Identity, never value. There is no amount here and there is no schema
        # field for one.
        'customer': Str(),
        'customer_ref': Str(),
        'quantity': Float(),
    }), max_items=200)
    finished_lot_count = Int()
    customer_count = Int()
    still_on_hand = Float()


class TraceBackwardOutput(Schema):
    lot_name = Str()
    product_name = Str()
    consumed_lots = List(Nested({
        'lot_name': Str(),
        'product_name': Str(),
        'quantity': Float(),
    }), max_items=100)


class LotDispositionOutput(Schema):
    lot_name = Str()
    product_name = Str()
    locations = List(Nested({
        'location': Str(),
        'quantity': Float(),
    }), max_items=100)
    total_on_hand = Float()


def _lot(ctx, name):
    lot = ctx.model('stock.lot').search([('name', '=', name)], limit=1)
    if lot:
        ctx.check_records('stock.lot', lot.ids)
    return lot


@ai_tool(
    code='quality.trace_forward',
    category=ToolCategory.READ,
    autonomy=AutonomyLevel.ANALYZE,
    models=['stock.lot', 'stock.move', 'stock.move.line', 'res.partner',
            'product.product'],
    input_schema=LotInput,
    output_schema=TraceForwardOutput,
)
def trace_forward(ctx, params):
    """Where a batch went: which finished lots consumed it, and which customers
    received those.

    **Deterministic.** Odoo's genealogy computes this by following lot links on
    stock move lines; the tool reports what it found. Summarise the exposure in
    business language and rank by what is still recoverable — but the lots and
    the customers are Odoo's answer, not yours.

    You will not find monetary values here, and you cannot obtain them.
    """
    lot = _lot(ctx, params['lot_name'])
    if not lot:
        return {'lot_name': params['lot_name'], 'product_name': '',
                'finished_lots': [], 'shipments': [],
                'finished_lot_count': 0, 'customer_count': 0, 'still_on_hand': 0.0}

    MoveLine = ctx.model('stock.move.line')

    # 1. Where this batch was consumed: into a production location.
    consumed = MoveLine.search([
        ('lot_id', '=', lot.id),
        ('location_dest_id.usage', '=', 'production'),
    ])
    production_locations = consumed.mapped('location_dest_id')

    # 2. What came out of those production locations: the finished lots.
    produced = MoveLine.search([
        ('location_id', 'in', production_locations.ids),
        ('lot_id', '!=', False),
    ]) if production_locations else MoveLine.browse()
    finished = produced.filtered(lambda line: line.lot_id != lot)

    finished_rows, seen = [], set()
    for line in finished:
        if line.lot_id.id in seen:
            continue
        seen.add(line.lot_id.id)
        finished_rows.append({
            'lot_id': line.lot_id.id,
            'lot_name': line.lot_id.name,
            'product_name': line.product_id.display_name,
            'quantity_produced': line.quantity,
        })

    # 3. Where those finished lots went: out to customers.
    shipments, customers = [], set()
    if seen:
        delivered = MoveLine.search([
            ('lot_id', 'in', list(seen)),
            ('location_dest_id.usage', '=', 'customer'),
        ])
        for line in delivered:
            partner = line.move_id.partner_id
            if partner:
                customers.add(partner.id)
            shipments.append({
                'lot_name': line.lot_id.name,
                'customer': partner.name or '',
                'customer_ref': partner.ref or '',
                'quantity': line.quantity,
            })

    on_hand = sum(ctx.model('stock.quant').search([
        ('lot_id', 'in', list(seen)),
        ('location_id.usage', '=', 'internal'),
    ]).mapped('quantity')) if seen else 0.0

    return {
        'lot_name': lot.name,
        'product_name': lot.product_id.display_name,
        'finished_lots': finished_rows,
        'shipments': shipments,
        'finished_lot_count': len(finished_rows),
        'customer_count': len(customers),
        'still_on_hand': on_hand,
    }


@ai_tool(
    code='quality.trace_backward',
    category=ToolCategory.READ,
    autonomy=AutonomyLevel.ANALYZE,
    models=['stock.lot', 'stock.move', 'stock.move.line', 'product.product'],
    input_schema=LotInput,
    output_schema=TraceBackwardOutput,
)
def trace_backward(ctx, params):
    """What went into a lot, back to the supplier lot it came from.

    **Deterministic**, and the half that makes a recall answerable: a bromate
    exceedance traces forward to customers, and a packaging defect traces
    backward to a named supplier delivery.
    """
    lot = _lot(ctx, params['lot_name'])
    if not lot:
        return {'lot_name': params['lot_name'], 'product_name': '',
                'consumed_lots': []}

    MoveLine = ctx.model('stock.move.line')
    produced = MoveLine.search([
        ('lot_id', '=', lot.id),
        ('location_id.usage', '=', 'production'),
    ])
    production_locations = produced.mapped('location_id')

    consumed = MoveLine.search([
        ('location_dest_id', 'in', production_locations.ids),
        ('lot_id', '!=', False),
    ]) if production_locations else MoveLine.browse()

    rows, seen = [], set()
    for line in consumed.filtered(lambda l: l.lot_id != lot):
        if line.lot_id.id in seen:
            continue
        seen.add(line.lot_id.id)
        rows.append({
            'lot_name': line.lot_id.name,
            'product_name': line.product_id.display_name,
            'quantity': line.quantity,
        })
    return {'lot_name': lot.name,
            'product_name': lot.product_id.display_name,
            'consumed_lots': rows}


@ai_tool(
    code='quality.get_lot_disposition',
    category=ToolCategory.READ,
    autonomy=AutonomyLevel.QUERY,
    models=['stock.lot', 'stock.quant', 'stock.location', 'product.product'],
    input_schema=LotInput,
    output_schema=LotDispositionOutput,
)
def get_lot_disposition(ctx, params):
    """Where a lot's remaining quantity is sitting right now, by location.

    Use it to rank recall exposure: what is still on a shelf is recoverable,
    what has shipped is not.
    """
    lot = _lot(ctx, params['lot_name'])
    if not lot:
        return {'lot_name': params['lot_name'], 'product_name': '',
                'locations': [], 'total_on_hand': 0.0}

    quants = ctx.model('stock.quant').search([
        ('lot_id', '=', lot.id),
        ('location_id.usage', '=', 'internal'),
    ])
    rows = [{'location': quant.location_id.display_name,
             'quantity': quant.quantity} for quant in quants]
    return {'lot_name': lot.name,
            'product_name': lot.product_id.display_name,
            'locations': rows,
            'total_on_hand': sum(quant.quantity for quant in quants)}


# -- Document B §5.4, the five tools this pack never had -------------------

class CheckResultsInput(Schema):
    days_back = Int(min=1, max=365, required=False, default=7)
    limit = Int(min=1, max=200, required=False, default=50)


class CheckResultsOutput(Schema):
    checks = List(Nested({
        'check_id': Int(),
        'point': Str(),
        'product_name': Str(),
        'lot_name': Str(),
        'state': Str(),
        'date': Str(),
    }), max_items=200)
    count = Int()


class OutOfSpecInput(Schema):
    days_back = Int(min=1, max=365, required=False, default=30)


class OutOfSpecOutput(Schema):
    failures = List(Nested({
        'check_id': Int(),
        'point': Str(),
        'product_name': Str(),
        'lot_name': Str(),
        'date': Str(),
    }), max_items=200)
    count = Int()


class ProposeHoldInput(Schema):
    lot_name = Str(max_length=64)
    reason_code = Str(max_length=64)
    severity = Str(max_length=16, required=False, default='CRITICAL')
    note = Str(max_length=4000, required=False, default='')


class ProposeHoldOutput(Schema):
    alert_id = Int()
    reference = Str()
    lot_name = Str()
    state = Str()
    #: Always false. The schema carries it so the model is told, in its own
    #: output, that nothing moved.
    stock_moved = Bool()


class QualityHandoffInput(Schema):
    lot_name = Str(max_length=64)
    reason_code = Str(max_length=64)
    severity = Str(max_length=16, required=False, default='CRITICAL')
    to_manufacturing = Bool(required=False, default=False)


class QualityHandoffOutput(Schema):
    handoff_id = Int()
    reference = Str()
    to_profile = Str()
    handoff_type = Str()
    idempotent_hit = Bool()


@ai_tool(
    code='quality.get_check_results',
    category=ToolCategory.READ,
    autonomy=AutonomyLevel.QUERY,
    models=['quality.check', 'quality.point', 'product.product', 'stock.lot'],
    input_schema=CheckResultsInput,
    output_schema=CheckResultsOutput,
)
def get_check_results(ctx, params):
    """Checks by point, date and status. Result and status only, never a value."""
    since = datetime.datetime.now() - datetime.timedelta(
        days=params.get('days_back') or 7)
    checks = ctx.model('quality.check').search(
        [('create_date', '>=', since)],
        order='create_date desc',
        limit=min(params.get('limit') or 50,
                  ctx.security.max_records(ctx.profile, 'quality.check')))
    return {'checks': [_check_row(check) for check in checks],
            'count': len(checks)}


@ai_tool(
    code='quality.get_out_of_spec',
    category=ToolCategory.READ,
    autonomy=AutonomyLevel.ANALYZE,
    models=['quality.check', 'quality.point', 'product.product', 'stock.lot'],
    input_schema=OutOfSpecInput,
    output_schema=OutOfSpecOutput,
)
def get_out_of_spec(ctx, params):
    """Failed checks in the period. The origin of the recall cascade (§9)."""
    since = datetime.datetime.now() - datetime.timedelta(
        days=params.get('days_back') or 30)
    checks = ctx.model('quality.check').search(
        [('create_date', '>=', since), ('quality_state', '=', 'fail')],
        order='create_date desc',
        limit=ctx.security.max_records(ctx.profile, 'quality.check'))
    return {'failures': [_check_row(check) for check in checks],
            'count': len(checks)}


def _check_row(check):
    lots = check.lot_ids if 'lot_ids' in check._fields else check.browse()
    return {
        'check_id': check.id,
        'point': check.point_id.title or '',
        'product_name': check.product_id.display_name or '',
        'lot_name': lots[:1].name or '' if lots else '',
        'state': check.quality_state or '',
        'date': check.create_date.date().isoformat() if check.create_date else '',
    }


@ai_tool(
    code='quality.propose_hold',
    category=ToolCategory.DRAFT_WRITE,
    autonomy=AutonomyLevel.PREPARE,
    models=['quality.alert', 'stock.lot'],
    input_schema=ProposeHoldInput,
    output_schema=ProposeHoldOutput,
    idempotent=True,
)
def propose_hold(ctx, params):
    """Recommend a hold as a DRAFT quality.alert. §9 step 8, decision 1.

    **It moves no stock.** §4.4 is explicit: the agent proposes and the human
    executes. The alert is created in draft, the model permission carries a
    state restriction of draft, and there is no tool in this pack that can
    change a lot's location.
    """
    lot = ctx.model('stock.lot').search([('name', '=', params['lot_name'])], limit=1)
    if not lot:
        return {'alert_id': 0, 'reference': '', 'lot_name': params['lot_name'],
                'state': '', 'stock_moved': False}
    ctx.check_records('stock.lot', lot.ids)

    Alert = ctx.model('quality.alert')
    title = 'AI: proposed hold on %s (%s)' % (lot.name, params['reason_code'])
    existing = Alert.search([('name', '=', title)], limit=1)
    if existing:
        return {'alert_id': existing.id, 'reference': existing.name,
                'lot_name': lot.name, 'state': existing.stage_id.name or 'draft',
                'stock_moved': False}

    values = {
        'name': title,
        'description': params.get('note') or (
            'Proposed hold. Severity %s. The agent recommends; a human decides '
            'and executes the movement.' % (params.get('severity') or 'CRITICAL')),
    }
    if 'product_id' in Alert._fields and lot.product_id:
        values['product_id'] = lot.product_id.id
    # Explicitly the first stage. The model permission restricts this agent to
    # alerts in `stage_id.name=New`, so leaving the stage to a default would
    # make the write depend on whatever the database happens to order first.
    stage = ctx.env['quality.alert.stage'].search([], order='sequence, id', limit=1) \
        if 'quality.alert.stage' in ctx.env else None
    if stage and 'stage_id' in Alert._fields:
        values['stage_id'] = stage.id
    alert = Alert.create(values)
    # Both checks, deliberately. check_action evaluates the ACTION permission's
    # state restriction; check_records evaluates the MODEL permission's. The
    # second was never invoked for quality.alert, so the draft-only guarantee
    # this docstring advertises was enforced by nothing at all.
    ctx.security.check_action(ctx, 'quality.alert', 'CREATE_DRAFT', records=alert)
    ctx.check_records('quality.alert', alert.ids, operation='create')
    return {
        'alert_id': alert.id,
        'reference': alert.name,
        'lot_name': lot.name,
        'state': alert.stage_id.name or 'draft',
        'stock_moved': False,
    }


@ai_tool(
    code='quality.create_review_activity',
    category=ToolCategory.DRAFT_WRITE,
    autonomy=AutonomyLevel.PREPARE,
    models=['mail.activity', 'stock.lot'],
    input_schema=activity_mixin.ReviewActivityInput,
    output_schema=activity_mixin.ReviewActivityOutput,
)
def create_review_activity(ctx, params):
    """Put a quality decision on a named human's desk. §9 step 13."""
    return activity_mixin.create_review_activity(ctx, params, 'stock.lot')


@ai_tool(
    code='quality.raise_handoff',
    category=ToolCategory.HANDOFF,
    autonomy=AutonomyLevel.PREPARE,
    models=['ai.operations.handoff', 'stock.lot', 'product.product'],
    input_schema=QualityHandoffInput,
    output_schema=QualityHandoffOutput,
    idempotent=True,
)
def raise_quality_hold(ctx, params):
    """Fan a hold out to Inventory or Manufacturing. §9 steps 9 and 10.

    Two types, one tool: `QUALITY_HOLD_IMPACT` tells Inventory where the
    affected stock sits, `QUALITY_HOLD_PRODUCTION` tells Manufacturing which
    orders are consuming it. Neither carries a value, and neither grants the
    receiver anything it did not already hold.
    """
    lot = ctx.model('stock.lot').search([('name', '=', params['lot_name'])], limit=1)
    if not lot:
        return {'handoff_id': 0, 'reference': '', 'to_profile': '',
                'handoff_type': '', 'idempotent_hit': False}
    ctx.check_records('stock.lot', lot.ids)

    to_manufacturing = bool(params.get('to_manufacturing'))
    code = ('QUALITY_HOLD_PRODUCTION' if to_manufacturing
            else 'QUALITY_HOLD_IMPACT')
    key = handoff_idempotency_key(
        ctx.company_ids[0] if ctx.company_ids else 0,
        'hold', lot.name, code, params['reason_code'])

    before = ctx.env['ai.operations.handoff'].search_count(
        [('idempotency_key', '=', key)])
    payload = {
        'lot_ids': lot.ids,
        'product_id': lot.product_id.id,
        'reason_code': params['reason_code'],
        'severity': params.get('severity') or 'CRITICAL',
        'origin_ref': lot.name,
    }
    if to_manufacturing:
        orders = ctx.model('mrp.production').search(
            [('state', 'not in', ('done', 'cancel'))],
            limit=ctx.security.max_records(ctx.profile, 'mrp.production'))
        payload['mo_ids_affected'] = orders.ids[:50]
    else:
        quants = ctx.model('stock.quant').search([('lot_id', '=', lot.id)])
        payload['locations_affected'] = list({
            quant.location_id.display_name for quant in quants})[:50]

    handoff = ctx.env['ai.operations.handoff.service'].raise_handoff(
        ctx, code, payload=payload,
        source_model='stock.lot', source_res_id=lot.id,
        idempotency_key=key)
    return {
        'handoff_id': handoff.id,
        'reference': handoff.name,
        'to_profile': handoff.to_profile_id.code,
        'handoff_type': code,
        'idempotent_hit': before > 0,
    }
