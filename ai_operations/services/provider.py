"""The provider interface and its frozen registry. Document C 6.3, Document D 12.

**The kernel names no vendor, no endpoint and no credential variable.** CI check
16 enforces it. Providers are registered exactly like tools, for a sharper
reason: a tool is a bounded capability behind the guard, whereas a provider
adapter is the **egress point for the fully assembled context** -- system
prompt, tool definitions, and every authorised record the tools returned,
already past every permission check.

A runtime-registerable provider is therefore an arbitrary-exfiltration primitive
with full authorisation behind it. Registration is an import in an installed
module, which makes adding an egress destination a deployment act somebody can
review.
"""

from dataclasses import dataclass

from odoo import api, models

from .exceptions import AIProviderError, AIProviderRegistrationError

REQUIRED_METHODS = ('complete', 'get_models', 'health_check')


@dataclass(frozen=True)
class ProviderSpec:
    code: str
    label: str
    cls: type
    models: tuple          # ((code, label), ...) -- DECLARED, never fetched


_PROVIDERS = {}
_PROVIDERS_FROZEN = False


def ai_provider(code, label, models):
    """Register a provider adapter. Import-time only.

    ``models`` is a **declared constant** on the adapter, never a live call:
    configuration must not depend on the vendor being reachable, a profile form
    must not make an unauthenticated network request, and a vendor outage must
    not make an agent unconfigurable.
    """
    def decorator(cls):
        if _PROVIDERS_FROZEN:
            raise AIProviderRegistrationError(
                "The provider registry is frozen; %r cannot be registered at "
                "runtime. An adapter is an egress destination, so adding one is "
                "a deployment act." % code)
        if code in _PROVIDERS:
            raise AIProviderRegistrationError(
                "Provider %r is already registered." % code)
        if not models:
            raise AIProviderRegistrationError(
                "Provider %r must declare its models as a constant." % code)
        missing = [name for name in REQUIRED_METHODS if not hasattr(cls, name)]
        if missing:
            raise AIProviderRegistrationError(
                "Provider %r does not implement %s." % (code, ', '.join(missing)))

        _PROVIDERS[code] = ProviderSpec(
            code=code, label=label, cls=cls,
            models=tuple(tuple(entry) for entry in models))
        return cls
    return decorator


def freeze_provider_registry():
    global _PROVIDERS_FROZEN
    _PROVIDERS_FROZEN = True


def is_frozen():
    return _PROVIDERS_FROZEN


def get_provider(code):
    spec = _PROVIDERS.get(code)
    if spec is None:
        raise AIProviderError("No provider adapter is installed for %r." % code)
    return spec


def has_provider(code):
    return code in _PROVIDERS


def provider_selection():
    """(code, label) pairs for the profile's Selection field."""
    return [(spec.code, spec.label) for spec in _PROVIDERS.values()]


def model_selection(provider_code=None):
    """The declared models of one adapter, or of all installed adapters."""
    if provider_code:
        if not has_provider(provider_code):
            return []
        return [tuple(entry) for entry in get_provider(provider_code).models]
    seen = []
    for spec in _PROVIDERS.values():
        for entry in spec.models:
            if tuple(entry) not in seen:
                seen.append(tuple(entry))
    return seen


def all_providers():
    return dict(_PROVIDERS)


class AIProvider(models.AbstractModel):
    """The whole Phase 1 contract. Three methods.

    No embeddings, no vision, no audio, no streaming, no batch. Each is a real
    feature with its own security surface, and each waits until something
    actually needs it.

    > **A provider adapter may change how the LLM is called. It may never change
    > security behaviour.** Every adapter runs behind the same ContextBuilder,
    > tool registry, guard, ExecutionContext, serialiser and audit service.
    """

    _name = 'ai.operations.provider'
    _description = 'AI Operations Provider Interface'

    @api.model
    def get_models(self):
        """Declared ``(code, label)`` pairs. A CONSTANT. Never a network call."""
        raise NotImplementedError

    @api.model
    def health_check(self):
        """``(usable: bool, reason: str)``.

        Never returns, logs or renders the credential itself.
        """
        raise NotImplementedError

    @api.model
    def complete(self, messages, system=None, tools=None, model=None,
                 max_tokens=4096, timeout=120):
        """One request/response turn, normalised across vendors::

            {'content': [...], 'tool_calls': [{'id','name','input'}, ...],
             'stop_reason': str,
             'usage': {'input_tokens': int, 'output_tokens': int}}

        Raises only AIProviderError. Never raises anything else.
        """
        raise NotImplementedError
