"""The tool registry. Document C 6, Document D 8.

Tool registration is effectively a grant of business capability, so it is
developer territory: the registry is populated at module load by import side
effect and cannot be added to afterwards.

**On when the freeze happens.** Document C 6.2 says "frozen after load". There
is no Odoo hook that fires once every addon has been imported -- ``post_load``
and ``post_init_hook`` are both per-module, and tool packs load *after* the
kernel. Freezing at kernel load would therefore lock out the packs, and freezing
lazily on first read would lock them out too, because ``ai.operations.tool``
reads the registry to compute its own fields during install.

So the freeze is an explicit call. The execution runtime makes it once, before
its first provider call, which is long after every module has been imported.
That preserves the property that matters -- no registration at *runtime* -- and
is checked by T-05.
"""

import inspect
from dataclasses import dataclass

from .enums import AutonomyLevel, DenialReason, ToolCategory
from .exceptions import AIAccessDenied, AIToolRegistrationError

#: A tool that takes any of these is a tool the LLM can point at a model,
#: a method or a domain. Rejected at registration, not at review.
PROHIBITED_PARAM_NAMES = frozenset({
    'model', 'model_name', 'models',
    'method', 'method_name',
    'domain', 'filter',
    'code', 'python_code', 'expression', 'sql', 'query',
})

#: Every tool function has exactly this signature.
REQUIRED_SIGNATURE = ('ctx', 'params')


@dataclass(frozen=True)
class ToolSpec:
    code: str
    func: callable
    category: str
    autonomy: int
    models: tuple
    actions: tuple            # ((model, action_code), ...)
    input_schema: type
    output_schema: type
    idempotent: bool
    max_results: int
    description: str          # from the docstring; sent to the LLM


_REGISTRY = {}
_FROZEN = False


def ai_tool(code, category, autonomy, models, actions=(),
            input_schema=None, output_schema=None,
            idempotent=False, max_results=200):
    """Register a tool. Import-time only.

    Raises AIToolRegistrationError when the registry is frozen, the code is
    already registered, either schema is missing, ``models`` is empty or
    contains ``'*'``, any input schema field is a prohibited parameter name,
    the signature is not ``(ctx, params)``, or the function has no docstring.
    """
    category = getattr(category, 'value', category)
    autonomy = int(getattr(autonomy, 'value', autonomy))

    def decorator(func):
        if _FROZEN:
            raise AIToolRegistrationError(
                "The tool registry is frozen; %r cannot be registered at runtime. "
                "Registration is an import in an installed module, so that adding "
                "a capability stays a deployment act somebody can review." % code)

        if code in _REGISTRY:
            raise AIToolRegistrationError("Tool %r is already registered." % code)

        if input_schema is None or output_schema is None:
            raise AIToolRegistrationError(
                "Tool %r must declare both input_schema and output_schema." % code)

        if not models:
            raise AIToolRegistrationError(
                "Tool %r must declare the models it touches; the guard checks "
                "every one of them." % code)

        if '*' in models:
            raise AIToolRegistrationError(
                "Tool %r declares models=['*']. A wildcard is the opposite of an "
                "allowlist." % code)

        if category not in {member.value for member in ToolCategory}:
            raise AIToolRegistrationError(
                "Tool %r has an unknown category %r." % (code, category))

        if autonomy not in {int(member.value) for member in AutonomyLevel}:
            raise AIToolRegistrationError(
                "Tool %r has an unknown autonomy level %r." % (code, autonomy))

        declared_params = input_schema.field_names()
        prohibited = declared_params & PROHIBITED_PARAM_NAMES
        if prohibited:
            raise AIToolRegistrationError(
                "Tool %r declares the parameter(s) %s. A tool never takes a model "
                "name, a method name or a domain from the LLM."
                % (code, ', '.join(sorted(prohibited))))

        signature = tuple(inspect.signature(func).parameters)
        if signature != REQUIRED_SIGNATURE:
            raise AIToolRegistrationError(
                "Tool %r must be defined as (ctx, params); got %s."
                % (code, signature or '()'))

        description = inspect.getdoc(func)
        if not description:
            raise AIToolRegistrationError(
                "Tool %r has no docstring. The docstring is the description the "
                "LLM sees." % code)

        _REGISTRY[code] = ToolSpec(
            code=code,
            func=func,
            category=category,
            autonomy=autonomy,
            models=tuple(models),
            actions=tuple(tuple(a) for a in actions),
            input_schema=input_schema,
            output_schema=output_schema,
            idempotent=idempotent,
            max_results=max_results,
            description=description,
        )
        return func

    return decorator


def freeze_registry():
    """Close the registry. Called once by the runtime, after every import."""
    global _FROZEN
    _FROZEN = True


def is_frozen():
    return _FROZEN


def get_tool(code):
    """Return the ToolSpec, or deny.

    Guard step 1. Raises AIAccessDenied(UNKNOWN_TOOL) -- neutral to the caller,
    with the code on the attribute for the audit row.
    """
    spec = _REGISTRY.get(code)
    if spec is None:
        raise AIAccessDenied(
            DenialReason.UNKNOWN_TOOL,
            detail='no registry entry for %r' % code,
            tool_code=code,
        )
    return spec


def has_tool(code):
    """Non-raising existence check, for configuration screens and constraints."""
    return code in _REGISTRY


def all_tools():
    return dict(_REGISTRY)
