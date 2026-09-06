"""The chat surface. Document C 9.3.

*"A ``discuss.channel`` between the employee and the profile's partner."*
``discuss.channel`` lives in ``mail``, which the kernel already depends on, so
the conversational half of the platform adds no dependency and installs on
Odoo Community. That is a commercial position, not an accident.

**This file dispatches; it does not decide anything.** It resolves the profile
from the channel, hands the message to the one runtime with ``trigger=CHAT``,
and posts what comes back. Identity is ``env.user`` because C 9 says so and
because ``run()`` is what resolves it -- there is no fallback here, no
``sudo()``, and no second code path. Everything a chat message is allowed to do
is decided by the same guard a cron run goes through.
"""

import logging

from odoo import _, fields, models
from odoo.exceptions import UserError
from odoo.tools import html2plaintext

from ..services.enums import TriggerType
from ..services.exceptions import NEUTRAL_DENIAL

_logger = logging.getLogger(__name__)


class DiscussChannel(models.Model):
    _inherit = 'discuss.channel'

    ai_profile_id = fields.Many2one(
        'ai.operations.agent.profile', string='AI Agent',
        index=True, ondelete='cascade', copy=False,
        help="The agent bound to this conversation. A channel without one is an "
             "ordinary conversation and never reaches the runtime.")
    ai_run_active = fields.Boolean(
        copy=False,
        help="A run is in flight. The next message is refused rather than "
             "queued: two runs on one channel would share a session id, and the "
             "budget counters are reconciled on it.")

    # ------------------------------------------------------------------

    def message_post(self, **kwargs):
        message = super().message_post(**kwargs)   # ensure_one() is done there
        self._ai_dispatch(message)
        return message

    def _ai_dispatch(self, message):
        """Every message in a bound channel is a turn (decision B-ii).

        Requiring a mention would add parsing and a failure mode where the agent
        silently ignores a user who is talking to it.
        """
        profile = self.ai_profile_id
        if not profile or message.message_type != 'comment':
            return
        if profile.partner_id and message.author_id == profile.partner_id:
            return                      # the agent's own answer, not a new turn

        if self.ai_run_active:
            # Decision B-iii. Refused, never silently dropped.
            self._ai_say(_("I am still working on the previous message. "
                           "Please send this again once I have answered."))
            return

        self.ai_run_active = True
        try:
            result = self.env['ai.operations.execution'].run(
                profile.code,
                TriggerType.CHAT.value,
                session_id=self.id,
                entry_prompt=html2plaintext(message.body or ''),
                history=self._ai_history(message),
            )
        finally:
            # A provider outage must not wedge the channel forever.
            self.ai_run_active = False

        self._ai_say(self._ai_body(result))

    def _ai_history(self, message):
        """The earlier turns of **this** conversation, and nothing else.

        Scoped to this channel's own comments by ``res_id``, so nothing can
        reach it from another conversation, another employee or another
        company -- the freeze checklist's "no conversation history crosses a
        boundary". A chat channel has exactly two members, so the boundary is
        the record.

        Text only, deliberately. The agent's own earlier prose already carries
        whatever a tool returned, filtered by the serialiser at the time it was
        written, so nothing has to be persisted or reconstructed and no
        ``tool_use`` is ever replayed. The runtime narrows this again before it
        is used.
        """
        profile = self.ai_profile_id
        earlier = self.env['mail.message'].search(
            [('model', '=', 'discuss.channel'),
             ('res_id', '=', self.id),
             ('message_type', '=', 'comment'),
             ('id', '!=', message.id)],
            order='id desc', limit=self.env['ai.operations.execution'].MAX_HISTORY_TURNS)

        turns = []
        for earlier_message in reversed(earlier):
            body = html2plaintext(earlier_message.body or '')
            if not body.strip():
                continue
            turns.append({
                'role': ('assistant'
                         if profile.partner_id
                         and earlier_message.author_id == profile.partner_id
                         else 'user'),
                'content': body,
            })
        return turns

    def _ai_say(self, body):
        """Post as the agent. The author check in ``_ai_dispatch`` is what stops
        this from becoming a turn of its own."""
        return self.message_post(
            body=body, message_type='comment', subtype_xmlid='mail.mt_comment',
            author_id=self.ai_profile_id.partner_id.id)

    @staticmethod
    def _ai_body(result):
        """What the user sees. A failure says nothing about why.

        The neutrality rule that governs tool results (C 9, ``NEUTRAL_DENIAL``)
        applies to the channel too: a provider name, an endpoint or a reason code
        in the conversation is the same leak in a friendlier font.
        """
        result = result or {}
        # A refusal is not something the model gets to narrate. It was handed
        # NEUTRAL_DENIAL as the tool result and could still write whatever it
        # liked afterwards -- vendor concentration, a hard ceiling, a shortage
        # rule -- none of which was the reason. NEUTRAL_DENIAL is documented as
        # "the ONLY text a denial is ever allowed to show outside the audit
        # log", so the surface says it and discards the prose. The real reason
        # stays on the audit row, where an auditor reads it.
        #
        # Deterministic on purpose: a security boundary that depends on the
        # model choosing to be honest is not a boundary.
        if result.get('refused'):
            return NEUTRAL_DENIAL

        status = result.get('status')
        if status == 'COMPLETED':
            return (result.get('content')
                    or _("I have nothing to add."))
        if status == 'BUDGET_EXCEEDED':
            return _("I have reached my limit for this conversation. "
                     "Please start a new one.")
        return _("I am unavailable right now. Nothing has been changed.")
