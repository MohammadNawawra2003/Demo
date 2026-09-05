"""Session 9: T-50 to T-57. What crosses between two agents, and what does not."""

import json

from odoo import Command
from odoo.tests import tagged

from ..services.context import ExecutionContext, RunBudget
from ..services.enums import DenialReason, HandoffState
from ..services.exceptions import AIAccessDenied
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

        cls.receiver = cls._make_profile(code='hoff_procurement',
                                         name='Procurement (handoff test)')
        cls.raiser_a = cls._make_profile(code='hoff_manufacturing',
                                         name='Manufacturing (handoff test)')
        cls.raiser_b = cls._make_profile(code='hoff_inventory',
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
            company_ids=(self.company.id,), autonomy=2, tool_code='test',
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

    def test_a_different_receiver_is_a_different_unit_of_work(self):
        """Uniqueness is scoped to the receiver, not globally."""
        key = handoff_idempotency_key(self.company.id, 'shortage', 'X', 'RM', 'd')
        other_receiver = self._make_profile(code='hoff_other', name='Other')
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
