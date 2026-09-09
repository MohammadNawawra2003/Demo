"""Raising a shortage. Document B §6."""

from odoo.addons.ai_operations.services.enums import (
    AutonomyLevel, DenialReason, ToolCategory,
)
from odoo.addons.ai_operations.services.exceptions import AIAccessDenied
from odoo.addons.ai_operations.services.handoff_service import handoff_idempotency_key
from odoo.addons.ai_operations.services.registry import ai_tool
from odoo.addons.ai_operations.services.schema import Bool, Date, Float, Int, Schema, Str

from .tools import check_readiness


class RaiseShortageInput(Schema):
    production_id = Int(min=1)
    product_id = Int(min=1)
    #: Still declared, so the model states what it believes it is escalating and
    #: the tool description keeps telling it to measure first. They are no
    #: longer what gets sent: the payload carries the order's own figures.
    qty_required = Float(min=0.0)
    qty_available = Float(min=0.0)
    qty_shortage = Float(min=0.0)
    #: Optional, and derived from the order when absent. The warehouse of a
    #: shortage is a fact of the manufacturing order, not a choice: requiring it
    #: as input asked the model for a database id it has no way to reach from a
    #: business reference, and manual Test 3 stalled there.
    warehouse_id = Int(min=1, required=False)
    required_date = Date(required=False)


class RaiseShortageOutput(Schema):
    handoff_id = Int()
    reference = Str()
    to_profile = Str()
    qty_shortage = Float()
    idempotent_hit = Bool()


@ai_tool(
    code='manufacturing.raise_handoff',
    category=ToolCategory.HANDOFF,
    autonomy=AutonomyLevel.PREPARE,
    models=['ai.operations.handoff', 'mrp.production', 'product.product'],
    input_schema=RaiseShortageInput,
    output_schema=RaiseShortageOutput,
    idempotent=True,
)
def raise_material_shortage(ctx, params):
    """Put a material shortage on Procurement's queue.

    You are handing over a unit of work, not a conversation: exactly nine
    declared fields cross, and the receiving agent gains no access it did not
    already hold. If Inventory has already raised the same shortage today, this
    returns their item rather than creating a second one.

    The product must be a component of the order you name, and the quantities
    sent are the order's own -- call ``manufacturing.find_product`` to resolve a
    code like "PK-BTL-600" rather than guessing an id.
    """
    production = ctx.model('mrp.production').browse(params['production_id'])
    ctx.check_records('mrp.production', production.ids)
    product = ctx.model('product.product').browse(params['product_id'])
    ctx.check_records('product.product', product.ids)

    # The order decides what is short, not the model. Asked to hand over a 600
    # ml bottle shortage the agent had no way to reach an id for PK-BTL-600, so
    # it passed product_id 1 and quantities it had made up -- and the handoff
    # reached another department naming the wrong product, in the wrong volume,
    # with the wrong code baked into its idempotency key. Every figure below is
    # now read back out of ``check_readiness``, whose own docstring is the rule
    # this enforces: "the shortage figure you pass onward must be this one".
    #
    # Note the contrast with prepare_draft_rfq, which keeps an LLM-supplied
    # shortage ON PURPOSE because it feeds check_variance and DL-008. There the
    # number is a claim to be measured. A handoff has no variance control, so
    # here it is simply replaced.
    readiness = check_readiness(ctx, {'production_id': production.id})
    component = next((line for line in readiness['components']
                      if line['product_id'] == product.id), None)
    if component is None:
        raise AIAccessDenied(
            DenialReason.RECORD_OUT_OF_DOMAIN,
            detail='%s is not a component of %s'
                   % (product.default_code or product.id, production.name),
            model='product.product')

    warehouse_id = params.get('warehouse_id') or (
        production.picking_type_id.warehouse_id.id)
    key = handoff_idempotency_key(
        ctx.company_ids[0] if ctx.company_ids else 0,
        'shortage', product.default_code or product.id,
        warehouse_id,
        params.get('required_date') or 'open')

    before = ctx.env['ai.operations.handoff'].search_count(
        [('idempotency_key', '=', key)])
    handoff = ctx.env['ai.operations.handoff.service'].raise_handoff(
        ctx, 'MATERIAL_SHORTAGE',
        payload={
            'product_id': product.id,
            'qty_required': component['required'],
            'qty_available': component['available'],
            'qty_shortage': component['shortage'],
            'uom_id': product.uom_id.id,
            'required_date': str(params.get('required_date') or ''),
            'origin_ref': production.name,
            'warehouse_id': warehouse_id,
            'priority': '2',
        },
        source_model='mrp.production', source_res_id=production.id,
        idempotency_key=key)
    return {
        'handoff_id': handoff.id,
        'reference': handoff.name,
        'to_profile': handoff.to_profile_id.code,
        'qty_shortage': component['shortage'],
        'idempotent_hit': before > 0,
    }
