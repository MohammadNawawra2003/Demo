from odoo.tests import TransactionCase, tagged

from ..services.enums import AutonomyLevel
from ..services.exceptions import AISchemaError
from ..services.schema import (
    Bool,
    Date,
    Enum,
    Float,
    Int,
    List,
    Nested,
    Schema,
    Str,
)


class ShortageInput(Schema):
    product_id = Int(min=1)
    warehouse_id = Int(min=1)
    required_date = Date(required=False)


class VendorOutput(Schema):
    vendor = Nested({'id': Int(), 'name': Str()})
    lines = List(Nested({'product_id': Int(), 'quantity': Float()}), max_items=3)
    urgent = Bool(required=False, default=False)
    level = Enum(AutonomyLevel, required=False)


@tagged('post_install', '-at_install', 'ai_security')
class TestSchema(TransactionCase):

    def test_valid_input_is_coerced_to_a_plain_dict(self):
        result = ShortageInput.validate({
            'product_id': 42, 'warehouse_id': 7, 'required_date': '2026-09-04',
        })
        self.assertIsInstance(result, dict)
        self.assertEqual(result['product_id'], 42)
        self.assertEqual(result['required_date'].isoformat(), '2026-09-04')

    def test_undeclared_key_is_rejected_not_dropped(self):
        """Filtering would silently normalise an attempted leak into a success."""
        with self.assertRaises(AISchemaError):
            ShortageInput.validate({
                'product_id': 42, 'warehouse_id': 7, 'company_id': 1,
            })

    def test_missing_required_field_is_rejected(self):
        with self.assertRaises(AISchemaError):
            ShortageInput.validate({'product_id': 42})

    def test_optional_field_may_be_omitted(self):
        result = ShortageInput.validate({'product_id': 42, 'warehouse_id': 7})
        self.assertNotIn('required_date', result)

    def test_wrong_type_is_rejected(self):
        with self.assertRaises(AISchemaError):
            ShortageInput.validate({'product_id': 'forty-two', 'warehouse_id': 7})

    def test_boolean_is_not_an_integer(self):
        """bool subclasses int in Python; a flag where an id belongs is a defect."""
        with self.assertRaises(AISchemaError):
            ShortageInput.validate({'product_id': True, 'warehouse_id': 7})

    def test_range_is_enforced(self):
        with self.assertRaises(AISchemaError):
            ShortageInput.validate({'product_id': 0, 'warehouse_id': 7})

    def test_bad_date_is_rejected(self):
        with self.assertRaises(AISchemaError):
            ShortageInput.validate({
                'product_id': 1, 'warehouse_id': 1, 'required_date': '04/09/2026',
            })

    def test_nested_and_list_validate(self):
        result = VendorOutput.validate({
            'vendor': {'id': 3, 'name': 'Jeddah Plastic Industries'},
            'lines': [{'product_id': 1, 'quantity': 486000.0}],
        })
        self.assertEqual(result['vendor']['name'], 'Jeddah Plastic Industries')
        self.assertEqual(result['lines'][0]['quantity'], 486000.0)
        self.assertFalse(result['urgent'])

    def test_undeclared_key_inside_a_nested_object_is_rejected(self):
        """This is the leak the output schema exists to stop."""
        with self.assertRaises(AISchemaError):
            VendorOutput.validate({
                'vendor': {'id': 3, 'name': 'Jeddah Plastic', 'bank_ids': [9]},
                'lines': [],
            })

    def test_list_length_is_capped(self):
        with self.assertRaises(AISchemaError):
            VendorOutput.validate({
                'vendor': {'id': 1, 'name': 'x'},
                'lines': [{'product_id': i, 'quantity': 1.0} for i in range(4)],
            })

    def test_enum_accepts_a_declared_value(self):
        result = VendorOutput.validate({
            'vendor': {'id': 1, 'name': 'x'}, 'lines': [], 'level': '2',
        })
        self.assertEqual(result['level'], '2')

    def test_enum_rejects_anything_else(self):
        with self.assertRaises(AISchemaError):
            VendorOutput.validate({
                'vendor': {'id': 1, 'name': 'x'}, 'lines': [], 'level': '9',
            })

    def test_field_names(self):
        self.assertEqual(
            ShortageInput.field_names(),
            {'product_id', 'warehouse_id', 'required_date'},
        )

    def test_to_json_schema_is_the_shape_the_model_sees(self):
        spec = ShortageInput.to_json_schema()
        self.assertEqual(spec['type'], 'object')
        self.assertFalse(spec['additionalProperties'])
        self.assertEqual(sorted(spec['required']), ['product_id', 'warehouse_id'])
        self.assertEqual(spec['properties']['product_id']['type'], 'integer')
        self.assertEqual(spec['properties']['product_id']['minimum'], 1)
        self.assertEqual(spec['properties']['required_date']['format'], 'date')

    def test_json_schema_and_validator_agree_on_the_field_set(self):
        """The shape the model is told about is the shape the validator accepts."""
        spec = ShortageInput.to_json_schema()
        self.assertEqual(set(spec['properties']), ShortageInput.field_names())
