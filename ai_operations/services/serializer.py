"""The output sanitiser. Document C 8, Document D 10.

The highest-leverage control in the design, and it works by omission rather than
by exclusion: a schema declares what may be emitted, and nothing else can be.
``vendor`` emits two keys because the schema declares two. ``bank_ids`` is not
excluded -- it is never reachable. That is what makes related-record leakage
structurally impossible instead of a matter of remembering.

**Rule: never serialise a recordset.** ``record.read()`` is banned in tool packs
and grepped for in CI, which is why the traversal below walks fields explicitly.
"""

import datetime
import logging

from odoo import api, models

from . import blocklist
from .exceptions import AIBlocklistViolation

_logger = logging.getLogger(__name__)

#: Document D 10: "Traverses at most 2 relational hops."
MAX_RELATIONAL_HOPS = 2


class AISerializer(models.AbstractModel):
    _name = 'ai.operations.serializer'
    _description = 'AI Operations Output Serialiser'

    # ------------------------------------------------------------------

    @api.model
    def serialize(self, ctx, data, output_schema):
        """Emit only what ``output_schema`` declares, then assert the blocklist.

        Undeclared keys are **dropped and logged as a defect** -- the asymmetry
        with input validation is deliberate. An undeclared *input* key is
        rejected, because accepting it would be acting on something nobody
        declared. An undeclared *output* key is dropped, because the schema is
        an allowlist and the tool returning extra data is a bug in the tool, not
        an attack on the guard. Either way nothing undeclared leaves.
        """
        if not isinstance(data, dict):
            raise AIBlocklistViolation(
                "A tool must return a plain dict; %s returned %s"
                % (getattr(output_schema, '__name__', output_schema), type(data).__name__))

        declared = output_schema.field_names()
        undeclared = set(data) - declared
        if undeclared:
            _logger.error(
                "ai_operations: tool %s returned undeclared field(s) %s; dropped. "
                "This is a defect in the tool, not a routine filter.",
                getattr(ctx, 'tool_code', '?'), ', '.join(sorted(undeclared)))

        emitted = output_schema.validate(
            {key: value for key, value in data.items() if key in declared})

        self.assert_clean(ctx, emitted)
        return emitted

    @api.model
    def serialize_record(self, ctx, record, spec):
        """Render one record through an explicit key -> dotted-path mapping.

            {'id': 'id', 'name': 'name', 'country': 'country_id.name'}

        Every relational hop re-checks the model permission on the *target*
        model, so a path cannot be used to walk out of the agent's scope one
        dot at a time.
        """
        record.ensure_one()
        result = {}
        for key, path in spec.items():
            result[key] = self._traverse(ctx, record, path)
        self.assert_clean(ctx, result)
        return result

    @api.model
    def serialize_records(self, ctx, records, spec, limit=None):
        """The same, for a recordset, capped by the agent's ``max_records``."""
        cap = limit or ctx.security.max_records(ctx.profile, records._name)
        return [self.serialize_record(ctx, record, spec) for record in records[:cap]]

    # ------------------------------------------------------------------

    @api.model
    def assert_clean(self, ctx, payload):
        """The final check. A hit is a build-breaking defect, never a filter."""
        hits = blocklist.scan(payload)
        if not hits:
            return payload

        detail = 'blocklisted key(s) reached serialisation: %s' % ', '.join(hits)
        # Deliberately does NOT audit here. Serialisation happens inside the
        # savepoint that a failure rolls back, so a row written now would be
        # rolled back with the failure it records. The runtime audits this
        # outside the savepoint instead -- review finding B3-b.
        raise AIBlocklistViolation(
            "%s. An output schema is wrong: this is a defect, not something to "
            "filter out." % detail)

    # ------------------------------------------------------------------

    def _traverse(self, ctx, record, path):
        parts = path.split('.')
        value = record
        model_name = record._name
        hops = 0

        for index, part in enumerate(parts):
            if not hasattr(value, '_fields') or part not in value._fields:
                raise AIBlocklistViolation(
                    "%r is not a field of %s (path %r)" % (part, model_name, path))

            if blocklist.is_field_blocked(model_name, part):
                raise AIBlocklistViolation(
                    "%s.%s is on the global blocklist and must never be "
                    "declared by an output schema." % (model_name, part))

            field = value._fields[part]
            value = value[part]

            if field.relational:
                hops += 1
                if hops > MAX_RELATIONAL_HOPS:
                    raise AIBlocklistViolation(
                        "path %r traverses more than %d relational hops"
                        % (path, MAX_RELATIONAL_HOPS))
                model_name = field.comodel_name
                if blocklist.is_model_blocked(model_name):
                    raise AIBlocklistViolation(
                        "%s is blocked entirely; %r would reach it." % (model_name, path))
                # Re-check on the TARGET model, so a dotted path cannot walk
                # out of the agent's scope one hop at a time.
                ctx.security.check_model(ctx.profile, model_name, 'read')
                if index == len(parts) - 1:
                    # The path ends on the relation itself: emit ids, never the
                    # record, so nothing undeclared rides along.
                    return value.ids if len(value) != 1 else value.id

        return self._plain(value)

    @staticmethod
    def _plain(value):
        """Never return a recordset, never return an Odoo object."""
        if isinstance(value, models.BaseModel):
            return value.ids
        if isinstance(value, datetime.datetime):
            return value.isoformat(sep=' ')
        if isinstance(value, datetime.date):
            return value.isoformat()
        return value
