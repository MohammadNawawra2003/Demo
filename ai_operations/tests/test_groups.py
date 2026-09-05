from odoo import Command
from odoo.exceptions import AccessError
from odoo.tests import tagged
from odoo.tools import mute_logger

from .common import AIOperationsCommon


@tagged('post_install', '-at_install', 'ai_security')
class TestSecurityGroups(AIOperationsCommon):
    """Document C 11 -- neither administrator role alone can both expose a
    capability and grant an agent access to it."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.auditor = cls._make_user('ai.test.auditor', 'AI Auditor')
        cls.auditor.write({
            'group_ids': [Command.link(cls.env.ref('ai_operations.group_ai_auditor').id)],
        })
        cls.security_admin = cls._make_user('ai.test.secadmin', 'AI Security Admin')
        cls.security_admin.write({
            'group_ids': [
                Command.link(cls.env.ref('ai_operations.group_ai_security_admin').id)],
        })
        cls.technical_admin = cls._make_user('ai.test.techadmin', 'AI Technical Admin')
        cls.technical_admin.write({
            'group_ids': [
                Command.link(cls.env.ref('ai_operations.group_ai_technical_admin').id)],
        })

        cls.permission = cls.env['ai.operations.model.permission'].create({
            'profile_id': cls.profile.id,
            'model_id': cls.env['ir.model']._get('res.partner').id,
            'perm_read': True,
        })

    # -- the auditor reads everything and writes nothing -------------------

    def test_auditor_can_read_a_profile(self):
        self.assertTrue(self.profile.with_user(self.auditor).name)

    def test_auditor_can_read_a_permission(self):
        self.assertTrue(self.permission.with_user(self.auditor).model_id)

    @mute_logger('odoo.addons.base.models.ir_model')
    def test_auditor_cannot_write_a_profile(self):
        with self.assertRaises(AccessError):
            self.profile.with_user(self.auditor).write({'name': 'Rewritten'})

    @mute_logger('odoo.addons.base.models.ir_model')
    def test_auditor_cannot_write_a_permission(self):
        with self.assertRaises(AccessError):
            self.permission.with_user(self.auditor).write({'perm_write': True})

    @mute_logger('odoo.addons.base.models.ir_model')
    def test_auditor_cannot_create_a_profile(self):
        with self.assertRaises(AccessError):
            self.Profile.with_user(self.auditor).create({
                'name': 'Smuggled', 'code': 'smuggled',
                'company_ids': [Command.set([self.company.id])],
                'default_review_user_id': self.reviewer.id,
                'default_escalation_user_id': self.escalation.id,
            })

    # -- the separation that matters ---------------------------------------

    @mute_logger('odoo.addons.base.models.ir_model')
    def test_technical_admin_cannot_alter_a_model_permission(self):
        """The Technical Administrator may enable tools. It may never widen an
        agent's data scope."""
        with self.assertRaises(AccessError):
            self.permission.with_user(self.technical_admin).write({'perm_write': True})

    @mute_logger('odoo.addons.base.models.ir_model')
    def test_technical_admin_cannot_create_a_model_permission(self):
        with self.assertRaises(AccessError):
            self.ModelPermission.with_user(self.technical_admin).create({
                'profile_id': self.profile.id,
                'model_id': self._model('res.currency').id,
                'perm_read': True,
            })

    @mute_logger('odoo.addons.base.models.ir_model')
    def test_technical_admin_cannot_alter_an_action_permission(self):
        action = self.ActionPermission.create({
            'profile_id': self.profile.id,
            'model_id': self._model('res.partner').id,
            'action_code': 'CREATE_DRAFT',
        })
        with self.assertRaises(AccessError):
            action.with_user(self.technical_admin).write({'allowed': True})

    def test_technical_admin_can_read_a_permission(self):
        """It must be able to see the policy it is configuring providers for."""
        self.assertTrue(self.permission.with_user(self.technical_admin).model_id)

    def test_security_admin_can_write_a_permission(self):
        self.permission.with_user(self.security_admin).write({'perm_write': True})
        self.assertTrue(self.permission.perm_write)

    def test_security_admin_can_create_a_profile(self):
        profile = self.Profile.with_user(self.security_admin).create({
            'name': 'Quality Intelligence',
            'code': 'quality',
            'company_ids': [Command.set([self.company.id])],
            'default_review_user_id': self.reviewer.id,
            'default_escalation_user_id': self.escalation.id,
        })
        self.assertTrue(profile.id)

    # -- the guard has to be able to read policy without sudo() ------------

    def test_plain_ai_user_can_read_policy(self):
        """Not a convenience. The guard runs as the executing identity and
        sudo() is banned, so an ordinary user must be able to read the profile
        and permissions being enforced against them. See review finding B3."""
        user = self._make_user('ai.test.plainuser', 'Plain AI User')
        user.write({
            'group_ids': [Command.link(self.env.ref('ai_operations.group_ai_user').id)],
        })
        self.assertTrue(self.profile.with_user(user).name)
        self.assertTrue(self.permission.with_user(user).model_id)

    @mute_logger('odoo.addons.base.models.ir_model')
    def test_plain_ai_user_cannot_write_policy(self):
        user = self._make_user('ai.test.plainuser2', 'Plain AI User 2')
        user.write({
            'group_ids': [Command.link(self.env.ref('ai_operations.group_ai_user').id)],
        })
        with self.assertRaises(AccessError):
            self.permission.with_user(user).write({'perm_write': True})

    # -- group wiring -------------------------------------------------------

    def test_group_ladder_is_wired(self):
        user_group = self.env.ref('ai_operations.group_ai_user')
        auditor = self.env.ref('ai_operations.group_ai_auditor')
        security_admin = self.env.ref('ai_operations.group_ai_security_admin')
        technical_admin = self.env.ref('ai_operations.group_ai_technical_admin')

        self.assertIn(user_group, auditor.all_implied_ids)
        self.assertIn(auditor, security_admin.all_implied_ids)
        self.assertIn(auditor, technical_admin.all_implied_ids)

        # Neither administrator implies the other -- that is the separation.
        self.assertNotIn(technical_admin, security_admin.all_implied_ids)
        self.assertNotIn(security_admin, technical_admin.all_implied_ids)

    def test_the_deleted_approver_group_does_not_exist(self):
        """Review finding M4. There is no approval state machine, so a group
        whose only stated power is 'approve flagged actions' has nothing to do.
        Approval is a human pressing the native Confirm button."""
        self.assertFalse(
            self.env.ref('ai_operations.group_ai_approver', raise_if_not_found=False))
