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
            # The set the runtime actually OFFERS the model: an assignment
            # counts only when its tool record is enabled too. The packs wire an
            # assignment per registered tool in _register_hook, so the
            # assignment list alone is not the grant -- build_tool_definitions()
            # requires both, and so does this assertion.
            offered = set(profile.tool_assignment_ids.filtered('enabled')
                          .tool_id.filtered('enabled').mapped('code'))
            self.assertEqual(offered, {tool for tool, _ in pairs},
                             "%s offers tools beyond its scenarios" % code)

    def test_assigned_tools_are_capped(self):
        offered = self.procurement.tool_assignment_ids.filtered(
            lambda a: a.enabled and a.tool_id.enabled)
        self.assertTrue(offered)
        for assignment in offered:
            self.assertGreater(assignment.max_calls_per_run, 0,
                               "%s has no per-run cap" % assignment.tool_id.code)

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
                          'recommended_quantity': 100.0,}),
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
                          'recommended_quantity': 100.0,}),
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
                          'recommended_quantity': 100000.0,}),
                      _text('I have prepared a draft for your review.')):
            self._post(channel, 'noura.p', 'Prepare a draft RFQ for the shortage.')

        created = Purchase.search([]) - before
        self.assertEqual(len(created), 1, "the agent did not prepare exactly one draft")
        self.assertEqual(created.state, 'draft',
                         "the agent confirmed a business transaction")
        self.assertTrue(created.ai_idempotency_key.startswith('procurement:'),
                        "the order does not carry the derived namespaced key")

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
            'recommended_quantity': 100000.0,})

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


@tagged('post_install', '-at_install', 'ai_security')
class TestNouraProcurementPath(TestDemoConfiguration):
    """Manual Test 2, as the guard actually sees it, with no vendor involved.

    Every call goes through ``execute_tool`` as Noura, so the full intersection
    USER n AGENT n TOOL n ACTION n COMPANY is enforced exactly as it is in the
    chat. Nothing here grants a permission or uses sudo().
    """

    def setUp(self):
        super().setUp()
        self.noura = self._user('noura.p')
        self.runner = self.env['ai.operations.execution'].with_user(self.noura)

    def _call(self, code, params):
        return self.runner.execute_tool(
            self.procurement, code, params, 'INTERACTIVE', 'CHAT', 'test-2')

    def _post(self, channel, login, body):
        return channel.with_user(self._user(login)).message_post(
            body=Markup('<p>%s</p>' % body), message_type='comment',
            subtype_xmlid='mail.mt_comment')

    def _product_id(self):
        return self.env['product.product'].search(
            [('default_code', '=', 'PK-BTL-330')], limit=1).id

    def test_the_agent_can_resolve_a_product_code_to_an_id(self):
        """The defect behind Manual Test 2: every procurement tool takes
        ``product_id``, no tool resolved a code to one, so the model guessed
        330 from 'PK-BTL-330' and the guard denied a record that does not
        exist -- reported as USER_ACL_DENIED, which reads like a rights
        problem and is not one."""
        found = self._call('procurement.find_product', {'product_ref': 'PK-BTL-330'})
        codes = [p['code'] for p in found['products']]
        self.assertIn('PK-BTL-330', codes)
        match = next(p for p in found['products'] if p['code'] == 'PK-BTL-330')
        self.assertEqual(match['id'], self._product_id())

    def test_shortage_context_succeeds_for_noura(self):
        result = self._call('procurement.get_shortage_context',
                            {'product_id': self._product_id()})
        self.assertEqual(result['product_id'], self._product_id())
        self.assertIn('PK-BTL-330', result['product_name'])

    def test_compare_suppliers_returns_the_seeded_vendors_for_noura(self):
        """The second defect: Naqaa's supplier pricing was created without a
        company, so it landed on the installing user's company and no Naqaa
        user could see any of it -- compare_suppliers returned an empty list
        for every product."""
        result = self._call('procurement.compare_suppliers',
                            {'product_id': self._product_id()})
        vendors = [o['vendor'] for o in result['offers']]
        self.assertTrue(vendors, "no vendor offers are visible to Noura")
        self.assertIn('Jeddah Plastic Industries', vendors)

    def test_prepare_draft_rfq_creates_a_draft_and_never_confirms_it(self):
        product_id = self._product_id()
        offers = self._call('procurement.compare_suppliers',
                            {'product_id': product_id})['offers']
        partner_id = next(o['partner_id'] for o in offers
                          if o['vendor'] == 'Jeddah Plastic Industries')
        Purchase = self.env['purchase.order']
        before = Purchase.search([])

        self._call('procurement.prepare_draft_rfq', {
            'product_id': product_id, 'partner_id': partner_id,
            'deterministic_shortage': 100000.0,
            'recommended_quantity': 100000.0,})

        created = Purchase.search([]) - before
        self.assertEqual(len(created), 1)
        self.assertEqual(created.state, 'draft',
                         "the agent confirmed a business transaction")

    def test_the_draft_rfq_carries_the_vendor_price(self):
        """P00004 was created at 0.00 while the agent had just quoted 0.0550.

        The tool wrote ``product.standard_price`` -- our AVCO cost, which is
        company-dependent and was 0.0 under Naqaa -- instead of letting Odoo
        price the line from the vendor. Two sources of truth for one number,
        and the wrong one of the two.
        """
        product_id = self._product_id()
        offers = self._call('procurement.compare_suppliers',
                            {'product_id': product_id})['offers']
        jeddah = next(o for o in offers
                      if o['vendor'] == 'Jeddah Plastic Industries')
        Purchase = self.env['purchase.order']
        before = Purchase.search([])

        result = self._call('procurement.prepare_draft_rfq', {
            'product_id': product_id, 'partner_id': jeddah['partner_id'],
            'deterministic_shortage': 0.0,
            'recommended_quantity': 100000.0,})

        order = Purchase.search([]) - before
        line = order.order_line
        self.assertEqual(order.state, 'draft')
        self.assertAlmostEqual(line.price_unit, jeddah['price'], places=4,
                               msg="the RFQ was not priced from the vendor")
        self.assertAlmostEqual(line.price_subtotal, 100000.0 * jeddah['price'],
                               places=2, msg="the subtotal does not follow price x quantity")
        self.assertAlmostEqual(result['lines'][0]['price_unit'], line.price_unit,
                               places=4,
                               msg="what the tool reported and what Odoo stored disagree")

    def test_the_naqaa_cost_is_set_on_the_operating_company(self):
        """``standard_price`` is company-dependent and was written while the
        builder ran as the installing user, so every Naqaa read returned 0.0 --
        the same defect the supplier pricing had."""
        from ..models.demo_setup import COMPANY, SEED_COMPONENT
        company = self.env['res.company'].search([('name', '=', COMPANY)], limit=1)
        product = self.env['product.product'].search(
            [('default_code', '=', SEED_COMPONENT)], limit=1)
        self.assertGreater(product.with_company(company).standard_price, 0.0,
                           "Naqaa sees no cost for its own component")

    def test_repeating_the_request_does_not_duplicate_the_rfq(self):
        product_id = self._product_id()
        offers = self._call('procurement.compare_suppliers',
                            {'product_id': product_id})['offers']
        partner_id = offers[0]['partner_id']
        Purchase = self.env['purchase.order']
        before = Purchase.search([])
        params = {'product_id': product_id, 'partner_id': partner_id,
                  'deterministic_shortage': 100000.0,
                  'recommended_quantity': 100000.0,}

        self._call('procurement.prepare_draft_rfq', dict(params))
        self._call('procurement.prepare_draft_rfq', dict(params))

        self.assertEqual(len(Purchase.search([]) - before), 1,
                         "the idempotency key did not hold")

    def test_a_confirmation_turn_still_knows_what_it_confirms(self):
        """Manual Test 2, exactly as it failed: turn 1 establishes the product,
        the vendor and the quantity and asks the user to choose; turn 2 is only
        "(b) Go ahead". The agent must not ask which product it is."""
        channel = self._channel('Procurement (Noura)')
        seen = []

        def recorder(self, messages, system=None, tools=None, model=None,
                     max_tokens=4096, timeout=120):
            seen.append([dict(m) for m in messages])
            return _text('Understood.')

        provider = self.env['ai.operations.provider.anthropic']
        with patch.object(type(provider), 'complete', recorder):
            self._post(channel, 'noura.p',
                       'We are short 100000 units of PK-BTL-330. '
                       'Prepare a draft RFQ with Jeddah Plastic Industries.')
            self._post(channel, 'noura.p',
                       '(b) Go ahead and create a new 100,000-unit draft RFQ '
                       'with Jeddah Plastic Industries anyway.')

        self.assertEqual(len(seen), 2, "the follow-up never reached the runtime")
        replayed = ' '.join(m['content'] for m in seen[1]
                            if isinstance(m.get('content'), str))
        self.assertIn('PK-BTL-330', replayed,
                      "turn 2 did not carry the product from turn 1")
        self.assertIn('Jeddah Plastic Industries', replayed,
                      "turn 2 did not carry the vendor from turn 1")
        self.assertIn('100000', replayed.replace(',', ''),
                      "turn 2 did not carry the quantity from turn 1")

    def test_replayed_history_never_contains_a_tool_call(self):
        """History is prose. A replayed tool_use would be a call in the model's
        context that never passed the guard."""
        channel = self._channel('Procurement (Noura)')
        seen = []

        def recorder(self, messages, system=None, tools=None, model=None,
                     max_tokens=4096, timeout=120):
            seen.append([dict(m) for m in messages])
            return _text('ok')

        provider = self.env['ai.operations.provider.anthropic']
        with patch.object(type(provider), 'complete', recorder):
            self._post(channel, 'noura.p', 'first')
            self._post(channel, 'noura.p', 'second')

        for message in seen[1][:-1]:
            self.assertIn(message['role'], ('user', 'assistant'))
            self.assertNotIn('tool_calls', message)
            self.assertNotIn('tool_use_id', message)

    def test_the_whole_test_2_workflow_fits_in_one_run(self):
        """Manual Test 2 died on "tool call 5 exceeds the run cap of 2".

        The profile allows 8 calls and the workflow needs 5. It failed because
        prepare_draft_rfq's own assignment cap of 2 was being folded into the
        run's cap, so the fifth call was measured against the wrong number.
        """
        from odoo.addons.ai_operations.services.context import RunBudget
        budget = RunBudget(max_tool_calls=self.procurement.max_tool_calls,
                           max_write_ops=self.procurement.max_write_ops)

        def call(code, params):
            return self.runner.execute_tool(
                self.procurement, code, params, 'INTERACTIVE', 'CHAT',
                'test-2-run', budget=budget)

        found = call('procurement.find_product', {'product_ref': 'PK-BTL-330'})
        pid = next(p['id'] for p in found['products']
                   if p['code'] == 'PK-BTL-330')
        shortage = call('procurement.get_shortage_context', {'product_id': pid})
        offers = call('procurement.compare_suppliers', {'product_id': pid})['offers']
        call('procurement.get_open_pos', {'product_id': pid})
        partner_id = next(o['partner_id'] for o in offers
                          if o['vendor'] == 'Jeddah Plastic Industries')

        Purchase = self.env['purchase.order']
        before = Purchase.search([])
        call('procurement.prepare_draft_rfq', {          # the fifth call
            'product_id': pid, 'partner_id': partner_id,
            'deterministic_shortage': shortage['shortage'],
            'recommended_quantity': 100000.0,})

        self.assertEqual(budget.tool_calls, 5)
        created = Purchase.search([]) - before
        self.assertEqual(len(created), 1, "the workflow produced no draft")
        self.assertEqual(created.state, 'draft')


@tagged('post_install', '-at_install', 'ai_security')
class TestKhalidManufacturingPath(TestDemoConfiguration):
    """Manual Test 3, from business references only.

    Khalid says "MO for FG-330 is short 100000 units of PK-BTL-330". He must
    never be asked for a production_id, a product_id or a warehouse_id: those
    are database facts, and an agent that cannot reach them from a business
    reference cannot do the job.
    """

    def setUp(self):
        super().setUp()
        self.khalid = self._user('khalid.m')
        self.runner = self.env['ai.operations.execution'].with_user(self.khalid)

    def _call(self, code, params):
        return self.runner.execute_tool(
            self.manufacturing, code, params, 'INTERACTIVE', 'CHAT', 'test-3')

    def _post(self, channel, login, body):
        return channel.with_user(self._user(login)).message_post(
            body=Markup('<p>%s</p>' % body), message_type='comment',
            subtype_xmlid='mail.mt_comment')

    def test_the_manufacturing_agent_is_granted_a_way_to_find_its_orders(self):
        offered = set(self.manufacturing.tool_assignment_ids.filtered('enabled')
                      .tool_id.filtered('enabled').mapped('code'))
        self.assertIn('manufacturing.get_open_mos', offered,
                      "the agent cannot find a manufacturing order at all")

    def test_an_mo_resolves_from_its_finished_product(self):
        orders = self._call('manufacturing.get_open_mos', {})['orders']
        match = [o for o in orders if 'FG-330' in o['product_name']]
        self.assertTrue(match, "the FG-330 order is not reachable")
        self.assertTrue(match[0]['reference'])

    def test_readiness_names_the_short_component_and_its_numbers(self):
        production_id = self._resolve_production()
        readiness = self._call('manufacturing.check_readiness',
                               {'production_id': production_id})
        bottles = [c for c in readiness['components']
                   if 'PK-BTL-330' in c['product_name']]
        self.assertTrue(bottles, "the component is not visible on the order")
        self.assertIn('required', bottles[0])
        self.assertIn('shortage', bottles[0])

    def _resolve_production(self):
        orders = self._call('manufacturing.get_open_mos', {})['orders']
        return next(o['id'] for o in orders if 'FG-330' in o['product_name'])

    def _raise(self, key_suffix=''):
        production_id = self._resolve_production()
        readiness = self._call('manufacturing.check_readiness',
                               {'production_id': production_id})
        component = next(c for c in readiness['components']
                         if 'PK-BTL-330' in c['product_name'])
        return self._call('manufacturing.raise_handoff', {
            'production_id': production_id,
            'product_id': component['product_id'],
            'qty_required': component['required'],
            'qty_available': component['available'],
            'qty_shortage': component['shortage'] or 100000.0,
        })

    def test_a_handoff_is_raised_without_anyone_supplying_a_warehouse_id(self):
        """The only field the agent could not reach from a business reference.
        The order knows its own warehouse; the model should not have to."""
        Handoff = self.env['ai.operations.handoff']
        before = Handoff.search([])
        self._raise()
        created = Handoff.search([]) - before
        self.assertEqual(len(created), 1, "no handoff was raised")
        self.assertEqual(created.type_id.code, 'MATERIAL_SHORTAGE')
        self.assertEqual(created.from_profile_id, self.manufacturing)
        self.assertEqual(created.to_profile_id, self.procurement)

    def test_the_same_shortage_raised_twice_is_one_handoff(self):
        Handoff = self.env['ai.operations.handoff']
        before = Handoff.search([])
        self._raise()
        self._raise()
        self.assertEqual(len(Handoff.search([]) - before), 1,
                         "the handoff idempotency key did not hold")

    def test_raising_a_shortage_creates_no_purchase_order(self):
        Purchase = self.env['purchase.order']
        before = Purchase.search_count([])
        self._raise()
        self.assertEqual(Purchase.search_count([]), before,
                         "a handoff bought something by itself")

    def test_the_pack_ships_its_own_handoff_permission(self):
        """Previously the demo module compensated for this. The pack must carry
        it, or the handoff feature is unreachable in production."""
        permission = self.env['ai.operations.model.permission'].search([
            ('profile_id', '=', self.manufacturing.id),
            ('model_name', '=', 'ai.operations.handoff')], limit=1)
        self.assertTrue(permission, "the manufacturing pack still cannot hand off")
        data = self.env['ir.model.data'].search([
            ('model', '=', 'ai.operations.model.permission'),
            ('res_id', '=', permission.id)], limit=1)
        self.assertEqual(data.module, 'ai_operations_manufacturing',
                         "the permission still comes from the demo module")

    def test_scenario_4_the_read_only_users_message_survives_the_refusal(self):
        """Manual Test 4. Fahad's message vanished from Discuss with a warning
        triangle: the ORM refused purchase.order.create, the raw AccessError
        escaped the run and unwound message_post, so the post rolled back and
        took the audit row with it.

        The message must survive, the refusal must be neutral, and the denial
        must be on the record.
        """
        channel = self._channel('Fahad')
        product = self.env['product.product'].search(
            [('default_code', '=', 'PK-BTL-330')], limit=1)
        vendor = self.env['res.partner'].search(
            [('name', '=', 'Jeddah Plastic Industries')], limit=1)
        Purchase = self.env['purchase.order']
        Log = self.env['ai.operations.audit.log']
        orders_before = Purchase.search_count([])
        messages_before = len(channel.message_ids)

        with scripted(self.env,
                      _tool_call('procurement.prepare_draft_rfq', {
                          'product_id': product.id, 'partner_id': vendor.id,
                          'deterministic_shortage': 0.0,
                          'recommended_quantity': 100000.0,}),
                      _text('I am not able to do that.')):
            self._post(channel, 'fahad.p',
                       'We are short 100000 units of PK-BTL-330. '
                       'Prepare a draft RFQ with Jeddah Plastic Industries.')

        self.assertGreater(len(channel.message_ids), messages_before,
                           "the user's own message did not survive the refusal")
        self.assertEqual(Purchase.search_count([]), orders_before,
                         "a purchase order was created for a read-only user")
        denied = Log.search([('decision', '=', 'DENIED'),
                             ('tool_code', '=', 'procurement.prepare_draft_rfq')])
        self.assertTrue(denied, "the refusal was never recorded")
        self.assertEqual(denied[0].denial_reason, 'USER_ACL_DENIED')

    def test_scenario_4_the_refusal_names_nothing_to_the_user(self):
        channel = self._channel('Fahad')
        product = self.env['product.product'].search(
            [('default_code', '=', 'PK-BTL-330')], limit=1)
        vendor = self.env['res.partner'].search(
            [('name', '=', 'Jeddah Plastic Industries')], limit=1)

        with scripted(self.env,
                      _tool_call('procurement.prepare_draft_rfq', {
                          'product_id': product.id, 'partner_id': vendor.id,
                          'deterministic_shortage': 0.0,
                          'recommended_quantity': 100000.0,}),
                      _text('I am not able to do that.')):
            self._post(channel, 'fahad.p', 'Prepare a draft RFQ.')

        posted = ' '.join(channel.message_ids.mapped('body'))
        for leak in ('purchase.order', 'AccessError', 'USER_ACL_DENIED',
                     'not allowed to create'):
            self.assertNotIn(leak, posted, "%r leaked into the conversation" % leak)
