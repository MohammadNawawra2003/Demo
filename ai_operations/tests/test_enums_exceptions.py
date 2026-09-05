from odoo.tests import TransactionCase, tagged

from ..services.enums import (
    PHASE1_MAX_AUTONOMY,
    AuditLevel,
    AutonomyLevel,
    DenialReason,
    to_selection,
)
from ..services.exceptions import NEUTRAL_DENIAL, AIAccessDenied


@tagged('post_install', '-at_install', 'ai_security')
class TestEnumsAndExceptions(TransactionCase):

    def test_audit_level_has_no_none(self):
        """NONE could only mean 'disable the security log'."""
        self.assertNotIn('NONE', AuditLevel.__members__)
        self.assertEqual(
            {level.value for level in AuditLevel},
            {'BASIC', 'STANDARD', 'FULL'},
        )

    def test_access_denied_str_is_neutral_by_construction(self):
        """The reason reaches the audit log. It never reaches a rendered string.

        Asserted on the exception built directly, because the property must hold
        at construction -- not at some call site that remembers to neutralise it.
        """
        error = AIAccessDenied(
            DenialReason.MODEL_NOT_PERMITTED,
            detail='account.move is not in the allowlist',
            model='account.move',
            tool_code='procurement.get_shortage_context',
        )

        self.assertEqual(str(error), NEUTRAL_DENIAL)
        for leak in ('account.move', 'MODEL_NOT_PERMITTED',
                     'allowlist', 'procurement.get_shortage_context'):
            self.assertNotIn(leak, str(error))

        # ...and everything is still on the attributes, for the audit row.
        self.assertEqual(error.reason, DenialReason.MODEL_NOT_PERMITTED)
        self.assertEqual(error.model, 'account.move')
        self.assertEqual(error.tool_code, 'procurement.get_shortage_context')

    def test_denial_reasons_are_a_closed_set(self):
        """Document C 5.9. Drift here silently breaks the test matrix."""
        self.assertEqual(
            {reason.value for reason in DenialReason},
            {
                'UNKNOWN_TOOL', 'TOOL_DISABLED', 'TOOL_NOT_ASSIGNED',
                'PROFILE_INACTIVE', 'AUTONOMY_INSUFFICIENT', 'NO_SERVICE_USER',
                'MODEL_NOT_PERMITTED', 'OPERATION_NOT_PERMITTED',
                'RECORD_OUT_OF_DOMAIN', 'COMPANY_OUT_OF_SCOPE',
                'ACTION_NOT_PERMITTED', 'USER_ACL_DENIED', 'SCHEMA_INVALID',
                'HANDOFF_SCHEMA_VIOLATION', 'BOUND_EXCEEDED', 'BLOCKLIST_HIT',
                'BUDGET_EXCEEDED', 'ASSIGNEE_UNRESOLVED',
            },
        )

    def test_to_selection_emits_string_keys(self):
        """fields.Selection stores varchar, so an int enum must present strings."""
        autonomy = dict(to_selection(AutonomyLevel))
        self.assertEqual(autonomy['0'], 'Query')
        self.assertEqual(autonomy['2'], 'Prepare')
        for key in autonomy:
            self.assertIsInstance(key, str)

        self.assertEqual(dict(to_selection(AuditLevel))['STANDARD'], 'Standard')

    def test_phase1_ceiling_is_prepare(self):
        self.assertEqual(int(PHASE1_MAX_AUTONOMY), 2)
