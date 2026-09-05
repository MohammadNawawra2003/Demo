"""Configuration validators shared by the permission models.

Both ``ai.operations.model.permission`` and ``ai.operations.action.permission``
carry a ``state_restriction``, and the former also carries an agent ``domain``.
The rules live here once rather than in each model.
"""

import ast
import re

from odoo.exceptions import ValidationError

#: The only bare strings a domain may contain.
DOMAIN_OPERATORS = frozenset(('&', '|', '!'))

#: ``field=value``, where the field may be a dotted path (``stage_id.name``).
STATE_RESTRICTION_RE = re.compile(
    r'^(?P<field>[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*)'
    r'='
    r'(?P<value>.+)$'
)


def validate_domain(text):
    """Parse and structurally validate an agent record domain.

    Literal-only, by ``ast.literal_eval``. Never ``eval``. A domain that fails
    to parse, or that contains a callable, a lambda or any non-literal, is
    rejected on write -- Document C 5.2.

    Returns the parsed domain, or ``[]`` for an empty restriction.
    """
    if not text or not text.strip():
        return []

    try:
        parsed = ast.literal_eval(text)
    except (ValueError, SyntaxError, TypeError, MemoryError, RecursionError) as exc:
        raise ValidationError(
            "The agent domain must be a literal Odoo domain. It is parsed with "
            "ast.literal_eval, so a name, a lambda, a function call or any other "
            "non-literal expression is rejected.\n\nGot: %s" % text
        ) from exc

    if not isinstance(parsed, (list, tuple)):
        raise ValidationError(
            "The agent domain must be a list of leaves and operators. Got: %s" % text
        )

    for element in parsed:
        if isinstance(element, str):
            if element not in DOMAIN_OPERATORS:
                raise ValidationError(
                    "%r is not a valid domain operator. Expected one of %s."
                    % (element, ', '.join(sorted(DOMAIN_OPERATORS)))
                )
            continue

        if not isinstance(element, (list, tuple)) or len(element) != 3:
            raise ValidationError(
                "Every domain leaf must be a 3-part (field, operator, value) "
                "tuple. Got: %r" % (element,)
            )

        field_name, operator, _value = element
        if not isinstance(field_name, str) or not field_name:
            raise ValidationError(
                "A domain leaf's field must be a non-empty string. Got: %r" % (element,)
            )
        if not isinstance(operator, str) or not operator:
            raise ValidationError(
                "A domain leaf's operator must be a non-empty string. Got: %r" % (element,)
            )

    return parsed


def validate_state_restriction(text):
    """Validate a ``field=value`` state restriction -- Document C 5.2.

    A bare value cannot work, because the models this is applied to do not
    agree on a field name: ``purchase.order`` uses ``state``, ``quality.check``
    uses ``quality_state``, and ``quality.alert`` has no state field at all --
    it uses ``stage_id``, pointing at ``quality.alert.stage``.

    Returns ``(field_path, value)``, or ``None`` for an empty restriction.
    """
    if not text or not text.strip():
        return None

    match = STATE_RESTRICTION_RE.match(text.strip())
    if not match:
        raise ValidationError(
            "A state restriction must name its field: write it as 'field=value', "
            "for example 'state=draft' on purchase.order or 'stage_id.name=New' "
            "on quality.alert. A bare value cannot work, because these models do "
            "not agree on a field name -- purchase.order uses 'state', "
            "quality.check uses 'quality_state', and quality.alert has no state "
            "field at all.\n\nGot: %s" % text
        )

    return match.group('field'), match.group('value')
