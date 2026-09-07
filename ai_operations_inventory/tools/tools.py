"""Inventory Intelligence. Document B §5.2.

The only Phase 1 agent spanning both companies, which makes it the sharpest
multi-company test: it may see C2 branch stock and C1 plant stock, and must not
see C1 production cost or C2 selling price. **Quantities cross the company
boundary; values do not** — and no output schema here declares a value.
"""

import datetime

from odoo.addons.ai_operations.services.enums import AutonomyLevel, ToolCategory
from odoo.addons.ai_operations.services.registry import ai_tool
from odoo.addons.ai_operations.services.handoff_service import (
    handoff_idempotency_key,
)
from odoo.addons.ai_operations.services.schema import (
    Bool, Date, Float, Int, List, Nested, Schema, Str,
)
from odoo.addons.ai_operations.tools import activity_mixin


class StockPositionInput(Schema):
    product_id = Int(min=1)


class StockPositionOutput(Schema):
    product_id = Int()
    product_name = Str()
    by_location = List(Nested({
        'location': Str(),
        'on_hand': Float(),
        'reserved': Float(),
    }), max_items=100)
    total_on_hand = Float()
    total_reserved = Float()


class BelowReorderInput(Schema):
    limit = Int(min=1, max=200, required=False, default=50)


class BelowReorderOutput(Schema):
    products = List(Nested({
        'product_id': Int(),
        'product_name': Str(),
        'on_hand': Float(),
        'reorder_min': Float(),
        'shortfall': Float(),
    }), max_items=200)
    count = Int()


class ExpiringInput(Schema):
    days = Int(min=1, max=365, required=False, default=90)


class ExpiringOutput(Schema):
    lots = List(Nested({
        'lot_name': Str(),
        'product_name': Str(),
        'expiration_date': Str(),
        'days_remaining': Int(),
        'quantity': Float(),
    }), max_items=200)
    count = Int()


@ai_tool(
    code='inventory.get_stock_position',
    category=ToolCategory.READ,
    autonomy=AutonomyLevel.QUERY,
    models=['product.product', 'stock.quant', 'stock.location'],
    input_schema=StockPositionInput,
    output_schema=StockPositionOutput,
)
def get_stock_position(ctx, params):
    """On hand and reserved for a product, by location, across every warehouse
    in scope. Quantities only: there is no cost or price here."""
    product = ctx.model('product.product').browse(params['product_id'])
    ctx.check_records('product.product', product.ids)
    quants = ctx.model('stock.quant').search([
        ('product_id', '=', product.id),
        ('location_id.usage', '=', 'internal'),
    ])
    rows = [{'location': quant.location_id.display_name,
             'on_hand': quant.quantity,
             'reserved': quant.reserved_quantity} for quant in quants]
    return {
        'product_id': product.id,
        'product_name': product.display_name,
        'by_location': rows,
        'total_on_hand': sum(quant.quantity for quant in quants),
        'total_reserved': sum(quant.reserved_quantity for quant in quants),
    }


@ai_tool(
    code='inventory.get_below_reorder',
    category=ToolCategory.READ,
    autonomy=AutonomyLevel.ANALYZE,
    models=['stock.warehouse.orderpoint', 'stock.quant', 'product.product'],
    input_schema=BelowReorderInput,
    output_schema=BelowReorderOutput,
)
def get_below_reorder(ctx, params):
    """Products sitting below their reorder point. Odoo decides the rule; you
    decide which breach matters today."""
    orderpoints = ctx.model('stock.warehouse.orderpoint').search(
        [], limit=params.get('limit') or 50)
    rows = []
    for orderpoint in orderpoints:
        quants = ctx.model('stock.quant').search([
            ('product_id', '=', orderpoint.product_id.id),
            ('location_id.usage', '=', 'internal')])
        on_hand = sum(quants.mapped('quantity'))
        if on_hand >= orderpoint.product_min_qty:
            continue
        rows.append({
            'product_id': orderpoint.product_id.id,
            'product_name': orderpoint.product_id.display_name,
            'on_hand': on_hand,
            'reorder_min': orderpoint.product_min_qty,
            'shortfall': orderpoint.product_min_qty - on_hand,
        })
    return {'products': rows, 'count': len(rows)}


@ai_tool(
    code='inventory.get_expiring_lots',
    category=ToolCategory.READ,
    autonomy=AutonomyLevel.ANALYZE,
    models=['stock.lot', 'stock.quant', 'product.product'],
    input_schema=ExpiringInput,
    output_schema=ExpiringOutput,
)
def get_expiring_lots(ctx, params):
    """Lots inside the expiry alert window. Shelf life is twelve months and
    removal is FEFO, so a lot close to expiry sitting at a distant branch is
    worth surfacing before it becomes scrap."""
    horizon = datetime.date.today() + datetime.timedelta(days=params.get('days') or 90)
    lots = ctx.model('stock.lot').search([], limit=200)
    rows = []
    for lot in lots:
        expiry = getattr(lot, 'expiration_date', False)
        if not expiry:
            continue
        expiry_date = expiry.date() if hasattr(expiry, 'date') else expiry
        if expiry_date > horizon:
            continue
        quantity = sum(ctx.model('stock.quant').search([
            ('lot_id', '=', lot.id),
            ('location_id.usage', '=', 'internal')]).mapped('quantity'))
        rows.append({
            'lot_name': lot.name,
            'product_name': lot.product_id.display_name,
            'expiration_date': expiry_date.isoformat(),
            'days_remaining': (expiry_date - datetime.date.today()).days,
            'quantity': quantity,
        })
    return {'lots': rows, 'count': len(rows)}


# -- Document B §5.2, the four tools this pack never had -------------------

class ForecastInput(Schema):
    product_id = Int(min=1)
    horizon_days = Int(min=1, max=365, required=False, default=30)


class ForecastOutput(Schema):
    product_id = Int()
    product_name = Str()
    on_hand = Float()
    incoming = Float()
    outgoing = Float()
    forecasted = Float()
    horizon_days = Int()
    basis = Str()


class LateTransfersInput(Schema):
    limit = Int(min=1, max=200, required=False, default=50)


class LateTransfersOutput(Schema):
    transfers = List(Nested({
        'picking_id': Int(),
        'reference': Str(),
        'kind': Str(),
        'scheduled_date': Str(),
        'days_late': Int(),
        'state': Str(),
    }), max_items=200)
    count = Int()


class DiscrepancyInput(Schema):
    limit = Int(min=1, max=200, required=False, default=50)


class DiscrepancyOutput(Schema):
    discrepancies = List(Nested({
        'product_name': Str(),
        'location': Str(),
        'system_quantity': Float(),
        'counted_quantity': Float(),
        'difference': Float(),
    }), max_items=200)
    count = Int()


class ReplenishmentInput(Schema):
    product_id = Int(min=1)
    qty_suggested = Float(min=0.0)
    warehouse_id = Int(min=1, required=False)
    required_date = Date(required=False)
    reason_code = Str(max_length=64, required=False, default='BELOW_REORDER')


class ReplenishmentOutput(Schema):
    handoff_id = Int()
    reference = Str()
    to_profile = Str()
    qty_suggested = Float()
    idempotent_hit = Bool()


@ai_tool(
    code='inventory.get_forecast',
    category=ToolCategory.READ,
    autonomy=AutonomyLevel.ANALYZE,
    models=['product.product', 'stock.quant', 'stock.move'],
    input_schema=ForecastInput,
    output_schema=ForecastOutput,
)
def get_forecast(ctx, params):
    """Odoo's forecasted availability over a horizon.

    **The number is Odoo's.** §16 decision 2 settled this: the deterministic
    forecast is the native figure and any seasonal adjustment is presented
    beside it as a recommendation, never folded into it.
    """
    product = ctx.model('product.product').browse(params['product_id'])
    ctx.check_records('product.product', product.ids)
    horizon = params.get('horizon_days') or 30
    deadline = datetime.datetime.now() + datetime.timedelta(days=horizon)

    quants = ctx.model('stock.quant').search([
        ('product_id', '=', product.id),
        ('location_id.usage', '=', 'internal')])
    on_hand = sum(quants.mapped('quantity'))

    moves = ctx.model('stock.move').search([
        ('product_id', '=', product.id),
        ('state', 'not in', ('done', 'cancel')),
        ('date', '<=', deadline)])
    incoming = sum(m.product_uom_qty for m in moves
                   if m.location_dest_id.usage == 'internal'
                   and m.location_id.usage != 'internal')
    outgoing = sum(m.product_uom_qty for m in moves
                   if m.location_id.usage == 'internal'
                   and m.location_dest_id.usage != 'internal')
    return {
        'product_id': product.id,
        'product_name': product.display_name,
        'on_hand': on_hand,
        'incoming': incoming,
        'outgoing': outgoing,
        'forecasted': on_hand + incoming - outgoing,
        'horizon_days': horizon,
        'basis': "Odoo stock moves not yet done, within %s days" % horizon,
    }


@ai_tool(
    code='inventory.get_late_transfers',
    category=ToolCategory.READ,
    autonomy=AutonomyLevel.QUERY,
    models=['stock.picking'],
    input_schema=LateTransfersInput,
    output_schema=LateTransfersOutput,
)
def get_late_transfers(ctx, params):
    """Receipts and deliveries past their scheduled date. §8's 06:00 review."""
    now = datetime.datetime.now()
    pickings = ctx.model('stock.picking').search(
        [('state', 'not in', ('done', 'cancel')),
         ('scheduled_date', '<', now)],
        order='scheduled_date asc',
        limit=min(params.get('limit') or 50,
                  ctx.security.max_records(ctx.profile, 'stock.picking')))
    rows = []
    for picking in pickings:
        rows.append({
            'picking_id': picking.id,
            'reference': picking.name,
            'kind': picking.picking_type_id.code or '',
            'scheduled_date': picking.scheduled_date.date().isoformat()
                              if picking.scheduled_date else '',
            'days_late': (now - picking.scheduled_date).days
                         if picking.scheduled_date else 0,
            'state': picking.state,
        })
    return {'transfers': rows, 'count': len(rows)}


@ai_tool(
    code='inventory.get_stock_discrepancies',
    category=ToolCategory.READ,
    autonomy=AutonomyLevel.ANALYZE,
    models=['stock.quant', 'product.product', 'stock.location'],
    input_schema=DiscrepancyInput,
    output_schema=DiscrepancyOutput,
)
def get_stock_discrepancies(ctx, params):
    """Counted against system, where the two disagree.

    The gap is Odoo's own: `inventory_quantity` is what somebody counted and
    `quantity` is what the system believes. This reports the difference and
    explains nothing away.
    """
    quants = ctx.model('stock.quant').search(
        [('inventory_quantity_set', '=', True),
         ('location_id.usage', '=', 'internal')],
        limit=min(params.get('limit') or 50,
                  ctx.security.max_records(ctx.profile, 'stock.quant')))
    rows = []
    for quant in quants:
        difference = quant.inventory_quantity - quant.quantity
        if not difference:
            continue
        rows.append({
            'product_name': quant.product_id.display_name,
            'location': quant.location_id.display_name,
            'system_quantity': quant.quantity,
            'counted_quantity': quant.inventory_quantity,
            'difference': difference,
        })
    return {'discrepancies': rows, 'count': len(rows)}


@ai_tool(
    code='inventory.create_review_activity',
    category=ToolCategory.DRAFT_WRITE,
    autonomy=AutonomyLevel.PREPARE,
    models=['mail.activity', 'product.product'],
    input_schema=activity_mixin.ReviewActivityInput,
    output_schema=activity_mixin.ReviewActivityOutput,
)
def create_review_activity(ctx, params):
    """Put an inventory exception on a named human's desk. §12."""
    return activity_mixin.create_review_activity(ctx, params, 'product.product')


@ai_tool(
    code='inventory.raise_handoff',
    category=ToolCategory.HANDOFF,
    autonomy=AutonomyLevel.PREPARE,
    models=['ai.operations.handoff', 'product.product', 'stock.warehouse'],
    input_schema=ReplenishmentInput,
    output_schema=ReplenishmentOutput,
    idempotent=True,
)
def raise_replenishment_request(ctx, params):
    """Put a replenishment on Procurement's queue. §6.2.

    ⚠ The key is deliberately the same shape Manufacturing uses for a shortage
    on the same product, warehouse and date. §6.5: Inventory and Manufacturing
    can both notice one shortage on one morning and they raise *different
    types*, so uniqueness is scoped to the RECEIVER — Procurement sees one item
    of work however many agents noticed it.
    """
    product = ctx.model('product.product').browse(params['product_id'])
    ctx.check_records('product.product', product.ids)
    warehouse_id = params.get('warehouse_id') or 0
    if warehouse_id:
        ctx.check_records('stock.warehouse', [warehouse_id])
    key = handoff_idempotency_key(
        ctx.company_ids[0] if ctx.company_ids else 0,
        'shortage', product.default_code or product.id,
        warehouse_id,
        params.get('required_date') or 'open')

    before = ctx.env['ai.operations.handoff'].search_count(
        [('idempotency_key', '=', key)])
    handoff = ctx.env['ai.operations.handoff.service'].raise_handoff(
        ctx, 'REPLENISHMENT_REQUEST',
        payload={
            'product_id': product.id,
            'qty_suggested': params['qty_suggested'],
            'uom_id': product.uom_id.id,
            'warehouse_id': warehouse_id,
            'required_date': str(params.get('required_date') or ''),
            'reason_code': params.get('reason_code') or 'BELOW_REORDER',
            'priority': '2',
        },
        source_model='product.product', source_res_id=product.id,
        idempotency_key=key)
    return {
        'handoff_id': handoff.id,
        'reference': handoff.name,
        'to_profile': handoff.to_profile_id.code,
        'qty_suggested': params['qty_suggested'],
        'idempotent_hit': before > 0,
    }
