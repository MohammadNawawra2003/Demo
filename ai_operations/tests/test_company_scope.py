"""An agent whose company scope is wider than its user's must still run.

Document C §12 makes the Inventory agent span C1 and C2 deliberately -- "the
sharpest test", seeing quantities across the boundary and values across neither
-- while the people who use it sit in one company. So a profile scoped wider
than its executing user is not an edge case, it is the shape the specification
asks for.

It crashed. ``audit_service.open_entry`` and ``resolve_companies`` both read
``profile.company_ids`` as records, ``convert_to_record`` filters them on
``active``, and fetching those rows trips the multi-company record rule for any
user who is not in every company the profile spans. The call died with
AccessError out of the audit service before the guard had finished opening its
row: a crash, not a refusal, and nothing in the audit log to say why.

It survived every test and every demo because both ran as an administrator, who
reads all companies. uid 1 is worse still -- it bypasses record rules outright.
So this suite builds a real user, in one company, and asks it to use an agent
scoped to two.
"""

from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install', 'ai_security')
class TestProfileCompanyScope(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company_a = cls.env['res.company'].create({'name': 'KT Scope A'})
        cls.company_b = cls.env['res.company'].create({'name': 'KT Scope B'})
        # In ONE company, while the agent below spans two.
        cls.narrow_user = cls.env['res.users'].create({
            'name': 'KT Narrow User',
            'login': 'kt_narrow_user',
            'company_id': cls.company_a.id,
            'company_ids': [(6, 0, cls.company_a.ids)],
            'group_ids': [(4, cls.env.ref('base.group_user').id),
                          (4, cls.env.ref('ai_operations.group_ai_user').id)],
        })
        cls.profile = cls.env['ai.operations.agent.profile'].create({
            'name': 'KT Scope Agent',
            'code': 'kt_scope',
            'company_ids': [(6, 0, (cls.company_a + cls.company_b).ids)],
            'default_review_user_id': cls.narrow_user.id,
            'default_escalation_user_id': cls.narrow_user.id,
        })

    def _as_user(self):
        """The profile as the narrow user actually holds it."""
        return self.profile.with_user(self.narrow_user)

    def test_the_scope_reads_without_touching_company_records(self):
        self.assertEqual(
            sorted(self._as_user().scoped_company_ids()),
            sorted((self.company_a + self.company_b).ids),
            "a user narrower than the agent cannot read its own scope")

    def test_resolve_companies_intersects_instead_of_raising(self):
        """Step 8 must bound this user, not crash on it."""
        effective = self.env['ai.operations.security'].with_user(
            self.narrow_user).resolve_companies(
                self._as_user(), self.narrow_user)
        self.assertEqual(
            effective, self.company_a.ids,
            "the intersection must be the one company the user actually has")

    def test_opening_an_audit_row_does_not_raise(self):
        """The crash was here, before the guard had decided anything."""
        audit = self.env['ai.operations.audit'].with_user(self.narrow_user)
        correlation = audit.open_entry(
            'kt.scope.tool', self._as_user(), self.narrow_user,
            'INTERACTIVE', 'CHAT', 'kt-session', 'kt-correlation')
        self.assertEqual(correlation, 'kt-correlation')

    def test_the_audit_row_records_a_company_from_the_agents_scope(self):
        audit = self.env['ai.operations.audit'].with_user(self.narrow_user)
        audit.open_entry(
            'kt.scope.tool', self._as_user(), self.narrow_user,
            'INTERACTIVE', 'CHAT', 'kt-session', 'kt-correlation-2')
        row = self.env['ai.operations.audit.log'].search(
            [('correlation_id', '=', 'kt-correlation-2')], limit=1)
        self.assertTrue(row, "no audit row was written")
        self.assertIn(
            row.company_id.id, (self.company_a + self.company_b).ids,
            "the audit row's company is not one the agent is scoped to")

    def test_a_user_sharing_no_company_with_the_agent_is_still_denied(self):
        """The fix must not turn a real boundary into a pass.

        Widening how the scope is READ must not widen what it GRANTS: a user
        with no company in common with the agent still has an empty
        intersection, and step 8 still denies.
        """
        from odoo.addons.ai_operations.services.exceptions import AIAccessDenied

        stranger = self.env['res.users'].create({
            'name': 'KT Stranger',
            'login': 'kt_stranger',
            'company_id': self.company_b.id,
            'company_ids': [(6, 0, self.company_b.ids)],
            'group_ids': [(4, self.env.ref('base.group_user').id),
                          (4, self.env.ref('ai_operations.group_ai_user').id)],
        })
        only_a = self.env['ai.operations.agent.profile'].create({
            'name': 'KT Scope A Only',
            'code': 'kt_scope_a_only',
            'company_ids': [(6, 0, self.company_a.ids)],
            'default_review_user_id': self.narrow_user.id,
            'default_escalation_user_id': self.narrow_user.id,
        })
        with self.assertRaises(AIAccessDenied):
            self.env['ai.operations.security'].with_user(
                stranger).resolve_companies(
                    only_a.with_user(stranger), stranger)
