from odoo import Command
from odoo.exceptions import AccessError
from odoo.tests import tagged
from odoo.tools import mute_logger

from .common import AIOperationsCommon


@tagged('post_install', '-at_install', 'ai_security')
class TestRoleUIAccess(AIOperationsCommon):
    """Can each role actually OPEN the screens its job requires?

    Every earlier role test called ``search()`` and ``write()`` directly, which
    is why they all passed while Configuration → Tools raised an Access Error in
    the browser. These exercise the web read path the client actually uses --
    ``get_views``, ``web_search_read``, ``web_read``, ``default_get``,
    ``name_search`` -- as genuine internal users who are **not** Odoo
    administrators.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Tool = cls.env['ai.operations.tool']
        cls.ModelPerm = cls.env['ai.operations.model.permission']

        def role(login, name, xmlid):
            user = cls._make_user(login, name)
            user.write({'group_ids': [Command.link(cls.env.ref(xmlid).id)]})
            return user

        cls.tech = role('ai.ui.tech', 'AI Technical Admin',
                        'ai_operations.group_ai_technical_admin')
        cls.sec = role('ai.ui.sec', 'AI Security Admin',
                       'ai_operations.group_ai_security_admin')
        cls.auditor = role('ai.ui.auditor', 'AI Auditor',
                           'ai_operations.group_ai_auditor')
        cls.plain = role('ai.ui.plain', 'AI Plain User',
                         'ai_operations.group_ai_user')
        cls.outsider = cls._make_user('ai.ui.outsider', 'No AI Group')

    # -- the premise: these are not Odoo administrators --------------------

    def test_the_ai_roles_are_not_odoo_administrators(self):
        """If they were, none of the tests below would prove anything."""
        for user in (self.tech, self.sec, self.auditor, self.plain):
            self.assertFalse(user._has_group('base.group_system'), user.name)
            self.assertFalse(user._has_group('base.group_erp_manager'), user.name)

    # -- Technical Administrator opens Configuration -> Tools ---------------

    def test_technical_admin_can_open_the_tools_screen(self):
        """The manual failure, as a test: get_views then web_search_read with
        the list view's own field set."""
        Tool = self.Tool.with_user(self.tech)
        Tool.get_views([(None, 'list'), (None, 'form'), (None, 'search')])
        result = Tool.web_search_read([], {
            'code': {}, 'name': {}, 'category': {}, 'autonomy_required': {},
            'idempotent': {}, 'registered': {}, 'enabled': {}, 'version': {},
        }, limit=80)
        self.assertGreaterEqual(result['length'], 1)

    def test_technical_admin_sees_the_kernel_tool_on_that_screen(self):
        rows = self.Tool.with_user(self.tech).web_search_read(
            [], {'code': {}, 'registered': {}, 'enabled': {}}, limit=80)
        codes = [r['code'] for r in rows['records']]
        self.assertIn('core.describe_scope', codes)

    def test_technical_admin_can_open_the_tool_form(self):
        tool = self.Tool.with_user(self.tech).search(
            [('code', '=', 'core.describe_scope')])
        record = tool.web_read({
            'code': {}, 'name': {}, 'description': {}, 'models_used_names': {},
            'category': {}, 'autonomy_required': {}, 'idempotent': {},
            'registered': {}, 'enabled': {}, 'assignment_ids': {'fields': {}},
        })
        self.assertEqual(record[0]['models_used_names'], 'res.company')

    def test_technical_admin_can_click_new_on_tools(self):
        Tool = self.Tool.with_user(self.tech)
        Tool.default_get(list(Tool._fields))
        draft = Tool.new({})
        self.assertFalse(draft.registered)

    def test_no_view_exposes_an_ir_model_relation_on_the_tool(self):
        """Root cause, locked. ir.model is administrator-only metadata
        (base.group_user gets 0,0,0,0), so a relation to it makes this record
        unreadable by the roles meant to configure it."""
        self.assertNotIn('models_used', self.Tool._fields)
        for field in self.Tool._fields.values():
            self.assertNotEqual(
                getattr(field, 'comodel_name', None), 'ir.model',
                "%s relates the tool to administrator-only metadata" % field.name)

    # -- Technical Administrator's powers, and their limits ------------------

    def test_technical_admin_can_enable_a_tool(self):
        tool = self.Tool.with_user(self.tech).search(
            [('code', '=', 'core.describe_scope')])
        tool.write({'enabled': True})
        self.assertTrue(tool.enabled)

    @mute_logger('odoo.addons.base.models.ir_model')
    def test_technical_admin_cannot_alter_a_model_permission(self):
        permission = self.ModelPerm.create({
            'profile_id': self.profile.id,
            'model_id': self.env['ir.model']._get('res.partner').id,
            'perm_read': True})
        with self.assertRaises(AccessError):
            permission.with_user(self.tech).write({'perm_write': True})

    @mute_logger('odoo.addons.base.models.ir_model')
    def test_technical_admin_gets_no_ir_model_access(self):
        """Enabling a tool never required it, and it is not granted."""
        with self.assertRaises(AccessError):
            self.env['ir.model'].with_user(self.tech).search([], limit=1)

    # -- Security Administrator configures permissions -----------------------

    def test_security_admin_can_use_the_model_picker(self):
        """Second defect found manually: without ir.model read, name_search
        fails and the Security Administrator cannot choose a model at all --
        which is the entire job of the role."""
        results = self.env['ir.model'].with_user(self.sec).name_search(
            'res.partner', limit=8)
        self.assertTrue(results)

    def test_security_admin_can_open_and_create_a_model_permission(self):
        Perm = self.ModelPerm.with_user(self.sec)
        Perm.get_views([(None, 'list'), (None, 'form')])
        permission = Perm.create({
            'profile_id': self.profile.id,
            'model_id': self.env['ir.model']._get('res.currency').id,
            'perm_read': True})
        self.assertTrue(permission.id)

    def test_security_admins_ir_model_grant_is_read_only(self):
        """One targeted row, not Access Rights administration."""
        IrModel = self.env['ir.model'].with_user(self.sec)
        IrModel.check_access('read')
        for operation in ('write', 'create', 'unlink'):
            with self.assertRaises(AccessError, msg=operation):
                IrModel.check_access(operation)

    @mute_logger('odoo.addons.base.models.ir_model')
    def test_security_admin_still_cannot_enable_a_tool(self):
        """The separation the whole design rests on, re-asserted after the grant."""
        tool = self.Tool.search([('code', '=', 'core.describe_scope')])
        with self.assertRaises(AccessError):
            tool.with_user(self.sec).write({'enabled': True})

    # -- everyone below gets no metadata -------------------------------------

    @mute_logger('odoo.addons.base.models.ir_model')
    def test_auditor_gets_no_ir_model_access(self):
        with self.assertRaises(AccessError):
            self.env['ir.model'].with_user(self.auditor).search([], limit=1)

    @mute_logger('odoo.addons.base.models.ir_model')
    def test_plain_ai_user_gets_no_ir_model_access(self):
        with self.assertRaises(AccessError):
            self.env['ir.model'].with_user(self.plain).search([], limit=1)

    def test_plain_ai_user_may_read_tools_because_the_guard_must(self):
        """Not a leak, and not a convenience.

        The guard resolves a tool record as the executing identity and
        ``sudo()`` is banned, so an ordinary agent user must be able to read
        this table or the guard cannot run. Tool metadata is a name, a category
        and a docstring; nothing about it is sensitive. Reaching the screen is a
        separate question, and the Configuration menu still requires Auditor.
        """
        rows = self.Tool.with_user(self.plain).web_search_read(
            [], {'code': {}}, limit=80)
        self.assertTrue(rows['length'])

    @mute_logger('odoo.addons.base.models.ir_model')
    def test_plain_ai_user_cannot_configure_a_tool(self):
        """Reading is what the guard needs. Configuring is not."""
        tool = self.Tool.search([('code', '=', 'core.describe_scope')])
        with self.assertRaises(AccessError):
            tool.with_user(self.plain).write({'enabled': True})

    def test_plain_ai_user_has_no_configuration_menu(self):
        config = self.env.ref('ai_operations.menu_ai_operations_configuration')
        visible = self.env['ir.ui.menu'].with_user(self.plain)._visible_menu_ids()
        self.assertNotIn(config.id, visible)

    @mute_logger('odoo.addons.base.models.ir_model')
    def test_a_user_with_no_ai_group_reaches_nothing(self):
        with self.assertRaises(AccessError):
            self.Tool.with_user(self.outsider).search([], limit=1)
        with self.assertRaises(AccessError):
            self.env['ir.model'].with_user(self.outsider).search([], limit=1)

    # -- the permission screens render without ir.model ----------------------

    def test_permission_lists_show_the_stored_model_name(self):
        """The lists display model_name, a stored Char, so they render for any
        authorised role without touching administrator-only metadata."""
        self.ModelPerm.create({
            'profile_id': self.profile.id,
            'model_id': self.env['ir.model']._get('res.partner').id,
            'perm_read': True})
        rows = self.ModelPerm.with_user(self.auditor).web_search_read(
            [], {'profile_id': {'fields': {'display_name': {}}},
                 'model_name': {}, 'perm_read': {}}, limit=80)
        self.assertTrue(rows['length'])
        self.assertEqual(rows['records'][0]['model_name'], 'res.partner')
