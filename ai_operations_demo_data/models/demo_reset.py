"""Reset one demo run, so the next one starts where the first one did.

NON-PRODUCTION. This module is never installed on a customer database.

The owner's item I asks for the demo to be run twice: once while building it,
then reset and run again from the runbook alone. Without a reset the second run
is not the same demo. Two things leak:

* ``procurement.prepare_draft_rfq`` is idempotent on
  ``{profile}:{company}:{purpose}:{product}:{location}:{date}``. The key carries
  the date but not the quantity, so asking again on the SAME DAY returns the
  draft the first run created instead of creating one. That is correct
  production behaviour and is deliberately not changed here -- the residue is
  removed instead, and the same key then finds nothing.
* The kernel replays a channel's own messages as conversation history, so the
  second run's agent can see, and refer to, the first run's answers.

**What this deletes is decided by explicit markers, never by a search over
dates, products or vendors.** Every marker below is a field the product itself
writes when an agent creates a record, or a record the demo fixture owns:

===========================  ==================================================
``purchase.order``           ``ai_idempotency_key`` begins with a demo profile
                             code. A human-created RFQ -- P00001 -- has no key
                             at all and is invisible to this reset.
``mail.activity``            ``ai_profile_code`` is one of the demo profiles.
``ai.operations.handoff``    ``from_profile_id`` or ``to_profile_id`` is one of
                             the demo profiles.
``quality.alert``            name begins with ``AI: proposed hold on``, the
                             literal ``propose_hold`` builds and dedups on.
``mail.message``             posted in a channel the demo fixture bound to an
                             agent profile (``discuss.channel.ai_profile_id``).
===========================  ==================================================

**What it deliberately does NOT touch:** the deterministic base fixture. The
``AI-DEMO-E2E`` sales orders, the manufacturing order MTO created from them, the
``AI-DEMO`` seeded records, the eighteen scheduled orders, and the whole
Document A history all survive. They are the starting state, not residue.

**Component stock is LEVELLED, not left alone.** That is the one thing a reset
cannot do by deleting records. A demo that was actually performed *receives*
goods: run #1 on staging bought 4,000 bottles and took them through a lot
number, ten quality checks and a two-step warehouse, exactly as the runbook
says to. Afterwards the order reserved all 12,000 it needed, the shortage was
gone, and every later step of run #2 was about a problem that no longer
existed -- while the reset reported a clean sweep, because the paperwork had
indeed been cancelled. ``e2e_scenario.relevel()`` puts the components back to
their target figures in both directions, so the order is short by precisely the
documented 4,000 again.

No ``sudo()``. The reset runs with the privileges of whoever calls it.
"""

import logging

from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError

from odoo.addons.ai_operations.services.enums import HandoffState

from .demo_setup import ROUTING

_logger = logging.getLogger(__name__)

#: The literal title ``quality.propose_hold`` builds, and the only marker a
#: ``quality.alert`` carries -- the model has no AI field, and adding one would
#: mean changing a production pack.
ALERT_PREFIX = 'AI: proposed hold on '

#: The only state Odoo will delete a purchase order from. ``_unlink_if_cancelled``
#: in ``purchase`` refuses anything else -- a *draft* included, which is easy to
#: assume otherwise -- so every order is cancelled through its own button first,
#: never by writing ``state``.
DELETABLE_PO_STATE = 'cancel'


class AIOperationsDemoReset(models.AbstractModel):
    _name = 'ai.operations.demo.reset'
    _description = 'AI Operations Demo Reset (NON-PRODUCTION)'

    # ------------------------------------------------------------------

    @api.model
    def reset(self):
        """Remove one demo run's residue. Idempotent: running it twice is the
        same as running it once, and running it on a clean database is a no-op.

        Returns a summary dict so the runbook has something to show and to
        paste into the evidence log.
        """
        summary = {
            'purchase_orders_deleted': 0,
            'purchase_orders_cancelled_not_deleted': [],
            'account_moves_deleted': 0,
            'account_moves_not_deleted': [],
            'activities_deleted': 0,
            'handoffs_cancelled': 0,
            'quality_alerts_deleted': 0,
            'messages_deleted': 0,
            'relevelled': {},
            'token_budget_cleared': 0,
            'steps_failed': [],
        }
        # Every search below has to see all three demo companies. Multi-company
        # record rules scope a search to the caller's active companies, so an
        # administrator sitting in "My Company" -- which is where a fresh login
        # lands, and the reason the demo looked empty in the first review --
        # would match none of the Naqaa records and report a clean reset that
        # removed nothing at all. Not sudo: this is exactly the set of companies
        # the caller already has access to, never more.
        self = self.with_context(
            allowed_company_ids=self.env.user.company_ids.ids
            or self.env.companies.ids)
        codes = sorted(ROUTING)
        # Each step is isolated. One model the caller may not remove used to
        # abort the whole reset and roll back everything already done, which
        # reads on staging as "the reset is broken" rather than "this one step
        # could not run". A failed step is reported and the rest still happen.
        steps = (
            ('purchase orders', self._reset_draft_rfqs, (codes, summary)),
            ('bills and journal entries', self._reset_ai_moves, (codes, summary)),
            ('activities', self._reset_activities, (codes, summary)),
            ('handoffs', self._reset_handoffs, (codes, summary)),
            ('quality alerts', self._reset_quality_alerts, (summary,)),
            ('conversations', self._reset_conversations, (summary,)),
            # Last, because it re-reserves the order and wants the paperwork
            # already gone.
            ('stock level', self._relevel_stock, (summary,)),
            ('token budget', self._reset_token_budget, (summary,)),
        )
        for label, step, args in steps:
            try:
                with self.env.cr.savepoint(flush=False):
                    step(*args)
            except (UserError, AccessError) as exc:
                summary['steps_failed'].append('%s: %s' % (label, exc))
        _logger.info("ai_operations_demo_data: demo reset -> %s", summary)
        return summary

    # -- purchase orders ---------------------------------------------------

    @api.model
    def _reset_draft_rfqs(self, codes, summary):
        """Delete the orders an agent created, cancelling first if Odoo needs it.

        Odoo deletes a purchase order only from ``cancel``. Not from ``draft``:
        ``purchase._unlink_if_cancelled`` refuses every other state, so the draft
        the agent prepared has to be cancelled too, not only the one the runbook
        had a human confirm. Cancelling goes through ``button_cancel`` because it
        also cancels the receipts a confirmed order created; writing ``state``
        directly would leave those behind.
        """
        prefixes = tuple('%s:' % code for code in codes)
        candidates = self.env['purchase.order'].search(
            [('ai_idempotency_key', '!=', False)])
        orders = candidates.filtered(
            lambda o: o.ai_idempotency_key.startswith(prefixes))
        for order in orders:
            name = order.name
            if order.state != DELETABLE_PO_STATE:
                with self.env.cr.savepoint(flush=False):
                    try:
                        order.button_cancel()
                    except (UserError, AccessError) as exc:
                        summary['purchase_orders_cancelled_not_deleted'].append(
                            '%s (cancel refused: %s)' % (name, exc))
                        continue
            if order.state != DELETABLE_PO_STATE:
                summary['purchase_orders_cancelled_not_deleted'].append(
                    '%s (still %s)' % (name, order.state))
                continue
            with self.env.cr.savepoint(flush=False):
                try:
                    order.unlink()
                except (UserError, AccessError) as exc:
                    summary['purchase_orders_cancelled_not_deleted'].append(
                        '%s (cancelled, delete refused: %s)' % (name, exc))
                    continue
            summary['purchase_orders_deleted'] += 1

    # -- activities, handoffs, alerts --------------------------------------

    @api.model
    def _reset_ai_moves(self, codes, summary):
        """Delete the bills and journal entries the Accountant drafted (DL-010).

        The same marker discipline as the purchase orders: ``ai_idempotency_key``
        beginning with a demo profile code. A bill a person entered carries no
        key and is invisible here. One a person confirmed during the demo is
        reset to draft first, the way Odoo requires; if Odoo refuses, it is
        reported and left alone rather than forced.
        """
        prefixes = tuple('%s:' % code for code in codes)
        moves = self.env['account.move'].search(
            [('ai_idempotency_key', '!=', False)]).filtered(
            lambda m: m.ai_idempotency_key.startswith(prefixes))
        for move in moves:
            name = move.display_name
            # A flushing savepoint, unlike the steps above: account.move.unlink
            # deletes the lines (and flushes) before Odoo may refuse the move,
            # and only a flushing savepoint clears the cache on rollback.
            try:
                with self.env.cr.savepoint():
                    if move.state != 'draft':
                        move.button_draft()
                    move.unlink()
            except (UserError, AccessError) as exc:
                summary['account_moves_not_deleted'].append('%s (%s)' % (name, exc))
                continue
            summary['account_moves_deleted'] += 1

    @api.model
    def _reset_activities(self, codes, summary):
        activities = self.env['mail.activity'].search(
            [('ai_profile_code', 'in', codes)])
        summary['activities_deleted'] = len(activities)
        activities.unlink()

    @api.model
    def _reset_handoffs(self, codes, summary):
        """Handoffs are cancelled and their key released, never deleted.

        ``ir.model.access`` grants ``ai.operations.handoff`` read, write and
        create to AI Operations / User, and unlink to **nobody at all** -- the
        same posture as the audit log. That is deliberate: a handoff is
        audit-adjacent evidence, and "nobody may delete one" is a property worth
        keeping. So this does not reach for ``sudo()`` and does not widen a
        kernel ACL for the convenience of a demo helper.

        Cancelling on its own would not be enough. ``raise_handoff``
        deduplicates on ``(to_profile_id, idempotency_key)`` with **no state
        filter**, so a cancelled handoff still answers the second run's raise
        and the agent reports "already queued" instead of raising a fresh one.
        Releasing the key is what deleting a purchase order does for its own
        key; here it is done explicitly because the row has to stay.
        """
        cancelled = HandoffState.CANCELLED.value
        handoffs = self.env['ai.operations.handoff'].search([
            '|', ('from_profile_id.code', 'in', codes),
            ('to_profile_id.code', 'in', codes),
        ])
        # Anything already cancelled AND already keyless is done; leaving it out
        # is what makes a second reset report nothing to do.
        todo = handoffs.filtered(
            lambda h: h.state != cancelled or h.idempotency_key)
        summary['handoffs_cancelled'] = len(todo)
        if todo:
            todo.write({'state': cancelled, 'idempotency_key': False})

    @api.model
    def _reset_quality_alerts(self, summary):
        if 'quality.alert' not in self.env:
            return
        alerts = self.env['quality.alert'].search(
            [('name', '=like', ALERT_PREFIX + '%')])
        summary['quality_alerts_deleted'] = len(alerts)
        alerts.unlink()

    # -- the daily token counter -------------------------------------------

    @api.model
    def _reset_token_budget(self, summary):
        """Clear today's token counters for the demo profiles.

        Rehearsal spends the same daily budget as the performance. Six
        validation runs took the manufacturing profile to 204,620 of its 200,000
        ceiling, after which every turn it attempted was refused at guard step 5
        -- correctly, and in a way no prompt could recover from.

        This clears the COUNTER for the demo's own profiles. It does not touch
        ``max_daily_tokens``: the ceiling is a policy control and stays exactly
        where it was, still enforced, still fail-closed. What is being removed
        is the record of spend from a rehearsal, on a non-production database,
        by the same act that removes the rest of the rehearsal's residue.

        Non-production only, like everything else in this module.
        """
        profiles = self.env['ai.operations.agent.profile'].with_context(
            active_test=False).search([('code', 'in', sorted(ROUTING))])
        # Only rows that actually carry spend. Reporting every row every time
        # broke the "non-zero then zero" rule the runbook teaches presenters to
        # read a reset by -- and that rule is what distinguishes a real reset
        # from the silent no-op the multi-company bug used to produce.
        rows = self.env['ai.operations.budget'].search([
            ('profile_id', 'in', profiles.ids),
            ('date', '=', fields.Date.context_today(self)),
            ('tokens_used', '>', 0),
        ])
        summary['token_budget_cleared'] = len(rows)
        if rows:
            rows.write({'tokens_used': 0})

    # -- stock -------------------------------------------------------------

    @api.model
    def _relevel_stock(self, summary):
        """Put the components back to the figures the scenario starts from.

        Cancelling paperwork is not enough once a demo has actually been
        performed. Run #1 on staging bought 4,000 bottles and received them
        properly -- lot number, ten quality checks, a two-step warehouse -- so
        afterwards the order reserved all 12,000 it needed and the shortage the
        whole cascade is about had ceased to exist. Nothing in a reset that only
        deletes records can undo a receipt, and the fixture's own top-up is a
        floor that never removes a surplus.
        """
        summary['relevelled'] = self.env['ai.operations.e2e.scenario'].relevel()

    # -- conversations -----------------------------------------------------

    @api.model
    def _reset_conversations(self, summary):
        """Empty the demo channels.

        The kernel rebuilds conversation history from a channel's own messages,
        bounded at twenty turns. Leaving the first run's conversation in place
        would let the second run's agent answer from it -- which is the most
        invisible way first-run state leaks into a second run, because the reply
        still looks perfectly reasonable.

        The channels themselves are kept: they are fixture records, and the
        runbook's step numbers refer to them by name.
        """
        channels = self.env['discuss.channel'].search(
            [('ai_profile_id', '!=', False)])
        if not channels:
            return
        messages = self.env['mail.message'].search([
            ('model', '=', 'discuss.channel'),
            ('res_id', 'in', channels.ids),
        ])
        summary['messages_deleted'] = len(messages)
        messages.unlink()
        stuck = channels.filtered('ai_run_active')
        if stuck:
            stuck.write({'ai_run_active': False})
