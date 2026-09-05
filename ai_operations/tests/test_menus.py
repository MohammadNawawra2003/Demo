from odoo import Command
from odoo.tests import tagged

from .common import AIOperationsCommon


@tagged('post_install', '-at_install', 'ai_security')
class TestAppMenuVisibility(AIOperationsCommon):
    """Regression cover for the missing app tile.

    ``ir.ui.menu._visible_menu_ids()`` makes a menu visible only when it has an
    action whose model the user may read, then propagates that visibility up to
    its ancestors. These tests assert against that method rather than against a
    proxy such as the icon attachment, which can be perfectly correct while the
    tile is still invisible.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.root_menu = cls.env.ref('ai_operations.menu_ai_operations_root')
        cls.config_menu = cls.env.ref('ai_operations.menu_ai_operations_configuration')

        cls.auditor = cls._make_user('ai.menu.auditor', 'Menu Auditor')
        cls.auditor.write({'group_ids': [
            Command.link(cls.env.ref('ai_operations.group_ai_auditor').id)]})
        cls.plain_user = cls._make_user('ai.menu.plain', 'No AI Groups At All')

    def _visible_to(self, user):
        return self.env['ir.ui.menu'].with_user(user)._visible_menu_ids()

    # -- the app must exist as an app -------------------------------------

    def test_root_menu_is_a_top_level_app(self):
        self.assertFalse(self.root_menu.parent_id)
        self.assertEqual(
            self.root_menu.web_icon, 'ai_operations,static/description/icon.png')

    def test_root_menu_carries_no_group_of_its_own(self):
        """The regression itself.

        A group on the root cannot add visibility -- Odoo already hides a parent
        whose descendants are all hidden -- it can only subtract, hiding the
        whole app from someone who legitimately has a child menu. This root
        carried group_ai_user while its only child required group_ai_auditor,
        so the app was invisible to every user in the database.
        """
        self.assertFalse(
            self.root_menu.group_ids,
            "the root menu must not restrict itself; restrict the sections instead")

    # -- who sees it -------------------------------------------------------

    def test_tile_visible_to_the_auditor(self):
        self.assertIn(self.root_menu.id, self._visible_to(self.auditor))

    def test_tile_visible_to_the_bootstrapped_administrator(self):
        """The app must be openable on the day it is installed."""
        admin = self.env.ref('base.user_admin')
        self.assertIn(self.root_menu.id, self._visible_to(admin))

    def test_configuration_section_visible_to_the_auditor(self):
        self.assertIn(self.config_menu.id, self._visible_to(self.auditor))

    # -- and who does not --------------------------------------------------

    def test_tile_hidden_from_a_user_with_no_ai_group(self):
        """Fixing the tile must not hand the app to everybody."""
        visible = self._visible_to(self.plain_user)
        self.assertNotIn(self.root_menu.id, visible)
        self.assertNotIn(self.config_menu.id, visible)

    def test_configuration_still_requires_the_auditor_group(self):
        self.assertIn(
            self.env.ref('ai_operations.group_ai_auditor'),
            self.config_menu.group_ids)

    # -- the bootstrap grant, and its limits -------------------------------

    def test_administrator_is_bootstrapped_into_both_admin_roles(self):
        admin = self.env.ref('base.user_admin')
        self.assertTrue(admin._has_group('ai_operations.group_ai_security_admin'))
        self.assertTrue(admin._has_group('ai_operations.group_ai_technical_admin'))

    def test_group_system_still_implies_no_ai_group(self):
        """Document C 11: settings access is not AI security access.

        The bootstrap grants two groups to one named user. It must not have
        turned into an implication from base.group_system, which would hand the
        AI security model to every administrator in every database.
        """
        system_group = self.env.ref('base.group_system')
        for xmlid in ('group_ai_user', 'group_ai_auditor',
                      'group_ai_security_admin', 'group_ai_technical_admin'):
            self.assertNotIn(
                self.env.ref('ai_operations.%s' % xmlid),
                system_group.all_implied_ids,
                "base.group_system must not imply %s" % xmlid)

    def test_a_fresh_system_administrator_does_not_inherit_the_app(self):
        """Being an Odoo administrator is not being an AI administrator."""
        sysadmin = self._make_user('ai.menu.sysadmin', 'Fresh Sysadmin')
        sysadmin.write({'group_ids': [
            Command.link(self.env.ref('base.group_system').id)]})
        self.assertFalse(sysadmin._has_group('ai_operations.group_ai_security_admin'))
        self.assertNotIn(self.root_menu.id, self._visible_to(sysadmin))
