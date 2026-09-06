"""Session 12's real deliverable: the chat surface, and that it is a real entry
point into the one runtime.

Document C §9.3 specifies the surface as *"a `discuss.channel` between the
employee and the profile's partner"*, and Document D §11 pins the contract:
``session_id`` is the channel id, the identity is ``env.user``, and the
transcript is surfaced in the channel.

**Why these tests look the way they do.** T-99 already proves chat and cron are
one path — but it proves it by calling ``execute_tool()`` twice with different
trigger strings, which passes whether or not anything can produce a CHAT
trigger. That is how Session 12's STOP gate went green over an unbuilt
deliverable. So every test here starts from a **posted message on a real
channel** and asserts the runtime was reached; none of them calls ``run()``.
``test_the_runtime_really_runs_from_a_posted_message`` patches nothing at all.
"""

from markupsafe import Markup

from odoo import Command
from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged

from .common import AIOperationsCommon


@tagged('post_install', '-at_install', 'ai_security')
class TestChatEntryPoint(AIOperationsCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Log = cls.env['ai.operations.audit.log']
        cls.agent_partner = cls.env['res.partner'].create({'name': 'Kernel Test Agent'})
        cls.profile.write({'partner_id': cls.agent_partner.id})

        cls.employee = cls._make_user('ai.test.chat.employee', 'Chat Employee')
        cls.employee.write({'group_ids': [
            Command.link(cls.env.ref('ai_operations.group_ai_user').id)]})
        cls.stranger = cls._make_user('ai.test.chat.stranger', 'No AI Group')

    # ------------------------------------------------------------------
    # Opening a channel — B-i and B-iv
    # ------------------------------------------------------------------

    def _open(self, user=None):
        profile = self.profile.with_user(user or self.employee)
        return profile.action_open_chat()

    def _channel_of(self, action):
        return self.env['discuss.channel'].browse(action['params']['channel_id'])

    def test_opening_a_chat_binds_the_channel_to_the_profile(self):
        """B-i: the binding is a field on the channel, created on demand."""
        channel = self._channel_of(self._open())
        self.assertEqual(channel.ai_profile_id, self.profile)
        self.assertEqual(channel.channel_type, 'chat')
        self.assertIn(self.agent_partner, channel.channel_member_ids.partner_id)
        self.assertIn(self.employee.partner_id, channel.channel_member_ids.partner_id)

    def test_opening_the_same_chat_twice_reuses_the_channel(self):
        first = self._channel_of(self._open())
        second = self._channel_of(self._open())
        self.assertEqual(first, second, "a second click created a second channel")

    def test_a_user_without_the_ai_group_cannot_open_a_chat(self):
        """B-iv: group_ai_user is the group the guard already reads policy as."""
        with self.assertRaises(AccessError):
            self._open(user=self.stranger)

    def test_a_profile_without_a_partner_refuses_to_open_a_chat(self):
        """§9.3 names the profile's partner. No partner, no surface -- and it
        fails with something an administrator can act on, not a traceback."""
        self.profile.write({'partner_id': False})
        with self.assertRaises(UserError):
            self._open()

    # ------------------------------------------------------------------
    # The entry point itself — B-ii
    # ------------------------------------------------------------------

    def _capture_runs(self):
        calls = []

        def fake_run(self, profile_code, trigger, session_id=None,
                     entry_prompt=None, correlation_id=None, history=None):
            calls.append({'profile_code': profile_code, 'trigger': trigger,
                          'session_id': session_id, 'entry_prompt': entry_prompt,
                          'history': history, 'uid': self.env.uid})
            return {'status': 'COMPLETED', 'content': 'ack', 'correlation_id': 'c'}

        self.patch(type(self.env['ai.operations.execution']), 'run', fake_run)
        return calls

    def test_posting_a_message_calls_the_one_runtime(self):
        """The deliverable: a real message on a real channel reaches run()."""
        calls = self._capture_runs()
        channel = self._channel_of(self._open())

        channel.with_user(self.employee).message_post(
            body='What is my scope?', message_type='comment',
            subtype_xmlid='mail.mt_comment')

        self.assertEqual(len(calls), 1, "the posted message did not reach the runtime")
        self.assertEqual(calls[0]['profile_code'], self.profile.code)
        self.assertEqual(calls[0]['trigger'], 'CHAT')

    def test_the_session_id_is_the_channel_id(self):
        """Document D §11. Budgets and the audit log are reconciled on it."""
        calls = self._capture_runs()
        channel = self._channel_of(self._open())

        channel.with_user(self.employee).message_post(
            body='hello', message_type='comment', subtype_xmlid='mail.mt_comment')

        self.assertEqual(calls[0]['session_id'], channel.id)

    def test_the_run_happens_as_the_employee_not_as_an_administrator(self):
        """C §9: `identity = env.user (the employee)`. Never a fallback."""
        calls = self._capture_runs()
        channel = self._channel_of(self._open())

        channel.with_user(self.employee).message_post(
            body='hello', message_type='comment', subtype_xmlid='mail.mt_comment')

        self.assertEqual(calls[0]['uid'], self.employee.id)

    def test_the_message_body_is_the_entry_prompt(self):
        """Markup, not str: that is what the Discuss client actually posts. A
        plain str is escaped by mail into literal text, which would make this
        test pass against a stripper that does nothing."""
        calls = self._capture_runs()
        channel = self._channel_of(self._open())

        channel.with_user(self.employee).message_post(
            body=Markup('<p>How many pallets?</p>'), message_type='comment',
            subtype_xmlid='mail.mt_comment')

        self.assertIn('How many pallets?', calls[0]['entry_prompt'])
        self.assertNotIn('<p>', calls[0]['entry_prompt'],
                         "raw HTML reached the model's context")

    def test_the_runtime_really_runs_from_a_posted_message(self):
        """No patching anywhere. The profile has no provider configured, so the
        real runtime must fail on the provider and audit that failure -- which
        is only possible if a posted message genuinely entered run()."""
        channel = self._channel_of(self._open())
        before = self.Log.search_count([('event_type', '=', 'ERROR')])

        channel.with_user(self.employee).message_post(
            body='hello', message_type='comment', subtype_xmlid='mail.mt_comment')

        self.assertEqual(
            self.Log.search_count([('event_type', '=', 'ERROR')]), before + 1,
            "the real runtime was never entered by a real message")

    # ------------------------------------------------------------------
    # What must NOT trigger a run
    # ------------------------------------------------------------------

    def test_an_unbound_channel_never_triggers_a_run(self):
        calls = self._capture_runs()
        channel = self.env['discuss.channel'].with_user(self.employee).create(
            {'name': 'Ordinary channel', 'channel_type': 'channel'})

        channel.with_user(self.employee).message_post(
            body='hello', message_type='comment', subtype_xmlid='mail.mt_comment')

        self.assertEqual(calls, [], "an ordinary channel reached the runtime")

    def test_the_agents_own_reply_does_not_trigger_another_run(self):
        """Otherwise the first question loops until the budget stops it."""
        calls = self._capture_runs()
        channel = self._channel_of(self._open())

        channel.message_post(
            body='I am the agent', message_type='comment',
            subtype_xmlid='mail.mt_comment', author_id=self.agent_partner.id)

        self.assertEqual(calls, [], "the agent answered itself")

    def test_a_note_does_not_trigger_a_run(self):
        calls = self._capture_runs()
        channel = self._channel_of(self._open())

        channel.with_user(self.employee).message_post(
            body='internal note', message_type='notification')

        self.assertEqual(calls, [], "a non-comment message reached the runtime")

    # ------------------------------------------------------------------
    # B-iii — one run at a time
    # ------------------------------------------------------------------

    def test_a_second_message_while_a_run_is_in_flight_is_refused(self):
        calls = self._capture_runs()
        channel = self._channel_of(self._open())
        channel.ai_run_active = True

        channel.with_user(self.employee).message_post(
            body='and another thing', message_type='comment',
            subtype_xmlid='mail.mt_comment')

        self.assertEqual(calls, [], "a second run started while one was in flight")

    def test_the_refusal_is_visible_to_the_user(self):
        """Silently dropping the message is worse than refusing it."""
        channel = self._channel_of(self._open())
        channel.ai_run_active = True
        before = len(channel.message_ids)

        channel.with_user(self.employee).message_post(
            body='and another thing', message_type='comment',
            subtype_xmlid='mail.mt_comment')

        self.assertGreater(len(channel.message_ids), before + 1,
                           "the user was told nothing")

    def test_the_lock_is_released_when_the_run_fails(self):
        """A provider failure must not wedge the channel forever."""
        channel = self._channel_of(self._open())

        channel.with_user(self.employee).message_post(
            body='hello', message_type='comment', subtype_xmlid='mail.mt_comment')

        self.assertFalse(channel.ai_run_active,
                         "the channel stayed locked after a failed run")

    # ------------------------------------------------------------------
    # The transcript — Document D §11
    # ------------------------------------------------------------------

    def test_the_answer_is_posted_back_as_the_agent(self):
        self._capture_runs()
        channel = self._channel_of(self._open())

        channel.with_user(self.employee).message_post(
            body='hello', message_type='comment', subtype_xmlid='mail.mt_comment')

        replies = channel.message_ids.filtered(
            lambda m: m.author_id == self.agent_partner)
        self.assertTrue(replies, "the agent never answered in the channel")
        self.assertIn('ack', replies[0].body)

    # ------------------------------------------------------------------
    # Conversation history -- C §9.4, and the boundary rule
    # ------------------------------------------------------------------

    def _say(self, channel, body, user=None):
        return channel.with_user(user or self.employee).message_post(
            body=body, message_type='comment', subtype_xmlid='mail.mt_comment')

    def test_a_follow_up_carries_the_earlier_turns(self):
        """Manual Test 2 turn 2: the user answered "(b) go ahead" and the agent
        replied that it had no product in this conversation. Every message was
        starting a brand-new one."""
        calls = self._capture_runs()
        channel = self._channel_of(self._open())

        self._say(channel, 'We are short 100000 units of PK-BTL-330.')
        self._say(channel, '(b) Go ahead and create the draft RFQ.')

        self.assertEqual(len(calls), 2)
        history = calls[1]['history'] or []
        joined = ' '.join(h['content'] for h in history)
        self.assertIn('PK-BTL-330', joined,
                      "the follow-up forgot what the conversation was about")
        self.assertIn('ack', joined, "the agent's own earlier reply was dropped")

    def test_the_first_message_of_a_conversation_has_no_history(self):
        calls = self._capture_runs()
        channel = self._channel_of(self._open())
        self._say(channel, 'first thing I have said')
        self.assertFalse(calls[0]['history'])

    def test_history_never_crosses_between_channels(self):
        """The freeze checklist: no conversation history crosses a boundary."""
        calls = self._capture_runs()
        mine = self._channel_of(self._open())
        self._say(mine, 'PK-BTL-330 is the secret of this channel')

        other = self.env['discuss.channel'].with_context(install_mode=True).create({
            'name': 'Another conversation',
            'channel_type': 'chat',
            'ai_profile_id': self.profile.id,
            'channel_member_ids': [
                (0, 0, {'partner_id': self.employee.partner_id.id}),
                (0, 0, {'partner_id': self.agent_partner.id})],
        })
        self._say(other, 'what were we discussing?')

        history = calls[-1]['history'] or []
        joined = ' '.join(h['content'] for h in history)
        self.assertNotIn('secret of this channel', joined,
                         "history leaked from another conversation")

    def test_history_is_bounded(self):
        calls = self._capture_runs()
        channel = self._channel_of(self._open())
        for index in range(30):
            self._say(channel, 'message number %d' % index)
        history = calls[-1]['history'] or []
        self.assertLessEqual(len(history), 40,
                             "history grows without limit and so does the bill")

    def test_the_runtime_refuses_a_tool_call_smuggled_through_history(self):
        """History is text. If a caller could put tool_calls in it, a replay of
        an old call would skip the guard entirely."""
        runner = self.env['ai.operations.execution']
        cleaned = runner._sanitise_history([
            {'role': 'user', 'content': 'hello'},
            {'role': 'assistant', 'content': 'hi',
             'tool_calls': [{'id': 'x', 'name': 'core.anything', 'input': {}}]},
            {'role': 'tool', 'tool_use_id': 'x', 'content': 'result'},
        ])
        self.assertTrue(all(set(turn) == {'role', 'content'} for turn in cleaned),
                        "a non-text key survived into history")
        self.assertTrue(all(turn['role'] in ('user', 'assistant') for turn in cleaned),
                        "a tool turn survived into history")
