"""Single source of truth for every enumeration in the platform.

Models import from here. They never redeclare a selection list inline --
CI check 10 fails the build on any inline selection outside this file.
"""

from enum import Enum


class AutonomyLevel(int, Enum):
    QUERY               = 0
    ANALYZE             = 1
    PREPARE             = 2
    LIMITED_EXECUTION   = 3   # not permitted in Phase 1
    CONTROLLED_AUTONOMY = 4   # not permitted in Phase 1


PHASE1_MAX_AUTONOMY = AutonomyLevel.PREPARE


class ToolCategory(str, Enum):
    READ        = 'READ'
    DRAFT_WRITE = 'DRAFT_WRITE'
    HANDOFF     = 'HANDOFF'


class ExecutionMode(str, Enum):
    INTERACTIVE = 'INTERACTIVE'
    AUTONOMOUS  = 'AUTONOMOUS'


class TriggerType(str, Enum):
    CHAT    = 'CHAT'
    CRON    = 'CRON'
    HANDOFF = 'HANDOFF'


class Decision(str, Enum):
    ALLOWED = 'ALLOWED'
    DENIED  = 'DENIED'


class AuditLevel(str, Enum):
    """Verbosity of ALLOWED rows only. Never suppresses a row."""
    BASIC    = 'BASIC'
    STANDARD = 'STANDARD'
    FULL     = 'FULL'
    # NONE removed: it could only mean "disable the security log".


class RetentionClass(str, Enum):
    OPERATIONAL = 'OPERATIONAL'   # archived after 24 months
    SECURITY    = 'SECURITY'      # indefinite: denials, writes, escalations, policy changes


class RiskLevel(str, Enum):
    LOW      = 'LOW'
    MEDIUM   = 'MEDIUM'
    HIGH     = 'HIGH'
    CRITICAL = 'CRITICAL'


class DataClassification(str, Enum):
    PUBLIC              = 'PUBLIC'
    INTERNAL            = 'INTERNAL'
    CONFIDENTIAL        = 'CONFIDENTIAL'
    HIGHLY_CONFIDENTIAL = 'HIGHLY_CONFIDENTIAL'
    RESTRICTED          = 'RESTRICTED'


class HandoffState(str, Enum):
    DRAFT           = 'DRAFT'
    REQUESTED       = 'REQUESTED'
    ACCEPTED        = 'ACCEPTED'
    PROCESSING      = 'PROCESSING'
    ACTION_REQUIRED = 'ACTION_REQUIRED'
    COMPLETED       = 'COMPLETED'
    REJECTED        = 'REJECTED'
    FAILED          = 'FAILED'
    CANCELLED       = 'CANCELLED'


class DenialReason(str, Enum):
    """Closed set. Every entry maps to at least one test in Document C 16."""
    UNKNOWN_TOOL             = 'UNKNOWN_TOOL'
    TOOL_DISABLED            = 'TOOL_DISABLED'
    TOOL_NOT_ASSIGNED        = 'TOOL_NOT_ASSIGNED'
    PROFILE_INACTIVE         = 'PROFILE_INACTIVE'
    AUTONOMY_INSUFFICIENT    = 'AUTONOMY_INSUFFICIENT'
    NO_SERVICE_USER          = 'NO_SERVICE_USER'
    MODEL_NOT_PERMITTED      = 'MODEL_NOT_PERMITTED'
    OPERATION_NOT_PERMITTED  = 'OPERATION_NOT_PERMITTED'
    RECORD_OUT_OF_DOMAIN     = 'RECORD_OUT_OF_DOMAIN'
    COMPANY_OUT_OF_SCOPE     = 'COMPANY_OUT_OF_SCOPE'
    ACTION_NOT_PERMITTED     = 'ACTION_NOT_PERMITTED'
    USER_ACL_DENIED          = 'USER_ACL_DENIED'
    SCHEMA_INVALID           = 'SCHEMA_INVALID'
    HANDOFF_SCHEMA_VIOLATION = 'HANDOFF_SCHEMA_VIOLATION'
    BOUND_EXCEEDED           = 'BOUND_EXCEEDED'
    BLOCKLIST_HIT            = 'BLOCKLIST_HIT'
    BUDGET_EXCEEDED          = 'BUDGET_EXCEEDED'
    ASSIGNEE_UNRESOLVED      = 'ASSIGNEE_UNRESOLVED'


def to_selection(enum_cls):
    """Render an enum as an Odoo selection list.

    ``str()`` on the value is not decoration: ``odoo.fields.Selection`` stores
    ``varchar`` (``odoo/orm/fields_selection.py``), so an int-valued enum such
    as AutonomyLevel must present string keys. For the str-valued enums this is
    an identity.
    """
    return [(str(m.value), m.name.replace('_', ' ').title()) for m in enum_cls]
