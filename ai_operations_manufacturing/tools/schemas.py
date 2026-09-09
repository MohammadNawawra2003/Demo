"""Manufacturing schemas.

Note what is absent: no cost field appears in any output. Document B §4.3
denies the Manufacturing agent all cost fields on ``mrp.production`` and
``stock.move``, and the way that is enforced is by never declaring them.
"""

from odoo.addons.ai_operations.services.schema import (
    Float,
    Int,
    List,
    Nested,
    Schema,
    Str,
)


class FindProductInput(Schema):
    #: Not 'query'. The kernel refuses that name outright, so a parameter the
    #: LLM fills can never be mistaken for a domain or an expression.
    product_ref = Str(max_length=64)


class FindProductOutput(Schema):
    products = List(Nested({
        'id': Int(), 'code': Str(), 'name': Str(), 'uom': Str(),
    }), max_items=10)


class ReadinessInput(Schema):
    production_id = Int(min=1)


class ReadinessOutput(Schema):
    production_id = Int()
    reference = Str()
    product_name = Str()
    quantity = Float()
    state = Str()
    status = Str()                     # READY / AT RISK / BLOCKED
    components = List(Nested({
        'product_id': Int(),
        'product_name': Str(),
        'required': Float(),
        'available': Float(),
        'shortage': Float(),
    }), max_items=50)
    short_component_count = Int()


#: The most orders ``manufacturing.get_open_mos`` may emit.
#:
#: Named, because two numbers have to agree: the query limit and the schema cap.
#: They did not. The query took ``max_records`` (200 by default) and the schema
#: allowed 100, so the moment the plant carried more than a hundred open orders
#: the serialiser refused the tool's own output and the agent could not list
#: manufacturing orders at all. It stayed hidden while the demo database held
#: nineteen.
OPEN_MOS_MAX = 100


class OpenMosInput(Schema):
    days_ahead = Int(min=1, max=365, required=False, default=14)


class OpenMosOutput(Schema):
    orders = List(Nested({
        'id': Int(),
        'reference': Str(),
        'product_name': Str(),
        'quantity': Float(),
        'state': Str(),
        'planned_date': Str(),
    }), max_items=OPEN_MOS_MAX)
    count = Int()


class BomExplosionInput(Schema):
    product_id = Int(min=1)
    quantity = Float(min=0.0)


class BomExplosionOutput(Schema):
    product_id = Int()
    quantity = Float()
    components = List(Nested({
        'product_id': Int(),
        'product_name': Str(),
        'required': Float(),
        'uom': Str(),
    }), max_items=50)


class CapacityInput(Schema):
    days_ahead = Int(min=1, max=180, required=False, default=14)


class CapacityOutput(Schema):
    work_centres = List(Nested({
        'id': Int(),
        'name': Str(),
        'planned_hours': Float(),
        'order_count': Int(),
    }), max_items=20)


class ScrapInput(Schema):
    days_back = Int(min=1, max=365, required=False, default=30)


class ScrapOutput(Schema):
    entries = List(Nested({
        'product_id': Int(),
        'product_name': Str(),
        'quantity': Float(),
    }), max_items=50)
    total_quantity = Float()


class ReadinessNoteInput(Schema):
    production_id = Int(min=1)
    note = Str(max_length=2000)


class ReadinessNoteOutput(Schema):
    production_id = Int()
    message_id = Int()
    posted = Str()
