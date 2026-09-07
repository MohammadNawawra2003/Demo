"""The shared shape of every pack's ``create_review_activity``. Document B §12.

Four packs need the same tool with a different profile behind it, and §12 is
emphatic that the two questions stay apart:

* *May the agent create this activity at all?* — the model permission. Security.
* *Whose desk does it land on?* — the profile's routing. Operations.

So the schema and the body live here once, and each pack registers its own tool
code against them. A pack that wants to name a better assignee from business
context passes one, and it is validated exactly as a configured one is.
"""

from odoo.addons.ai_operations.services.schema import (
    Bool, Int, Schema, Str,
)


class ReviewActivityInput(Schema):
    """What the model may say. Note what is absent: no user id, no model name.

    The LLM never names the assignee. It names the *record* and the *reason*;
    routing is configuration the guard and the profile resolve. That is the
    §12 separation expressed as a schema.
    """
    res_id = Int(min=1)
    summary = Str(max_length=200)
    note = Str(max_length=4000)
    reason_code = Str(max_length=64)
    severity = Str(max_length=16, required=False, default='ATTENTION')
    escalate = Bool(required=False, default=False)


class ReviewActivityOutput(Schema):
    activity_id = Int()
    assignee = Str()
    summary = Str()
    severity = Str()
    escalated = Bool()
    #: True when an existing activity was updated rather than a new one created
    #: -- §8's deduplication, visible to the model so it does not try again.
    deduplicated = Bool()
    #: True when nothing was created: either the assignee did not resolve
    #: (audited ASSIGNEE_UNRESOLVED) or the daily ceiling was reached.
    suppressed = Bool()


def create_review_activity(ctx, params, model_name, assignee=None):
    """Put a decision on a human's desk. §8 and §12.

    Returns ``suppressed`` rather than raising when nothing is created. A
    failure to route is not a failure of the run: §12 says the run continues
    without the activity, and the denial is already audited by the service.
    """
    Activity = ctx.env['ai.operations.activity']
    records = ctx.check_records(model_name, [params['res_id']])
    severity = (params.get('severity') or 'ATTENTION').upper()
    if severity not in ('INFO', 'ATTENTION', 'CRITICAL'):
        severity = 'ATTENTION'

    before = ctx.env['mail.activity'].search_count([
        ('ai_dedup_key', '=', Activity.dedup_key(
            ctx.profile.code, model_name, records.id, params['reason_code']))])

    activity = Activity.create_or_update(
        ctx, model_name, records.id,
        summary=params['summary'],
        note=params['note'],
        reason_code=params['reason_code'],
        severity=severity,
        escalate=bool(params.get('escalate')),
        assignee=assignee,
    )
    if not activity:
        return {
            'activity_id': 0, 'assignee': '', 'summary': params['summary'],
            'severity': severity, 'escalated': bool(params.get('escalate')),
            'deduplicated': False, 'suppressed': True,
        }
    return {
        'activity_id': activity.id,
        'assignee': activity.user_id.login,
        'summary': activity.summary or '',
        'severity': severity,
        'escalated': bool(params.get('escalate')),
        'deduplicated': bool(before),
        'suppressed': False,
    }
