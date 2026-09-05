"""Inventory Intelligence. Document B §5.2.

The only Phase 1 agent spanning both companies, which makes it the sharpest
multi-company test: it may see C2 branch stock and C1 plant stock, and must not
see C1 production cost or C2 selling price. **Quantities cross the company
boundary; values do not** — and no output schema here declares a value.
"""

import datetime

from odoo.addons.ai_operations.services.enums import AutonomyLevel, ToolCategory
from odoo.addons.ai_operations.services.registry import ai_tool
from odoo.addons.ai_operations.services.schema import (
    Float, Int, List, Nested, Schema, Str,
)


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
