from odoo import Command
from odoo.tests import TransactionCase


class AIOperationsCommon(TransactionCase):
    """Synthetic fixtures, seeded by the test.

    Never alshayeb_demo_water -- that module is for the end-to-end suite only
    (Document D 14).
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Profile = cls.env['ai.operations.agent.profile']
        cls.ModelPermission = cls.env['ai.operations.model.permission']
        cls.ActionPermission = cls.env['ai.operations.action.permission']
        cls.IrModel = cls.env['ir.model']

        cls.company = cls.env['res.company'].create({'name': 'AI Test Manufacturing'})
        cls.other_company = cls.env['res.company'].create({'name': 'AI Test Distribution'})

        cls.reviewer = cls._make_user('ai.test.reviewer', 'Routine Reviewer')
        cls.escalation = cls._make_user('ai.test.escalation', 'Escalation Manager')
        cls.service_user = cls._make_user('ai.test.service', 'AI / Test Service')
        # A service user must hold AI Operations / User. The guard reads its own
        # policy as the executing identity and sudo() is banned, so without it
        # every autonomous run dies on its own configuration.
        cls.service_user.write({'group_ids': [
            Command.link(cls.env.ref('ai_operations.group_ai_user').id)]})
        cls.outsider = cls._make_user(
            'ai.test.outsider', 'Other Company User', company=cls.other_company)

        cls.system_user = cls._make_user('ai.test.system', 'System Administrator')
        cls.system_user.write({
            'group_ids': [Command.link(cls.env.ref('base.group_system').id)],
        })

        cls.profile = cls._make_profile()

    @classmethod
    def _make_user(cls, login, name, company=None):
        company = company or cls.company
        return cls.env['res.users'].create({
            'name': name,
            'login': login,
            'company_id': company.id,
            'company_ids': [Command.set([company.id])],
        })

    @classmethod
    def _make_profile(cls, **overrides):
        values = {
            # Deliberately not 'procurement'. Once the real tool packs ship
            # their policy profiles, a fixture squatting on a production code
            # collides with the unique constraint and takes every kernel test
            # down with it.
            'name': 'Kernel Test Agent',
            'code': 'kt_kernel',
            'company_ids': [Command.set([cls.company.id])],
            'max_autonomy_level': '2',
            'default_review_user_id': cls.reviewer.id,
            'default_escalation_user_id': cls.escalation.id,
        }
        values.update(overrides)
        return cls.env['ai.operations.agent.profile'].create(values)

    def _model(self, model_name):
        return self.env['ir.model']._get(model_name)
