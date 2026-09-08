"""A tool an agent cannot use is not a capability. It is a dead menu entry.

Every pack declares its tools in Python and its policy in
``data/policy_pack.xml``. Nothing tied the two together, so the two halves were
free to drift -- and they did, silently, for as long as the packs have existed.

The drift was measured on staging on 2026-09-07. Nine of the twenty-one shipped
tools could never run:

* Inventory held no permission for ``mail.activity`` or ``ai.operations.handoff``,
  so ``create_review_activity`` and ``raise_handoff`` denied every call.
* Quality held none for ``mail.activity``, ``mail.message``,
  ``ai.operations.handoff`` or ``quality.alert``, which killed ``propose_hold``
  outright.
* Manufacturing held none for ``mail.activity``.

The guard was right every time: ``MODEL_NOT_PERMITTED``, "X is not in the
allowlist". The permissions existed in the pack XML. They had simply never been
loaded, because ``policy_pack.xml`` is ``noupdate="1"`` and the manifest version
was not bumped when the records were added, so Odoo never re-read the file.

A version bump fixes the instance. This test fixes the class: it fails the
moment a profile is assigned a tool that touches a model the profile has no
permission row for, whatever the cause -- a forgotten permission, a forgotten
version bump, or a tool that grows a new model later.

It sweeps every profile in the database rather than testing one pack, so it
lives in the kernel and covers packs that do not exist yet.
"""

from odoo.tests import tagged

from ..services import registry as registry_module
from ..services.security_service import PERM_FIELD
from ..services.enums import AutonomyLevel, ToolCategory
from .common import AIOperationsCommon


@tagged('post_install', '-at_install', 'ai_security')
class TestPackPolicyCoverage(AIOperationsCommon):

    def _offenders(self, assignments):
        """Which of these assignments the guard would deny on every call.

        Two ways a tool can be dead on arrival, and the first version of this
        test only caught one of them.

        A model missing from the allowlist denies at ``check_model`` step 11,
        before the operation is even looked at. That was the original sweep, and
        it caught George's two refusals.

        But membership is not enough. Step 12 then checks the OPERATION, and
        ``_required_operations`` asks for ``read`` on every declared model. A
        profile holding ``mail.message`` as create-only satisfies the name check
        and is denied ``OPERATION_NOT_PERMITTED`` on every call --
        ``manufacturing.post_readiness_note`` was in exactly that state, unusable
        since the day it shipped, and this test passed it. Comparing names where
        the guard compares operations is how a sweep reports green on a tool
        nobody can run.

        So this asks the guard itself what each tool requires rather than
        re-deriving it, and compares that against the permission flags.
        """
        security = self.env['ai.operations.security']
        Permission = self.env['ai.operations.model.permission']
        offenders = []
        for assignment in assignments:
            code = assignment.tool_id.code
            if not registry_module.has_tool(code):
                # Covered by T-04: a record with no Python behind it cannot be
                # enabled. Not this test's business.
                continue
            profile = assignment.profile_id
            permissions = {
                perm.model_name: perm
                for perm in Permission.search([('profile_id', '=', profile.id)])
            }
            required = security._required_operations(registry_module.get_tool(code))
            for model_name, operations in sorted(required.items()):
                permission = permissions.get(model_name)
                if not permission:
                    offenders.append('%s -> %s needs %s' % (
                        profile.code, code, model_name))
                    continue
                lacking = sorted(
                    operation for operation in operations
                    if not permission[PERM_FIELD[operation]])
                if lacking:
                    offenders.append('%s -> %s needs %s on %s' % (
                        profile.code, code, ', '.join(lacking), model_name))
        return sorted(offenders)

    def test_every_assigned_tool_has_its_models_in_the_allowlist(self):
        """The general form of George's two refusals."""
        offenders = self._offenders(
            self.env['ai.operations.tool.assignment'].search([
                ('enabled', '=', True),
            ]))
        self.assertFalse(
            offenders,
            "these tools are assigned but can never run; the profile has no "
            "model permission for what they touch:\n  %s"
            % '\n  '.join(offenders))

    def test_the_sweep_detects_a_missing_permission(self):
        """Guards the guard.

        The sweep above is vacuous on a bare database -- no packs, no
        assignments, nothing to check -- and a test that cannot fail reports
        green forever, which is how the original drift survived so long.

        Proving it can fail by deleting a real permission does not work: the
        upgrade that runs the suite recreates any ``noupdate`` record whose
        xmlid has lost its row, so the breakage is repaired before the test
        sees it. So the offender is built here instead, synthetically, and fed
        through the same comparison.
        """
        registry_module.allow_registration_for_tests()
        self.addCleanup(registry_module._REGISTRY.pop, 'test.uncovered', None)

        from ..services.schema import Int, Schema, Str

        class _In(Schema):
            partner_id = Int(min=1)

        class _Out(Schema):
            name = Str()

        @registry_module.ai_tool(
            code='test.uncovered', category=ToolCategory.READ,
            autonomy=AutonomyLevel.QUERY, models=['res.currency'],
            input_schema=_In, output_schema=_Out)
        def _tool(ctx, params):
            """Names a model its profile is deliberately not granted."""
            return {}

        tool = self.env['ai.operations.tool'].create({
            'name': 'test.uncovered', 'code': 'test.uncovered', 'enabled': True,
        })
        assignment = self.env['ai.operations.tool.assignment'].create({
            'profile_id': self.profile.id, 'tool_id': tool.id,
        })

        self.assertEqual(
            self._offenders(assignment),
            ['%s -> test.uncovered needs res.currency' % self.profile.code],
            "the sweep no longer detects a tool whose model is unpermitted; "
            "the check that would have caught George's two refusals is dead")

    def test_a_model_declared_only_as_an_action_does_not_also_require_read(self):
        """A create-only permission must be satisfiable.

        Giving every declared model an implicit ``read`` made
        ``manufacturing.post_readiness_note`` impossible to run: it posts to a
        chatter and never reads a message, the pack grants ``mail.message``
        create-only deliberately, and the guard demanded read anyway. The only
        way to satisfy it would have been to let an agent read all chatter in
        order to write one note.
        """
        security = self.env['ai.operations.security']
        spec = registry_module.get_tool('manufacturing.post_readiness_note')
        required = security._required_operations(spec)
        self.assertEqual(
            required.get('mail.message'), {'create'},
            "mail.message is declared through actions alone and must require "
            "only create")
        self.assertEqual(
            required.get('mrp.production'), {'read'},
            "a model in `models` still requires read")

    def test_an_action_only_model_still_has_to_be_in_the_allowlist(self):
        """Dropping the implicit read must not drop the allowlist itself."""
        security = self.env['ai.operations.security']
        spec = registry_module.get_tool('manufacturing.post_readiness_note')
        self.assertIn(
            'mail.message', security._required_operations(spec),
            "an action-only model that vanished from the requirements would "
            "no longer be checked against the profile at all")
