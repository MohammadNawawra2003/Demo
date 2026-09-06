"""The demo configuration is real, and the four scenarios run on it.

**No live vendor call anywhere in this file.** Every scenario patches
``AnthropicProvider.complete`` with a scripted response, so the loop, the guard,
the serialiser, the audit trail and the handoff service are all the production
ones and only the vendor is a double. That is the same discipline the adapter's
own suite uses.

The scenario tests deliberately start from a **posted channel message**, not
from ``run()``: the STOP-gate rule in ``docs/decision-log.md`` DL-006 says a test
must fail when the deliverable is absent, and a test that calls ``run()``
directly would pass with no chat surface at all.
"""

from unittest.mock import patch

from markupsafe import Markup

from odoo.tests import TransactionCase, tagged

from ..models.demo_setup import ASSIGNMENTS, COMPANY, MODEL, PROVIDER, ROUTING


def scripted(env, *responses):
    """Feed the runtime a fixed sequence of vendor replies.

    Patches the *registry* class, as the adapter's own suite does: that is the
    class the runtime resolves through, and patching the source class alone does
    not always reach it.
    """
    calls = list(responses)

    def fake_complete(self, messages, system=None, tools=None, model=None,
                      max_tokens=4096, timeout=120):
        return calls.pop(0) if calls else _text('done')

    provider = env['ai.operations.provider.anthropic']
    return patch.object(type(provider), 'complete', fake_complete)


def _text(body):
    return {'content': body, 'tool_calls': [], 'stop_reason': 'end_turn',
            'usage': {'input_tokens': 10, 'output_tokens': 5}}


def _tool_call(name, arguments, call_id='call-1'):
    return {'content': '', 'stop_reason': 'tool_use',
            'tool_calls': [{'id': call_id, 'name': name, 'input': arguments}],
            'usage': {'input_tokens': 10, 'output_tokens': 5}}


@tagged('post_install', '-at_install', 'ai_security')
class TestDemoConfiguration(TransactionCase):
    """What the module promises a tester will not have to create by hand."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Profile = cls.env['ai.operations.agent.profile'].with_context(
            active_test=False)
        cls.Log = cls.env['ai.operations.audit.log']
        cls.procurement = cls.Profile.search([('code', '=', 'procurement')], limit=1)
        cls.manufacturing = cls.Profile.search([('code', '=', 'manufacturing')], limit=1)

    def _user(self, login):
        return self.env['res.users'].with_context(active_test=False).search(
            [('login', '=', login)], limit=1)

    def _channel(self, name_fragment):
        return self.env['discuss.channel'].search(
            [('name', 'like', name_fragment)], limit=1)

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------

    def test_both_demo_profiles_are_active(self):
        for profile in (self.procurement, self.manufacturing):
            self.assertTrue(profile, "profile missing")
            self.assertTrue(profile.active, "%s is not active" % profile.code)

    def test_profiles_are_scoped_to_the_naqaa_operating_company(self):
        for profile in (self.procurement, self.manufacturing):
            self.assertEqual(profile.company_ids.mapped('name'), [COMPANY])

    def test_routing_users_are_configured(self):
        for code, (reviewer, escalation, service) in ROUTING.items():
            profile = self.Profile.search([('code', '=', code)], limit=1)
            self.assertEqual(profile.default_review_user_id.login, reviewer)
            self.assertEqual(profile.default_escalation_user_id.login, escalation)
            self.assertEqual(profile.service_user_id.login, service)

    def test_the_service_users_are_not_administrators(self):
        """C §10, restated here because a demo is where it would slip."""
        for profile in (self.procurement, self.manufacturing):
            service = profile.service_user_id
            self.assertFalse(service._has_group('base.group_system'))
            self.assertFalse(service.share)

    def test_provider_and_model_are_configured(self):
        for profile in (self.procurement, self.manufacturing):
            self.assertEqual(profile.provider_code, PROVIDER)
            self.assertEqual(profile.model_code, MODEL)

    def test_autonomy_never_exceeds_prepare(self):
        for profile in (self.procurement, self.manufacturing):
            self.assertEqual(int(profile.max_autonomy_level), 2)

    def test_autonomous_running_stays_off_until_a_credential_exists(self):
        for profile in (self.procurement, self.manufacturing):
            self.assertFalse(profile.allow_autonomous)
            self.assertTrue(profile.allow_interactive)

    def test_every_profile_has_a_partner_to_speak_as(self):
        for profile in (self.procurement, self.manufacturing):
            self.assertTrue(profile.partner_id)

    def test_model_permissions_come_from_the_packs(self):
        self.assertTrue(self.procurement.model_permission_ids)
        self.assertIn('purchase.order',
                      self.procurement.model_permission_ids.mapped('model_name'))

    def test_action_permissions_exist_for_the_draft_scenario(self):
        codes = self.procurement.action_permission_ids.mapped('action_code')
        self.assertIn('CREATE_DRAFT', codes)

    def test_only_the_scenario_tools_are_assigned(self):
        for code, pairs in ASSIGNMENTS.items():
            profile = self.Profile.search([('code', '=', code)], limit=1)
            enabled = set(profile.tool_assignment_ids.filtered('enabled')
                          .tool_id.mapped('code'))
            self.assertEqual(enabled, {tool for tool, _ in pairs},
                             "%s grants tools beyond its scenarios" % code)

    def test_assigned_tools_are_enabled_and_capped(self):
        for assignment in self.procurement.tool_assignment_ids.filtered('enabled'):
            self.assertTrue(assignment.tool_id.enabled)
            self.assertGreater(assignment.max_calls_per_run, 0)

    def test_the_handoff_type_is_the_one_the_pack_ships(self):
        handoff_type = self.env['ai.operations.handoff.type'].search(
            [('code', '=', 'MATERIAL_SHORTAGE')], limit=1)
        self.assertTrue(handoff_type)
        self.assertEqual(handoff_type.to_profile_id, self.procurement)
        self.assertIn(self.manufacturing, handoff_type.from_profile_ids)

    def test_the_channels_are_bound_to_their_profiles(self):
        self.assertEqual(self._channel('Procurement (Noura)').ai_profile_id,
                         self.procurement)
        self.assertEqual(self._channel('Manufacturing (Khalid)').ai_profile_id,
                         self.manufacturing)

    def test_the_test_employees_can_reach_the_platform(self):
        for login in ('noura.p', 'fahad.p', 'khalid.m'):
            self.assertTrue(
                self._user(login)._has_group('ai_operations.group_ai_user'),
                "%s cannot reach AI Operations" % login)

    def test_the_crons_exist_and_stay_disabled(self):
        for xmlid in ('ai_operations_procurement.cron_ai_procurement',
                      'ai_operations_manufacturing.cron_ai_manufacturing'):
            cron = self.env.ref(xmlid)
            self.assertEqual(cron.model_id.model, 'ai.operations.execution')
            self.assertFalse(cron.active, "%s would call the vendor daily" % xmlid)

    def test_the_module_contains_no_credential(self):
        """A demo module is exactly where a key gets pasted 'just for testing'."""
        import pathlib
        import re
        root = pathlib.Path(__file__).resolve().parents[1]
        # Assembled at runtime so this file does not match its own pattern.
        secret_prefix = 'sk' + '-ant-'
        pattern = re.compile(secret_prefix + r"|api[_-]?key\s*=\s*['\"][^'\"]{12,}"
                             r"|ODOO_AI_ANTHROPIC" + r"_TOKEN\s*=")
        for path in root.rglob('*'):
            if path.suffix in ('.py', '.xml', '.md', '.csv') and path.is_file():
                self.assertIsNone(pattern.search(path.read_text()),
                                  "possible credential in %s" % path.name)

    def test_running_the_setup_twice_changes_nothing(self):
        """Install, upgrade and re-run must converge."""
        Channel = self.env['discuss.channel']
        before = (self.Profile.search_count([]),
                  self.env['ai.operations.tool.assignment'].search_count([]),
                  Channel.search_count([('ai_profile_id', '!=', False)]),
                  self.env['res.partner'].search_count(
                      [('name', 'like', 'AI / Procurement Intelligence')]))

        self.env['ai.operations.demo.setup'].build_all()

        after = (self.Profile.search_count([]),
                 self.env['ai.operations.tool.assignment'].search_count([]),
                 Channel.search_count([('ai_profile_id', '!=', False)]),
                 self.env['res.partner'].search_count(
                     [('name', 'like', 'AI / Procurement Intelligence')]))
        self.assertEqual(before, after, "the setup duplicated records")


@tagged('post_install', '-at_install', 'ai_security')
class TestDemoScenarios(TestDemoConfiguration):
    """The four prepared scenarios, on the real runtime, with a scripted vendor."""

    def _post(self, channel, login, body):
        return channel.with_user(self._user(login)).message_post(
            body=Markup('<p>%s</p>' % body), message_type='comment',
            subtype_xmlid='mail.mt_comment')

    # -- Test 1: a successful read ---------------------------------------

    def test_scenario_1_a_read_question_reaches_the_runtime_and_answers(self):
        channel = self._channel('Procurement (Noura)')
        with scripted(self.env, _tool_call('procurement.get_open_pos', {}),
                      _text('You have one open order with Jeddah Plastic '
                            'Industries for Naqaa.')):
            self._post(channel, 'noura.p', 'List my open purchase orders.')

        replies = channel.message_ids.filtered(
            lambda m: m.author_id == self.procurement.partner_id)
        self.assertTrue(replies, "the agent never answered")
        self.assertIn('Naqaa', replies[0].body)

        allowed = self.Log.search([('tool_code', '=', 'procurement.get_open_pos'),
                                   ('decision', '=', 'ALLOWED')])
        self.assertTrue(allowed, "no ALLOWED audit row for the read")
        # trigger is stamped on the OPEN row: the call is reconstructed by
        # correlation_id, because the log is append-only (finding B3).
        opened = self.Log.search([
            ('correlation_id', '=', allowed[0].correlation_id),
            ('event_type', '=', 'OPEN')], limit=1)
        self.assertEqual(opened.trigger, 'CHAT',
                         "the run did not come from the chat surface")

    # -- Test 4: a denial -------------------------------------------------

    def test_scenario_4_a_read_only_user_is_denied_the_draft(self):
        """EFFECTIVE = USER ∩ AGENT. Fahad is READ ONLY on purchase, so the
        same request Noura may make is refused for him -- by Naqaa's own seeded
        least privilege, not by a weakened profile."""
        channel = self._channel('Fahad')
        self.assertTrue(channel, "the read-only tester has no channel")
        orders_before = self.env['purchase.order'].with_context(
            active_test=False).search_count([])

        with scripted(self.env, _tool_call('procurement.prepare_draft_rfq', {
                          'product_id': 1, 'partner_id': 1,
                          'deterministic_shortage': 100.0,
                          'recommended_quantity': 100.0,
                          'idempotency_key': 'demo-denial-probe'}),
                      _text('I cannot help with that.')):
            self._post(channel, 'fahad.p', 'Please prepare a draft RFQ.')

        denied = self.Log.search([('decision', '=', 'DENIED')])
        self.assertTrue(denied, "no DENIED audit row was written")
        # Pin the reason: a denial for a malformed payload would make this test
        # pass while proving nothing about least privilege.
        self.assertNotEqual(denied[0].denial_reason, 'SCHEMA_INVALID',
                            "denied for a bad payload, not for a lack of rights")
        self.assertEqual(
            self.env['purchase.order'].with_context(active_test=False)
            .search_count([]), orders_before,
            "a business record was created despite the denial")

    def test_scenario_4_the_denial_never_reaches_the_user_as_detail(self):
        channel = self._channel('Fahad')
        with scripted(self.env, _tool_call('procurement.prepare_draft_rfq', {
                          'product_id': 1, 'partner_id': 1,
                          'deterministic_shortage': 100.0,
                          'recommended_quantity': 100.0,
                          'idempotency_key': 'demo-denial-probe-2'}),
                      _text('I cannot help with that.')):
            self._post(channel, 'fahad.p', 'Please prepare a draft RFQ.')

        posted = ' '.join(channel.message_ids.mapped('body'))
        for leak in ('purchase.order', 'AccessError', 'USER_ACL_DENIED',
                     'anthropic', 'ir.model.access'):
            self.assertNotIn(leak, posted, "%r leaked into the conversation" % leak)

    # -- Test 2: a prepared draft ----------------------------------------

    def _seeded(self, model):
        from ..models.demo_setup import SEED_ORIGIN
        return self.env[model].search([('origin', '=', SEED_ORIGIN)], limit=1)

    def test_scenario_2_the_agent_prepares_a_draft_and_never_confirms_it(self):
        from ..models.demo_setup import SEED_COMPONENT, SEED_VENDOR
        channel = self._channel('Procurement (Noura)')
        product = self.env['product.product'].search(
            [('default_code', '=', SEED_COMPONENT)], limit=1)
        vendor = self.env['res.partner'].search([('name', '=', SEED_VENDOR)], limit=1)
        Purchase = self.env['purchase.order']
        before = Purchase.search([])

        with scripted(self.env, _tool_call('procurement.prepare_draft_rfq', {
                          'product_id': product.id, 'partner_id': vendor.id,
                          'deterministic_shortage': 100000.0,
                          'recommended_quantity': 100000.0,
                          'idempotency_key': 'demo-scenario-2'}),
                      _text('I have prepared a draft for your review.')):
            self._post(channel, 'noura.p', 'Prepare a draft RFQ for the shortage.')

        created = Purchase.search([]) - before
        self.assertEqual(len(created), 1, "the agent did not prepare exactly one draft")
        self.assertEqual(created.state, 'draft',
                         "the agent confirmed a business transaction")
        self.assertEqual(created.ai_idempotency_key, 'demo-scenario-2')

    def test_scenario_2_running_twice_prepares_one_draft(self):
        from ..models.demo_setup import SEED_COMPONENT, SEED_VENDOR
        channel = self._channel('Procurement (Noura)')
        product = self.env['product.product'].search(
            [('default_code', '=', SEED_COMPONENT)], limit=1)
        vendor = self.env['res.partner'].search([('name', '=', SEED_VENDOR)], limit=1)
        Purchase = self.env['purchase.order']
        before = Purchase.search([])
        call = _tool_call('procurement.prepare_draft_rfq', {
            'product_id': product.id, 'partner_id': vendor.id,
            'deterministic_shortage': 100000.0,
            'recommended_quantity': 100000.0,
            'idempotency_key': 'demo-scenario-2-twice'})

        for _attempt in range(2):
            with scripted(self.env, call, _text('Draft ready.')):
                self._post(channel, 'noura.p', 'Prepare a draft RFQ.')

        self.assertEqual(len(Purchase.search([]) - before), 1,
                         "the idempotency key did not hold")

    # -- Test 3: a handoff -------------------------------------------------

    def test_scenario_3_the_agent_raises_a_real_handoff(self):
        channel = self._channel('Manufacturing (Khalid)')
        production = self._seeded('mrp.production')
        self.assertTrue(production, "the demo manufacturing order is missing")
        component = self.env['product.product'].search(
            [('default_code', '=', 'PK-BTL-330')], limit=1)
        warehouse = self.env['stock.warehouse'].search(
            [('company_id', '=', production.company_id.id)], limit=1)
        Handoff = self.env['ai.operations.handoff']
        before = Handoff.search([])

        with scripted(self.env, _tool_call('manufacturing.raise_handoff', {
                          'production_id': production.id,
                          'product_id': component.id,
                          'qty_required': 120000.0,
                          'qty_available': 20000.0,
                          'qty_shortage': 100000.0,
                          'warehouse_id': warehouse.id}),
                      _text('I have raised the shortage with Procurement.')):
            self._post(channel, 'khalid.m', 'We are short of 330 ml bottles.')

        created = Handoff.search([]) - before
        self.assertEqual(len(created), 1, "no handoff was raised")
        self.assertEqual(created.type_id.code, 'MATERIAL_SHORTAGE')
        self.assertEqual(created.from_profile_id, self.manufacturing)
        self.assertEqual(created.to_profile_id, self.procurement)
        self.assertTrue(created.idempotency_key)
