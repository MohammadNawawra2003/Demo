"""Session 11's real deliverable: the cron, and that it is a real entry point
into the one runtime.

Document C §9's diagram gives the autonomous branch as
``ir.cron → trigger = CRON``. Session 11's STOP gate was T-97/T-98, which test
the activity service directly and pass whether or not any cron exists — the same
shape as Session 12's gate. So these tests start from **the shipped cron record**
and run the server action the scheduler itself runs
(``ir_cron._callback`` → ``ir.actions.server.run()``), rather than calling
``run()`` and asserting it works.

``_callback`` commits, so it is deliberately not used here; the server action
underneath it is the same object and stays inside the test transaction.
"""

from odoo import Command
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install', 'ai_security')
class TestCronEntryPoint(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.cron = cls.env.ref('ai_operations_procurement.cron_ai_procurement')

    def test_the_pack_ships_a_cron_for_its_profile(self):
        self.assertTrue(self.cron, "no cron ships with the procurement pack")

    def test_the_cron_ships_inactive(self):
        """It belongs to a profile that ships inactive for the same reason: a
        policy pack cannot know the client's company or routing users."""
        self.assertFalse(self.cron.active)

    def test_the_cron_targets_the_one_runtime(self):
        """Not a pack-local helper, not a second loop. The runner in C §9."""
        self.assertEqual(self.cron.model_id.model, 'ai.operations.execution')
        self.assertEqual(self.cron.state, 'code')

    def test_running_the_cron_reaches_the_runtime_with_the_cron_trigger(self):
        """The deliverable. This runs the server action the scheduler runs."""
        calls = []

        def fake_run(self, profile_code, trigger, session_id=None,
                     entry_prompt=None, correlation_id=None):
            calls.append({'profile_code': profile_code, 'trigger': trigger})
            return {'status': 'COMPLETED', 'correlation_id': 'c'}

        self.patch(type(self.env['ai.operations.execution']), 'run', fake_run)

        self.cron.ir_actions_server_id.run()

        self.assertEqual(len(calls), 1, "the cron never reached the runtime")
        self.assertEqual(calls[0]['profile_code'], 'procurement')
        self.assertEqual(calls[0]['trigger'], 'CRON')

    def test_the_cron_really_runs_the_runtime(self):
        """No patching. Once the profile is activated the way a deployment must
        activate it, the real runtime fails on the unconfigured provider and
        audits that -- which can only happen if the cron genuinely entered
        run()."""
        self._activate_profile()
        Log = self.env['ai.operations.audit.log']
        before = Log.search_count([('event_type', '=', 'ERROR')])

        self.cron.ir_actions_server_id.run()

        self.assertEqual(Log.search_count([('event_type', '=', 'ERROR')]),
                         before + 1,
                         "the real runtime was never entered by the cron")

    def _activate_profile(self):
        """Exactly what C §5.1's constraints demand before a cron can fire:
        a company scope, both routing users, and an autonomous identity."""
        company = self.env['res.company'].create({'name': 'Naqaa Cron Test'})
        users = self.env['res.users']
        reviewer, escalation, service = (
            users.create({'name': name, 'login': login,
                          'company_id': company.id,
                          'company_ids': [Command.set([company.id])]})
            for name, login in (('Cron Reviewer', 'ai.cron.reviewer'),
                                ('Cron Escalation', 'ai.cron.escalation'),
                                ('AI / Cron Service', 'ai.cron.service')))
        service.write({'group_ids': [
            Command.link(self.env.ref('ai_operations.group_ai_user').id)]})

        profile = self.env['ai.operations.agent.profile'].with_context(
            active_test=False).search([('code', '=', 'procurement')], limit=1)
        profile.write({
            'company_ids': [Command.set([company.id])],
            'default_review_user_id': reviewer.id,
            'default_escalation_user_id': escalation.id,
            'service_user_id': service.id,
            'allow_autonomous': True,
            'active': True,
        })
        return profile
