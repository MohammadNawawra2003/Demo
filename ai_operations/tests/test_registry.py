from odoo import Command
from odoo.exceptions import ValidationError
from odoo.tests import tagged

from ..services import registry as registry_module
from ..services.enums import AutonomyLevel, DenialReason, ToolCategory
from ..services.exceptions import AIAccessDenied, AIToolRegistrationError
from ..services.registry import ai_tool, get_tool, has_tool
from ..services.schema import Int, Schema, Str
from .common import AIOperationsCommon


class _OkInput(Schema):
    partner_id = Int(min=1)


class _OkOutput(Schema):
    name = Str()


class _ModelNamedInput(Schema):
    model = Str()


@tagged('post_install', '-at_install', 'ai_security')
class TestToolRegistry(AIOperationsCommon):

    def _register(self, code, **overrides):
        """Register a throwaway tool, cleaned up whether or not it registers."""
        self.addCleanup(registry_module._REGISTRY.pop, code, None)
        kwargs = {
            'category': ToolCategory.READ,
            'autonomy': AutonomyLevel.QUERY,
            'models': ['res.company'],
            'input_schema': _OkInput,
            'output_schema': _OkOutput,
        }
        kwargs.update(overrides)

        @ai_tool(code=code, **kwargs)
        def _tool(ctx, params):
            """A tool registered by the test suite."""
            return {}

        return _tool

    def _tool_record(self, code, enabled=True):
        return self.env['ai.operations.tool'].create({
            'name': code, 'code': code, 'enabled': enabled,
        })

    # -- T-01 to T-03: what the guard's first steps resolve ----------------

    def test_t01_unknown_tool_code(self):
        with self.assertRaises(AIAccessDenied) as caught:
            get_tool('procurement.definitely_not_a_tool')
        self.assertEqual(caught.exception.reason, DenialReason.UNKNOWN_TOOL)
        self.assertEqual(
            caught.exception.tool_code, 'procurement.definitely_not_a_tool')

    def test_t02_disabled_tool(self):
        self._register('test.disabled')
        self._tool_record('test.disabled', enabled=False)
        with self.assertRaises(AIAccessDenied) as caught:
            self.env['ai.operations.tool'].record_for('test.disabled')
        self.assertEqual(caught.exception.reason, DenialReason.TOOL_DISABLED)

    def test_t02_tool_with_no_record_at_all(self):
        """Registered in Python but never configured is still unavailable."""
        self._register('test.unconfigured')
        with self.assertRaises(AIAccessDenied) as caught:
            self.env['ai.operations.tool'].record_for('test.unconfigured')
        self.assertEqual(caught.exception.reason, DenialReason.TOOL_DISABLED)

    def test_t03_tool_not_assigned_to_profile(self):
        """No assignment means no access. There is no default grant."""
        self._register('test.unassigned')
        record = self._tool_record('test.unassigned')
        with self.assertRaises(AIAccessDenied) as caught:
            record.assignment_for(self.profile)
        self.assertEqual(caught.exception.reason, DenialReason.TOOL_NOT_ASSIGNED)

    def test_t03_assignment_present_but_disabled(self):
        self._register('test.assigned_off')
        record = self._tool_record('test.assigned_off')
        self.env['ai.operations.tool.assignment'].create({
            'profile_id': self.profile.id, 'tool_id': record.id, 'enabled': False,
        })
        with self.assertRaises(AIAccessDenied) as caught:
            record.assignment_for(self.profile)
        self.assertEqual(caught.exception.reason, DenialReason.TOOL_NOT_ASSIGNED)

    def test_assigned_and_enabled_resolves(self):
        self._register('test.assigned_on')
        record = self._tool_record('test.assigned_on')
        assignment = self.env['ai.operations.tool.assignment'].create({
            'profile_id': self.profile.id, 'tool_id': record.id,
        })
        self.assertEqual(record.assignment_for(self.profile), assignment)

    # -- T-04: configuration cannot outrun code ---------------------------

    def test_t04_tool_record_with_no_registry_entry_cannot_be_enabled(self):
        with self.assertRaises(ValidationError):
            self._tool_record('test.no_python_behind_it', enabled=True)

    def test_t04_unregistered_tool_record_may_exist_while_disabled(self):
        record = self._tool_record('test.placeholder', enabled=False)
        self.assertFalse(record.registered)
        with self.assertRaises(ValidationError):
            record.enabled = True

    # -- T-05: the registry closes ----------------------------------------

    def test_t05_runtime_registration_is_refused(self):
        registry_module.freeze_registry()
        self.addCleanup(setattr, registry_module, '_FROZEN', False)
        self.assertTrue(registry_module.is_frozen())
        with self.assertRaises(AIToolRegistrationError):
            self._register('test.too_late')

    # -- T-06 / T-07: prohibited tool shapes ------------------------------

    def test_t06_input_schema_field_named_model_is_rejected(self):
        with self.assertRaises(AIToolRegistrationError):
            self._register('test.takes_a_model', input_schema=_ModelNamedInput)

    def test_t07_wildcard_models_is_rejected(self):
        with self.assertRaises(AIToolRegistrationError):
            self._register('test.wildcard', models=['*'])

    def test_empty_models_is_rejected(self):
        with self.assertRaises(AIToolRegistrationError):
            self._register('test.no_models', models=[])

    # -- T-08 and the rest of the registration contract -------------------

    def test_t08_missing_output_schema_is_rejected(self):
        with self.assertRaises(AIToolRegistrationError):
            self._register('test.no_output', output_schema=None)

    def test_t08_missing_input_schema_is_rejected(self):
        with self.assertRaises(AIToolRegistrationError):
            self._register('test.no_input', input_schema=None)

    def test_duplicate_code_is_rejected(self):
        self._register('test.duplicate')
        with self.assertRaises(AIToolRegistrationError):
            self._register('test.duplicate')

    def test_wrong_signature_is_rejected(self):
        self.addCleanup(registry_module._REGISTRY.pop, 'test.bad_signature', None)
        with self.assertRaises(AIToolRegistrationError):
            @ai_tool(code='test.bad_signature', category=ToolCategory.READ,
                     autonomy=AutonomyLevel.QUERY, models=['res.company'],
                     input_schema=_OkInput, output_schema=_OkOutput)
            def _tool(context, arguments):
                """Wrong parameter names."""
                return {}

    def test_missing_docstring_is_rejected(self):
        """The docstring is the description the LLM sees, so it is mandatory."""
        self.addCleanup(registry_module._REGISTRY.pop, 'test.no_docstring', None)
        with self.assertRaises(AIToolRegistrationError):
            @ai_tool(code='test.no_docstring', category=ToolCategory.READ,
                     autonomy=AutonomyLevel.QUERY, models=['res.company'],
                     input_schema=_OkInput, output_schema=_OkOutput)
            def _tool(ctx, params):
                return {}

    # -- the kernel's own tool --------------------------------------------

    def test_kernel_ships_a_registered_read_tool(self):
        self.assertTrue(has_tool('core.describe_scope'))
        spec = get_tool('core.describe_scope')
        self.assertEqual(spec.category, ToolCategory.READ.value)
        self.assertEqual(spec.autonomy, int(AutonomyLevel.QUERY))
        self.assertEqual(spec.models, ('res.company',))
        self.assertTrue(spec.description)

    def test_tool_record_mirrors_the_decorator(self):
        """Admins configure. They never author."""
        record = self._tool_record('core.describe_scope')
        self.assertTrue(record.registered)
        self.assertEqual(record.category, ToolCategory.READ.value)
        self.assertEqual(record.autonomy_required, 0)
        self.assertIn('res.company', record.models_used.mapped('model'))
        self.assertIn('scope', record.description.lower())

    def test_no_registered_tool_takes_a_prohibited_parameter(self):
        """Swept across the whole registry, not just the tool under test."""
        for code, spec in registry_module.all_tools().items():
            offending = spec.input_schema.field_names() & registry_module.PROHIBITED_PARAM_NAMES
            self.assertFalse(
                offending, "tool %r accepts %s from the LLM" % (code, offending))


@tagged('post_install', '-at_install', 'ai_security')
class TestToolAssignmentSecurity(AIOperationsCommon):
    """Neither administrator role can both expose a capability and grant it."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.security_admin = cls._make_user('ai.t2.secadmin', 'AI Security Admin')
        cls.security_admin.write({'group_ids': [
            Command.link(cls.env.ref('ai_operations.group_ai_security_admin').id)]})
        cls.technical_admin = cls._make_user('ai.t2.techadmin', 'AI Technical Admin')
        cls.technical_admin.write({'group_ids': [
            Command.link(cls.env.ref('ai_operations.group_ai_technical_admin').id)]})
        cls.tool = cls.env['ai.operations.tool'].create({
            'name': 'Describe Scope', 'code': 'core.describe_scope',
        })

    def test_technical_admin_can_enable_a_tool(self):
        self.tool.with_user(self.technical_admin).write({'enabled': True})
        self.assertTrue(self.tool.enabled)

    def test_security_admin_cannot_enable_a_tool(self):
        """Tool registration confers business capability, so it is deliberately
        not in the Security Administrator's hands."""
        from odoo.exceptions import AccessError
        from odoo.tools import mute_logger
        with self.assertRaises(AccessError), mute_logger('odoo.addons.base.models.ir_model'):
            self.tool.with_user(self.security_admin).write({'enabled': True})

    def test_security_admin_can_assign_a_tool(self):
        assignment = self.env['ai.operations.tool.assignment'].with_user(
            self.security_admin).create({
                'profile_id': self.profile.id, 'tool_id': self.tool.id,
            })
        self.assertTrue(assignment.id)

    def test_technical_admin_cannot_assign_a_tool(self):
        from odoo.exceptions import AccessError
        from odoo.tools import mute_logger
        with self.assertRaises(AccessError), mute_logger('odoo.addons.base.models.ir_model'):
            self.env['ai.operations.tool.assignment'].with_user(
                self.technical_admin).create({
                    'profile_id': self.profile.id, 'tool_id': self.tool.id,
                })
