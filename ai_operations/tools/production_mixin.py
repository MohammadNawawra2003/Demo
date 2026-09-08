"""Resolve a manufacturing order reference to the id the other tools need.

Shared, because two packs need the same resolution and neither should own a
second copy of it -- the same reason ``activity_mixin`` exists.

The gap this closes was found on staging run #3, and it produced three separate
failures that looked unrelated. The runbook names an order the way a person
does, ``RM/MO/00002``. Every tool that takes an order takes a numeric id. With
nothing to convert one to the other the agent did the obvious thing and read the
digits out of the name, passing ``production_id: 2`` -- which is a real order,
``WIP/MO/00001``, finished long ago and short of nothing.

From there: the order-scoped shortage came back as zero, so the draft was
written for the wrong quantity; the components tool was called six times as the
agent tried other ids until it hit its own per-tool cap and the turn rendered as
a refusal; and the agent correctly declined to raise an alert it could not
substantiate, because the data it had been given was about the wrong order.

None of those is a bug in the tool that failed. The fix is to stop making the
model guess, which is what ``find_product`` already does for products.
"""

MAX_MATCHES = 10


def find_production(ctx, params):
    """Match a manufacturing order by reference, or by the product it makes.

    ``=ilike`` on the reference so ``rm/mo/00002`` finds ``RM/MO/00002``:
    references are typed by people and read off screens, and case is not a
    meaningful difference. Done and cancelled orders are included rather than
    filtered -- "why does this finished order show nothing missing" is a fair
    question, and hiding the record would send the agent guessing again, which
    is the whole failure being fixed.
    """
    production_ref = params['production_ref']
    orders = ctx.model('mrp.production').search(
        ['|', ('name', '=ilike', production_ref),
         ('product_id.default_code', '=ilike', production_ref)],
        limit=MAX_MATCHES)
    ctx.check_records('mrp.production', orders.ids)
    return {
        'productions': [{
            'id': order.id,
            'reference': order.name,
            'state': order.state,
            'product_code': order.product_id.default_code or '',
            'product_name': order.product_id.display_name,
            'quantity': order.product_qty,
        } for order in orders],
    }
