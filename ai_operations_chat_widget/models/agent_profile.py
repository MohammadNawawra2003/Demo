"""What the widget is allowed to ask the server, and nothing more.

Two methods. Both are ordinary ORM methods, so the record rules and ACLs that
protect every other read and write protect these too -- **there is no
controller and no new endpoint**, which is the point: a second door is a second
thing to get wrong.

Neither method executes a tool, chooses a model or builds a domain. They resolve
a conversation and post a message into it; everything after that is the chat
surface the Discuss path already uses, which means the same guard, the same
audit rows, the same budgets, the same bounded history and the same company
isolation.
"""

from odoo import _, api, models
from odoo.tools import html2plaintext


class AIOperationsAgentProfile(models.Model):
    _inherit = 'ai.operations.agent.profile'

    @api.model
    def ai_widget_profiles(self):
        """The agents this user may actually talk to.

        The company scope is not applied here; it is applied by the record rule
        on the model, so this cannot be the place that forgets it. A user
        without ``group_ai_user`` is offered nothing, which is what hides the
        launcher: a tool call would be refused anyway, so a launcher would only
        promise something the guard would take away.
        """
        if not self.env.user._has_group('ai_operations.group_ai_user'):
            return []
        profiles = self.search([('allow_interactive', '=', True),
                                ('partner_id', '!=', False)])
        return [{'id': profile.id,
                 'name': profile.name,
                 'code': profile.code} for profile in profiles]

    #: How many turns the panel shows when it opens. A display bound, not a
    #: security one: what the model is given is bounded separately by the
    #: runtime, and this is only what the user can scroll back through.
    WIDGET_HISTORY_LIMIT = 30

    def _ai_widget_channel(self):
        """The conversation this agent and this user already share.

        ``action_open_chat`` carries the ``group_ai_user`` check, the "profile
        must have a partner" check and the get-or-create, so reusing it is what
        keeps the widget on the same channel as Discuss instead of inventing a
        second one.
        """
        self.ensure_one()
        action = self.action_open_chat()
        return self.env['discuss.channel'].browse(action['params']['channel_id'])

    def _ai_widget_messages(self, channel):
        """What has already been said here, oldest first.

        Read through the ORM as the current user, so a conversation someone
        else owns is not readable here for the same reason it is not readable
        in Discuss.
        """
        messages = self.env['mail.message'].search(
            [('model', '=', 'discuss.channel'),
             ('res_id', '=', channel.id),
             ('message_type', '=', 'comment')],
            order='id desc', limit=self.WIDGET_HISTORY_LIMIT)
        rendered = []
        for message in reversed(messages):
            body = html2plaintext(message.body or '')
            if not body.strip():
                continue
            rendered.append({
                'id': message.id,
                'author': 'agent' if message.author_id == self.partner_id else 'user',
                'author_name': message.author_id.display_name or '',
                'body': body,
                'date': message.date and message.date.isoformat() or '',
            })
        return rendered

    def ai_widget_open(self):
        """Everything the panel needs to show this conversation."""
        self.ensure_one()
        channel = self._ai_widget_channel()
        return {
            'channel_id': channel.id,
            'profile_id': self.id,
            'messages': self._ai_widget_messages(channel),
        }

    def ai_widget_send(self, body):
        """One turn, through the conversation Discuss already uses.

        ``action_open_chat`` is reused rather than reimplemented: it carries the
        ``group_ai_user`` check, the "profile must have a partner" check and the
        get-or-create of the channel. A forged profile id fails before this line
        -- browsing a profile outside the user's companies raises on the record
        rule -- and a user without the group fails inside it.

        The body is posted as a plain string, which ``mail`` escapes, so a
        message cannot carry markup into anyone's conversation.
        """
        self.ensure_one()
        channel = self._ai_widget_channel()

        before = channel.message_ids.ids
        channel.message_post(body=body or '', message_type='comment',
                             subtype_xmlid='mail.mt_comment')

        reply = channel.message_ids.filtered(
            lambda message: message.id not in before
            and message.author_id == self.partner_id)
        return {
            'channel_id': channel.id,
            'profile_id': self.id,
            'reply': html2plaintext(reply[0].body or '') if reply
                     else _("I am unavailable right now. Nothing has been changed."),
        }
