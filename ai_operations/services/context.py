"""The frozen contract handed to every tool. Document D 6."""

from dataclasses import dataclass, field
from typing import Any

from .enums import DenialReason
from .exceptions import AIAccessDenied, AIBudgetExceeded


class RunBudget:
    """Per-run counters. Held in memory for the life of the run and reconciled
    against the audit log, which is indexed on ``session_id``."""

    def __init__(self, max_tool_calls=12, max_write_ops=3):
        self.max_tool_calls = max_tool_calls
        self.max_write_ops = max_write_ops
        self.tool_calls = 0
        self.write_ops = 0
        #: Per-tool counts. Document C 5.1's ``max_tool_calls`` is the loop cap
        #: for the whole run; C 5.6's ``max_calls_per_run`` sits on the
        #: assignment and bounds **that tool**. They are two different caps and
        #: conflating them made a tight cap on one tool shrink the entire run.
        self.calls_by_tool = {}

    def consume_tool_call(self, tool_code=None, max_calls_for_tool=0):
        self.tool_calls += 1
        if self.tool_calls > self.max_tool_calls:
            raise AIAccessDenied(
                DenialReason.BUDGET_EXCEEDED,
                detail='tool call %d exceeds the run cap of %d'
                       % (self.tool_calls, self.max_tool_calls))

        if not tool_code:
            return
        used = self.calls_by_tool.get(tool_code, 0) + 1
        self.calls_by_tool[tool_code] = used
        if max_calls_for_tool and used > max_calls_for_tool:
            raise AIAccessDenied(
                DenialReason.BUDGET_EXCEEDED,
                detail='call %d of %s exceeds its own cap of %d'
                       % (used, tool_code, max_calls_for_tool))

    def consume_write(self):
        self.write_ops += 1
        if self.write_ops > self.max_write_ops:
            raise AIBudgetExceeded(
                'write %d exceeds the run cap of %d'
                % (self.write_ops, self.max_write_ops))


@dataclass(frozen=True)
class ExecutionContext:
    """Produced by the guard. A tool that builds its own env is a defect."""

    env: Any                      # already with_user() + allowed_company_ids
    profile: Any
    execution_user: Any
    execution_mode: str
    trigger: str
    company_ids: tuple
    autonomy: int
    tool_code: str
    correlation_id: str
    session_id: str
    audit_id: int
    policy_version: str
    idempotency_key: str = None
    handoff_id: int = None
    budget: Any = field(default=None, repr=False)

    # -- the sanctioned paths ------------------------------------------

    @property
    def security(self):
        return self.env['ai.operations.security']

    def model(self, name):
        """The ONLY sanctioned way for a tool to reach a model.

        Re-asserts the model is permitted and raises AIAccessDenied otherwise.
        Direct ``ctx.env[...]`` inside a tool is a defect -- this exists so the
        permitted path is shorter to type than the unpermitted one, which is the
        only thing that keeps a convention alive across fourteen sessions.
        """
        self.security.check_model(self.profile, name, 'read')
        return self.env[name]

    def domain_for(self, model_name):
        """AND of the agent domain and any state restriction."""
        return self.security.agent_domain(self.profile, model_name)

    def check_records(self, model_name, record_ids, operation='read'):
        """Guard steps 10, 13 and 14, for ids the tool has resolved."""
        return self.security.check_records(self, model_name, record_ids, operation)

    def consume_write(self):
        if self.budget is not None:
            self.budget.consume_write()

    def check_variance(self, deterministic, proposed, model_name=None,
                       action_code=None, category_ref=None):
        """Classify a proposal against the two bounds -- guard steps 16 and 17.

        Above ``variance_ceiling_pct`` raises AIAccessDenied(BOUND_EXCEEDED).
        Above ``variance_bound_pct`` returns ``approval_required=True``; the
        caller writes the record and stamps it. No bound configured raises,
        because the guard fails closed.
        """
        return self.security.check_bound(
            self, deterministic, proposed,
            model_name=model_name, action_code=action_code,
            category_ref=category_ref)
