from odoo import api, models

from .enums import AuditEvent, Decision


class AIAuditService(models.AbstractModel):
    """Writes the security log. Document D 11, with the B3 correction.

    Every method APPENDS. Nothing updates a previous row, so the identity being
    recorded can never rewrite what was recorded about it -- which matters
    because that identity is an ordinary employee in CHAT mode and ``sudo()`` is
    banned.

    ``open_entry`` still runs BEFORE the guard, so a denial can never escape
    unlogged. That is the property T-80 depends on.
    """

    _name = 'ai.operations.audit'
    _description = 'AI Operations Audit Service'

    def _log(self):
        return self.env['ai.operations.audit.log']

    def _append(self, event_type, correlation_id, sequence, values=None):
        payload = dict(values or {})
        payload.update({
            'event_type': event_type,
            'correlation_id': correlation_id,
            'sequence': sequence,
        })
        # Every row carries the identity that wrote it. That is what lets an
        # ordinary user hold create-only access to their own entries without
        # ever being able to see, or touch, anybody else's.
        payload['user_id'] = payload.get('user_id') or self.env.uid
        return self._log().create(payload)

    @api.model
    def open_entry(self, tool_code, profile, user, execution_mode, trigger,
                   session_id, correlation_id, service_user=None):
        """Open the call. Returns the correlation id, which keys every later row."""
        self._append(AuditEvent.OPEN.value, correlation_id, 0, {
            'tool_code': tool_code,
            'profile_id': profile.id if profile else False,
            'profile_code': profile.code if profile else False,
            'policy_version': profile.policy_version if profile else False,
            'provider_code': getattr(profile, 'provider_code', False) or False,
            'user_id': user.id if user else False,
            'service_user_id': service_user.id if service_user else False,
            'execution_mode': execution_mode,
            'trigger': trigger,
            'session_id': session_id,
        })
        return correlation_id

    @api.model
    def record_decision(self, correlation_id, decision, profile=None, reason=None,
                        detail=None, tool_code=None, models_accessed=None,
                        records_accessed=None, input_args=None, action_code=None):
        values = {
            'decision': getattr(decision, 'value', decision),
            'denial_reason': getattr(reason, 'value', reason) if reason else False,
            'denial_detail': detail or False,
            'tool_code': tool_code or False,
            'profile_id': profile.id if profile else False,
            'profile_code': profile.code if profile else False,
            'models_accessed': models_accessed or False,
            'records_accessed': records_accessed or False,
            'input_args': input_args or False,
            'action_code': action_code or False,
        }
        values = self._log().apply_verbosity(profile, values)
        return self._append(AuditEvent.DECISION.value, correlation_id, 1, values)

    @api.model
    def record_result(self, correlation_id, profile=None, output_summary=None,
                      duration_ms=0, tokens_in=None, tokens_out=None):
        values = self._log().apply_verbosity(profile, {
            'decision': Decision.ALLOWED.value,
            'output_summary': output_summary or False,
            'duration_ms': duration_ms,
            'token_input': tokens_in or 0,
            'token_output': tokens_out or 0,
        })
        return self._append(AuditEvent.RESULT.value, correlation_id, 2, values)

    @api.model
    def record_write(self, correlation_id, model, res_id, before=None, after=None):
        return self._append(AuditEvent.WRITE.value, correlation_id, 3, {
            'models_accessed': model,
            'records_accessed': str(res_id),
            'values_before': before or False,
            'values_after': after or False,
        })

    @api.model
    def record_variance(self, correlation_id, variance_pct, approval_required):
        return self._append(AuditEvent.VARIANCE.value, correlation_id, 4, {
            'variance_pct': variance_pct,
            'approval_required': approval_required,
        })

    @api.model
    def record_idempotent_hit(self, correlation_id, detail=None):
        return self._append(AuditEvent.DECISION.value, correlation_id, 1, {
            'decision': Decision.ALLOWED.value,
            'idempotent_hit': True,
            'denial_detail': detail or False,
        })

    @api.model
    def record_error(self, correlation_id, error):
        return self._append(AuditEvent.ERROR.value, correlation_id, 5, {
            'error': str(error),
        })

    @api.model
    def call_events(self, correlation_id):
        """Reconstruct one call from its rows, in order."""
        return self._log().search(
            [('correlation_id', '=', correlation_id)], order='sequence, id')
