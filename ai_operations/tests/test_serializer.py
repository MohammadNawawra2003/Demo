import pathlib
import re

from odoo.tests import tagged

from ..services import blocklist
from ..services.enums import DenialReason
from ..services.exceptions import AIAccessDenied, AIBlocklistViolation
from ..services.schema import Int, Nested, Schema, Str
from .common import AIOperationsCommon


class VendorOutput(Schema):
    """What a procurement tool is allowed to say about a vendor."""
    id = Int()
    name = Str()
    ref = Str(required=False)


class LeakyOutput(Schema):
    id = Int()
    api_key = Str()          # a schema that should never have been written


@tagged('post_install', '-at_install', 'ai_security')
class TestSerializer(AIOperationsCommon):
    """Document C 8. Nothing serialises unless it is declared."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.serializer = cls.env['ai.operations.serializer']
        cls.env['ai.operations.model.permission'].create({
            'profile_id': cls.profile.id,
            'model_id': cls.env['ir.model']._get('res.partner').id,
            'perm_read': True,
        })
        cls.vendor = cls.env['res.partner'].create({
            'name': 'Jeddah Plastic Industries',
            'ref': 'JPI-001',
            'comment': 'internal note nobody outside should read',
            'vat': 'SA1234567890',
        })

    def _ctx(self):
        from ..services.context import ExecutionContext
        return ExecutionContext(
            env=self.env, profile=self.profile, execution_user=self.env.user,
            execution_mode='INTERACTIVE', trigger='CHAT',
            company_ids=(self.company.id,), autonomy=2,
            tool_code='test.serialise', correlation_id='corr-ser',
            session_id='s', audit_id=0, policy_version='1.0.0')

    # ==================================================================
    # T-41 / T-45 -- what comes out is only what was declared
    # ==================================================================

    def test_t41_vendor_output_carries_no_bank_details(self):
        """Not excluded. Unreachable: the schema declares three keys."""
        result = self.serializer.serialize_record(
            self._ctx(), self.vendor, {'id': 'id', 'name': 'name', 'ref': 'ref'})
        self.assertEqual(set(result), {'id', 'name', 'ref'})
        for leaked in ('bank_ids', 'vat', 'comment', 'credit', 'debit'):
            self.assertNotIn(leaked, result)

    def test_t41_declaring_a_blocklisted_field_is_refused(self):
        """And if a schema did try, the blocklist stops it as a defect."""
        with self.assertRaises(AIBlocklistViolation):
            self.serializer.serialize_record(
                self._ctx(), self.vendor, {'id': 'id', 'bank': 'bank_ids'})

    def test_t45_an_undeclared_sensitive_field_simply_never_appears(self):
        """The Manufacturing-asks-for-purchase-price shape, on a base model:
        the value exists on the record and the schema does not mention it."""
        self.assertTrue(self.vendor.vat, "premise: the data is really there")
        result = self.serializer.serialize_record(
            self._ctx(), self.vendor, {'id': 'id', 'name': 'name'})
        self.assertNotIn('vat', result)
        self.assertNotIn(self.vendor.vat, str(result))

    def test_serialize_emits_only_declared_keys(self):
        result = self.serializer.serialize(
            self._ctx(),
            {'id': 1, 'name': 'JPI', 'ref': 'X', 'credit': 999.0},
            VendorOutput)
        self.assertEqual(set(result), {'id', 'name', 'ref'})

    # ==================================================================
    # T-42 -- the ban on read()
    # ==================================================================

    def test_t42_no_tool_pack_calls_read(self):
        """CI check 2 as a test, so it fails in the suite and not only in CI."""
        root = pathlib.Path(__file__).resolve().parent.parent
        offenders = []
        for path in (root / 'tools').rglob('*.py'):
            source = path.read_text()
            for banned in (r'\.read\(', r'\.read_group\(', r'fields_get\(',
                           r'json\.dumps\(record'):
                if re.search(banned, source):
                    offenders.append('%s: %s' % (path.name, banned))
        self.assertFalse(offenders, "banned serialisation call(s): %s" % offenders)

    def test_t42_the_serialiser_never_returns_an_odoo_object(self):
        result = self.serializer.serialize_record(
            self._ctx(), self.vendor, {'id': 'id', 'name': 'name'})
        for value in result.values():
            self.assertNotIsInstance(value, type(self.vendor))

    # ==================================================================
    # T-43 -- a blocklist hit is a defect
    # ==================================================================

    def test_t43_blocklisted_key_in_the_payload_raises(self):
        with self.assertRaises(AIBlocklistViolation):
            self.serializer.assert_clean(self._ctx(), {'api_key': 'sk-live-xxx'})

    def test_t43_a_blocklisted_key_stops_serialisation(self):
        """Auditing it is the runtime's job, outside the savepoint (B3-b)."""
        with self.assertRaises(AIBlocklistViolation):
            self.serializer.serialize(self._ctx(), {'id': 1, 'api_key': 'x'}, LeakyOutput)

    def test_the_serialiser_does_not_audit_from_inside_the_savepoint(self):
        """Finding B3-b, closed by ordering rather than infrastructure.

        Serialisation runs inside the savepoint a failure rolls back, so a row
        written here would be rolled back with the failure it records. The
        runtime audits after the rollback instead --
        ``test_a_failure_inside_the_savepoint_is_still_audited`` proves the row
        survives.
        """
        Log = self.env['ai.operations.audit.log']
        with self.assertRaises(AIBlocklistViolation):
            self.serializer.assert_clean(self._ctx(), {'password': 'hunter2'})
        self.env.flush_all()
        self.assertFalse(Log.search([('correlation_id', '=', 'corr-ser')]))

    def test_t43_nested_and_listed_keys_are_scanned_too(self):
        with self.assertRaises(AIBlocklistViolation):
            self.serializer.assert_clean(
                self._ctx(), {'lines': [{'vendor': {'totp_secret': 'x'}}]})

    def test_t43_a_clean_payload_passes(self):
        payload = {'id': 1, 'name': 'JPI', 'lines': [{'product_id': 2}]}
        self.assertEqual(self.serializer.assert_clean(self._ctx(), payload), payload)

    def test_blocked_model_is_unreachable_entirely(self):
        self.assertTrue(blocklist.is_model_blocked('hr.employee'))
        self.assertTrue(blocklist.is_model_blocked('ir.config_parameter'))
        self.assertTrue(blocklist.is_field_blocked('hr.employee', 'name'))

    def test_ir_config_parameter_has_no_carve_out(self):
        """Where a database-stored API key would have lived."""
        self.assertTrue(blocklist.is_field_blocked('ir.config_parameter', 'value'))

    # ==================================================================
    # T-44 -- undeclared output is dropped, and shouted about
    # ==================================================================

    def test_t44_undeclared_output_field_is_dropped(self):
        with self.assertLogs('odoo.addons.ai_operations.services.serializer',
                             level='ERROR') as captured:
            result = self.serializer.serialize(
                self._ctx(), {'id': 1, 'name': 'JPI', 'sneaky': 'value'}, VendorOutput)
        self.assertNotIn('sneaky', result)
        self.assertIn('sneaky', ''.join(captured.output))
        self.assertIn('defect', ''.join(captured.output).lower())

    def test_a_tool_returning_a_non_dict_is_refused(self):
        with self.assertRaises(AIBlocklistViolation):
            self.serializer.serialize(self._ctx(), ['not', 'a', 'dict'], VendorOutput)

    # ==================================================================
    # Relational traversal
    # ==================================================================

    def test_a_hop_rechecks_the_permission_on_the_target_model(self):
        """A dotted path must not walk out of the agent's scope one dot at a
        time. res.country is not in this agent's allowlist."""
        with self.assertRaises(AIAccessDenied) as caught:
            self.serializer.serialize_record(
                self._ctx(), self.vendor, {'country': 'country_id.name'})
        self.assertEqual(caught.exception.reason, DenialReason.MODEL_NOT_PERMITTED)

    def test_a_permitted_hop_is_allowed(self):
        self.env['ai.operations.model.permission'].create({
            'profile_id': self.profile.id,
            'model_id': self.env['ir.model']._get('res.country').id,
            'perm_read': True,
        })
        self.vendor.country_id = self.env.ref('base.sa')
        result = self.serializer.serialize_record(
            self._ctx(), self.vendor, {'country': 'country_id.name'})
        self.assertEqual(result['country'], self.env.ref('base.sa').name)

    def test_a_path_ending_on_a_relation_emits_ids_not_records(self):
        self.env['ai.operations.model.permission'].create({
            'profile_id': self.profile.id,
            'model_id': self.env['ir.model']._get('res.country').id,
            'perm_read': True,
        })
        self.vendor.country_id = self.env.ref('base.sa')
        result = self.serializer.serialize_record(
            self._ctx(), self.vendor, {'country': 'country_id'})
        self.assertEqual(result['country'], self.env.ref('base.sa').id)

    def test_an_unknown_field_in_a_path_is_refused(self):
        with self.assertRaises(AIBlocklistViolation):
            self.serializer.serialize_record(
                self._ctx(), self.vendor, {'x': 'no_such_field'})

    def test_max_records_caps_a_recordset(self):
        partners = self.env['res.partner'].create(
            [{'name': 'Bulk %d' % i} for i in range(6)])
        rows = self.serializer.serialize_records(
            self._ctx(), partners, {'id': 'id', 'name': 'name'}, limit=3)
        self.assertEqual(len(rows), 3)
