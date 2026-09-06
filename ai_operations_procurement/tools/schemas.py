"""Input and output schemas for the Procurement pack.

Every output schema is an allowlist. ``res.partner`` emits ``id``, ``name`` and
``ref`` and nothing else, so ``bank_ids``, ``vat``, ``credit`` and ``comment``
are not excluded — they are unreachable (Document B §4.1).
"""

from odoo.addons.ai_operations.services.schema import (
    Bool,
    Date,
    Float,
    Int,
    List,
    Nested,
    Schema,
    Str,
)


class ProductRef(Schema):
    product_id = Int(min=1)


class FindProductInput(Schema):
    #: Not 'query'. The kernel refuses that name outright (registry.py
    #: PROHIBITED_PARAM_NAMES) because a parameter the LLM fills must never be
    #: mistakable for a domain, a model name or an expression.
    product_ref = Str(max_length=64)


class FindProductOutput(Schema):
    products = List(Nested({'id': Int(), 'code': Str(), 'name': Str(),
                            'uom': Str()}), max_items=10)


class ShortageContextInput(Schema):
    product_id = Int(min=1)
    warehouse_id = Int(min=1, required=False)


class ShortageContextOutput(Schema):
    product_id = Int()
    product_name = Str()
    uom = Str()
    on_hand = Float()
    reserved = Float()
    available = Float()
    incoming = Float()
    reorder_min = Float()
    reorder_max = Float()
    shortage = Float()


class OpenPosInput(Schema):
    product_id = Int(min=1, required=False)
    partner_id = Int(min=1, required=False)


class OpenPosOutput(Schema):
    orders = List(Nested({
        'id': Int(),
        'reference': Str(),
        'vendor': Str(),
        'state': Str(),
        'expected_date': Str(),
        'days_late': Int(),
        'quantity': Float(),
    }), max_items=50)
    overdue_count = Int()


class CompareSuppliersInput(Schema):
    product_id = Int(min=1)


class CompareSuppliersOutput(Schema):
    product_id = Int()
    offers = List(Nested({
        'partner_id': Int(),
        'vendor': Str(),
        'ref': Str(),
        'price': Float(),
        'lead_days': Int(),
        'min_qty': Float(),
    }), max_items=20)


class ForecastInput(Schema):
    product_id = Int(min=1)
    horizon_days = Int(min=1, max=365, required=False, default=30)


class ForecastOutput(Schema):
    product_id = Int()
    horizon_days = Int()
    deterministic_forecast = Float()
    basis = Str()


class PriceHistoryInput(Schema):
    product_id = Int(min=1)
    months = Int(min=1, max=36, required=False, default=12)


class PriceHistoryOutput(Schema):
    product_id = Int()
    points = List(Nested({'date': Str(), 'price': Float(), 'vendor': Str()}),
                  max_items=100)


class PrepareDraftRfqInput(Schema):
    #: No idempotency_key. Document D §13 fixes the key as
    #: ``{profile_code}:{company_id}:{purpose}:{product_ref}:{location_ref}:{date}``
    #: and the model knows neither the company id nor the profile code, so it
    #: cannot produce one. Asked for free text it invented a different value
    #: every turn, which is how the same request produced two draft orders.
    #: The tool derives the key from the business facts instead.
    product_id = Int(min=1)
    partner_id = Int(min=1)
    recommended_quantity = Float(min=0.0)
    deterministic_shortage = Float(min=0.0)
    required_date = Date(required=False)


class DraftRfqOutput(Schema):
    purchase_order_id = Int()
    reference = Str()
    vendor = Nested({'id': Int(), 'name': Str()})
    required_date = Str(required=False)
    lines = List(Nested({
        'product_id': Int(),
        'product_name': Str(),
        'quantity': Float(),
        'uom': Str(),
        'price_unit': Float(),
    }))
    # Document B §6.3: the deterministic value and the recommendation are
    # separate fields in every schema where AI judgement produces a quantity.
    # The tool may not merge them.
    deterministic_shortage = Float()
    recommended_quantity = Float()
    variance_pct = Float()
    approval_required = Bool()
    idempotent_hit = Bool()
