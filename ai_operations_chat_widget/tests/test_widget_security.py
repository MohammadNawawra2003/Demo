"""The widget is a surface. It must not become a second way in.

Every test here asks the same question from a different angle: does going
through the widget reach anything that going through Discuss would not?
"""

from odoo import Command
from odoo.exceptions import AccessError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install', 'ai_security')
class TestChatWidgetSecurity(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Profile = cls.env['ai.operations.agent.profile']
        cls.company = cls.env['res.company'].create({'name': 'Widget Co'})
        cls.other_company = cls.env['res.company'].create({'name': 'Widget Other Co'})

        cls.reviewer = cls._user('widget.reviewer', cls.company)
        cls.escalation = cls._user('widget.escalation', cls.company)
        cls.employee = cls._user('widget.employee', cls.company)
        cls.employee.write({'group_ids': [
            Command.link(cls.env.ref('ai_operations.group_ai_user').id)]})
        cls.stranger = cls._user('widget.stranger', cls.company)
        cls.outsider = cls._user('widget.outsider', cls.other_company)
        cls.outsider.write({'group_ids': [
            Command.link(cls.env.ref('ai_operations.group_ai_user').id)]})

        cls.partner = cls.env['res.partner'].create({'name': 'Widget Agent'})
        cls.profile = cls.Profile.create({
            'name': 'Widget Agent', 'code': 'wg_agent',
            'company_ids': [Command.set([cls.company.id])],
            'partner_id': cls.partner.id,
            'max_autonomy_level': '2',
            'default_review_user_id': cls.reviewer.id,
            'default_escalation_user_id': cls.escalation.id,
        })

    @classmethod
    def _user(cls, login, company):
        return cls.env['res.users'].create({
            'name': login, 'login': login, 'company_id': company.id,
            'company_ids': [Command.set([company.id])]})

    # -- who may see the launcher at all -------------------------------

    def test_a_user_without_the_ai_group_is_offered_nothing(self):
        profiles = self.Profile.with_user(self.stranger).ai_widget_profiles()
        self.assertEqual(profiles, [],
                         "the launcher would appear for a user who cannot use it")

    def test_an_ai_user_is_offered_their_own_profiles(self):
        profiles = self.Profile.with_user(self.employee).ai_widget_profiles()
        self.assertIn(self.profile.id, [p['id'] for p in profiles])

    def test_another_companys_profiles_are_never_offered(self):
        profiles = self.Profile.with_user(self.outsider).ai_widget_profiles()
        self.assertNotIn(self.profile.id, [p['id'] for p in profiles],
                         "a profile from another company was offered")

    # -- forging a profile id ------------------------------------------

    def test_a_user_without_the_ai_group_cannot_send(self):
        with self.assertRaises(AccessError):
            self.profile.with_user(self.stranger).ai_widget_send('hello')

    def test_a_forged_profile_id_from_another_company_is_refused(self):
        with self.assertRaises(Exception):
            self.profile.with_user(self.outsider).ai_widget_send('hello')

    # -- it is the same surface, not a second one ----------------------

    def test_the_widget_talks_through_the_discuss_channel(self):
        result = self.profile.with_user(self.employee).ai_widget_send('hello')
        channel = self.env['discuss.channel'].browse(result['channel_id'])
        self.assertEqual(channel.ai_profile_id, self.profile,
                         "the widget invented a conversation of its own")
        self.assertEqual(channel.channel_type, 'chat')

    def test_the_widget_and_discuss_share_one_conversation(self):
        """"Open in Discuss" has to land on the same conversation, or the two
        surfaces would keep separate histories of the same relationship."""
        sent = self.profile.with_user(self.employee).ai_widget_send('hello')
        action = self.profile.with_user(self.employee).action_open_chat()
        self.assertEqual(sent['channel_id'], action['params']['channel_id'])

    def test_a_widget_message_is_audited_like_any_other(self):
        Log = self.env['ai.operations.audit.log']
        before = Log.search_count([])
        self.profile.with_user(self.employee).ai_widget_send('hello')
        self.assertGreater(Log.search_count([]), before,
                           "a widget message left no audit trail")

    def test_the_reply_is_neutral_when_the_provider_fails(self):
        """No provider is configured, so the run fails. The user must get a
        sentence, not a traceback and not a vendor name."""
        result = self.profile.with_user(self.employee).ai_widget_send('hello')
        self.assertTrue(result['reply'])
        for leak in ('Traceback', 'anthropic', 'AIProviderError', 'api_key'):
            self.assertNotIn(leak, result['reply'])

    def test_history_does_not_cross_between_users(self):
        colleague = self._user('widget.colleague', self.company)
        colleague.write({'group_ids': [
            Command.link(self.env.ref('ai_operations.group_ai_user').id)]})

        mine = self.profile.with_user(self.employee).ai_widget_send('my secret topic')
        theirs = self.profile.with_user(colleague).ai_widget_send('what were we saying?')

        self.assertNotEqual(mine['channel_id'], theirs['channel_id'],
                            "two employees shared one conversation")
