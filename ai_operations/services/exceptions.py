"""Exception hierarchy. Document D 5."""


class AIOperationsError(Exception):
    """Base. Never raised directly."""


#: The ONLY text a denial is ever allowed to show outside the audit log.
NEUTRAL_DENIAL = "Refused: this request is outside the agent's authorised scope."


class AIAccessDenied(AIOperationsError):
    """
    The guard refused. ALWAYS carries a DenialReason.
    Audited before propagation, without exception.

    str() is NEUTRAL BY CONSTRUCTION. The reason, the model and the detail
    live on attributes and reach the audit log; they never reach a rendered
    string, because anything that renders this exception -- a log line, a
    traceback, a tool result handed back to the model -- would otherwise
    publish the shape of the permission model.
    """

    def __init__(self, reason, detail=None, model=None, tool_code=None):
        self.reason = reason          # DenialReason
        self.detail = detail          # audit only
        self.model = model            # audit only
        self.tool_code = tool_code    # audit only
        super().__init__(NEUTRAL_DENIAL)


class AISchemaError(AIOperationsError):
    """Input or output failed schema validation."""

    def __init__(self, field, message, schema_name=None):
        self.field = field
        self.schema_name = schema_name
        super().__init__(f"{schema_name or 'schema'}.{field}: {message}")


class AIBlocklistViolation(AIOperationsError):
    """
    Blocklisted field reached serialisation.
    THIS IS A DEFECT, NOT A FILTER. Fails the build.
    """


class AIToolRegistrationError(AIOperationsError):
    """Raised at import time. Prevents module load."""


class AIProviderRegistrationError(AIOperationsError):
    """
    Bad or late provider registration. Raised at import time.
    A provider adapter is an egress destination, so a failed
    registration prevents module load rather than degrading.
    """


class AIProviderError(AIOperationsError):
    """
    Provider failure -- unknown code, unusable adapter, transport,
    timeout, vendor error. Never blocks an Odoo workflow.
    """


class AIBudgetExceeded(AIOperationsError):
    """Tool call or write budget exhausted."""
