from odoo.exceptions import ValidationError
from odoo.tests import tagged

from .common import AIOperationsCommon


@tagged('post_install', '-at_install', 'ai_security')
class TestModelPermission(AIOperationsCommon):

    def _permission(self, **overrides):
        values = {
            'profile_id': self.profile.id,
            'model_id': self._model('res.partner').id,
            'perm_read': True,
        }
        values.update(overrides)
        return self.ModelPermission.create(values)

    # -- domain validation -------------------------------------------------

    def test_literal_domain_is_accepted(self):
        permission = self._permission(domain="[('supplier_rank', '>', 0)]")
        self.assertEqual(permission.domain, "[('supplier_rank', '>', 0)]")

    def test_empty_domain_is_accepted(self):
        self.assertTrue(self._permission(domain=False))

    def test_t17_domain_containing_a_lambda_is_rejected(self):
        with self.assertRaises(ValidationError):
            self._permission(domain="[('id', '=', lambda r: r.id)]")

    def test_t17_domain_containing_a_call_is_rejected(self):
        with self.assertRaises(ValidationError):
            self._permission(domain="[('id', '=', get_id())]")

    def test_t17_unparseable_domain_is_rejected(self):
        with self.assertRaises(ValidationError):
            self._permission(domain="[('id', '=',")

    def test_t17_domain_that_is_not_a_list_is_rejected(self):
        with self.assertRaises(ValidationError):
            self._permission(domain="'everything'")

    def test_t17_malformed_leaf_is_rejected(self):
        with self.assertRaises(ValidationError):
            self._permission(domain="[('id', '=')]")

    def test_t17_unknown_operator_string_is_rejected(self):
        with self.assertRaises(ValidationError):
            self._permission(domain="['AND', ('id', '=', 1)]")

    def test_finding_b2_policy_pack_sample_domain_is_rejected(self):
        """Review finding B2 -- executable proof, not an opinion.

        Document D 13's shipped policy-pack sample carries
        [('company_id','in',allowed_company_ids)]. `allowed_company_ids` is a
        bare name, so ast.literal_eval raises and the kernel's own validator
        (Document C 5.2) rejects it. That sample is copied verbatim into four
        tool packs in Sessions 8-11.
        """
        with self.assertRaises(ValidationError):
            self._permission(domain="[('company_id','in',allowed_company_ids)]")

    # -- state restriction -------------------------------------------------

    def test_state_restriction_field_equals_value_is_accepted(self):
        permission = self._permission(state_restriction='state=draft')
        self.assertEqual(permission.state_restriction, 'state=draft')

    def test_t19_state_restriction_accepts_a_dotted_field_path(self):
        """quality.alert has no state field: it must be keyed on stage_id."""
        permission = self._permission(state_restriction='stage_id.name=New')
        self.assertEqual(permission.state_restriction, 'stage_id.name=New')

    def test_finding_b2_bare_state_restriction_is_rejected(self):
        """Review finding B2, second half.

        Document C 5.2 states a bare value cannot work, then Document D 13's
        sample ships `<field name="state_restriction">draft</field>` anyway.
        """
        with self.assertRaises(ValidationError):
            self._permission(state_restriction='draft')

    def test_state_restriction_without_a_value_is_rejected(self):
        with self.assertRaises(ValidationError):
            self._permission(state_restriction='state=')

    # -- structure ---------------------------------------------------------

    def test_permissions_default_to_deny(self):
        """Allowlist onto a deny baseline: nothing is granted implicitly."""
        permission = self.ModelPermission.create({
            'profile_id': self.profile.id,
            'model_id': self._model('res.currency').id,
        })
        self.assertFalse(permission.perm_read)
        self.assertFalse(permission.perm_create)
        self.assertFalse(permission.perm_write)
        self.assertFalse(permission.perm_unlink)
        self.assertFalse(permission.allow_read_group)
        self.assertEqual(permission.max_records, 200)

    def test_one_permission_record_per_model_per_profile(self):
        from psycopg2 import IntegrityError

        from odoo.tools import mute_logger
        self._permission()
        with self.assertRaises(IntegrityError), mute_logger('odoo.sql_db'):
            self._permission()
            self.env.flush_all()


@tagged('post_install', '-at_install', 'ai_security')
class TestActionPermission(AIOperationsCommon):

    def _action(self, **overrides):
        values = {
            'profile_id': self.profile.id,
            'model_id': self._model('res.partner').id,
            'action_code': 'CREATE_DRAFT',
        }
        values.update(overrides)
        return self.ActionPermission.create(values)

    def test_action_defaults_to_denied(self):
        action = self._action()
        self.assertFalse(action.allowed)

    def test_two_bounds_have_two_defaults(self):
        """20 escalates, 100 denies. They are not the same control."""
        action = self._action()
        self.assertEqual(action.variance_bound_pct, 20.0)
        self.assertEqual(action.variance_ceiling_pct, 100.0)

    def test_finding_b2_bare_state_restriction_is_rejected(self):
        with self.assertRaises(ValidationError):
            self._action(state_restriction='draft')

    def test_state_restriction_field_equals_value_is_accepted(self):
        self.assertTrue(self._action(state_restriction='state=draft'))
