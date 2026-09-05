from odoo import Command
from odoo.exceptions import AccessError
from odoo.tests import tagged
from odoo.tools import mute_logger

from ..services.registry import all_tools
from .common import AIOperationsCommon


@tagged('post_install', '-at_install', 'ai_security')
class TestToolMaterialisation(AIOperationsCommon):
    """Regression cover for "No tools registered yet".

    Session 2 reported a registered tool and passed its tests, while the Tools
    list was empty in the UI: the registry held ``core.describe_scope`` and the
    table held nothing, because nothing ever created the row. These tests assert
    the DATABASE state that the install produced, not the registry, which was
    correct the whole time.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Tool = cls.env['ai.operations.tool']

    # -- the records exist because installing made them --------------------

    def test_installing_materialises_the_kernel_tool(self):
        tool = self.Tool.search([('code', '=', 'core.describe_scope')])
        self.assertTrue(
            tool, "installing the module must materialise every registered tool")
        self.assertTrue(tool.registered)

    def test_every_registered_tool_has_a_record(self):
        """Swept across the registry, so a tool pack cannot ship half-wired."""
        codes = set(all_tools())
        materialised = set(
            self.Tool.with_context(active_test=False).search([]).mapped('code'))
        self.assertFalse(
            codes - materialised,
            "registered but not materialised: %s" % (codes - materialised))

    # -- ...and they arrive inert -----------------------------------------

    def _freshly_materialised(self, code='core.describe_scope'):
        """Re-materialise from scratch.

        These assert what the SYNC produces, not what the database happens to
        hold: a Technical Administrator enabling a tool is a legitimate act and
        must not break the suite. An earlier version of these tests read ambient
        configuration and duly went red on staging the moment a tool was
        enabled there.
        """
        self.Tool.with_context(active_test=False).search(
            [('code', '=', code)]).unlink()
        self.Tool._sync_from_registry()
        return self.Tool.search([('code', '=', code)])

    def test_materialised_tools_are_disabled(self):
        """Registration makes a tool configurable. It never makes it available."""
        tool = self._freshly_materialised()
        self.assertTrue(tool, "the sync must recreate the record")
        self.assertFalse(
            tool.enabled,
            "a tool must not become callable merely by existing in the code")

    def test_materialised_tools_have_no_assignment(self):
        tool = self._freshly_materialised()
        self.assertFalse(
            tool.assignment_ids,
            "no assignment means no access; materialisation grants nothing")

    def test_a_materialised_tool_is_still_refused_until_enabled(self):
        """The whole point: the row exists and the guard still says no."""
        from ..services.exceptions import AIAccessDenied
        self._freshly_materialised()
        with self.assertRaises(AIAccessDenied):
            self.Tool.record_for('core.describe_scope')

    # -- idempotence and the sync contract ---------------------------------

    def test_sync_is_idempotent(self):
        before = self.Tool.with_context(active_test=False).search_count([])
        self.Tool._sync_from_registry()
        self.Tool._sync_from_registry()
        after = self.Tool.with_context(active_test=False).search_count([])
        self.assertEqual(before, after, "re-syncing must not duplicate records")

    def test_sync_recreates_a_deleted_record(self):
        """This is what makes an upgrade self-healing."""
        self.Tool.search([('code', '=', 'core.describe_scope')]).unlink()
        self.assertFalse(self.Tool.search([('code', '=', 'core.describe_scope')]))
        self.Tool._sync_from_registry()
        self.assertTrue(self.Tool.search([('code', '=', 'core.describe_scope')]))

    def test_sync_leaves_existing_configuration_alone(self):
        """An upgrade must not reset what a Technical Administrator chose."""
        tool = self.Tool.search([('code', '=', 'core.describe_scope')])
        tool.write({'enabled': True, 'timeout_seconds': 45})
        self.Tool._sync_from_registry()
        self.assertTrue(tool.enabled)
        self.assertEqual(tool.timeout_seconds, 45)

    def test_derived_name_is_readable(self):
        self.assertEqual(
            self.Tool._default_tool_name('procurement.prepare_draft_rfq'),
            'Prepare Draft Rfq')

    # -- the mirror is readonly -------------------------------------------

    def test_description_is_computed_and_readonly(self):
        """It goes into the model's context as the tool definition, so an
        editable description would be a prompt-injection surface reachable by
        configuration rather than by code."""
        field = self.Tool._fields['description']
        self.assertTrue(field.compute)
        self.assertTrue(field.readonly)
        self.assertFalse(field.inverse)

    def test_the_mirrored_fields_all_come_from_the_decorator(self):
        for name in ('description', 'category', 'autonomy_required',
                     'idempotent', 'registered', 'models_used_names'):
            self.assertTrue(
                self.Tool._fields[name].compute,
                "%s must mirror the decorator, not be authored" % name)

    def test_materialised_record_matches_the_registry(self):
        tool = self.Tool.search([('code', '=', 'core.describe_scope')])
        spec = all_tools()['core.describe_scope']
        self.assertEqual(tool.category, spec.category)
        self.assertEqual(tool.autonomy_required, spec.autonomy)
        self.assertEqual(tool.description, spec.description)
        self.assertEqual(tool.models_used_names, ', '.join(spec.models))

    # -- and it is visible to the people who configure it -------------------

    def test_technical_admin_sees_and_may_enable_it(self):
        tech = self._make_user('ai.mat.tech', 'Technical Admin')
        tech.write({'group_ids': [
            Command.link(self.env.ref('ai_operations.group_ai_technical_admin').id)]})
        tool = self.Tool.with_user(tech).search([('code', '=', 'core.describe_scope')])
        self.assertTrue(tool, "the Technical Administrator must see the Tools list")
        tool.write({'enabled': True})
        self.assertTrue(tool.enabled)

    @mute_logger('odoo.addons.base.models.ir_model')
    def test_a_user_with_no_ai_group_sees_no_tools(self):
        outsider = self._make_user('ai.mat.outsider', 'No AI Group')
        with self.assertRaises(AccessError):
            self.Tool.with_user(outsider).search([])
