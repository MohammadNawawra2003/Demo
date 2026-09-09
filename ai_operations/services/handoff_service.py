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

import logging

from odoo import _, api, models
from odoo.tools.mail import plaintext2html

from .enums import DenialReason, HandoffState, TriggerType
from .exceptions import AIAccessDenied

_logger = logging.getLogger(__name__)


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

        # One hop. A run STARTED by a handoff may not raise another, or two
        # agents can pass the same work back and forth with nobody watching --
        # every hop a provider call, and one bad payload escaping the department
        # that produced it. Checked here because all three raisers
        # (manufacturing, inventory, quality) come through this one function.
        if ctx.trigger == TriggerType.HANDOFF.value:
            raise AIAccessDenied(
                DenialReason.HANDOFF_CASCADE_BLOCKED,
                detail='a run triggered by a handoff may not raise one')

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

        handoff = Handoff.create({
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
        # Only for a row that was actually created. The idempotent branch above
        # returns before this: the dedup search carries no state filter, so a
        # CANCELLED handoff keeps answering its key, and notifying there would
        # put a dead item on someone's desk every time a demo is re-run.
        self._notify_receiver(ctx, handoff)
        return handoff

    def _notify_receiver(self, ctx, handoff):
        """Tell the receiving side, then let its agent open the work.

        A queue nobody is told about is a queue nobody works. Three things
        happen here and each one degrades on its own without taking the raise
        down with it -- the handoff is the deliverable, the notification is not.
        """
        receiver = handoff.to_profile_id
        summary = _('Incoming request from %(department)s: %(reference)s',
                    department=(handoff.from_profile_id.name
                                or _('another department')),
                    reference=handoff.name)
        note = _(
            'Type: %(type)s\nRaised by: %(department)s\nPriority: %(priority)s\n'
            '%(details)s',
            type=handoff.type_id.name or handoff.type_id.code,
            department=handoff.from_profile_id.name or '',
            priority=dict(handoff._fields['priority'].selection or []).get(
                handoff.priority, handoff.priority or ''),
            details=self._payload_lines(handoff))

        # plaintext2html, not the string itself: both message bodies and
        # activity notes are HTML fields, so "\n" is not a line break there and
        # an unescaped value would be markup. The note rendered as one unbroken
        # run until this was fixed. The field's content type decides, never the
        # string.
        handoff.message_post(body=plaintext2html('%s\n%s' % (summary, note)))

        # Reuse, do not rebuild: this service already deduplicates, honours the
        # five-a-day ceiling and FAILS CLOSED on an unresolved assignee with an
        # audited denial. The one thing it cannot know is that the desk belongs
        # to the RECEIVER, not to the agent that raised the work.
        self.env['ai.operations.activity'].create_or_update(
            ctx, 'ai.operations.handoff', handoff.id,
            summary=summary, note=plaintext2html(note),
            reason_code='HANDOFF_RECEIVED',
            assignee=receiver.default_review_user_id,
            routing_profile=receiver)

        self._open_the_work(ctx, handoff)

    def _payload_lines(self, handoff):
        """The payload as something a person can act on.

        The values are the entire point of the note, and they were the one
        thing it did not carry: handing the dict to a lazy ``_()`` rendered it
        as its comma-joined KEY NAMES, so a receiver opening the activity
        learned only which fields exist. Rendered here, before translation.

        Every declared field is shown rather than a chosen few, because the
        payload shape differs per handoff type and a fixed list would go quiet
        the moment a pack declares a new one. ``product_id`` is resolved to a
        code because "product_id: 9" is the reference-is-not-an-id problem
        pointed at a human this time.
        """
        payload = handoff.payload or {}
        if not payload:
            return _('Details: none declared.')
        lines = [_('Details:')]
        for field, value in payload.items():
            if field == 'product_id' and value:
                product = self.env['product.product'].browse(int(value)).exists()
                if product:
                    value = '%s (%s)' % (product.display_name,
                                         product.default_code or value)
            lines.append('  %s: %s' % (field, value if value != '' else '-'))
        return '\n'.join(lines)

    def _open_the_work(self, ctx, handoff):
        """Let the receiving agent read its own new item and prepare a draft.

        Document C 9's autonomous branch, entered by handoff rather than by
        cron. The identity is the receiver's own service user, resolved inside
        ``run()`` -- never the raiser, never an administrator, never ``sudo()``.

        A refusal here is not a failure of the raise. The work is queued and the
        human has been told; an agent that cannot start is exactly the
        fail-closed outcome, and it is already audited by the runtime.
        """
        receiver = handoff.to_profile_id
        try:
            self.env['ai.operations.execution'].run(
                receiver.code, TriggerType.HANDOFF.value,
                entry_prompt=self._entry_prompt(handoff),
                correlation_id=ctx.correlation_id)
        except AIAccessDenied as denial:
            _logger.info(
                "ai_operations: %s did not open %s: %s",
                receiver.code, handoff.name, denial.detail)

    def _entry_prompt(self, handoff):
        """Composed here, from the record -- never by the model.

        Naming the tools and forbidding the rest is not decoration. The same
        step driven by a vague sentence spent thirteen tool calls against a cap
        of eight, and drafted the handoff's quantity instead of the order's.
        """
        return (
            'Handoff %(reference)s of type %(type)s is on your queue, raised by '
            '%(department)s. Payload: %(payload)s.\n'
            'Accept it, prepare a draft purchase order for the shortage it '
            'reports, put the draft on a human desk for approval, then close '
            'the handoff. Use the deterministic figure from the payload; do not '
            'invent quantities. Do not raise a handoff of your own.'
            % {'reference': handoff.name,
               'type': handoff.type_id.code,
               'department': handoff.from_profile_id.code or 'another department',
               'payload': handoff.payload or {}})

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
