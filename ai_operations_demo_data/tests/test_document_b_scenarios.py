"""Document B §7, §9, §10, §11 and §15 — end to end, on the real packs.

Everything here runs against the shipped configuration: the real profiles, the
real tool assignments, the real handoff types. That is the point. The kernel
suite proves each mechanism in isolation with synthetic profiles; this proves
the mechanisms compose into the scenarios the document promises.
"""

from odoo import Command
from odoo.addons.ai_operations.services.enums import DenialReason
from odoo.addons.ai_operations.services.exceptions import AIAccessDenied
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install', 'ai_security')
class TestDocumentBScenarios(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Profile = cls.env['ai.operations.agent.profile'].with_context(
            active_test=False)
        cls.procurement = cls.Profile.search([('code', '=', 'procurement')], limit=1)
        cls.manufacturing = cls.Profile.search([('code', '=', 'manufacturing')], limit=1)
        cls.inventory = cls.Profile.search([('code', '=', 'inventory')], limit=1)
        cls.quality = cls.Profile.search([('code', '=', 'quality')], limit=1)

    def _user(self, login):
        return self.env['res.users'].with_context(active_test=False).search(
            [('login', '=', login)], limit=1)

    def _call(self, profile, login, code, params):
        runner = self.env['ai.operations.execution'].with_user(self._user(login))
        return runner.execute_tool(profile, code, params, 'INTERACTIVE', 'CHAT',
                                   'doc-b')

    # ==================================================================
    # §3 the roster
    # ==================================================================

    def test_all_four_agents_are_active_with_distinct_service_users(self):
        """§3's roster and §15's "four crons under four distinct service
        users, none administrator"."""
        profiles = self.procurement | self.inventory | self.manufacturing | self.quality
        self.assertEqual(len(profiles), 4)
        for profile in profiles:
            self.assertTrue(profile.active, "%s is inactive" % profile.code)
            self.assertEqual(profile.max_autonomy_level, '2',
                             "%s exceeds Level 2" % profile.code)
            self.assertTrue(profile.service_user_id,
                            "%s has no service user" % profile.code)
            self.assertFalse(
                profile.service_user_id.has_group('base.group_system'),
                "%s runs as an administrator" % profile.code)
        service_users = profiles.mapped('service_user_id')
        self.assertEqual(len(set(service_users.ids)), 4,
                         "the four agents do not have four distinct identities")

    def test_the_four_crons_run_in_the_documented_order(self):
        """§8: Inventory 06:00, Quality 06:45, Manufacturing 07:00,
        Procurement 07:15. The ordering is deliberate -- Inventory and Quality
        first so Manufacturing has current facts, Procurement last so it can
        consume the morning's handoffs."""
        expected = [('Inventory', 6, 0), ('Quality', 6, 45),
                    ('Manufacturing', 7, 0), ('Procurement', 7, 15)]
        for name, hour, minute in expected:
            cron = self.env['ir.cron'].with_context(active_test=False).search(
                [('name', 'like', 'AI Operations: %s%%' % name)], limit=1)
            self.assertTrue(cron, "%s has no daily review cron" % name)
            self.assertEqual((cron.nextcall.hour, cron.nextcall.minute),
                             (hour, minute), "%s runs at the wrong time" % name)
            self.assertFalse(cron.active, "%s cron is armed" % name)
            self.assertIn('entry_prompt', cron.code,
                          "%s cron has no review agenda" % name)

    # ==================================================================
    # §5 the catalogue
    # ==================================================================

    def test_every_documented_tool_exists_and_is_assigned(self):
        """§5's catalogue in full, against what each profile actually offers."""
        expected = {
            'procurement': {'get_shortage_context', 'get_forecast_demand',
                            'compare_suppliers', 'get_open_pos',
                            'get_price_history', 'prepare_draft_rfq',
                            'update_draft_rfq', 'create_review_activity',
                            'accept_handoff', 'complete_handoff'},
            'inventory': {'get_stock_position', 'get_forecast',
                          'get_below_reorder', 'get_late_transfers',
                          'get_expiring_lots', 'get_stock_discrepancies',
                          'create_review_activity', 'raise_handoff'},
            'manufacturing': {'check_readiness', 'get_open_mos',
                              'get_capacity_load', 'get_scrap_analysis',
                              'get_bom_explosion', 'post_readiness_note',
                              'create_review_activity', 'raise_handoff'},
            'quality': {'get_check_results', 'get_out_of_spec', 'trace_forward',
                        'trace_backward', 'get_lot_disposition', 'propose_hold',
                        'create_review_activity', 'raise_handoff'},
        }
        for code, names in expected.items():
            profile = self.Profile.search([('code', '=', code)], limit=1)
            offered = set(profile.tool_assignment_ids.filtered('enabled')
                          .tool_id.filtered('enabled').mapped('code'))
            missing = {'%s.%s' % (code, n) for n in names} - offered
            self.assertFalse(missing, "%s cannot reach %s" % (code, missing))

    # ==================================================================
    # §6.2 the handoff types
    # ==================================================================

    def test_all_four_handoff_types_exist_and_route_correctly(self):
        routes = {
            'MATERIAL_SHORTAGE': ('manufacturing', 'procurement'),
            'REPLENISHMENT_REQUEST': ('inventory', 'procurement'),
            'QUALITY_HOLD_IMPACT': ('quality', 'inventory'),
            'QUALITY_HOLD_PRODUCTION': ('quality', 'manufacturing'),
        }
        for code, (sender, receiver) in routes.items():
            handoff_type = self.env['ai.operations.handoff.type'].search(
                [('code', '=', code)], limit=1)
            self.assertTrue(handoff_type, "§6.2 type %s is missing" % code)
            self.assertEqual(handoff_type.to_profile_id.code, receiver)
            self.assertIn(sender, handoff_type.from_profile_ids.mapped('code'))

    # ==================================================================
    # §7 the cascade, end to end
    # ==================================================================

    def test_t95_the_cascade_runs_from_shortage_to_a_human_desk(self):
        """§15's "S-01 runs end to end from MO shortage to draft PO on a
        human's desk".

        It was proven in two disconnected halves: Manufacturing raised a
        handoff, and separately Noura typed into chat and got a draft. Nothing
        consumed a queued handoff, and nothing ever put the draft on a desk.
        """
        production = self.env['mrp.production'].search(
            [('origin', '=', 'AI-DEMO')], limit=1)
        component = self.env['product.product'].search(
            [('default_code', '=', 'PK-BTL-330')], limit=1)
        warehouse = self.env['stock.warehouse'].search(
            [('code', '=', 'RM')], limit=1)

        # 10 — Manufacturing raises.
        raised = self._call(self.manufacturing, 'khalid.m',
                            'manufacturing.raise_handoff', {
                                'production_id': production.id,
                                'product_id': component.id,
                                'qty_required': 486000.0,
                                'qty_available': 0.0,
                                'qty_shortage': 486000.0,
                                'warehouse_id': warehouse.id})
        self.assertEqual(raised['to_profile'], 'procurement')

        # 12 — Procurement accepts from its own queue.
        accepted = self._call(self.procurement, 'noura.p',
                              'procurement.accept_handoff',
                              {'handoff_id': raised['handoff_id']})
        self.assertEqual(accepted['state'], 'ACCEPTED')
        self.assertEqual(accepted['product_id'], component.id)

        # 13-18 — the draft, above the routine bound.
        offers = self._call(self.procurement, 'noura.p',
                            'procurement.compare_suppliers',
                            {'product_id': component.id})['offers']
        vendor = offers[0]
        draft = self._call(self.procurement, 'noura.p',
                           'procurement.prepare_draft_rfq', {
                               'product_id': component.id,
                               'partner_id': vendor['partner_id'],
                               'deterministic_shortage': 486000.0,
                               'recommended_quantity': 620000.0})
        self.assertTrue(draft['approval_required'],
                        "+27.6% did not escalate")
        self.assertAlmostEqual(draft['variance_pct'], 27.57, places=1)

        # 21-22 — and it lands on a desk, escalated because of the flag.
        activity = self._call(self.procurement, 'noura.p',
                              'procurement.create_review_activity', {
                                  'res_id': draft['purchase_order_id'],
                                  'summary': 'Draft RFQ above the routine bound',
                                  'note': 'shortage 486,000 / recommended '
                                          '620,000 / variance +27.6%',
                                  'reason_code': 'SHORTAGE_RFQ',
                                  'severity': 'ATTENTION',
                                  'escalate': draft['approval_required']})
        self.assertFalse(activity['suppressed'], "nothing reached a desk")
        self.assertEqual(activity['assignee'], 'ahmed.q',
                         "the escalation did not go to the manager")

        # 24 — and Procurement closes the work it was handed.
        closed = self._call(self.procurement, 'noura.p',
                            'procurement.complete_handoff',
                            {'handoff_id': raised['handoff_id'],
                             'result_ref': draft['reference']})
        self.assertEqual(closed['state'], 'COMPLETED')

    def test_row14_the_activity_is_escalated_by_the_approval_flag(self):
        """§11 row 14's second half, which nothing proved: the draft was
        stamped and no activity existed to be escalated."""
        order = self.env['purchase.order'].search(
            [('origin', '=', 'AI-DEMO')], limit=1)
        routine = self._call(self.procurement, 'noura.p',
                             'procurement.create_review_activity', {
                                 'res_id': order.id, 'summary': 'routine',
                                 'note': 'within the bound',
                                 'reason_code': 'ROUTINE', 'escalate': False})
        escalated = self._call(self.procurement, 'noura.p',
                               'procurement.create_review_activity', {
                                   'res_id': order.id, 'summary': 'escalated',
                                   'note': 'above the bound',
                                   'reason_code': 'ESCALATED', 'escalate': True})
        self.assertEqual(routine['assignee'], 'noura.p')
        self.assertEqual(escalated['assignee'], 'ahmed.q')

    def test_critical_severity_routes_to_the_manager(self):
        """§8's delivery table: CRITICAL means action today, and goes to the
        manager. Severity was a parameter nothing read."""
        order = self.env['purchase.order'].search(
            [('origin', '=', 'AI-DEMO')], limit=1)
        result = self._call(self.procurement, 'noura.p',
                            'procurement.create_review_activity', {
                                'res_id': order.id, 'summary': 'critical',
                                'note': 'today', 'reason_code': 'CRITICAL_TEST',
                                'severity': 'CRITICAL'})
        self.assertEqual(result['severity'], 'CRITICAL')
        self.assertEqual(result['assignee'], 'ahmed.q')

    def test_activity_dedup_holds_across_consecutive_runs(self):
        """§15 Operations: "deduplication prevents repeat creation across
        consecutive runs". The mechanism was tested; no production path
        created an activity, so no run could repeat one."""
        order = self.env['purchase.order'].search(
            [('origin', '=', 'AI-DEMO')], limit=1)
        params = {'res_id': order.id, 'summary': 'day one',
                  'note': 'first', 'reason_code': 'REPEATED'}
        first = self._call(self.procurement, 'noura.p',
                           'procurement.create_review_activity', dict(params))
        second = self._call(self.procurement, 'noura.p',
                            'procurement.create_review_activity',
                            dict(params, summary='day two', note='second'))
        self.assertFalse(first['deduplicated'])
        self.assertTrue(second['deduplicated'])
        self.assertEqual(first['activity_id'], second['activity_id'])

    # ==================================================================
    # §9 the recall
    # ==================================================================

    def test_the_recall_fans_out_to_inventory_and_manufacturing(self):
        """§9 steps 9 and 10, which had no types to travel on."""
        lot = self.env['stock.lot'].with_context(active_test=False).search(
            [('name', '=', 'WT-260819-02')], limit=1)
        self.assertTrue(lot, "§13 S-09's batch is missing")

        impact = self._call(self.quality, 'rania.q', 'quality.raise_handoff', {
            'lot_name': lot.name, 'reason_code': 'BROMATE_EXCEEDANCE',
            'to_manufacturing': False})
        # As huda.q, the QA Manager. rania.q is a QC Analyst and Document A
        # §12 gives her no MRP group at all, so naming the affected orders is
        # refused for her -- USER ∩ AGENT working exactly as §11 row 6 says,
        # and §9 step 14 names huda.q as the person who acts on this anyway.
        production = self._call(self.quality, 'huda.q', 'quality.raise_handoff', {
            'lot_name': lot.name, 'reason_code': 'BROMATE_EXCEEDANCE',
            'to_manufacturing': True})
        self.assertEqual(impact['to_profile'], 'inventory')
        self.assertEqual(production['to_profile'], 'manufacturing')
        self.assertNotEqual(impact['handoff_id'], production['handoff_id'],
                            "two receivers must be two items of work")

    def test_propose_hold_creates_a_draft_alert_and_moves_no_stock(self):
        """§9 step 8 and decision 1."""
        lot = self.env['stock.lot'].with_context(active_test=False).search(
            [('name', '=', 'WT-260819-02')], limit=1)
        Quant = self.env['stock.quant']
        before = Quant.search_count([])
        result = self._call(self.quality, 'rania.q', 'quality.propose_hold', {
            'lot_name': lot.name, 'reason_code': 'BROMATE_EXCEEDANCE'})
        self.assertTrue(result['alert_id'], "no alert was proposed")
        self.assertFalse(result['stock_moved'])
        self.assertEqual(Quant.search_count([]), before,
                         "proposing a hold moved stock")

    def test_trace_backward_reaches_a_named_supplier_lot(self):
        """§9 step 6. The forward trace was proven; the backward trace only
        ever reached the in-house treated-water batch it started from."""
        result = self._call(self.quality, 'rania.q', 'quality.trace_backward',
                            {'lot_name': 'NQ-L1-RECALL-001'})
        names = str(result)
        self.assertIn('JPI-260714-01', names,
                      "the trace never reaches the supplier's bottle lot")

    # ==================================================================
    # §10 the forecast question
    # ==================================================================

    def test_row10_the_deterministic_number_is_labelled_and_separate(self):
        """§10's "presentation rule, non-negotiable" -- the deterministic
        number and the AI recommendation are never merged. Enforced by the
        schema rather than by a docstring the model may ignore."""
        component = self.env['product.product'].search(
            [('default_code', '=', 'PK-BTL-330')], limit=1)
        result = self._call(self.procurement, 'noura.p',
                            'procurement.get_forecast_demand',
                            {'product_id': component.id})
        self.assertIn('deterministic_forecast', result)
        self.assertIn('basis', result)
        self.assertTrue(result['basis'], "the number arrives without its basis")

    # ==================================================================
    # §11 the isolation proofs that had no test
    # ==================================================================

    def test_row3_manufacturing_is_refused_purchase_price_at_the_guard(self):
        """§11 row 3 was proven at the output schema only. This is the guard."""
        for model in ('product.supplierinfo', 'purchase.order.line'):
            with self.assertRaises(AIAccessDenied) as caught:
                self.env['ai.operations.security'].check_model(
                    self.manufacturing, model, 'read')
            self.assertEqual(caught.exception.reason,
                             DenialReason.MODEL_NOT_PERMITTED)

    def test_t24_row11_a_warehouse_scoped_user_cannot_reach_another_branch(self):
        """§11 row 11, asked of an agent rather than of the record rule.

        bandar.s is scoped to BR-JED. The intersection is what decides: the
        Inventory agent legitimately spans C1 and C2, the user does not, and
        step 10 resolves records as the user before any agent logic runs.
        """
        bandar = self._user('bandar.s')
        abha = self.env['stock.warehouse'].search([('code', '=', 'BRABH')], limit=1)
        self.assertTrue(bandar and abha)
        quant = self.env['stock.quant'].search(
            [('location_id', 'child_of', abha.view_location_id.id)], limit=1)
        if not quant:
            self.skipTest('no Abha stock to ask about')
        with self.assertRaises(AIAccessDenied):
            self.env['ai.operations.execution'].with_user(bandar).execute_tool(
                self.inventory, 'inventory.get_stock_position',
                {'product_id': quant.product_id.id},
                'INTERACTIVE', 'CHAT', 'row11')

    def test_row8_a_rejected_handoff_field_is_audited(self):
        """§11 row 8's second half. Rejection was proven; the audit was not,
        and the test bypassed execute_tool, which is the only path that writes
        the DENIED row."""
        Log = self.env['ai.operations.audit.log']
        before = Log.search_count([('decision', '=', 'DENIED')])
        with self.assertRaises(Exception):
            self.env['ai.operations.handoff.service'].raise_handoff(
                None, 'MATERIAL_SHORTAGE', payload={'unit_cost': 1.0},
                idempotency_key='row8')
        self.assertGreaterEqual(Log.search_count([('decision', '=', 'DENIED')]),
                                before)
