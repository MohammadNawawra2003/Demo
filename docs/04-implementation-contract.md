# Document D — Implementation Contract

**Project:** `ai_operations` — AlShayeb AI Operations Platform for Odoo 19 Enterprise
**Inputs:** Document A v1.2 · Document B v1.3 · Document C v0.4
**Purpose:** Fix the interfaces, enumerations and conventions that every build session binds to.
**Status:** DRAFT — pre-freeze review corrections applied 2026-09-04. Ready for freeze.
**Version:** 0.4
**Date:** 2026-09-04
**Changes in 0.4:** `ASSIGNEE_UNRESOLVED` added to the closed denial set; `stock_security_warehouse` added to the module map (§3.2, §4).
**Changes in 0.3:** `@ai_provider` registry mirroring the tool registry, generic `AIProvider` interface, adapter-owned credential names, provider parity invariant and CI checks (§8.2, §12, §15).
**Changes in 0.2:** one runtime for chat and cron (§11); approval enum/fields removed; `AIAccessDenied` made neutral by construction (§5); secrets moved out of the ORM (§12); Odoo 19 constraint idiom (§13); idempotency key namespaced (§13); prompt-caching expectation corrected (§12); daily token ceiling added (§9, §11); CI checks extended (§15).

---

## 1. What This Document Is

Document C says what the models are and why. This says what the code looks like where it matters.

**In scope:** service API signatures, `ExecutionContext`, exception hierarchy, enumerations, schema module API, serialiser API, registry API, provider adapter interface, tool pack conventions, CI checks.

**Deliberately out of scope:** view XML, `ir.model.access.csv` rows, menus, sequences, boilerplate. These are mechanical and derived from the model definitions. Writing them in prose duplicates the code at lower fidelity.

**The rule this document exists to enforce:** four tool packs written in four separate sessions must be indistinguishable in style. Every interface below is frozen before Session 1.

---

## 2. Conventions

| Item | Convention |
|---|---|
| Model names | `ai.operations.<noun>` — dots, singular |
| Python modules | `snake_case.py` matching the model noun |
| Tool codes | `<domain>.<verb>_<object>` — `procurement.prepare_draft_rfq` |
| Action codes | `SCREAMING_SNAKE` — `CREATE_DRAFT`, `UPDATE_DRAFT`, `CONFIRM` |
| Handoff types | `SCREAMING_SNAKE` — `MATERIAL_SHORTAGE` |
| Denial reasons | `SCREAMING_SNAKE`, closed set (§4.2) |
| XML ids | `<module>.<type>_<name>` — `ai_operations.group_ai_security_admin` |
| Policy pack files | `data/policy_pack.xml`, always `noupdate="1"` |
| Test files | `tests/test_<area>.py`, classes `Test<Area>` |
| Test method names | `test_<matrix_id>_<slug>` — `test_t80_adversarial_prompt_override` |

**Language:** English throughout code, comments, docstrings, tool descriptions, denial messages and audit text. Arabic arrives as translation in Session 13, never as source.

**Every test method carries its matrix id.** This is how the acceptance checklist is verified mechanically rather than by reading.

---

## 3. Module Manifests

### 3.1 `ai_operations` — kernel

```python
{
    'name': 'AI Operations',
    'version': '19.0.1.0.0',
    'category': 'Productivity/AI',
    'summary': 'Secure execution platform for departmental AI agents',
    'author': 'AlShayeb Partners',
    'license': 'OPL-1',
    'depends': ['base', 'mail'],          # NOTHING ELSE. EVER.
    'data': [
        'security/ai_operations_groups.xml',
        'security/ir.model.access.csv',
        'security/ir_rule.xml',
        'data/ir_sequence.xml',
        'views/agent_profile_views.xml',
        'views/model_permission_views.xml',
        'views/action_permission_views.xml',
        'views/tool_views.xml',
        'views/handoff_views.xml',
        'views/audit_log_views.xml',
        'views/menus.xml',
    ],
    'installable': True,
    'application': True,
}
```

> **The dependency list is a security control, not a preference.** A CI job installs `ai_operations` on a bare database with no other apps and runs its full test suite. If `purchase`, `stock`, `mrp` or `ai` ever appears in `depends`, the kernel has stopped being portable and the Community fallback is gone.

### 3.2 Remaining modules

| Module | Depends |
|---|---|
| `ai_operations_anthropic` | `ai_operations` — **a provider adapter, not *the* provider.** Phase 1 ships this one; the kernel names no vendor |
| `ai_operations_bridge` | `ai_operations`, `ai` — **optional**; the only module importing from the AI app; routes no tool call |
| `ai_operations_procurement` | `ai_operations`, `purchase`, `stock` |
| `ai_operations_inventory` | `ai_operations`, `stock` |
| `ai_operations_manufacturing` | `ai_operations`, `mrp`, `stock`, **`quality_mrp`** |
| `ai_operations_quality` | `ai_operations`, **`quality_mrp`**, `stock`, `mrp` |
| **`stock_security_warehouse`** | `stock` — **and nothing else.** A standalone reusable authorisation addon: `allowed_warehouse_ids` on `res.users`, one scoped group, record rules on `stock.quant`, `stock.move`, `stock.move.line`, `stock.picking`, `stock.location`. It knows nothing about AI, and `ai_operations` knows nothing about it |
| `alshayeb_demo_water` | `purchase`, `stock`, `mrp`, **`quality_mrp`**, **`quality_mrp_workorder`**, `sale_management`, `account`, `l10n_sa`, `l10n_sa_edi`, `hr`, **`stock_security_warehouse`** — **not `ai_operations`** |

> **`stock_security_warehouse` is not part of this product.** It ships alongside because the demo needs warehouse-scoped users and because nearly every client does. It carries no dependency on `ai_operations` in either direction, and it must be independently installable and sellable. Warehouse restriction reaches the guard the ordinary way — through the execution user's record rules at §7 steps 10 and 13. **Do not add `allowed_warehouse_ids` to any `ai_operations` model.** See Document C §12.
>
> One implementation caution carried from Document A §12: **do not write a warehouse rule on `stock.lot`.** `stock.lot.location_id` is computed as the lot's single quant location and is `False` whenever the lot spans more than one — so such a rule would hide precisely the lots a recall is about and break `quality.trace_forward`.

> **`quality_mrp`, not `quality_control`.** Version 0.1 depended on `quality_control`, which provides quality checks on transfers and standalone alerts. Every quality control point in Document A §8.3 that matters to Phase 1 — QCP-03 bromate per treatment batch, QCP-06 fill volume, QCP-07 cap torque, QCP-08 finished lot micro — attaches to a manufacturing order or a work order, and so does the entire S-09 recall chain. Those come from `quality_mrp` (which depends on `quality_control`, which depends on `quality`) and `quality_mrp_workorder`.

> **The bridge is optional and nothing depends on it.** Per Document B §16 decision 3 and Document C §9, `ai_operations` owns the runtime for both chat and cron. The bridge exists so the agent is discoverable from the Enterprise AI app's UI. Uninstalling it changes discoverability and nothing else — no behaviour, no security, no test outcome. `ai_operations` and every tool pack must install and pass their suites with the bridge absent, and CI runs them that way.

---

## 4. Enumerations

`services/enums.py`. **Single source of truth.** Models import from here; they never redeclare selection lists inline.

```python
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
    PUBLIC                = 'PUBLIC'
    INTERNAL              = 'INTERNAL'
    CONFIDENTIAL          = 'CONFIDENTIAL'
    HIGHLY_CONFIDENTIAL   = 'HIGHLY_CONFIDENTIAL'
    RESTRICTED            = 'RESTRICTED'


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
```

### 4.2 Denial reasons

Closed set. Every entry maps to at least one test in Document C §16.

```python
class DenialReason(str, Enum):
    UNKNOWN_TOOL              = 'UNKNOWN_TOOL'
    TOOL_DISABLED             = 'TOOL_DISABLED'
    TOOL_NOT_ASSIGNED         = 'TOOL_NOT_ASSIGNED'
    PROFILE_INACTIVE          = 'PROFILE_INACTIVE'
    AUTONOMY_INSUFFICIENT     = 'AUTONOMY_INSUFFICIENT'
    NO_SERVICE_USER           = 'NO_SERVICE_USER'
    MODEL_NOT_PERMITTED       = 'MODEL_NOT_PERMITTED'
    OPERATION_NOT_PERMITTED   = 'OPERATION_NOT_PERMITTED'
    RECORD_OUT_OF_DOMAIN      = 'RECORD_OUT_OF_DOMAIN'
    COMPANY_OUT_OF_SCOPE      = 'COMPANY_OUT_OF_SCOPE'
    ACTION_NOT_PERMITTED      = 'ACTION_NOT_PERMITTED'
    USER_ACL_DENIED           = 'USER_ACL_DENIED'
    SCHEMA_INVALID            = 'SCHEMA_INVALID'
    HANDOFF_SCHEMA_VIOLATION  = 'HANDOFF_SCHEMA_VIOLATION'
    BOUND_EXCEEDED            = 'BOUND_EXCEEDED'
    BLOCKLIST_HIT             = 'BLOCKLIST_HIT'
    BUDGET_EXCEEDED           = 'BUDGET_EXCEEDED'
    ASSIGNEE_UNRESOLVED       = 'ASSIGNEE_UNRESOLVED'
```

**Helper for Odoo selections:**

```python
def to_selection(enum_cls):
    return [(m.value, m.name.replace('_', ' ').title()) for m in enum_cls]
```

---

## 5. Exception Hierarchy

`services/exceptions.py`.

```python
from odoo.exceptions import UserError


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
```

**Rules:**
- `AIAccessDenied` is audited before it propagates. No exceptions to this.
- Nothing in `ai_operations` catches a bare `Exception`.
- The message is neutral **at construction**, not at the point of display. Version 0.1 built the message as `f"{reason.value}: {detail}"` and relied on every call site remembering to neutralise it before showing it. One forgetful call site is enough, and there is one that cannot be fixed by remembering: any runtime that catches a tool exception and hands its text back to the model. Making the string neutral in `__init__` removes the class of mistake instead of policing it.
- The runner returns `NEUTRAL_DENIAL` to the model as the tool result and writes the reason to the audit row. Test T-86 asserts the model never receives a model name, a field name or a denial code.

---

## 6. `ExecutionContext`

The frozen contract passed to every tool. A tool that constructs its own `env` is a defect.

```python
from dataclasses import dataclass, field
from typing import Any

@dataclass(frozen=True)
class ExecutionContext:
    env: Any                      # already with_user() + allowed_company_ids
    profile: Any                  # ai.operations.agent.profile record
    execution_user: Any           # res.users — employee or service user
    execution_mode: ExecutionMode
    trigger: TriggerType
    company_ids: tuple            # effective intersection, ordered
    autonomy: AutonomyLevel       # effective, already min()-resolved
    tool_code: str
    correlation_id: str
    session_id: str
    audit_id: int
    policy_version: str
    idempotency_key: str = None
    handoff_id: int = None
    _budget: Any = field(default=None, repr=False)

    def model(self, name):
        """
        The ONLY sanctioned way for a tool to reach a model.
        Re-asserts the model is permitted; raises AIAccessDenied otherwise.
        Direct self.env[...] inside a tool is a defect.
        """
        ...

    def domain_for(self, model_name):
        """AND of the agent domain and any state restriction."""
        ...

    def consume_write(self):
        """Decrement write budget. Raises AIBudgetExceeded."""
        ...

    def check_variance(self, deterministic, proposed, category_ref=None):
        """
        Resolve the bounds for this action and category and classify the
        proposal. Returns (variance_pct, approval_required).

        Above variance_ceiling_pct -> raises AIAccessDenied(BOUND_EXCEEDED).
        Above variance_bound_pct   -> returns approval_required=True; the
                                      caller writes the record and stamps it.
        No bound configured        -> raises. Fail closed.
        """
        ...
```

`ctx.model()` existing at all is deliberate. It makes the permitted path shorter to type than the unpermitted one, which is the only reliable way to keep a convention alive across thirteen sessions.

---

## 7. Schema Module

`services/schema.py`. Custom, no dependencies. Roughly 150 lines.

```python
class Field:
    def __init__(self, required=True, default=None): ...
    def validate(self, value, name): raise NotImplementedError

class Int(Field):
    def __init__(self, min=None, max=None, **kw): ...

class Float(Field):
    def __init__(self, min=None, max=None, **kw): ...

class Str(Field):
    def __init__(self, max_length=None, choices=None, **kw): ...

class Bool(Field): ...
class Date(Field): ...
class Datetime(Field): ...

class Enum(Field):
    def __init__(self, enum_cls, **kw): ...

class List(Field):
    def __init__(self, inner, max_items=None, **kw): ...

class Nested(Field):
    def __init__(self, fields: dict, **kw): ...


class Schema:
    """
    Declarative. Subclass and declare fields as class attributes.

        class ShortageInput(Schema):
            product_id    = Int(min=1)
            warehouse_id  = Int(min=1)
            required_date = Date(required=False)
    """
    @classmethod
    def validate(cls, data: dict) -> dict:
        """Returns coerced dict. Raises AISchemaError on first failure."""

    @classmethod
    def field_names(cls) -> set: ...

    @classmethod
    def to_json_schema(cls) -> dict:
        """For the tool description sent to the LLM."""
```

**Guarantees:**
- Validation is **rejection**, never coercion of unknown keys. An undeclared key in input raises `AISchemaError`.
- `validate()` returns a plain dict. Never a recordset, never an Odoo object.
- `to_json_schema()` is the only path by which a tool's parameter shape reaches the LLM.

---

## 8. Registry

`services/registry.py`.

```python
@dataclass(frozen=True)
class ToolSpec:
    code: str
    func: callable
    category: ToolCategory
    autonomy: AutonomyLevel
    models: tuple
    actions: tuple            # ((model, action_code), ...)
    input_schema: type
    output_schema: type
    idempotent: bool
    max_results: int
    description: str          # from the docstring


_REGISTRY: dict = {}
_FROZEN: bool = False


def ai_tool(code, category, autonomy, models, actions=(),
            input_schema=None, output_schema=None,
            idempotent=False, max_results=200):
    """
    Register a tool. Import-time only.

    Raises AIToolRegistrationError when:
      - the registry is frozen
      - the code is already registered
      - input_schema or output_schema is missing
      - models is empty or contains '*'
      - any input_schema field is named in PROHIBITED_PARAM_NAMES
      - the function has no docstring (it is the LLM description)
    """


PROHIBITED_PARAM_NAMES = frozenset({
    'model', 'model_name', 'models',
    'method', 'method_name',
    'domain', 'filter',
    'code', 'python_code', 'expression', 'sql', 'query',
})


def freeze_registry():   """Called post-load. No registration afterwards."""
def get_tool(code) -> ToolSpec:   """Raises AIAccessDenied(UNKNOWN_TOOL)."""
def all_tools() -> dict: ...
```

### 8.2 Provider registry

Same shape as the tool registry, same freeze rule, for a sharper reason.

```python
@dataclass(frozen=True)
class ProviderSpec:
    code: str
    label: str
    cls: type              # AIProvider subclass
    models: tuple          # ((code, label), ...) — DECLARED, never fetched


_PROVIDERS: dict = {}
_PROVIDERS_FROZEN: bool = False


def ai_provider(code, label, models):
    """
    Register a provider adapter. Import-time only.

    Raises AIProviderRegistrationError when:
      - the registry is frozen
      - the code is already registered
      - models is empty
      - the class does not implement complete/get_models/health_check
    """


def freeze_provider_registry():  """Called post-load. No registration afterwards."""
def get_provider(code) -> ProviderSpec:  """Raises AIProviderError on unknown code."""
def provider_selection() -> list:  """(code, label) for the profile's Selection field."""
def model_selection(provider_code) -> list:  """The adapter's declared models."""
```

**Why frozen matters more here than for tools.** A tool is a bounded capability behind the guard. A provider adapter is the **egress point for the fully assembled context** — system prompt, tool definitions, and every authorised record the tools returned, already past every permission check. A runtime-registerable provider is an arbitrary-exfiltration primitive with full authorisation behind it. Registration is an import in an installed module, so adding an egress destination is a deployment act somebody can review.

**`models` is a declared constant on the adapter, never a live call.** Configuration must not depend on the vendor being reachable, a profile form must not make an unauthenticated network request, and a vendor outage must not make an agent unconfigurable.

**Tool function signature — invariant across all packs:**

```python
@ai_tool(
    code="procurement.get_shortage_context",
    category=ToolCategory.READ,
    autonomy=AutonomyLevel.QUERY,
    models=["product.product", "stock.quant", "stock.move",
            "stock.warehouse.orderpoint"],
    input_schema=ShortageContextInput,
    output_schema=ShortageContextOutput,
)
def get_shortage_context(ctx: ExecutionContext, params: dict) -> dict:
    """
    Return current stock position, incoming quantity, reserved quantity
    and reorder configuration for a product at a warehouse.
    """
    Product = ctx.model('product.product')
    ...
    return {...}          # plain dict, matching output_schema
```

**Invariants, checked in CI:**
- Exactly two parameters, named `ctx` and `params`
- Returns a plain `dict`
- Never touches `ctx.env[...]` directly — always `ctx.model()`
- Never calls `sudo()`
- Never calls `.read()`
- Docstring present and written for an LLM audience

---

## 9. `AISecurityService`

`services/security_service.py`. The guard. Every step of Document C §7 lives here and nowhere else.

```python
class AISecurityService(models.AbstractModel):
    _name = 'ai.operations.security'
    _description = 'AI Operations Security Service'

    # ---- entry point ------------------------------------------------
    def authorize(self, tool_code, params, profile=None,
                  execution_mode=ExecutionMode.INTERACTIVE,
                  trigger=TriggerType.CHAT,
                  session_id=None, correlation_id=None,
                  handoff_id=None) -> ExecutionContext:
        """
        Runs Document C §7 steps 1-18 in order.
        Returns a frozen ExecutionContext, or raises AIAccessDenied
        AFTER writing the denial to the audit log.
        """

    # ---- individual checks, each independently testable --------------
    def check_tool(self, profile, tool_code): ...
    def check_profile(self, profile): ...
    def check_autonomy(self, profile, tool_spec, action=None): ...
    def resolve_identity(self, profile, execution_mode): ...
    def resolve_companies(self, profile, user): ...
    def check_model(self, profile, model_name, operation): ...
    def check_records(self, ctx, model_name, record_ids, operation): ...
    def check_action(self, ctx, model_name, action_code, values=None): ...
    def check_bound(self, ctx, model_name, category_ref,
                    deterministic, proposed): ...
    def check_token_ceiling(self, profile): ...
    def check_handoff(self, from_profile, to_profile, type_code, payload): ...
```

**Rules:**
- Each `check_*` returns `None` or raises `AIAccessDenied`. Never returns a boolean, because a boolean invites `if not check(): pass`.
- Every check is independently unit-testable against its matrix id.
- Permission logic exists here only. A tool pack that re-implements a check is a defect.
- Caching: profile configuration is cached per request with `tools.ormcache` keyed on `(profile_id, policy_version)`. **User ACLs, record rules, dynamic domains and company access are never cached.**

---

## 10. Serialiser

`services/serializer.py`.

```python
class AISerializer(models.AbstractModel):
    _name = 'ai.operations.serializer'

    def serialize(self, ctx, data, output_schema) -> dict:
        """
        Emit ONLY fields declared in output_schema.
        Then assert the global blocklist.
        Raises AIBlocklistViolation on any hit — a defect, not a filter.
        """

    def serialize_record(self, ctx, record, spec: dict) -> dict:
        """
        spec maps output key -> dotted field path.
            {'id': 'id', 'name': 'name', 'country': 'country_id.name'}
        Traverses at most 2 relational hops.
        Every hop re-checks model permission on the target model.
        """
```

**Banned in every module, grepped in CI:** `.read(`, `.read_group(` outside the service layer, `json.dumps(record`, `fields_get(`.

**Global blocklist** lives in `services/blocklist.py`, developer-defined, per Document C §5.4. A hit fails the test suite.

---

## 11. Audit, Handoff, Context, Execution

```python
class AIAuditService(models.AbstractModel):
    _name = 'ai.operations.audit'

    def open_entry(self, tool_code, profile, user, execution_mode,
                   trigger, session_id, correlation_id) -> int:
        """Create the audit row BEFORE the guard runs. Returns id."""

    def record_decision(self, audit_id, decision, reason=None, detail=None): ...
    def record_result(self, audit_id, output_summary, duration_ms,
                      tokens_in=None, tokens_out=None): ...
    def record_write(self, audit_id, model, res_id, before, after): ...
    def record_variance(self, audit_id, variance_pct, approval_required): ...
    def record_error(self, audit_id, error): ...
```

The audit row opens **before** the guard runs. A denial can therefore never escape unlogged, which is the property T-80 depends on.

```python
class AIHandoffService(models.AbstractModel):
    _name = 'ai.operations.handoff.service'

    def raise_handoff(self, ctx, type_code, payload,
                      source_model=None, source_res_id=None,
                      priority='1', required_date=None,
                      idempotency_key=None):
        """Validates payload against the type schema. Rejects, never filters."""

    def accept(self, ctx, handoff_id): ...
    def complete(self, ctx, handoff_id, result_model=None, result_res_id=None): ...
    def reject(self, ctx, handoff_id, reason): ...
```

```python
class AIContextBuilder(models.AbstractModel):
    _name = 'ai.operations.context.builder'

    def build_system_prompt(self, profile) -> str: ...
    def build_tool_definitions(self, profile) -> list:
        """Anthropic tool-use format, from registry + assignments."""
    def build_record_context(self, ctx, record, schema) -> dict:
        """Through an output schema. Never a raw record."""
```

```python
class AIExecutionRunner(models.AbstractModel):
    _name = 'ai.operations.execution'

    def run(self, profile_code, trigger, session_id,
            entry_prompt=None, entry_tool=None, correlation_id=None):
        """
        THE loop. One implementation, two triggers.

        1. Resolve profile; must be active.
           trigger CRON -> must allow_autonomous
           trigger CHAT -> must allow_interactive
        2. Resolve execution identity:
           CRON -> profile.service_user_id. ABSENT or archived -> abort.
                   Never sudo. Never fall back.
           CHAT -> self.env.user
        3. env = self.env(user=identity,
                          context={'allowed_company_ids': company_ids})
        4. Check the daily token ceiling before the first provider call.
        5. Build prompt and tool definitions (ContextBuilder, registry
           intersected with this profile's assignments).
        6. Loop capped at profile.max_tool_calls:
             provider.complete() -> tool_use -> tool.execute()
             AIAccessDenied -> append NEUTRAL_DENIAL as the tool result,
                               audit the real reason, CONTINUE the loop.
             any other error -> savepoint rollback, audit FAILED, ABORT.
        7. Post mail.message to the record worked on.
        8. Accumulate usage into profile.tokens_today. Close the audit run.

        Provider failure -> audit FAILED, return cleanly.
        NEVER raises into the cron. NEVER blocks Odoo.
        """
```

**The branch table — this is the whole difference between the two modes:**

| | `CHAT` | `CRON` |
|---|---|---|
| Execution identity | `env.user` (the employee) | `profile.service_user_id` |
| `session_id` | `discuss.channel` id | run id |
| Transcript surfaced in | the channel | the audit log + record chatter |
| Loop driver, guard, serialiser, registry, prompt builder, provider | **identical object, identical code path** | |

Anything else that differs between the modes is a defect, and T-99 is the test that says so. Version 0.1 hosted the interactive loop inside the Enterprise `ai` app and asserted equivalence; Document B §16 decision 3 records why that could not be true.

---

## 12. Provider Interface and Adapters

`ai_operations/services/provider.py` defines the interface and the registry (§8.2). Adapters implement it. **The kernel names no vendor, no endpoint and no credential variable.**

```python
class AIProvider(models.AbstractModel):
    _name = 'ai.operations.provider'

    # ---- the whole Phase 1 contract. Three methods. -----------------
    def get_models(self) -> list:
        """
        Declared (code, label) pairs this adapter supports.
        A CONSTANT on the class. Never a network call.
        """

    def health_check(self) -> tuple:
        """
        (usable: bool, reason: str) -- is this adapter configured and
        credentialed. The reason is neutral text for an admin screen.
        NEVER returns, logs or renders the credential itself.
        """

    def complete(self, messages, system=None, tools=None,
                 model=None, max_tokens=4096, timeout=120) -> dict:
        """
        One request/response turn, normalised across vendors:
            {
              'content':    [...],          # normalised blocks
              'tool_calls': [{'id','name','input'}, ...],
              'stop_reason': str,
              'usage': {'input_tokens': int, 'output_tokens': int},
            }
        Raises AIProviderError on any failure. Never raises anything else.
        """
```

**Nothing else in Phase 1.** No embeddings, no vision, no audio, no streaming, no batch. Each is a real feature with its own security surface, and each waits until something actually needs it.

**The resolution path.** The runner never imports an adapter:

```python
spec = get_provider(profile.provider_code)      # registry lookup, frozen
provider = self.env[spec.cls._name]
result = provider.complete(..., model=profile.model_code)
```

### The parity invariant

> **A provider adapter may change how the LLM is called. It may never change security behaviour.**

Every adapter runs behind the same `ContextBuilder`, tool registry, `AISecurityService`, `ExecutionContext`, serialiser and audit service. Swapping the adapter must not alter one permission decision, one serialised field, or one audit row beyond `provider_code` and `model_code`. **Test T-100** (Document C §16.12) asserts this against a null adapter registered by the test suite, so it is implementable in Phase 1 with one vendor and one key.

The invariant is about security *decisions*. It says nothing about **data egress**, which a provider change alters completely — see Document C §6.3 and §20. Provider change is a SECURITY audit event and bumps `policy_version`.

### `ai_operations_anthropic` — the Phase 1 adapter

```python
@ai_provider(code="anthropic", label="Anthropic",
             models=(("claude-opus-5",   "Claude Opus 5"),
                     ("claude-sonnet-5", "Claude Sonnet 5")))
class AnthropicProvider(models.AbstractModel):
    _name = 'ai.operations.provider.anthropic'
    _inherit = 'ai.operations.provider'
```

Implementation notes:

- `POST https://api.anthropic.com/v1/messages`
- **API key from the environment or `odoo.conf` only, and the name belongs to the adapter.** Never `ir.config_parameter`, never a model record, never the audit log, never a log line or traceback:

  ```python
  # inside ai_operations_anthropic, nowhere else
  from odoo.tools import config
  key = (os.environ.get('ODOO_AI_ANTHROPIC_TOKEN')
         or config.get('ai_anthropic_token'))
  ```

  A later OpenAI adapter reads `ODOO_AI_OPENAI_TOKEN`, a Gemini adapter `ODOO_AI_GEMINI_TOKEN`. **`ai_operations` contains none of those strings** — the kernel's only question is `provider.health_check()`. CI check 16 enforces it.

  `ir.config_parameter` carries a single ACL row — `base.group_system` — and `get_param()` calls `check_access('read')`. Service users are barred from that group by constraint, so a DB-stored key would force the first `sudo()` into the kernel and the CI grep that guards the architecture would have to be disabled to ship it. Reading from the environment needs no privilege, no ORM and no exception, and keeps the key out of every database dump. See Document C §5.10.

- **`model_code` is a `Selection` sourced from `get_models()`** on the adapter the profile selected, not free text. A typo must be a configuration error at save time, not a runtime provider error at 07:00.
- **Prompt caching, with a correct expectation.** Put a `cache_control` breakpoint at the end of the tool definitions and the system block, and keep everything volatile — timestamps, the record under discussion, the user's question — after it. The saving is **within a single run's tool loop**, where the same system block and tool list are re-sent on every iteration of a loop that can reach `max_tool_calls`. That is real and worth having.

  It is **not** a cross-run saving, and version 0.1 claimed it was: "daily reviews repeat the same system prompt across four agents". Four agents have four different system prompts and four different tool sets, so there is no shared prefix between them; and the runs are 24 hours apart while the ephemeral cache TTL is five minutes (one hour with `ttl: "1h"`). Every daily run starts cold no matter what. Verify with `usage.cache_read_input_tokens` — zero across the iterations of one run means a silent invalidator, most likely a timestamp rendered into the system prompt.

- Retry: 2 attempts, exponential backoff, on 429 and 5xx only.
- Content block parsing **by type, never by position**.
- `usage.input_tokens` and `usage.output_tokens` are written to the audit row and accumulated into `profile.tokens_today` on every call. The daily ceiling is checked before the next call and enforced fail-closed.

---

## 13. Tool Pack Conventions

Every pack is identical in shape.

```
ai_operations_procurement/
├── __manifest__.py
├── __init__.py
├── models/
│   └── purchase_order.py          # ai_idempotency_key field only
├── tools/
│   ├── __init__.py                # imports every tool module — registration
│   ├── schemas.py                 # all input/output schemas for the pack
│   ├── read_tools.py
│   ├── draft_tools.py
│   └── handoff_tools.py
├── data/
│   └── policy_pack.xml            # noupdate="1"
└── tests/
    └── test_procurement_tools.py
```

**Idempotency mixin** — each pack adds to the models it writes:

```python
class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

    ai_idempotency_key = fields.Char(index=True, copy=False)
    ai_approval_required = fields.Boolean(
        copy=False,
        help="An AI recommendation on this record exceeded the routine "
             "variance bound and requires manager approval.",
    )

    _ai_idempotency_key_uniq = models.Constraint(
        'unique(company_id, ai_idempotency_key)',
        'An AI-generated record already exists for this key.',
    )
```

**Two things to note.**

*The Odoo 19 constraint idiom.* Constraints are `models.Constraint(...)` class attributes. Core v19 uses that form in 176 modules and the legacy `_sql_constraints` list in exactly one. Version 0.1 of this document used the legacy form, and code samples here are copied verbatim across fourteen build sessions.

*The key is namespaced.* Uniqueness is on `(company_id, ai_idempotency_key)` and the key itself is `{profile_code}:{company_id}:{purpose}:{product_ref}:{location_ref}:{date}` (Document C §13). A globally unique bare key would collide the moment two of the three demo companies — or two profiles — hit the same purpose, product, location and date, and the second write would silently receive the first's record.

**Policy pack pattern:**

```xml
<odoo noupdate="1">
  <record id="profile_procurement" model="ai.operations.agent.profile">
    <field name="name">Procurement Intelligence</field>
    <field name="code">procurement</field>
    <field name="max_autonomy_level">2</field>
    <field name="policy_version">1.0.0</field>
  </record>

  <record id="perm_procurement_purchase_order"
          model="ai.operations.model.permission">
    <field name="profile_id" ref="profile_procurement"/>
    <field name="model_id" ref="purchase.model_purchase_order"/>
    <field name="perm_read" eval="True"/>
    <field name="perm_create" eval="True"/>
    <field name="perm_write" eval="True"/>
    <field name="state_restriction">draft</field>
    <field name="domain">[('company_id','in',allowed_company_ids)]</field>
  </record>
</odoo>
```

---

## 14. Testing Conventions

```python
from odoo.tests import TransactionCase, tagged

@tagged('post_install', '-at_install', 'ai_security')
class TestModelScope(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._seed_fixtures()      # synthetic, never client data

    def test_t11_procurement_denied_account_move(self):
        with self.assertRaises(AIAccessDenied) as e:
            self.security.check_model(
                self.profile_procurement, 'account.move', 'read')
        self.assertEqual(e.exception.reason,
                         DenialReason.MODEL_NOT_PERMITTED)
        self.assertAudited(DenialReason.MODEL_NOT_PERMITTED)
```

**Rules:**
- Method name carries the matrix id. A CI job maps §16 to test methods and fails on any gap.
- Denial tests assert the **specific** `DenialReason`, never merely that something raised. A test passing for the wrong reason is worse than no test.
- Every denial test also asserts the audit entry.
- Fixtures are synthetic and seeded by the test. Never `alshayeb_demo_water` for unit tests; that module is for the end-to-end suite only.
- Tag `ai_security` so the full security suite runs standalone on every push.
- Denial tests assert the **audited** reason, never the exception's string — `str(AIAccessDenied)` is the fixed neutral message by construction (§5) and asserting on it proves nothing.

---

## 15. CI Checks

Each is a build failure, not a warning.

| # | Check |
|---|---|
| 1 | `grep -rn "sudo()" ai_operations*/` → any hit fails |
| 2 | `grep -rn "\.read(" ai_operations*/tools/` → any hit fails |
| 3 | Kernel installs and passes its suite on a **bare database** |
| 4 | No import of `odoo.addons.ai` outside `ai_operations_bridge` |
| 5 | Every `@ai_tool` declares `models`, `input_schema`, `output_schema`, docstring |
| 6 | No `@ai_tool` input schema field in `PROHIBITED_PARAM_NAMES` |
| 7 | Every Document C §16 matrix id has a matching test method |
| 8 | Every `DenialReason` member is asserted by at least one test |
| 9 | Tool function signatures are exactly `(ctx, params)` |
| 10 | No selection list declared inline outside `enums.py` |
| 11 | `grep -rn "ir.config_parameter" ai_operations*/` outside a test → fails. The API key never touches the ORM |
| 12 | `grep -rn "expression.AND\|expression.OR\|_sql_constraints" ai_operations*/` → fails. Odoo 19 idioms only |
| 13 | Kernel and every tool pack install and pass with `ai_operations_bridge` **absent** |
| 14 | Kernel and every tool pack install and pass on an **Odoo Community** database |
| 15 | No `Many2one` in `ai_operations/models/` targets a model outside `base` or `mail` |
| 16 | `grep -rniE "anthropic\|claude\|openai\|gemini\|api\.anthropic\|_TOKEN" ai_operations/` → fails. The kernel names no vendor, no endpoint and no credential variable |
| 17 | Every `@ai_provider` declares a non-empty constant `models` and implements `complete` / `get_models` / `health_check` |

Checks 1, 2, 4, 11, 15 and 16 are the ones that keep the architecture honest twelve months from now, when someone under deadline pressure reaches for the shortcut. Check 14 is the one that keeps the commercial position true: the moment the platform stops installing on Community, "runs without Odoo Enterprise AI" has quietly become marketing rather than fact.

---

## 16. Session 1 — Definition of Done

- [ ] `ai_operations` installs on a bare database — and on Odoo **Community**
- [ ] No `Many2one` in the kernel targets a model outside `base` or `mail` (CI check 15)
- [ ] `enums.py`, `exceptions.py` complete and imported by the models
- [ ] `str(AIAccessDenied(...))` returns the neutral message, with the reason on the attribute
- [ ] Five security groups created with the Document C §11 separation
- [ ] `agent.profile`, `model.permission`, `action.permission` with all constraints
- [ ] Constraint fires: `max_autonomy_level > 2`
- [ ] Constraint fires: `allow_autonomous` without `service_user_id`
- [ ] Constraint fires: service user in `base.group_system`
- [ ] Domain validator rejects a lambda, a callable and unparseable text
- [ ] Auditor group can read and cannot write
- [ ] Security Admin cannot enable a tool; Technical Admin cannot alter a permission
- [ ] CI checks 1, 3, 4, 10, 12, 14 and 15 green
- [ ] **STOP** — review before Session 2

---

## 17. Freeze Checklist

- [ ] Conventions §2 agreed
- [ ] Manifests §3 agreed, especially the kernel dependency rule and `quality_mrp`
- [ ] Enumerations §4 agreed — these propagate everywhere and are expensive to change later
- [ ] Exception hierarchy §5 agreed
- [ ] `ExecutionContext` §6 agreed — the most-referenced interface in the codebase
- [ ] Service signatures §9 to §11 agreed, including the one-runtime branch table
- [ ] Provider interface and registry §8.2 / §12 agreed — three methods, frozen registry, declared models
- [ ] Parity invariant and T-100 agreed, including the residency caveat it does not cover
- [ ] Provider contract §12 agreed, especially the key never entering the ORM and the adapter owning its name
- [ ] Tool pack conventions §13 agreed
- [ ] CI checks §15 agreed as build-failing, including 11 to 15
- [ ] Session 1 definition of done §16 agreed

On freeze: Documents A, B, C and D go to the vault with a decision log entry, and Session 1 begins.
