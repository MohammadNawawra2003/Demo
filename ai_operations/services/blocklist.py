"""The global field blocklist. Document C 5.4.

**This is defence in depth, not the defence.** Field-level leakage is solved
structurally by output schemas: nothing serialises unless a tool declares it, so
``partner_id`` becomes ``{id, name}`` because the schema says so, not because
somebody remembered to block ``bank_ids``.

A configurable field-permission model was rejected precisely because it would be
a second, weaker mechanism inviting the assumption that undeclared fields are
safe by default. That assumption is what the whole design is against.

So a hit here is a **defect, not a routine filter**: it means an output schema is
wrong. It raises, it is audited as a security event, and it fails the build.
"""

#: Developer-defined. Never configurable from the UI -- a blocklist an
#: administrator can edit is a blocklist an administrator can empty.
GLOBAL_FIELD_BLOCKLIST = {
    'res.partner': {'bank_ids', 'comment', 'credit', 'debit', 'vat'},
    'res.users': {'password', 'api_key_ids', 'totp_secret'},
    'hr.employee': '*',            # the entire model
    'ir.config_parameter': '*',    # where a DB-stored API key would have lived
}

#: Caught by name, wherever they appear, on any model.
FIELD_NAME_PATTERNS = ('password', 'token', 'secret', 'api_key', 'private_key')


def is_model_blocked(model_name):
    """True when the whole model is off limits."""
    return GLOBAL_FIELD_BLOCKLIST.get(model_name) == '*'


def is_field_blocked(model_name, field_name):
    if is_model_blocked(model_name):
        return True
    blocked = GLOBAL_FIELD_BLOCKLIST.get(model_name) or set()
    if blocked != '*' and field_name in blocked:
        return True
    return matches_pattern(field_name)


def matches_pattern(name):
    lowered = (name or '').lower()
    return any(pattern in lowered for pattern in FIELD_NAME_PATTERNS)


def scan(data, _path=''):
    """Walk a serialised structure and return the paths of suspicious keys.

    The last check before anything leaves the platform. It looks at emitted key
    names rather than source fields, because by this point the source is gone
    and the key is what the model will see.
    """
    hits = []
    if isinstance(data, dict):
        for key, value in data.items():
            path = '%s.%s' % (_path, key) if _path else str(key)
            if matches_pattern(str(key)):
                hits.append(path)
            hits.extend(scan(value, path))
    elif isinstance(data, (list, tuple)):
        for index, item in enumerate(data):
            hits.extend(scan(item, '%s[%d]' % (_path, index)))
    return hits
