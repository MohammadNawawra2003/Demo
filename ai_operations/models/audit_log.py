from odoo import api, fields, models
from odoo.exceptions import AccessError

from ..services.enums import (
    AuditEvent,
    AuditLevel,
    Decision,
    DenialReason,
    ExecutionMode,
    RetentionClass,
    TriggerType,
    to_selection,
)


class AIOperationsAuditLog(models.Model):
    """The security log. One model, and it is APPEND-ONLY.

    Document C 5.9 keeps execution audit and policy decisions in one model,
    separated by ``decision`` plus an index, because two models means two places
    to look during an incident and two schemas to keep aligned.

    **Append-only is a deviation, and it is the answer to review finding B3.**
    Document D 11 has the row opened before the guard and then updated five
    times. The executing identity is an ordinary employee in CHAT mode, and
    ``sudo()`` is banned -- so "update" would mean granting every user of the
    platform write access to the log recording their own denials. Instead each
    event appends its own row and a call is reconstructed by ``correlation_id``
    and ``sequence``. Nothing can rewrite history, and no ``sudo()`` carve-out
    is needed.
    """

    _name = 'ai.operations.audit.log'
    _description = 'AI Operations Audit Log'
    _order = 'id desc'

    # -- identity of the call ------------------------------------------
    event_type = fields.Selection(
        to_selection(AuditEvent), required=True, index=True,
        default=AuditEvent.OPEN.value)
    sequence = fields.Integer(default=0, help="Order of events within one call.")
    correlation_id = fields.Char(required=True, index=True)
    session_id = fields.Char(index=True)

    profile_id = fields.Many2one(
        'ai.operations.agent.profile', index=True, ondelete='set null')
    profile_code = fields.Char(help="Denormalised; survives profile deletion.")
    user_id = fields.Many2one(
        'res.users', string='Interactive User', index=True, ondelete='set null')
    service_user_id = fields.Many2one(
        'res.users', string='Autonomous Identity', ondelete='set null')
    execution_mode = fields.Selection(to_selection(ExecutionMode))
    trigger = fields.Selection(to_selection(TriggerType))

    tool_id = fields.Many2one('ai.operations.tool', index=True, ondelete='set null')
    tool_code = fields.Char(index=True, help="Denormalised; survives tool deletion.")

    # -- the decision ---------------------------------------------------
    decision = fields.Selection(to_selection(Decision), index=True)
    denial_reason = fields.Selection(to_selection(DenialReason))
    denial_detail = fields.Text()

    # -- what was touched ------------------------------------------------
    models_accessed = fields.Char()
    records_accessed = fields.Text(help="Capped at 200 ids, then summarised.")
    action_code = fields.Char()
    input_args = fields.Json(help="Redacted.")
    output_summary = fields.Text()
    values_before = fields.Json()
    values_after = fields.Json()

    # -- bounds, idempotency, budget --------------------------------------
    approval_required = fields.Boolean(
        help="A recommendation exceeded the routine bound and was escalated.")
    variance_pct = fields.Float(help="Recorded whenever a bound was evaluated.")
    idempotent_hit = fields.Boolean()

    # -- provenance --------------------------------------------------------
    provider_code = fields.Char(
        help="Denormalised so an incident can state which vendor saw the data, "
             "even after the profile is reconfigured.")
    model_code = fields.Char()
    policy_version = fields.Char()
    company_id = fields.Many2one('res.company', ondelete='set null')
    handoff_id = fields.Integer()

    duration_ms = fields.Integer()
    token_input = fields.Integer()
    token_output = fields.Integer()
    error = fields.Text()

    retention_class = fields.Selection(
        to_selection(RetentionClass), compute='_compute_retention_class',
        store=True, index=True)

    @api.depends('decision', 'event_type', 'approval_required')
    def _compute_retention_class(self):
        """Retention is a property of the EVENT, not of the profile.

        Version 0.1 keyed it on ``audit_level``, a profile setting -- so a denial
        written under a STANDARD profile would have been discarded at 24 months.
        """
        for row in self:
            is_security = (
                row.decision == Decision.DENIED.value
                or row.event_type in (AuditEvent.WRITE.value, AuditEvent.ERROR.value)
                or row.approval_required
            )
            row.retention_class = (
                RetentionClass.SECURITY.value if is_security
                else RetentionClass.OPERATIONAL.value
            )

    # ------------------------------------------------------------------
    # Append-only, enforced in code as well as by the ACLs.
    # ------------------------------------------------------------------

    def write(self, vals):
        raise AccessError(
            "The AI audit log is append-only. A security log that can be edited "
            "by the identity it records is not a security log."
        )

    def unlink(self):
        raise AccessError("The AI audit log is append-only; rows are never deleted.")

    @api.model
    def verbosity_fields(self):
        """Fields that ``audit_level`` may blank. It never suppresses a row."""
        return ('input_args', 'records_accessed', 'output_summary')

    @api.model
    def apply_verbosity(self, profile, values):
        """Blank the verbosity fields on an ALLOWED read, per the profile's level.

        The row itself is always written: the per-run counters that enforce
        ``max_tool_calls`` and ``max_write_ops`` read from this table, so an
        ``audit_level`` that could suppress rows would silently disable the
        budget.
        """
        level = (profile.audit_level if profile else AuditLevel.STANDARD.value)
        if level == AuditLevel.FULL.value:
            return values
        if values.get('decision') == Decision.DENIED.value:
            return values          # a denial is never trimmed
        trimmed = dict(values)
        if level == AuditLevel.BASIC.value:
            for field_name in self.verbosity_fields():
                trimmed[field_name] = False
        else:  # STANDARD: keep the summary, drop the raw arguments
            trimmed['input_args'] = False
            trimmed['records_accessed'] = False
        return trimmed
