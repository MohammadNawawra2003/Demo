"""Creating the human's work. Document B §8 and §12.

Two rules make this survivable in a real inbox, and both are here rather than in
each tool pack:

* **Deduplicate.** A repeated exception updates its existing activity. Without
  it the daily review becomes noise a user learns to ignore.
* **Fail closed on assignment.** If no valid assignee resolves inside the
  effective company scope, the activity is **not created** — no fallback to
  Administrator, to the service user, to the record's creator, or to an
  arbitrary member of a group. An AI task on the wrong desk is worse than no
  task: it is silently absorbed rather than visibly missing.
"""

import logging

from odoo import api, models

from .enums import DenialReason
from .exceptions import AIAccessDenied

_logger = logging.getLogger(__name__)

SEVERITY_INFO = 'INFO'
SEVERITY_ATTENTION = 'ATTENTION'
SEVERITY_CRITICAL = 'CRITICAL'

#: Document B §8. Beyond this the agent consolidates and says so.
MAX_ACTIVITIES_PER_USER_PER_DAY = 5


class AIActivityService(models.AbstractModel):
    _name = 'ai.operations.activity'
    _description = 'AI Operations Activity Service'

    @api.model
    def dedup_key(self, profile_code, model_name, res_id, reason_code):
        return '%s:%s:%s:%s' % (profile_code, model_name, res_id, reason_code)

    @api.model
    def resolve_assignee(self, ctx, escalate=False):
        """Routing is configuration, not permission — and it fails closed.

        *May the agent create this activity at all?* is the model permission, a
        security decision. *Whose desk does it land on?* is these two fields, an
        operational one. Keeping them apart is what stops a routing change from
        becoming a privilege change.
        """
        profile = ctx.profile
        user = (profile.default_escalation_user_id if escalate
                else profile.default_review_user_id)
        if not user or not user.active:
            raise AIAccessDenied(
                DenialReason.ASSIGNEE_UNRESOLVED,
                detail='no %s user configured on %s'
                       % ('escalation' if escalate else 'review', profile.code))
        if profile.company_ids and not (user.company_ids & profile.company_ids):
            raise AIAccessDenied(
                DenialReason.ASSIGNEE_UNRESOLVED,
                detail='%s is outside the effective company scope' % user.login)
        return user

    @api.model
    def _validate_override(self, ctx, user):
        """A pack-supplied assignee faces exactly the checks a configured one
        does. Same reasons, same audit, same fail-closed outcome."""
        if not user or not user.active:
            raise AIAccessDenied(
                DenialReason.ASSIGNEE_UNRESOLVED,
                detail='the override assignee is missing or archived')
        if user.share:
            raise AIAccessDenied(
                DenialReason.ASSIGNEE_UNRESOLVED,
                detail='%s is a portal user' % user.login)
        profile = ctx.profile
        if profile.company_ids and not (user.company_ids & profile.company_ids):
            raise AIAccessDenied(
                DenialReason.ASSIGNEE_UNRESOLVED,
                detail='%s is outside the effective company scope' % user.login)
        return user

    @api.model
    def create_or_update(self, ctx, model_name, res_id, summary, note,
                         reason_code, severity=SEVERITY_ATTENTION,
                         escalate=False, assignee=None):
        """The one path a tool pack uses. Returns the activity, or None when the
        assignee could not be resolved — the run continues without it."""
        Activity = self.env['mail.activity']
        audit = self.env['ai.operations.audit']

        try:
            # An override is checked, not trusted. §12 lets a tool pack name a
            # better assignee from business context and says it "may never widen
            # what the agent is allowed to do" -- and `assignee or resolve(...)`
            # skipped both the active check and the company-scope check for any
            # user a pack passed in. That was the one path by which an AI task
            # could land on an archived user, or outside the effective company
            # scope, with no ASSIGNEE_UNRESOLVED row and no audit.
            user = (self._validate_override(ctx, assignee) if assignee
                    else self.resolve_assignee(ctx, escalate=escalate))
        except AIAccessDenied as denial:
            audit.record_decision(
                ctx.correlation_id, 'DENIED', profile=ctx.profile,
                reason=denial.reason, detail=denial.detail,
                tool_code=ctx.tool_code)
            _logger.warning("ai_operations: activity not created, %s", denial.detail)
            return None

        # Document B 8: CRITICAL goes to the manager. Severity was a parameter
        # that was never read, so the three delivery behaviours the table
        # describes did not exist.
        if severity == SEVERITY_CRITICAL and not escalate:
            escalate = True
            try:
                user = self._validate_override(ctx, assignee) if assignee \
                    else self.resolve_assignee(ctx, escalate=True)
            except AIAccessDenied:
                pass

        key = self.dedup_key(ctx.profile.code, model_name, res_id, reason_code)
        existing = Activity.search([
            ('ai_dedup_key', '=', key),
            ('user_id', '=', user.id),
        ], limit=1)
        if existing:
            existing.write({
                'summary': summary,
                'note': note,
                'ai_severity': severity,
                'ai_occurrence_count': (existing.ai_occurrence_count or 1) + 1,
            })
            return existing

        if self._over_daily_ceiling(ctx, user):
            # Document B 8: "the agent consolidates into one summary activity
            # and says so". Silently dropping the item was half the rule -- a
            # human at the ceiling could not tell the difference between a quiet
            # day and a suppressed one.
            self._say_it_consolidated(ctx, user, summary, model_name, res_id)
            return None

        model = self.env['ir.model']._get(model_name)
        return Activity.create({
            'res_model_id': model.id,
            'res_id': res_id,
            'user_id': user.id,
            'summary': summary,
            'note': note,
            'activity_type_id': self._activity_type(ctx).id,
            'ai_severity': severity,
            'ai_dedup_key': key,
            'ai_profile_code': ctx.profile.code,
            'ai_reason_code': reason_code,
        })

    @api.model
    def _say_it_consolidated(self, ctx, user, summary, model_name, res_id):
        """Fold the suppressed item into the day's consolidation activity."""
        Activity = self.env['mail.activity']
        key = self.dedup_key(ctx.profile.code, 'res.users', user.id,
                             'DAILY_CEILING')
        existing = Activity.search([('ai_dedup_key', '=', key),
                                    ('user_id', '=', user.id)], limit=1)
        line = '\n- %s' % summary
        if existing:
            existing.write({
                'note': (existing.note or '') + line,
                'ai_occurrence_count': (existing.ai_occurrence_count or 1) + 1,
            })
            return existing
        # Attached to the record that triggered it, not to the user: an
        # activity on res.users renders through a notification template that
        # does not survive it, and the consolidation is more use sitting where
        # the work is anyway. The KEY is still per user per agent per day.
        model = self.env['ir.model']._get(model_name)
        return Activity.create({
            'res_model_id': model.id,
            'res_id': res_id,
            'user_id': user.id,
            'summary': '%s: further items today, consolidated'
                       % ctx.profile.code,
            'note': 'The daily activity ceiling was reached, so the rest of '
                    'today is summarised here rather than raised '
                    'individually:' + line,
            'activity_type_id': self._activity_type(ctx).id,
            'ai_dedup_key': key,
            'ai_profile_code': ctx.profile.code,
            'ai_reason_code': 'DAILY_CEILING',
            'ai_severity': SEVERITY_INFO,
        })

    @api.model
    def _over_daily_ceiling(self, ctx, user):
        """Document B §8's volume ceiling, which the specification stated and
        never gave a field, a guard step or a test. Five per user per agent per
        day; beyond that the agent consolidates."""
        from odoo import fields as odoo_fields
        today = odoo_fields.Date.context_today(self)
        count = self.env['mail.activity'].search_count([
            ('user_id', '=', user.id),
            ('ai_profile_code', '=', ctx.profile.code),
            ('create_date', '>=', '%s 00:00:00' % today),
        ])
        return count >= MAX_ACTIVITIES_PER_USER_PER_DAY

    #: Document B 12's table: one type per department, so a human can filter
    #: their inbox by the agent that raised it. A single shared type made every
    #: agent's work look the same in the list.
    ACTIVITY_TYPE_NAMES = {
        'procurement': 'AI Review Required',
        'inventory': 'AI Inventory Exception',
        'manufacturing': 'AI Production Alert',
        'quality': 'AI Quality Alert',
    }

    @api.model
    def _activity_type(self, ctx):
        Type = self.env['mail.activity.type']
        name = self.ACTIVITY_TYPE_NAMES.get(ctx.profile.code, 'AI Review Required')
        existing = Type.search([('name', '=', name),
                                ('ai_generated', '=', True)], limit=1)
        if existing:
            return existing
        # Never create. mail.activity.type is administrator-owned, and the
        # execution identity is a Purchase Officer -- creating one raised
        # "Access Denied by ACLs for operation: create" the moment a real
        # employee ran an agent. Reading needs no elevation, and sudo() is
        # banned outright, so the four types ship as data instead.
        return Type.search([('ai_generated', '=', True)], limit=1)
