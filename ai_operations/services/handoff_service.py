"""Raising and accepting handoffs. Document D 11.

**The idempotency keys are two, not one — review finding B1.**

Document C 13 defines a single format prefixed with the *raising* profile, and
C 5.8 scopes handoff uniqueness to the *receiver* so that two agents spotting
one shortage produce one item of work. Those cannot both be true: prefixed with
the raiser, Manufacturing and Inventory generate different strings and the
unique index never fires, so T-57 and T-94 fail as specified.

One format was doing two jobs with opposite requirements:

* the **record** key (on ``purchase.order.ai_idempotency_key``) needs the
  profile prefix — C 13's own argument is that without it two profiles collide;
* the **handoff** key must not have it, because collision across raisers is the
  desired behaviour.

So there are two builders below, named for what they key.
"""

from odoo import api, models

from .enums import DenialReason, HandoffState
from .exceptions import AIAccessDenied


def record_idempotency_key(profile_code, company_id, purpose, product_ref,
                           location_ref, date):
    """Keys a RECORD an agent creates. Prefixed with the raising profile, so two
    profiles writing the same purpose on the same day do not collide."""
    return ':'.join(str(part) for part in (
        profile_code, company_id, purpose, product_ref, location_ref, date))


def handoff_idempotency_key(company_id, purpose, product_ref, location_ref, date):
    """Keys a UNIT OF WORK on a receiver's queue. Deliberately raiser-agnostic:
    two agents noticing the same shortage must produce the same key so the
    receiver sees one item."""
    return ':'.join(str(part) for part in (
        company_id, purpose, product_ref, location_ref, date))


class AIHandoffService(models.AbstractModel):
    _name = 'ai.operations.handoff.service'
    _description = 'AI Operations Handoff Service'

    @api.model
    def raise_handoff(self, ctx, type_code, payload, source_model=None,
                      source_res_id=None, priority='1', required_date=None,
                      idempotency_key=None):
        """Validate against the type's schema and queue it. Rejects, never filters."""
        HandoffType = self.env['ai.operations.handoff.type']
        Handoff = self.env['ai.operations.handoff']

        handoff_type = HandoffType.search([('code', '=', type_code)], limit=1)
        if not handoff_type:
            raise AIAccessDenied(
                DenialReason.HANDOFF_SCHEMA_VIOLATION,
                detail='unknown handoff type %r' % type_code)

        receiver = handoff_type.to_profile_id
        if idempotency_key:
            existing = Handoff.search([
                ('to_profile_id', '=', receiver.id),
                ('idempotency_key', '=', idempotency_key)], limit=1)
            if existing:
                # B1 in action: the second raise returns the first, audited.
                self.env['ai.operations.audit'].record_idempotent_hit(
                    ctx.correlation_id,
                    detail='handoff already queued for %s' % receiver.code)
                return existing

        return Handoff.create({
            'type_id': handoff_type.id,
            'from_profile_id': ctx.profile.id,
            'to_profile_id': receiver.id,
            'payload': payload,
            'source_model': source_model,
            'source_res_id': source_res_id,
            'priority': priority or handoff_type.priority_default,
            'required_date': required_date,
            'state': HandoffState.REQUESTED.value,
            'correlation_id': ctx.correlation_id,
            'idempotency_key': idempotency_key,
            'company_id': ctx.company_ids[0] if ctx.company_ids else False,
        })

    @api.model
    def accept(self, ctx, handoff_id):
        handoff = self._for_receiver(ctx, handoff_id)
        handoff.state = HandoffState.ACCEPTED.value
        return handoff

    @api.model
    def complete(self, ctx, handoff_id, result_model=None, result_res_id=None):
        handoff = self._for_receiver(ctx, handoff_id)
        handoff.write({
            'state': HandoffState.COMPLETED.value,
            'result_model': result_model,
            'result_res_id': result_res_id,
        })
        return handoff

    @api.model
    def reject(self, ctx, handoff_id, reason):
        handoff = self._for_receiver(ctx, handoff_id)
        handoff.state = HandoffState.REJECTED.value
        return handoff

    def _for_receiver(self, ctx, handoff_id):
        handoff = self.env['ai.operations.handoff'].browse(handoff_id).exists()
        if not handoff or handoff.to_profile_id != ctx.profile:
            raise AIAccessDenied(
                DenialReason.RECORD_OUT_OF_DOMAIN,
                detail='handoff is not on this agent queue',
                model='ai.operations.handoff')
        return handoff
