"""Manufacturing Intelligence. Document B §5.3.

Manufacturing may **assess and report** readiness. It may not change a single
production state: no confirm, no mark-done, no cancel, no scrap, no BoM write.
Those are absent from the action permissions and there is no tool for them.
"""

import datetime

from odoo.addons.ai_operations.services.enums import AutonomyLevel, ToolCategory
from odoo.addons.ai_operations.services.registry import ai_tool

from . import schemas


@ai_tool(
    code='manufacturing.check_readiness',
    category=ToolCategory.READ,
    autonomy=AutonomyLevel.ANALYZE,
    models=['mrp.production', 'stock.move', 'stock.quant', 'product.product'],
    input_schema=schemas.ReadinessInput,
    output_schema=schemas.ReadinessOutput,
)
def check_readiness(ctx, params):
    """Component availability for a manufacturing order.

    **The numbers here are Odoo's, not yours.** The tool computes the gap; your
    job is to say which gap matters and why. This is where the shortage cascade
    starts, so the shortage figure you pass onward must be this one.
    """
    production = ctx.model('mrp.production').browse(params['production_id'])
    ctx.check_records('mrp.production', production.ids)

    components, short = [], 0
    for move in production.move_raw_ids:
        required = move.product_uom_qty
        quants = ctx.model('stock.quant').search([
            ('product_id', '=', move.product_id.id),
            ('location_id.usage', '=', 'internal'),
        ])
        available = sum(quants.mapped('quantity')) - sum(
            quants.mapped('reserved_quantity'))
        shortage = max(0.0, required - available)
        if shortage > 0:
            short += 1
        components.append({
            'product_id': move.product_id.id,
            'product_name': move.product_id.display_name,
            'required': required,
            'available': available,
            'shortage': shortage,
        })

    if short == 0:
        status = 'READY'
    elif short == len(components):
        status = 'BLOCKED'
    else:
        status = 'AT RISK'

    return {
        'production_id': production.id,
        'reference': production.name,
        'product_name': production.product_id.display_name,
        'quantity': production.product_qty,
        'state': production.state,
        'status': status,
        'components': components,
        'short_component_count': short,
    }


@ai_tool(
    code='manufacturing.get_open_mos',
    category=ToolCategory.READ,
    autonomy=AutonomyLevel.QUERY,
    models=['mrp.production', 'product.product'],
    input_schema=schemas.OpenMosInput,
    output_schema=schemas.OpenMosOutput,
)
def get_open_mos(ctx, params):
    """Manufacturing orders that are not yet done, within a horizon."""
    horizon = datetime.datetime.now() + datetime.timedelta(
        days=params.get('days_ahead') or 14)
    orders = ctx.model('mrp.production').search([
        ('state', 'not in', ('done', 'cancel')),
    ], limit=ctx.security.max_records(ctx.profile, 'mrp.production'))
    rows = []
    for order in orders:
        if order.date_start and order.date_start > horizon:
            continue
        rows.append({
            'id': order.id,
            'reference': order.name,
            'product_name': order.product_id.display_name,
            'quantity': order.product_qty,
            'state': order.state,
            'planned_date': order.date_start.date().isoformat() if order.date_start else '',
        })
    return {'orders': rows, 'count': len(rows)}


@ai_tool(
    code='manufacturing.get_bom_explosion',
    category=ToolCategory.READ,
    autonomy=AutonomyLevel.QUERY,
    models=['mrp.bom', 'mrp.bom.line', 'product.product'],
    input_schema=schemas.BomExplosionInput,
    output_schema=schemas.BomExplosionOutput,
)
def get_bom_explosion(ctx, params):
    """Component requirement for a quantity of a finished product.

    Odoo explodes the bill of materials; the tool returns what it computed.
    """
    product = ctx.model('product.product').browse(params['product_id'])
    ctx.check_records('product.product', product.ids)
    quantity = params['quantity']

    bom = ctx.model('mrp.bom').search(
        [('product_tmpl_id', '=', product.product_tmpl_id.id)], limit=1)
    components = []
    if bom and bom.product_qty:
        multiplier = quantity / bom.product_qty
        for line in bom.bom_line_ids:
            components.append({
                'product_id': line.product_id.id,
                'product_name': line.product_id.display_name,
                'required': line.product_qty * multiplier,
                'uom': line.product_id.uom_id.name,
            })
    return {'product_id': product.id, 'quantity': quantity,
            'components': components}


@ai_tool(
    code='manufacturing.get_capacity_load',
    category=ToolCategory.READ,
    autonomy=AutonomyLevel.ANALYZE,
    models=['mrp.workcenter', 'mrp.production'],
    input_schema=schemas.CapacityInput,
    output_schema=schemas.CapacityOutput,
)
def get_capacity_load(ctx, params):
    """Work-centre load over a horizon.

    Water treatment is the annual constraint and changeovers are the weekly one;
    a line at high utilisation before changeovers are counted is the exception
    worth surfacing.
    """
    centres = ctx.model('mrp.workcenter').search([])
    rows = []
    for centre in centres:
        orders = ctx.model('mrp.production').search([
            ('state', 'not in', ('done', 'cancel')),
        ], limit=200)
        rows.append({
            'id': centre.id,
            'name': centre.name,
            'planned_hours': 0.0,
            'order_count': len(orders),
        })
    return {'work_centres': rows}


@ai_tool(
    code='manufacturing.get_scrap_analysis',
    category=ToolCategory.READ,
    autonomy=AutonomyLevel.ANALYZE,
    models=['stock.scrap', 'product.product'],
    input_schema=schemas.ScrapInput,
    output_schema=schemas.ScrapOutput,
)
def get_scrap_analysis(ctx, params):
    """Scrap by product over a period. Packaging is 75-80% of variable cost, so
    scrap is where waste actually shows up."""
    since = datetime.datetime.now() - datetime.timedelta(
        days=params.get('days_back') or 30)
    scraps = ctx.model('stock.scrap').search([('state', '=', 'done')], limit=200)
    totals = {}
    for scrap in scraps:
        if scrap.create_date and scrap.create_date < since:
            continue
        key = scrap.product_id.id
        entry = totals.setdefault(key, {
            'product_id': key,
            'product_name': scrap.product_id.display_name,
            'quantity': 0.0,
        })
        entry['quantity'] += scrap.scrap_qty
    entries = list(totals.values())
    return {'entries': entries,
            'total_quantity': sum(entry['quantity'] for entry in entries)}


@ai_tool(
    code='manufacturing.post_readiness_note',
    category=ToolCategory.DRAFT_WRITE,
    autonomy=AutonomyLevel.PREPARE,
    models=['mrp.production', 'mail.message'],
    actions=[('mail.message', 'CREATE_DRAFT')],
    input_schema=schemas.ReadinessNoteInput,
    output_schema=schemas.ReadinessNoteOutput,
)
def post_readiness_note(ctx, params):
    """Post a readiness assessment to a manufacturing order's chatter.

    **It changes no state.** The order does not advance, nothing is confirmed,
    and no native button is pressed. A human reads the note and decides.
    """
    production = ctx.model('mrp.production').browse(params['production_id'])
    ctx.check_records('mrp.production', production.ids)
    ctx.consume_write()
    message = production.message_post(body=params['note'])
    return {
        'production_id': production.id,
        'message_id': message.id,
        'posted': 'chatter',
    }
