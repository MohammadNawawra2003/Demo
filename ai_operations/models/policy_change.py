"""Every policy change is a SECURITY audit event. Document C §15, §5.9, §6.3.

Three separate requirements said this and none of them was implemented:

* §15 — "When a permission changes, the version increments and a SECURITY audit
  entry records old and new."
* §5.9 — "every policy configuration change always logged".
* §6.3 — "changing ``provider_code`` is a SECURITY-class audit event and
  increments ``policy_version``."

``policy_version`` was read on every audit row and **never incremented
anywhere**. So a permission could be widened, or the provider — an egress
destination — switched, and every subsequent row would state the *old* version
with no record that anything had changed. Across N client databases drifting
apart that defeats exactly the incident investigation §15 was written for.

The mixin below is applied to the five models that carry policy. It writes the
before/after itself rather than relying on Odoo's own tracking, because the
audit log is append-only and is the only record a security reviewer is asked to
trust.
"""

import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

#: Writing any of these is a policy change. Everything else on these models is
#: presentation.
WATCHED_FIELDS = {
    'ai.operations.agent.profile': (
        'active', 'company_ids', 'service_user_id', 'allow_interactive',
        'allow_autonomous', 'max_autonomy_level', 'max_tool_calls',
        'max_write_ops', 'max_daily_tokens', 'provider_code', 'model_code',
        'default_review_user_id', 'default_escalation_user_id', 'audit_level',
    ),
    'ai.operations.model.permission': (
        'perm_read', 'perm_create', 'perm_write', 'perm_unlink', 'domain',
        'state_restriction', 'max_records', 'allow_read_group',
    ),
    'ai.operations.action.permission': (
        'allowed', 'autonomy_required', 'variance_bound_pct',
        'variance_ceiling_pct', 'max_amount', 'max_quantity',
        'state_restriction', 'risk_level',
    ),
    'ai.operations.tool.assignment': ('enabled', 'max_calls_per_run'),
    'ai.operations.tool': ('enabled', 'max_results'),
}


class AIPolicyAudited(models.AbstractModel):
    """Mixin: audit every policy write and bump the profile's version."""

    _name = 'ai.operations.policy.audited'
    _description = 'AI Operations Policy Change Auditing'

    def write(self, vals):
        watched = WATCHED_FIELDS.get(self._name, ())
        changed = [name for name in vals if name in watched]
        # skip_policy_audit: the version bump is itself a write on the profile,
        # and install_mode covers the data files that BUILD the policy -- a
        # module creating its own pack is not somebody changing one.
        if not changed or self.env.context.get('skip_policy_audit') \
                or self.env.context.get('install_mode'):
            return super().write(vals)

        before = {
            record.id: {name: self._readable(record, name) for name in changed}
            for record in self
        }
        result = super().write(vals)
        for record in self:
            after = {name: self._readable(record, name) for name in changed}
            if after == before.get(record.id):
                continue
            record._record_policy_change(before.get(record.id) or {}, after)
        return result

    @api.model
    def _readable(self, record, name):
        """A comparable, loggable rendering of one field."""
        value = record[name]
        if isinstance(value, models.BaseModel):
            return sorted(value.ids)
        return value

    def _record_policy_change(self, before, after):
        profile = self._policy_profile()
        detail = '; '.join(
            '%s: %r -> %r' % (name, before.get(name), after.get(name))
            for name in sorted(after))
        self.env['ai.operations.audit'].record_policy_change(
            profile=profile, model_name=self._name, res_id=self.id,
            detail=detail)
        # §6.3 and §15: the version moves when the policy behind it moves, so a
        # row stamped 1.0.0 cannot silently describe two different policies.
        if profile and profile.policy_version:
            profile.sudo_free_bump_policy_version()

    def _policy_profile(self):
        """The profile this record's policy belongs to."""
        self.ensure_one()
        if self._name == 'ai.operations.agent.profile':
            return self
        if 'profile_id' in self._fields and self.profile_id:
            return self.profile_id
        return self.env['ai.operations.agent.profile'].browse()
