"""Quality Intelligence. Document B §5.4 and §9.

**The sharp edge.** Quality needs cross-company lot trace to do its job: a recall
must follow product into the branches and out to customers. So it reads customer
*identity* and never customer *value*. It can tell you eleven customers received
an affected lot; it cannot tell you what those shipments were worth. That figure
needs `account.move`, which is outside Quality's scope in every direction — and
the refusal is a selling point, not a limitation. It is the moment a prospect
understands the difference between this and a chatbot with database access.
"""

from odoo.addons.ai_operations.services.enums import AutonomyLevel, ToolCategory
from odoo.addons.ai_operations.services.registry import ai_tool
from odoo.addons.ai_operations.services.schema import (
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
