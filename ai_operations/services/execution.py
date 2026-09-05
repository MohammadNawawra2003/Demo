"""THE loop. One implementation, two triggers. Document C 9, Document D 11.

Chat and cron are two ways into the same runner: the same guard, the same
serialiser, the same audit service, the same provider interface. Divergence
between the two is not a defect to police -- it is impossible, because there is
only one path. The only branch is identity resolution and where the transcript
is surfaced.

**On audit ordering (review finding B3-b).** A tool executes inside a savepoint
that is rolled back on failure. An audit row written *inside* that savepoint is
rolled back with the failure it records, which would make "a denial can never
escape unlogged" false. So every audit write for a failed call happens **after**
the savepoint has been rolled back, in the outer transaction. Ordering, not
infrastructure.
"""

import logging
import uuid

from odoo import api, models

from .enums import Decision, DenialReason, ExecutionMode, TriggerType
from .exceptions import (
    AIAccessDenied,
    AIBlocklistViolation,
    AIBudgetExceeded,
    AIProviderError,
)
from .exceptions import NEUTRAL_DENIAL
from .provider import get_provider

_logger = logging.getLogger(__name__)


class AIExecutionRunner(models.AbstractModel):
    _name = 'ai.operations.execution'
    _description = 'AI Operations Execution Runtime'

    # ------------------------------------------------------------------
    # One tool call, guarded, executed and serialised
    # ------------------------------------------------------------------

    @api.model
    def execute_tool(self, profile, tool_code, params, execution_mode,
                     trigger, session_id, correlation_id=None, budget=None):
        """Run one tool call end to end. Returns a serialised plain dict.

        Raises AIAccessDenied to the caller; the runner converts it to the
        neutral string before anything reaches the model (see :meth:`run`).
        """
        audit = self.env['ai.operations.audit']
        security = self.env['ai.operations.security']
        correlation_id = correlation_id or uuid.uuid4().hex

        ctx = security.authorize(                              # steps 1-19
            tool_code, params, profile,
            execution_mode=execution_mode, trigger=trigger,
            session_id=session_id, correlation_id=correlation_id, budget=budget)

        spec = self.env['ai.operations.tool'].registry_spec(tool_code)

        try:
            with self.env.cr.savepoint():                      # step 20
                raw = spec.func(ctx, ctx.validated_params)
                result = self.env['ai.operations.serializer'].serialize(
                    ctx, raw, spec.output_schema)               # steps 21-22
        except (AIAccessDenied, AIBlocklistViolation, AIBudgetExceeded) as failure:
            # Outside the savepoint: the rollback has already happened, so this
            # row survives it. B3-b.
            reason = getattr(failure, 'reason', None) or self._reason_for(failure)
            audit.record_decision(
                correlation_id, Decision.DENIED, profile=profile, reason=reason,
                detail=str(getattr(failure, 'detail', None) or failure),
                tool_code=tool_code)
            raise
        except Exception as error:                             # step 24
            audit.record_error(correlation_id, error)
            raise

        audit.record_result(correlation_id, profile=profile,
                            output_summary=self._summarise(result))
        return result

    @staticmethod
    def _reason_for(failure):
        if isinstance(failure, AIBlocklistViolation):
            return DenialReason.BLOCKLIST_HIT
        if isinstance(failure, AIBudgetExceeded):
            return DenialReason.BUDGET_EXCEEDED
        return DenialReason.OPERATION_NOT_PERMITTED

    @staticmethod
    def _summarise(result, limit=400):
        text = str(result)
        return text if len(text) <= limit else text[:limit] + '...'

    # ------------------------------------------------------------------
    # The loop
    # ------------------------------------------------------------------

    @api.model
    def run(self, profile_code, trigger, session_id=None, entry_prompt=None,
            correlation_id=None):
        """Resolve, budget, loop, close. Never raises into a cron.

        A provider failure is audited and returns cleanly: core ERP must never
        depend on LLM availability.
        """
        from .context import RunBudget

        Profile = self.env['ai.operations.agent.profile']
        profile = Profile.search([('code', '=', profile_code)], limit=1)
        security = self.env['ai.operations.security']
        audit = self.env['ai.operations.audit']

        security.check_profile(profile)                          # 1
        execution_mode = (ExecutionMode.AUTONOMOUS.value
                          if trigger == TriggerType.CRON.value
                          else ExecutionMode.INTERACTIVE.value)

        if execution_mode == ExecutionMode.AUTONOMOUS.value and not profile.allow_autonomous:
            raise AIAccessDenied(DenialReason.PROFILE_INACTIVE,
                                 detail='profile does not allow autonomous runs')
        if execution_mode == ExecutionMode.INTERACTIVE.value and not profile.allow_interactive:
            raise AIAccessDenied(DenialReason.PROFILE_INACTIVE,
                                 detail='profile does not allow interactive runs')

        # 2. Identity. ABSENT or archived -> abort. Never sudo, never fall back.
        identity = security.resolve_identity(profile, execution_mode)
        correlation_id = correlation_id or uuid.uuid4().hex
        session_id = session_id or correlation_id

        budget = RunBudget(max_tool_calls=profile.max_tool_calls or 12,
                           max_write_ops=profile.max_write_ops or 3)

        security.check_token_ceiling(profile)                    # 4

        try:
            provider = self._provider_for(profile)
        except AIProviderError as error:
            audit.record_error(correlation_id, error)
            _logger.warning("ai_operations: provider unusable for %s: %s",
                            profile_code, error)
            return {'status': 'FAILED', 'reason': 'provider', 'correlation_id': correlation_id}

        messages = [{'role': 'user', 'content': entry_prompt or ''}]
        tools = self.build_tool_definitions(profile)
        system = self.build_system_prompt(profile)

        for _iteration in range(budget.max_tool_calls + 1):      # 6
            try:
                response = provider.complete(
                    messages, system=system, tools=tools,
                    model=profile.model_code, timeout=profile.timeout_seconds or 120)
            except AIProviderError as error:
                audit.record_error(correlation_id, error)
                return {'status': 'FAILED', 'reason': 'provider',
                        'correlation_id': correlation_id}

            self._accumulate_usage(profile, response.get('usage') or {})

            calls = response.get('tool_calls') or []
            if not calls:
                return {'status': 'COMPLETED', 'correlation_id': correlation_id,
                        'content': response.get('content'),
                        'tool_calls_used': budget.tool_calls}

            for call in calls:
                try:
                    result = self.execute_tool(
                        profile, call['name'], call.get('input') or {},
                        execution_mode, trigger, session_id,
                        correlation_id=uuid.uuid4().hex, budget=budget)
                    payload = result
                except AIAccessDenied:
                    # The model is told nothing. NEUTRAL_DENIAL carries no model
                    # name, no field name and no reason code; the reason is in
                    # the audit row. T-86.
                    payload = NEUTRAL_DENIAL
                except AIBudgetExceeded:
                    return {'status': 'BUDGET_EXCEEDED',
                            'correlation_id': correlation_id}
                messages.append({'role': 'tool', 'tool_use_id': call.get('id'),
                                 'content': payload})

            try:
                security.check_token_ceiling(profile)
            except AIAccessDenied:
                audit.record_decision(
                    correlation_id, Decision.DENIED, profile=profile,
                    reason=DenialReason.BUDGET_EXCEEDED,
                    detail='daily token ceiling reached mid-run')
                return {'status': 'BUDGET_EXCEEDED', 'correlation_id': correlation_id}

        return {'status': 'BUDGET_EXCEEDED', 'correlation_id': correlation_id}

    # ------------------------------------------------------------------

    @api.model
    def _provider_for(self, profile):
        if not profile.provider_code:
            raise AIProviderError("No provider is configured for %s." % profile.code)
        spec = get_provider(profile.provider_code)
        return self.env[spec.cls._name]

    @api.model
    def _accumulate_usage(self, profile, usage):
        """Tokens accrue after the response; the ceiling is checked before the
        next call. The overshoot is bounded by one call, and it is deliberate --
        see DEVIATIONS.md finding H9."""
        total = int(usage.get('input_tokens') or 0) + int(usage.get('output_tokens') or 0)
        if not total:
            return
        self.env['ai.operations.budget'].add_tokens(profile, total)

    @api.model
    def build_system_prompt(self, profile):
        return (profile.description or
                "You are %s, an operations agent inside Odoo. Answer only from "
                "the tools you are given." % profile.name)

    @api.model
    def build_tool_definitions(self, profile):
        """From the registry, intersected with this profile's assignments.

        The parameter shape comes from ``input_schema.to_json_schema()`` and
        from nowhere else, so it cannot diverge from what the validator accepts.
        """
        Tool = self.env['ai.operations.tool']
        definitions = []
        for assignment in profile.tool_assignment_ids.filtered('enabled'):
            tool = assignment.tool_id
            if not tool.enabled or not tool.registered:
                continue
            spec = Tool.registry_spec(tool.code)
            definitions.append({
                'name': spec.code,
                'description': spec.description,
                'input_schema': spec.input_schema.to_json_schema(),
            })
        return definitions
