"""Session 9: T-50 to T-57. What crosses between two agents, and what does not."""

import json
from dataclasses import replace

from odoo import Command
from odoo.tests import tagged

from ..services.context import ExecutionContext, RunBudget
from ..services.enums import (
    DenialReason,
    ExecutionMode,
    HandoffState,
    TriggerType,
)
from ..services.exceptions import AIAccessDenied, NEUTRAL_DENIAL
from ..services.handoff_service import (
    handoff_idempotency_key,
    record_idempotency_key,
)
from .common import AIOperationsCommon

SCHEMA = json.dumps({
    'product_id': 'int', 'qty_required': 'float', 'qty_available': 'float',
    'qty_shortage': 'float', 'uom_id': 'int', 'required_date': 'date',
    'origin_ref': 'str', 'warehouse_id': 'int', 'priority': 'str',
})

PAYLOAD = {
    'product_id': 1, 'qty_required': 1000.0, 'qty_available': 514.0,
    'qty_shortage': 486.0, 'uom_id': 1, 'required_date': '2026-09-10',
    'origin_ref': 'MO-00842', 'warehouse_id': 1, 'priority': '2',
}


@tagged('post_install', '-at_install', 'ai_security')
class TestHandoffs(AIOperationsCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.service = cls.env['ai.operations.handoff.service']
        cls.Handoff = cls.env['ai.operations.handoff']

        cls.receiver = cls._make_profile(code='kt_hoff_procurement',
                                         name='Procurement (handoff test)')
        cls.raiser_a = cls._make_profile(code='kt_hoff_manufacturing',
                                         name='Manufacturing (handoff test)')
        cls.raiser_b = cls._make_profile(code='kt_hoff_inventory',
                                         name='Inventory (handoff test)')

        cls.shortage_type = cls.env['ai.operations.handoff.type'].create({
            'code': 'TEST_MATERIAL_SHORTAGE', 'name': 'Material Shortage',
            'from_profile_ids': [Command.set([cls.raiser_a.id])],
            'to_profile_id': cls.receiver.id, 'payload_schema': SCHEMA})
        cls.replenish_type = cls.env['ai.operations.handoff.type'].create({
            'code': 'TEST_REPLENISHMENT', 'name': 'Replenishment Request',
            'from_profile_ids': [Command.set([cls.raiser_b.id])],
            'to_profile_id': cls.receiver.id, 'payload_schema': SCHEMA})

    def _ctx(self, profile):
        return ExecutionContext(
            env=self.env, profile=profile, execution_user=self.env.user,
            execution_mode='INTERACTIVE', trigger='CHAT',
            company_ids=(self.company.id,), autonomy=2, tool_code='kt_test',
            correlation_id='corr-handoff', session_id='s', audit_id=0,
            policy_version='1.0.0', budget=RunBudget())

    # -- T-50 to T-53: what may cross -------------------------------------

    def test_t50_a_valid_shortage_carries_exactly_nine_fields(self):
        handoff = self.service.raise_handoff(
            self._ctx(self.raiser_a), 'TEST_MATERIAL_SHORTAGE', dict(PAYLOAD))
        self.assertEqual(len(handoff.payload), 9)
        self.assertEqual(handoff.state, HandoffState.REQUESTED.value)
        self.assertTrue(handoff.name.startswith('AIH/'))

    def test_t51_a_cost_field_in_the_payload_is_rejected(self):
        """Rejected at write time, not filtered. Filtering would normalise an
        attempted leak into a success."""
        payload = dict(PAYLOAD, unit_cost=4.42)
        with self.assertRaises(AIAccessDenied) as caught:
            self.service.raise_handoff(
                self._ctx(self.raiser_a), 'TEST_MATERIAL_SHORTAGE', payload)
        self.assertEqual(caught.exception.reason,
                         DenialReason.HANDOFF_SCHEMA_VIOLATION)

    def test_t52_conversation_history_cannot_ride_along(self):
        payload = dict(PAYLOAD, conversation=[{'role': 'user', 'content': 'hi'}])
        with self.assertRaises(AIAccessDenied):
            self.service.raise_handoff(
                self._ctx(self.raiser_a), 'TEST_MATERIAL_SHORTAGE', payload)

    def test_a_missing_declared_field_is_also_rejected(self):
        payload = dict(PAYLOAD)
        payload.pop('qty_shortage')
        with self.assertRaises(AIAccessDenied):
            self.service.raise_handoff(
                self._ctx(self.raiser_a), 'TEST_MATERIAL_SHORTAGE', payload)

    def test_t53_an_unauthorised_raiser_is_refused(self):
        from odoo.exceptions import ValidationError
        with self.assertRaises(ValidationError):
            self.Handoff.create({
                'type_id': self.shortage_type.id,
                'from_profile_id': self.raiser_b.id,   # not in from_profile_ids
                'to_profile_id': self.receiver.id,
                'payload': dict(PAYLOAD)})

    def test_t55_an_unknown_handoff_type_is_refused(self):
        with self.assertRaises(AIAccessDenied) as caught:
            self.service.raise_handoff(
                self._ctx(self.raiser_a), 'NO_SUCH_TYPE', dict(PAYLOAD))
        self.assertEqual(caught.exception.reason,
                         DenialReason.HANDOFF_SCHEMA_VIOLATION)

    def test_t54_the_receiver_gains_no_access_from_the_reference(self):
        """source_model and source_res_id are labels for human traceability.
        The receiving agent resolves records through its OWN permissions, so a
        handoff naming MO-00842 does not let Procurement read it."""
        handoff = self.service.raise_handoff(
            self._ctx(self.raiser_a), 'TEST_MATERIAL_SHORTAGE', dict(PAYLOAD),
            source_model='mrp.production', source_res_id=4242)
        self.assertEqual(handoff.source_model, 'mrp.production')
        receiver_ctx = self._ctx(self.receiver)
        with self.assertRaises(AIAccessDenied) as caught:
            receiver_ctx.security.check_model(
                self.receiver, 'mrp.production', 'read')
        self.assertEqual(caught.exception.reason, DenialReason.MODEL_NOT_PERMITTED)

    # -- T-56 / T-57: idempotency, and finding B1 ---------------------------

    def test_t56_the_same_key_returns_the_first_handoff(self):
        key = handoff_idempotency_key(self.company.id, 'shortage', 'PK-BTL-330',
                                      'RM', '2026-09-04')
        first = self.service.raise_handoff(
            self._ctx(self.raiser_a), 'TEST_MATERIAL_SHORTAGE', dict(PAYLOAD),
            idempotency_key=key)
        second = self.service.raise_handoff(
            self._ctx(self.raiser_a), 'TEST_MATERIAL_SHORTAGE', dict(PAYLOAD),
            idempotency_key=key)
        self.assertEqual(first, second)

    def test_t57_two_agents_one_shortage_one_item_of_work(self):
        """Review finding B1, and the reason the key format had to change.

        Manufacturing and Inventory notice the same shortage on the same morning
        and raise DIFFERENT types. Document C §13's key is prefixed with the
        raising profile, so the two would produce different strings, the unique
        index would never fire, and Procurement would work the shortage twice --
        which is exactly what Document B §11 row 13 says cannot happen.

        The handoff key is therefore raiser-agnostic.
        """
        key = handoff_idempotency_key(self.company.id, 'shortage', 'PK-BTL-330',
                                      'RM', '2026-09-04')
        from_manufacturing = self.service.raise_handoff(
            self._ctx(self.raiser_a), 'TEST_MATERIAL_SHORTAGE', dict(PAYLOAD),
            idempotency_key=key)
        from_inventory = self.service.raise_handoff(
            self._ctx(self.raiser_b), 'TEST_REPLENISHMENT', dict(PAYLOAD),
            idempotency_key=key)

        self.assertEqual(from_manufacturing, from_inventory,
                         "Procurement must see one item of work, not two")
        queue = self.Handoff.search([
            ('to_profile_id', '=', self.receiver.id),
            ('idempotency_key', '=', key)])
        self.assertEqual(len(queue), 1)

    def test_the_two_key_builders_are_deliberately_different(self):
        """One format was doing two jobs with opposite requirements."""
        record_key = record_idempotency_key(
            'manufacturing', 1, 'shortage', 'PK-BTL-330', 'RM', '2026-09-04')
        other_record_key = record_idempotency_key(
            'inventory', 1, 'shortage', 'PK-BTL-330', 'RM', '2026-09-04')
        self.assertNotEqual(record_key, other_record_key,
                            "record keys must not collide across profiles")

        work_key = handoff_idempotency_key(
            1, 'shortage', 'PK-BTL-330', 'RM', '2026-09-04')
        self.assertNotIn('manufacturing', work_key)
        self.assertNotIn('inventory', work_key)

    def test_t94_a_different_receiver_is_a_different_unit_of_work(self):
        """Uniqueness is scoped to the receiver, not globally."""
        key = handoff_idempotency_key(self.company.id, 'shortage', 'X', 'RM', 'd')
        other_receiver = self._make_profile(code='kt_hoff_other', name='Other')
        other_type = self.env['ai.operations.handoff.type'].create({
            'code': 'TEST_OTHER', 'name': 'Other',
            'to_profile_id': other_receiver.id, 'payload_schema': SCHEMA})
        first = self.service.raise_handoff(
            self._ctx(self.raiser_a), 'TEST_MATERIAL_SHORTAGE', dict(PAYLOAD),
            idempotency_key=key)
        second = self.service.raise_handoff(
            self._ctx(self.raiser_a), 'TEST_OTHER', dict(PAYLOAD),
            idempotency_key=key)
        self.assertNotEqual(first, second)

    # -- the queue -----------------------------------------------------------

    def test_the_receiver_accepts_and_completes_its_own_work(self):
        handoff = self.service.raise_handoff(
            self._ctx(self.raiser_a), 'TEST_MATERIAL_SHORTAGE', dict(PAYLOAD))
        ctx = self._ctx(self.receiver)
        self.service.accept(ctx, handoff.id)
        self.assertEqual(handoff.state, HandoffState.ACCEPTED.value)
        self.service.complete(ctx, handoff.id,
                              result_model='purchase.order', result_res_id=7)
        self.assertEqual(handoff.state, HandoffState.COMPLETED.value)

    def test_an_agent_cannot_accept_work_from_another_queue(self):
        handoff = self.service.raise_handoff(
            self._ctx(self.raiser_a), 'TEST_MATERIAL_SHORTAGE', dict(PAYLOAD))
        with self.assertRaises(AIAccessDenied) as caught:
            self.service.accept(self._ctx(self.raiser_b), handoff.id)
        self.assertEqual(caught.exception.reason, DenialReason.RECORD_OUT_OF_DOMAIN)

    # -- somebody is told -----------------------------------------------------

    def _activities_for(self, handoff):
        return self.env['mail.activity'].search([
            ('res_model', '=', 'ai.operations.handoff'),
            ('res_id', '=', handoff.id),
            ('ai_reason_code', '=', 'HANDOFF_RECEIVED')])

    def test_raising_puts_the_work_on_the_receivers_desk(self):
        """The gap George reported: a handoff was raised and nobody was told.

        A queue nobody is notified about is a queue nobody works.
        """
        handoff = self.service.raise_handoff(
            self._ctx(self.raiser_a), 'TEST_MATERIAL_SHORTAGE', dict(PAYLOAD))
        activity = self._activities_for(handoff)
        self.assertEqual(len(activity), 1)
        self.assertEqual(activity.user_id, self.receiver.default_review_user_id,
                         "the item must land on the RECEIVER's desk, not the "
                         "desk of the agent that raised it")
        self.assertIn(handoff.name, activity.summary)

    def test_the_handoff_narrates_itself_on_its_own_record(self):
        """The chatter is where the cascade explains itself, because the record
        is already evidence and a chat channel belongs to one employee."""
        handoff = self.service.raise_handoff(
            self._ctx(self.raiser_a), 'TEST_MATERIAL_SHORTAGE', dict(PAYLOAD))
        bodies = handoff.message_ids.mapped('body')
        self.assertTrue(any(handoff.name in (body or '') for body in bodies))

    def test_the_note_carries_the_values_not_the_field_names(self):
        """It shipped rendering the payload as its comma-joined KEY NAMES.

        The dict reached a lazy ``_()`` and came back as "product_id,
        qty_required, qty_available, ... and priority" -- so a receiver opening
        the activity was told which fields exist and nothing else. It was on a
        customer-facing screen before anyone read it.
        """
        handoff = self.service.raise_handoff(
            self._ctx(self.raiser_a), 'TEST_MATERIAL_SHORTAGE', dict(PAYLOAD))
        note = self._activities_for(handoff).note or ''

        self.assertIn('486', note, "the shortage quantity is the whole point")
        self.assertIn('1000', note)
        self.assertIn('MO-00842', note, "the receiver needs the order reference")
        self.assertNotIn('qty_shortage, uom_id', note,
                         "the payload rendered as a list of field names again")

    def test_the_note_breaks_into_lines_in_an_html_field(self):
        """``mail.activity.note`` and a message body are HTML, so "\\n" is not a
        line break there and the whole note rendered as one run. The field's
        content type decides, never the string."""
        handoff = self.service.raise_handoff(
            self._ctx(self.raiser_a), 'TEST_MATERIAL_SHORTAGE', dict(PAYLOAD))
        note = self._activities_for(handoff).note or ''
        self.assertIn('<br', note)
        self.assertNotIn('\n', note.strip('\n'))

    def test_an_idempotent_hit_does_not_raise_a_second_notification(self):
        """The dedup search carries no state filter, so a CANCELLED handoff
        keeps answering its key. Notifying on the second raise would put a dead
        item back on somebody's desk every time the demo is re-run."""
        key = handoff_idempotency_key(self.company.id, 'shortage', 'PK-BTL-600',
                                      'RM', '2026-09-09')
        first = self.service.raise_handoff(
            self._ctx(self.raiser_a), 'TEST_MATERIAL_SHORTAGE', dict(PAYLOAD),
            idempotency_key=key)
        self.service.raise_handoff(
            self._ctx(self.raiser_a), 'TEST_MATERIAL_SHORTAGE', dict(PAYLOAD),
            idempotency_key=key)
        self.assertEqual(len(self._activities_for(first)), 1)

    def test_the_work_is_still_queued_when_nobody_can_be_assigned(self):
        """Routing fails closed and the raise survives it. The handoff is the
        deliverable; the notification is not, and losing the second must never
        cost the first."""
        reviewer = self._make_user('kt.hoff.gone', 'Left the company')
        receiver = self._make_profile(code='kt_hoff_unrouted',
                                      name='Unrouted receiver',
                                      default_review_user_id=reviewer.id)
        self.env['ai.operations.handoff.type'].create({
            'code': 'TEST_UNROUTED', 'name': 'Unrouted',
            'to_profile_id': receiver.id, 'payload_schema': SCHEMA})
        # An active profile must name both routing users, so the way a desk
        # actually disappears is the person leaving, not the field emptying.
        reviewer.active = False

        handoff = self.service.raise_handoff(
            self._ctx(self.raiser_a), 'TEST_UNROUTED', dict(PAYLOAD))

        self.assertTrue(handoff.exists())
        self.assertEqual(handoff.state, HandoffState.REQUESTED.value)
        self.assertFalse(self._activities_for(handoff))

    def test_a_handoff_triggered_run_may_not_raise_a_handoff(self):
        """One hop. Two agents passing the same work back and forth spend a
        provider call per bounce and carry one bad payload past the department
        that produced it."""
        cascading = replace(self._ctx(self.raiser_a), trigger='HANDOFF')
        with self.assertRaises(AIAccessDenied) as caught:
            self.service.raise_handoff(
                cascading, 'TEST_MATERIAL_SHORTAGE', dict(PAYLOAD))
        self.assertEqual(caught.exception.reason,
                         DenialReason.HANDOFF_CASCADE_BLOCKED)

    def test_arrival_tells_the_receiver_and_runs_NOTHING(self):
        """Phase 1 is Level 2 Prepare, and Level 2 has a human in it.

        Arrival may put work on a desk. It may not do the work. An agent that
        accepts a handoff, drafts a purchase order and files a review activity
        with nobody watching is executing unattended, whatever the records it
        writes are called -- and Document B §3 caps Phase 1 below that.

        Patched at ``run`` rather than driven for real, for the same reason the
        cron entry-point test patches it: what is asserted is the wiring.
        """
        calls = []

        def fake_run(self, profile_code, trigger, session_id=None,
                     entry_prompt=None, correlation_id=None, history=None,
                     images=None):
            calls.append(profile_code)
            return {'status': 'COMPLETED', 'correlation_id': correlation_id}

        self.patch(type(self.env['ai.operations.execution']), 'run', fake_run)
        handoff = self.service.raise_handoff(
            self._ctx(self.raiser_a), 'TEST_MATERIAL_SHORTAGE', dict(PAYLOAD))

        self.assertEqual(calls, [], "arrival entered an agent unattended")
        self.assertEqual(handoff.state, HandoffState.REQUESTED.value,
                         "arrival moved the handoff's state by itself")
        # and the notification half is untouched
        self.assertEqual(len(self._activities_for(handoff)), 1)
        self.assertTrue(handoff.message_ids)

    def test_arrival_writes_no_business_record_of_its_own(self):
        """The same claim, stated as a census rather than as a patch.

        A count is the honest form here: patching ``run`` proves nothing was
        entered through the door we know about, and this proves nothing was
        written through any other one.
        """
        Purchase = self.env['purchase.order'] if 'purchase.order' in self.env \
            else None
        before_activities = self.env['mail.activity'].search_count([])
        before_purchases = Purchase.search_count([]) if Purchase else 0

        handoff = self.service.raise_handoff(
            self._ctx(self.raiser_a), 'TEST_MATERIAL_SHORTAGE', dict(PAYLOAD))

        after_activities = self.env['mail.activity'].search_count([])
        self.assertEqual(
            after_activities - before_activities, 1,
            "arrival created something besides the one review activity")
        if Purchase:
            self.assertEqual(
                Purchase.search_count([]), before_purchases,
                "arrival drafted a purchase order with nobody watching")
        self.assertFalse(handoff.result_model)
        self.assertFalse(handoff.result_res_id)

    def test_the_human_starts_the_work_and_the_run_is_interactive(self):
        """The replacement for the unattended entry.

        The button carries the trigger for provenance -- the audit still says
        this run came from a handoff -- and nothing else about it is
        autonomous: the identity is the person who pressed it, so their own
        ACLs and their own eligibility apply.
        """
        calls = []

        def fake_run(self, profile_code, trigger, session_id=None,
                     entry_prompt=None, correlation_id=None, history=None,
                     images=None):
            calls.append({'profile_code': profile_code, 'trigger': trigger,
                          'entry_prompt': entry_prompt,
                          'user': self.env.user})
            return {'status': 'COMPLETED', 'correlation_id': correlation_id}

        self.patch(type(self.env['ai.operations.execution']), 'run', fake_run)
        handoff = self.service.raise_handoff(
            self._ctx(self.raiser_a), 'TEST_MATERIAL_SHORTAGE', dict(PAYLOAD))
        self.assertEqual(calls, [])

        self.receiver.user_ids = [Command.link(self.env.user.id)]
        handoff.action_start_work()

        self.assertEqual(len(calls), 1, "the button did not enter the agent")
        self.assertEqual(calls[0]['profile_code'], self.receiver.code)
        self.assertEqual(calls[0]['trigger'], 'HANDOFF',
                         "provenance was lost when the entry became attended")
        self.assertIn(handoff.name, calls[0]['entry_prompt'])
        self.assertEqual(calls[0]['user'], self.env.user,
                         "the run did not carry the identity that started it")

    def _start_work_returning(self, result):
        def fake_run(self, profile_code, trigger, session_id=None,
                     entry_prompt=None, correlation_id=None, history=None,
                     images=None):
            return dict(result, correlation_id=correlation_id)

        self.patch(type(self.env['ai.operations.execution']), 'run', fake_run)
        handoff = self.service.raise_handoff(
            self._ctx(self.raiser_a), 'TEST_MATERIAL_SHORTAGE', dict(PAYLOAD))
        self.receiver.user_ids = [Command.link(self.env.user.id)]
        return handoff.action_start_work()

    def test_start_work_returns_an_action_the_web_client_can_run(self):
        """A button's return value IS a client action.

        The web client hands whatever a button returns to its action service,
        and a dict with no ``type`` is an error dialog: the run had finished
        and committed, and the person who pressed the button was shown a
        failure. Calling the method from Python, as every test above does,
        accepts any return value at all.
        """
        action = self._start_work_returning(
            {'status': 'COMPLETED', 'refused': False,
             'content': 'Drafted P00099 for review.'})

        self.assertEqual(action['type'], 'ir.actions.client')
        self.assertEqual(action['tag'], 'display_notification')
        self.assertEqual(action['params']['message'],
                         'Drafted P00099 for review.')
        self.assertEqual(action['params']['next']['tag'], 'soft_reload',
                         "the form never shows the handoff it just closed")

    def test_a_refused_start_work_shows_only_the_neutral_denial(self):
        """The button is a surface, like the chat, and the same rule holds.

        Whatever the model wrote after a refusal is dropped; the reason lives
        on the audit row.
        """
        action = self._start_work_returning(
            {'status': 'COMPLETED', 'refused': True,
             'content': 'You lack purchase rights for that vendor.'})

        self.assertEqual(action['params']['message'], NEUTRAL_DENIAL)
        self.assertEqual(action['params']['type'], 'warning')

    def test_a_handoff_run_is_INTERACTIVE_and_carries_the_human(self):
        """The mode itself, at the one place that decides it.

        A HANDOFF run used to resolve to AUTONOMOUS and therefore to the
        profile's service user. It is now the same mode a chat is, because
        there is now a human in it -- which is also what makes eligibility and
        `USER_ACL_DENIED` mean anything on this path.
        """
        security = self.env['ai.operations.security']
        self.assertEqual(
            security.resolve_mode(TriggerType.HANDOFF.value),
            ExecutionMode.INTERACTIVE.value)
        self.assertEqual(
            security.resolve_mode(TriggerType.CRON.value),
            ExecutionMode.AUTONOMOUS.value)
        self.assertEqual(
            security.resolve_identity(
                self.receiver, security.resolve_mode(TriggerType.HANDOFF.value)),
            self.env.user)

    def test_a_receiver_the_starter_may_not_use_is_refused(self):
        """Eligibility is not decorative on this path either.

        Pressed by a plain AI user the receiving profile does not name. Not by
        the test's own user: a security administrator is eligible for every
        agent by design, so a refusal asserted as the superuser asserts
        nothing. (And one exception class, not a tuple: Odoo's
        ``assertRaises`` takes ``issubclass`` of its argument.)
        """
        handoff = self.service.raise_handoff(
            self._ctx(self.raiser_a), 'TEST_MATERIAL_SHORTAGE', dict(PAYLOAD))
        clerk = self._make_user('ai.test.clerk', 'Not On This Agent')
        clerk.write({'group_ids': [
            Command.link(self.env.ref('ai_operations.group_ai_user').id)]})
        self.assertNotIn(clerk, self.receiver.user_ids)
        with self.assertRaises(AIAccessDenied) as caught:
            handoff.with_user(clerk).action_start_work()
        self.assertEqual(caught.exception.reason,
                         DenialReason.PROFILE_NOT_ELIGIBLE)
