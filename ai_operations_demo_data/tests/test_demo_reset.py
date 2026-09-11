"""The reset that makes the second demo run the same demo as the first.

Item I asks for the whole thing to be run twice, the second time from the
runbook alone. Two things stop that from being the same demo, and this suite
holds both closed.

The first is the reason the reset exists at all. ``prepare_draft_rfq`` is
idempotent on a key carrying the date but not the quantity, so asking again on
the same day returns the first run's draft. That is correct production
behaviour and is not changed; the residue is removed instead, and the same key
then finds nothing. ``test_the_same_key_is_free_again_after_a_reset`` is the
direct proof.

The second is what a reset must never do. Deleting by anything looser than an
explicit marker -- by date, by product, by vendor -- would take the human's own
purchase order with it, and on a demo database the operator would not notice
until the next customer meeting. So every assertion here comes in a pair: the
agent's record goes, and the record beside it that no agent created stays.
"""

from odoo.tests import TransactionCase, tagged

from ..models.demo_reset import ALERT_PREFIX
from ..models.demo_setup import COMPANY
from ..models.e2e_scenario import (
    SHORTAGE_ORIGIN, SHORT_COMPONENT, SHORT_COMPONENT_ONHAND)


@tagged('post_install', '-at_install', 'ai_security')
class TestDemoReset(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env['res.company'].search(
            [('name', '=', COMPANY)], limit=1)
        # The reset runs as a REAL user, never as the superuser this suite
        # otherwise runs as. uid 1 bypasses ir.model.access entirely, so a
        # superuser reset proves nothing about whether an administrator can
        # actually perform it -- and that is not hypothetical: the first version
        # of this suite passed while the reset died on staging with AccessError,
        # because nobody may unlink ai.operations.handoff and uid 1 never asked.
        cls.operator = cls.env.ref('base.user_admin')
        cls.Reset = cls.env['ai.operations.demo.reset'].with_user(cls.operator)
        cls.Scenario = cls.env['ai.operations.e2e.scenario']
        cls.Profile = cls.env['ai.operations.agent.profile'].with_context(
            active_test=False)
        cls.Purchase = cls.env['purchase.order']
        cls.Activity = cls.env['mail.activity']
        cls.Handoff = cls.env['ai.operations.handoff']

        cls.supplier = cls.env['res.partner'].search(
            [('supplier_rank', '>', 0)], limit=1)
        cls.component = cls.env['product.product'].search(
            [('default_code', '=', SHORT_COMPONENT)], limit=1)
        # A profile no demo routing knows about, so its handoff is the "someone
        # else's record" half of every pair below.
        # Inactive, the way the packs ship theirs: an active profile is required
        # to carry a company scope, and this one exists only to own a handoff.
        cls.outsider = cls.Profile.with_context(skip_policy_audit=True).create({
            'name': 'Unrelated Agent (reset test)',
            'code': 'kt_reset_outsider',
            'active': False,
        })

    # -- fixtures ---------------------------------------------------------

    def _key(self, profile='procurement', date='2026-09-08'):
        """The shape record_idempotency_key() builds."""
        return '%s:%s:draft_rfq:%s:976:%s' % (
            profile, self.company.id, SHORT_COMPONENT, date)

    def _order(self, key=None, confirm=False):
        order = self.Purchase.create({
            'partner_id': self.supplier.id,
            'company_id': self.company.id,
            'ai_idempotency_key': key,
            'order_line': [(0, 0, {
                'product_id': self.component.id,
                'product_qty': 4_000,
                'price_unit': 0.078,
            })],
        })
        if confirm:
            order.button_confirm()
        return order

    def _activity(self, profile_code, record):
        return self.Activity.create({
            'res_model_id': self.env['ir.model']._get_id(record._name),
            'res_id': record.id,
            'activity_type_id': self.env['mail.activity.type'].search(
                [], limit=1).id,
            'summary': 'reset test',
            'date_deadline': '2026-09-30',
            'user_id': self.env.user.id,
            'ai_profile_code': profile_code,
        })

    def _handoff_type(self, code, from_profile, to_profile):
        """A type wired for exactly this pair, with an empty payload schema.

        The shipped types constrain who may raise and who receives, and reject
        any payload that is not exactly their declared fields. Reusing one would
        make this suite depend on a pack's routing; what is under test is the
        reset, not the pairing rules.
        """
        return self.env['ai.operations.handoff.type'].create({
            'code': code,
            'name': code,
            'payload_schema': '{}',
            'from_profile_ids': [(6, 0, from_profile.ids)],
            'to_profile_id': to_profile.id,
        })

    def _handoff(self, from_profile, to_profile, code='KT_RESET'):
        return self.Handoff.create({
            'name': 'reset test',
            'type_id': self._handoff_type(code, from_profile, to_profile).id,
            'from_profile_id': from_profile.id,
            'to_profile_id': to_profile.id,
            'payload': {},
        })

    def _alert(self, name):
        if 'quality.alert' not in self.env:
            self.skipTest('quality is Enterprise-only and is not installed')
        return self.env['quality.alert'].create({
            'name': name,
            'company_id': self.company.id,
            'team_id': self.env['quality.alert.team'].search([], limit=1).id,
        })

    def _production(self):
        order = self.env['sale.order'].search(
            [('origin', '=', SHORTAGE_ORIGIN)], limit=1)
        self.assertTrue(order, "the scenario sales order is missing")
        return self.env['mrp.production'].with_context(
            active_test=False).search([('origin', '=', order.name)], limit=1)

    def _unreserved(self, production):
        return [move.product_id.default_code
                for move in production.move_raw_ids
                if move.state != 'assigned']

    def _demo_profile(self, code='procurement'):
        return self.Profile.search([('code', '=', code)], limit=1)

    # -- what goes ---------------------------------------------------------

    def test_reset_removes_the_agents_purchase_order(self):
        order = self._order(key=self._key())
        self.Reset.reset()
        self.assertFalse(order.exists(), "the agent's draft RFQ survived the reset")

    def test_reset_removes_the_agents_activity(self):
        activity = self._activity('procurement', self._order(key=self._key()))
        self.Reset.reset()
        self.assertFalse(activity.exists(), "the agent's review activity survived")

    def test_reset_cancels_the_agents_handoff_and_frees_its_key(self):
        """Nobody may delete a handoff, so it is cancelled and its key released.

        Releasing the key is the half that matters for run two: raise_handoff
        deduplicates on (to_profile_id, idempotency_key) with no state filter,
        so a cancelled handoff that kept its key would still answer the second
        run and the agent would raise nothing.
        """
        handoff = self._handoff(
            self._demo_profile('manufacturing'), self._demo_profile('procurement'))
        handoff.idempotency_key = 'kt:reset:key'
        self.Reset.reset()
        self.assertTrue(handoff.exists(), "the handoff was deleted; the ACL "
                                          "grants unlink to nobody")
        self.assertEqual(handoff.state, 'CANCELLED', "the handoff was not cancelled")
        self.assertFalse(handoff.idempotency_key,
                         "the key was not released, so run two would dedup "
                         "against this handoff and raise nothing")

    def test_reset_removes_the_proposed_hold(self):
        alert = self._alert(ALERT_PREFIX + 'LOT-TEST (SPEC_EXCEEDED)')
        self.Reset.reset()
        self.assertFalse(alert.exists(), "the proposed hold survived")

    def test_reset_empties_the_demo_conversations(self):
        """History leaking into run two is invisible: the reply still reads well."""
        channel = self.env['discuss.channel'].search(
            [('ai_profile_id', '!=', False)], limit=1)
        self.assertTrue(channel, "the demo bound no channels")
        channel.message_post(body='first run', message_type='comment')
        self.Reset.reset()
        self.assertFalse(
            self.env['mail.message'].search_count([
                ('model', '=', 'discuss.channel'), ('res_id', '=', channel.id)]),
            "the first run's conversation is still replayable as history")
        self.assertTrue(channel.exists(), "the reset deleted a fixture channel")

    # -- what stays --------------------------------------------------------

    def test_a_purchase_order_no_agent_created_survives(self):
        """P00001 is the real one. It carries no key and must be invisible here."""
        human = self._order(key=False)
        self.Reset.reset()
        self.assertTrue(
            human.exists(),
            "the reset deleted a purchase order no agent created; matching on "
            "anything looser than ai_idempotency_key takes the customer's own "
            "orders with it")

    def test_an_activity_no_agent_created_survives(self):
        human = self._activity(False, self._order(key=False))
        self.Reset.reset()
        self.assertTrue(human.exists(), "the reset deleted a human's activity")

    def test_a_handoff_outside_the_demo_profiles_survives(self):
        outsider = self._handoff(self.outsider, self.outsider, code='KT_RESET_OUT')
        outsider.idempotency_key = 'kt:outsider:key'
        before = (outsider.state, outsider.idempotency_key)
        self.Reset.reset()
        self.assertEqual(
            (outsider.state, outsider.idempotency_key), before,
            "the reset deleted a handoff belonging to a profile the demo does "
            "not route")

    def test_a_quality_alert_no_agent_proposed_survives(self):
        human = self._alert('Manual hold raised by the QA manager')
        self.Reset.reset()
        self.assertTrue(human.exists(), "the reset deleted a human's quality alert")

    def test_the_base_fixture_survives(self):
        """The scenario orders are the starting state, not residue."""
        order = self.env['sale.order'].search(
            [('origin', '=', SHORTAGE_ORIGIN)], limit=1)
        production = self.env['mrp.production'].with_context(
            active_test=False).search([('origin', '=', order.name)], limit=1)
        self.Reset.reset()
        self.assertTrue(order.exists(), "the reset deleted the scenario sales order")
        self.assertTrue(production.exists(),
                        "the reset deleted the scenario manufacturing order")

    # -- and it can be run again -------------------------------------------

    def test_reset_twice_is_the_same_as_once(self):
        self._order(key=self._key())
        self._handoff(self._demo_profile('manufacturing'),
                      self._demo_profile('procurement'))
        first = self.Reset.reset()
        second = self.Reset.reset()
        self.assertEqual(
            second['purchase_orders_deleted'], 0, "the second reset found residue")
        self.assertEqual(second['handoffs_cancelled'], 0)
        self.assertEqual(first['steps_failed'], [], "a reset step could not run")
        self.assertEqual(second['steps_failed'], [])
        self.assertFalse(second['purchase_orders_cancelled_not_deleted'])
        self.assertGreaterEqual(first['purchase_orders_deleted'], 1)

    def test_reset_on_a_clean_database_is_a_no_op(self):
        self.Reset.reset()
        summary = self.Reset.reset()
        for key in ('purchase_orders_deleted', 'account_moves_deleted',
                    'activities_deleted',
                    'handoffs_cancelled', 'quality_alerts_deleted',
                    'messages_deleted'):
            self.assertEqual(
                summary[key], 0,
                "a reset with nothing to remove reported %s: %s" % (key, summary))
        self.assertFalse(summary['purchase_orders_cancelled_not_deleted'])

    def test_the_accountants_drafts_go_and_a_persons_stay(self):
        """DL-010. A bill or entry the agent drafted is residue; one a person
        entered is not, and carries no key for the reset to find."""
        Move = self.env['account.move']
        ours = Move.create({
            'move_type': 'entry', 'company_id': self.company.id,
            'ref': 'reset test (agent)',
            'ai_idempotency_key': 'accounting:%s:journal_entry:reset test:entry:'
                                  '2026-09-11' % self.company.id})
        theirs = Move.create({
            'move_type': 'entry', 'company_id': self.company.id,
            'ref': 'reset test (person)'})
        summary = self.Reset.reset()
        self.assertFalse(ours.exists(), "the agent's draft survived the reset")
        self.assertTrue(theirs.exists(), "the reset deleted a person's entry")
        self.assertGreaterEqual(summary['account_moves_deleted'], 1)
        self.assertFalse(summary['account_moves_not_deleted'])
        self.assertEqual(summary['steps_failed'], [])

    def test_reset_cancels_a_confirmed_order_before_deleting_it(self):
        """The runbook has a human press Confirm, so by reset time it is not a
        draft, and Odoo refuses to delete a confirmed purchase order."""
        order = self._order(key=self._key(), confirm=True)
        self.assertEqual(order.state, 'purchase')
        summary = self.Reset.reset()
        self.assertFalse(
            order.exists(),
            "a confirmed order was not cancelled and removed: %s"
            % summary['purchase_orders_cancelled_not_deleted'])

    # -- the starting state is genuinely restored ---------------------------

    def test_the_shortage_is_exactly_what_it_was_before_the_run(self):
        """The number the whole runbook quotes: 12,000 required, 8,000 available."""
        self._order(key=self._key())
        self.Reset.reset()
        self.Scenario.build()

        order = self.env['sale.order'].search(
            [('origin', '=', SHORTAGE_ORIGIN)], limit=1)
        production = self.env['mrp.production'].with_context(
            active_test=False).search([('origin', '=', order.name)], limit=1)
        move = production.move_raw_ids.filtered(
            lambda m: m.product_id.default_code == SHORT_COMPONENT)

        self.assertEqual(move.product_uom_qty, 12_000, "the requirement moved")
        self.assertEqual(move.quantity, float(SHORT_COMPONENT_ONHAND),
                         "the available quantity moved")
        self.assertEqual(
            [m.product_id.default_code for m in production.move_raw_ids
             if m.state != 'assigned'],
            [SHORT_COMPONENT],
            "after a reset and rebuild the demo is no longer short of exactly "
            "one component")

    def test_the_same_key_is_free_again_after_a_reset(self):
        """The blocker itself.

        Running the demo twice in one day builds the same idempotency key both
        times. Before the reset existed, the second run returned the first run's
        draft; a unique constraint on (company_id, ai_idempotency_key) means it
        could not even be recreated. After a reset the key is free, so the second
        run creates its own order and the customer sees the same demo.
        """
        key = self._key()
        first = self._order(key=key)
        self.env.flush_all()
        self.Reset.reset()

        second = self._order(key=key)
        self.env.flush_all()

        self.assertTrue(second.exists())
        self.assertNotEqual(second.id, first.id,
                            "the second run reused the first run's order")
        self.assertEqual(second.ai_idempotency_key, key)

    # -- the reset must survive a demo that actually happened ---------------

    def test_a_received_surplus_is_levelled_back_out(self):
        """The failure that stopped run #2 on staging.

        The runbook has the presenter buy the missing bottles and receive them.
        That is the point of the receipt steps, and it means the reset cannot
        just cancel paperwork: after one complete run the order reserves all
        12,000 it needs and the shortage the whole cascade is about is gone.
        The fixture's own top-up is a floor and will never remove a surplus.
        """
        production = self._production()
        move = production.move_raw_ids.filtered(
            lambda m: m.product_id.default_code == SHORT_COMPONENT)
        location = self.env['stock.location'].search(
            [('complete_name', '=', 'RM/Stock')], limit=1)

        # Receive the 4,000 the demo would have bought.
        quant = self.env['stock.quant'].with_context(inventory_mode=True).search(
            [('product_id', '=', move.product_id.id),
             ('location_id', 'child_of', location.id)], limit=1)
        self.assertTrue(quant, "no stock quant to receive into")
        quant.with_context(inventory_mode=True).write(
            {'inventory_quantity': quant.quantity + 4_000})
        quant.with_context(inventory_mode=True).action_apply_inventory()
        production.action_assign()
        production.invalidate_recordset()
        self.assertFalse(
            self._unreserved(production),
            "the fixture did not reach the post-run state this test is about")

        self.Reset.reset()

        production.invalidate_recordset()
        self.assertEqual(
            self._unreserved(production), [SHORT_COMPONENT],
            "after a reset the order must be short of the bottle again")
        move.invalidate_recordset()
        self.assertEqual(move.product_uom_qty, 12_000)
        self.assertEqual(
            move.quantity, float(SHORT_COMPONENT_ONHAND),
            "the reset did not level the received surplus back out")

    def test_relevelling_reports_what_it_moved(self):
        summary = self.Reset.reset()
        self.assertIn('relevelled', summary)
        self.assertEqual(summary['steps_failed'], [])

    # -- the daily token counter -------------------------------------------

    def test_the_daily_token_counter_is_cleared_for_demo_profiles(self):
        """Rehearsal spends the same budget as the performance.

        Six validation runs took manufacturing to 204,620 of its 200,000
        ceiling, after which every turn was refused at guard step 5 -- correctly,
        and unrecoverably by any prompt.
        """
        profile = self._demo_profile('manufacturing')
        budget = self.env['ai.operations.budget'].create({
            'profile_id': profile.id,
            'date': self.env['ai.operations.budget']._fields['date'].default(
                self.env['ai.operations.budget']),
            'tokens_used': 204_620,
        })
        summary = self.Reset.reset()
        budget.invalidate_recordset()
        self.assertEqual(budget.tokens_used, 0, "the counter was not cleared")
        self.assertGreaterEqual(summary['token_budget_cleared'], 1)

    def test_the_ceiling_itself_is_never_touched(self):
        """The counter is rehearsal residue. The ceiling is a policy control."""
        profile = self._demo_profile('manufacturing')
        before = profile.max_daily_tokens
        self.assertTrue(before, "the fixture has no ceiling to protect")
        self.Reset.reset()
        profile.invalidate_recordset()
        self.assertEqual(
            profile.max_daily_tokens, before,
            "the reset weakened a policy ceiling instead of clearing a counter")
