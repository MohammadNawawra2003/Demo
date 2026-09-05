"""Declarative input/output schemas. Document D 7.

Custom and dependency-free on purpose: Pydantic is a dependency to manage on
Odoo.sh across upgrades, `jsonschema` is not guaranteed present, and Odoo fields
would couple a wire format to the ORM. The surface needed here is small.

Two guarantees the rest of the platform leans on:

* **Validation is rejection, never coercion.** An undeclared key raises rather
  than being dropped, because silently normalising an attempted leak into a
  success is the failure mode this whole design exists to avoid.
* **`to_json_schema()` is the only path** by which a tool's parameter shape
  reaches the LLM, so the shape the model sees cannot drift from the shape the
  validator will accept.
"""

import datetime

from .exceptions import AISchemaError

_UNSET = object()


class Field:
    """Base field. Subclasses implement ``_check``."""

    json_type = 'string'

    def __init__(self, required=True, default=_UNSET, description=None):
        self.required = required
        self.default = default
        self.description = description

    @property
    def has_default(self):
        return self.default is not _UNSET

    def validate(self, value, name, schema_name=None):
        if value is None:
            if self.required:
                raise AISchemaError(name, 'must not be null', schema_name)
            return None
        return self._check(value, name, schema_name)

    def _check(self, value, name, schema_name):
        raise NotImplementedError

    def json_spec(self):
        spec = {'type': self.json_type}
        if self.description:
            spec['description'] = self.description
        return spec


class Int(Field):
    json_type = 'integer'

    def __init__(self, min=None, max=None, **kw):
        super().__init__(**kw)
        self.min = min
        self.max = max

    def _check(self, value, name, schema_name):
        # bool is an int subclass; a boolean where an id belongs is a defect.
        if isinstance(value, bool) or not isinstance(value, int):
            raise AISchemaError(name, 'must be an integer', schema_name)
        if self.min is not None and value < self.min:
            raise AISchemaError(name, 'must be >= %s' % self.min, schema_name)
        if self.max is not None and value > self.max:
            raise AISchemaError(name, 'must be <= %s' % self.max, schema_name)
        return value

    def json_spec(self):
        spec = super().json_spec()
        if self.min is not None:
            spec['minimum'] = self.min
        if self.max is not None:
            spec['maximum'] = self.max
        return spec


class Float(Field):
    json_type = 'number'

    def __init__(self, min=None, max=None, **kw):
        super().__init__(**kw)
        self.min = min
        self.max = max

    def _check(self, value, name, schema_name):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise AISchemaError(name, 'must be a number', schema_name)
        value = float(value)
        if self.min is not None and value < self.min:
            raise AISchemaError(name, 'must be >= %s' % self.min, schema_name)
        if self.max is not None and value > self.max:
            raise AISchemaError(name, 'must be <= %s' % self.max, schema_name)
        return value

    def json_spec(self):
        spec = super().json_spec()
        if self.min is not None:
            spec['minimum'] = self.min
        if self.max is not None:
            spec['maximum'] = self.max
        return spec


class Str(Field):
    json_type = 'string'

    def __init__(self, max_length=None, choices=None, **kw):
        super().__init__(**kw)
        self.max_length = max_length
        self.choices = tuple(choices) if choices else None

    def _check(self, value, name, schema_name):
        if not isinstance(value, str):
            raise AISchemaError(name, 'must be a string', schema_name)
        if self.max_length is not None and len(value) > self.max_length:
            raise AISchemaError(
                name, 'must be at most %s characters' % self.max_length, schema_name)
        if self.choices is not None and value not in self.choices:
            raise AISchemaError(
                name, 'must be one of %s' % ', '.join(self.choices), schema_name)
        return value

    def json_spec(self):
        spec = super().json_spec()
        if self.choices:
            spec['enum'] = list(self.choices)
        if self.max_length is not None:
            spec['maxLength'] = self.max_length
        return spec


class Bool(Field):
    json_type = 'boolean'

    def _check(self, value, name, schema_name):
        if not isinstance(value, bool):
            raise AISchemaError(name, 'must be a boolean', schema_name)
        return value


class Date(Field):
    json_type = 'string'

    def _check(self, value, name, schema_name):
        if isinstance(value, datetime.datetime):
            return value.date()
        if isinstance(value, datetime.date):
            return value
        if isinstance(value, str):
            try:
                return datetime.date.fromisoformat(value)
            except ValueError:
                pass
        raise AISchemaError(name, 'must be an ISO date (YYYY-MM-DD)', schema_name)

    def json_spec(self):
        spec = super().json_spec()
        spec['format'] = 'date'
        return spec


class Datetime(Field):
    json_type = 'string'

    def _check(self, value, name, schema_name):
        if isinstance(value, datetime.datetime):
            return value
        if isinstance(value, str):
            try:
                return datetime.datetime.fromisoformat(value)
            except ValueError:
                pass
        raise AISchemaError(name, 'must be an ISO datetime', schema_name)

    def json_spec(self):
        spec = super().json_spec()
        spec['format'] = 'date-time'
        return spec


class Enum(Field):
    """A value drawn from one of the enums in ``services/enums.py``."""

    json_type = 'string'

    def __init__(self, enum_cls, **kw):
        super().__init__(**kw)
        self.enum_cls = enum_cls
        self._values = {str(member.value) for member in enum_cls}

    def _check(self, value, name, schema_name):
        text = str(value.value) if hasattr(value, 'value') else str(value)
        if text not in self._values:
            raise AISchemaError(
                name, 'must be one of %s' % ', '.join(sorted(self._values)), schema_name)
        return text

    def json_spec(self):
        spec = super().json_spec()
        spec['enum'] = sorted(self._values)
        return spec


class List(Field):
    json_type = 'array'

    def __init__(self, inner, max_items=None, **kw):
        super().__init__(**kw)
        self.inner = inner
        self.max_items = max_items

    def _check(self, value, name, schema_name):
        if not isinstance(value, (list, tuple)):
            raise AISchemaError(name, 'must be a list', schema_name)
        if self.max_items is not None and len(value) > self.max_items:
            raise AISchemaError(
                name, 'must hold at most %s items' % self.max_items, schema_name)
        return [
            self.inner.validate(item, '%s[%d]' % (name, index), schema_name)
            for index, item in enumerate(value)
        ]

    def json_spec(self):
        spec = super().json_spec()
        spec['items'] = self.inner.json_spec()
        if self.max_items is not None:
            spec['maxItems'] = self.max_items
        return spec


class Nested(Field):
    json_type = 'object'

    def __init__(self, fields, **kw):
        super().__init__(**kw)
        self.fields = dict(fields)

    def _check(self, value, name, schema_name):
        if not isinstance(value, dict):
            raise AISchemaError(name, 'must be an object', schema_name)

        undeclared = set(value) - set(self.fields)
        if undeclared:
            raise AISchemaError(
                '%s.%s' % (name, sorted(undeclared)[0]),
                'is not declared by the schema', schema_name)

        result = {}
        for key, field in self.fields.items():
            path = '%s.%s' % (name, key)
            if key in value:
                result[key] = field.validate(value[key], path, schema_name)
            elif field.required:
                raise AISchemaError(path, 'is required', schema_name)
            elif field.has_default:
                result[key] = field.default
        return result

    def json_spec(self):
        spec = super().json_spec()
        spec['properties'] = {k: f.json_spec() for k, f in self.fields.items()}
        spec['required'] = [k for k, f in self.fields.items() if f.required]
        spec['additionalProperties'] = False
        return spec


class Schema:
    """Subclass and declare fields as class attributes.

        class ShortageInput(Schema):
            product_id    = Int(min=1)
            warehouse_id  = Int(min=1)
            required_date = Date(required=False)
    """

    @classmethod
    def _declared(cls):
        """Declared fields, base classes first so a subclass can override."""
        fields = {}
        for klass in reversed(cls.__mro__):
            for key, value in vars(klass).items():
                if isinstance(value, Field):
                    fields[key] = value
        return fields

    @classmethod
    def field_names(cls):
        return set(cls._declared())

    @classmethod
    def validate(cls, data):
        """Return a coerced plain dict. Raise AISchemaError on the first failure.

        Never returns a recordset and never returns an Odoo object.
        """
        if not isinstance(data, dict):
            raise AISchemaError('<root>', 'must be an object', cls.__name__)

        declared = cls._declared()
        undeclared = set(data) - set(declared)
        if undeclared:
            raise AISchemaError(
                sorted(undeclared)[0], 'is not declared by the schema', cls.__name__)

        result = {}
        for name, field in declared.items():
            if name in data:
                result[name] = field.validate(data[name], name, cls.__name__)
            elif field.required:
                raise AISchemaError(name, 'is required', cls.__name__)
            elif field.has_default:
                result[name] = field.default
        return result

    @classmethod
    def to_json_schema(cls):
        """The tool's parameter shape as the LLM will see it, and nowhere else."""
        declared = cls._declared()
        return {
            'type': 'object',
            'properties': {name: f.json_spec() for name, f in declared.items()},
            'required': sorted(name for name, f in declared.items() if f.required),
            'additionalProperties': False,
        }
