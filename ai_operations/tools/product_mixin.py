"""Resolve a product code or name to the id the other tools need.

Shared for the same reason ``production_mixin`` is: two packs need the same
resolution and neither should own a second copy of it.

``production_mixin``'s own docstring closes with "the fix is to stop making the
model guess, which is what ``find_product`` already does for products" -- and
that was only true of Procurement. Manufacturing held no product resolver at
all, so when an operator asked it to hand a 600 ml bottle shortage to
Procurement, the agent had no way to reach an id for ``PK-BTL-600``. It passed
``product_id: 1``, said so plainly in its reply, and the handoff went to another
department describing the wrong product -- with the wrong product's code then
baked into the idempotency key, because that key is built from
``default_code``.

The guard could not have caught it. A fabricated id is a perfectly readable
record; it is simply the wrong one.
"""

MAX_MATCHES = 10


def find_product(ctx, params):
    """Match a product by internal reference, or by name.

    ``=ilike`` on the code and ``ilike`` on the name, for the same reason
    ``find_production`` does it: references are typed by people and read off
    screens, and case is not a meaningful difference.
    """
    product_ref = params['product_ref']
    products = ctx.model('product.product').search(
        ['|', ('default_code', '=ilike', product_ref),
         ('name', 'ilike', product_ref)],
        limit=MAX_MATCHES)
    ctx.check_records('product.product', products.ids)
    return {
        'products': [{
            'id': product.id,
            'code': product.default_code or '',
            'name': product.display_name,
            'uom': product.uom_id.name or '',
        } for product in products],
    }
