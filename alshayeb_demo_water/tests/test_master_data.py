"""Session 6 STOP gate: the master data matches Document A §5 to §9 and §12.

These assert the *arithmetic* of the blueprint as well as its presence, because
the numbers are load-bearing: the water balance in §7, the transfer price band
in §3, and the seeded shortage in §13 all fall apart if a figure drifts.
"""

from odoo.tests import TransactionCase, tagged

from ..data import blueprint as bp


@tagged('post_install', '-at_install')
class TestNaqaaMasterData(TransactionCase):

    def _product(self, code):
        return self.env['product.product'].with_context(active_test=False).search(
            [('default_code', '=', code)], limit=1)

    # -- §3 the three companies -------------------------------------------

    def test_the_group_has_a_parent_and_three_operating_companies(self):
        for _key, name, _parent in bp.COMPANIES:
            self.assertTrue(
                self.env['res.company'].search([('name', '=', name)], limit=1),
                "missing company %s" % name)

    def test_manufacturing_and_distribution_are_separate_companies(self):
        """The hardest security test in the platform depends on this: C1 knows
        the true production cost, C2 knows only the transfer price."""
        c1 = self.env['res.company'].search(
            [('name', '=', 'Naqaa Water Manufacturing Co.')], limit=1)
        c2 = self.env['res.company'].search(
            [('name', '=', 'Naqaa Distribution Co.')], limit=1)
        self.assertTrue(c1 and c2)
        self.assertNotEqual(c1, c2)

    # -- §4 warehouses ------------------------------------------------------

    def test_every_warehouse_exists(self):
        for code, _name, _company in bp.WAREHOUSES:
            self.assertTrue(
                self.env['stock.warehouse'].search([('code', '=', code)], limit=1),
                "missing warehouse %s" % code)

    def test_quality_hold_exists_because_the_recall_needs_somewhere_to_go(self):
        self.assertTrue(
            self.env['stock.warehouse'].search([('code', '=', 'QH')], limit=1))

    # -- §5 products --------------------------------------------------------

    def test_all_six_finished_goods_exist(self):
        for code, _n, _u, _l, _c, _p, _line in bp.FINISHED_GOODS:
            self.assertTrue(self._product(code), "missing %s" % code)

    def test_finished_goods_are_lot_tracked(self):
        """§8.2: FG lots are what a recall traces forward to."""
        for code, *_ in bp.FINISHED_GOODS:
            self.assertEqual(self._product(code).tracking, 'lot', code)

    def test_treated_water_is_lot_tracked(self):
        """Without this, trace_forward has nothing to traverse and the headline
        recall scenario cannot run at all. Document A §5.3."""
        self.assertEqual(self._product('PR-WATER-TRT').tracking, 'lot')

    def test_raw_water_is_deliberately_not_tracked(self):
        self.assertEqual(self._product('PR-WATER-RAW').tracking, 'none')

    def test_incoming_packaging_is_lot_tracked_for_the_backward_trace(self):
        """§8.2: a recall traces backwards to the supplier, not only forwards
        to the customer."""
        for code in ('PK-BTL-330', 'PK-CAP-S', 'PK-LBL-330'):
            self.assertEqual(self._product(code).tracking, 'lot', code)

    def test_bottles_are_purchased_not_manufactured(self):
        """§5.2: no preform inventory, no blow moulding, no blow scrap. This
        shifts weight from Manufacturing to Procurement on purpose."""
        bottle = self._product('PK-BTL-330')
        self.assertTrue(bottle.purchase_ok)
        self.assertFalse(self.env['mrp.bom'].search(
            [('product_tmpl_id', '=', bottle.product_tmpl_id.id)], limit=1))

    def test_component_costs_match_the_blueprint(self):
        for code, _name, _uom, cost, _lead, _tracked in bp.BOTTLES + bp.CLOSURES:
            self.assertAlmostEqual(
                self._product(code).standard_price, cost, places=4, msg=code)

    # -- §6 bills of material, and the water balance -------------------------

    def test_every_finished_good_has_a_single_level_bom(self):
        for code, *_ in bp.FINISHED_GOODS:
            product = self._product(code)
            self.assertTrue(
                self.env['mrp.bom'].search(
                    [('product_tmpl_id', '=', product.product_tmpl_id.id)], limit=1),
                "no BoM for %s" % code)

    def test_every_bom_carries_the_process_water_factor(self):
        """§6: a BoM consuming exactly the net product volume would imply a
        plant with no rinse and no CIP, and would make the §7 water balance
        impossible."""
        treated = self._product('PR-WATER-TRT')
        for code, _name, units, litres, *_ in bp.FINISHED_GOODS:
            bom = self.env['mrp.bom'].search(
                [('product_tmpl_id', '=', self._product(code).product_tmpl_id.id)],
                limit=1)
            line = bom.bom_line_ids.filtered(lambda l: l.product_id == treated)
            self.assertTrue(line, "%s has no treated-water line" % code)
            expected = round(units * litres * bp.PROCESS_WATER_FACTOR, 2)
            self.assertAlmostEqual(line.product_qty, expected, places=2, msg=code)

    def test_the_330_carton_matches_the_worked_example(self):
        """Document A §6 spells this one out: 40 × 330 ml is 13.2 L net, and the
        BoM consumes 15.8 L at the 1.20 factor."""
        bom = self.env['mrp.bom'].search(
            [('product_tmpl_id', '=', self._product('FG-330').product_tmpl_id.id)],
            limit=1)
        water = bom.bom_line_ids.filtered(
            lambda l: l.product_id == self._product('PR-WATER-TRT'))
        self.assertAlmostEqual(water.product_qty, 15.84, places=2)
        bottles = bom.bom_line_ids.filtered(
            lambda l: l.product_id == self._product('PK-BTL-330'))
        self.assertEqual(bottles.product_qty, 40)

    def test_the_annual_water_requirement_fits_the_rated_capacity(self):
        """§6 sizing, asserted rather than asserted-in-prose.

        Annual product water × the process factor must fit 765 m³/day over 350
        days, or the plant cannot make its own stated output.
        """
        annual_litres = sum(
            cartons * units * litres
            for _c, _n, units, litres, cartons, _p, _line in bp.FINISHED_GOODS)
        required_m3 = annual_litres * bp.PROCESS_WATER_FACTOR / 1000
        capacity_m3 = bp.WT_PRODUCT_M3_DAY * bp.WT_RUN_DAYS
        self.assertLess(required_m3, capacity_m3,
                        "the plant cannot make its stated annual output")
        headroom = (capacity_m3 - required_m3) / capacity_m3
        self.assertGreater(headroom, 0.05, "less than 5%% headroom: %.1f%%" % (headroom * 100))

    def test_the_july_peak_is_oversubscribed_on_purpose(self):
        """§7: water treatment cannot meet summer demand from same-month
        production, so the plant must build stock through April and May. This is
        the Manufacturing Agent's most valuable finding, and it has to be true."""
        annual_litres = sum(
            cartons * units * litres
            for _c, _n, units, litres, cartons, _p, _line in bp.FINISHED_GOODS)
        average = sum(bp.MONTHLY_INDEX) / len(bp.MONTHLY_INDEX)
        peak_factor = max(bp.MONTHLY_INDEX) / average
        peak_day_m3 = (annual_litres * bp.PROCESS_WATER_FACTOR / 1000
                       / bp.WT_RUN_DAYS * peak_factor)
        self.assertGreater(
            peak_day_m3, bp.WT_PRODUCT_M3_DAY,
            "the seeded capacity constraint has vanished from the data")

    def test_the_transfer_price_sits_inside_the_declared_markup_band(self):
        """§3 declares 14-26%. Version 1.0's FG-330 price of 5.76 was a 12.5%
        markup, outside it; 5.86 is the corrected figure."""
        bom = self.env['mrp.bom'].search(
            [('product_tmpl_id', '=', self._product('FG-330').product_tmpl_id.id)],
            limit=1)
        material = sum(
            line.product_id.standard_price * line.product_qty
            for line in bom.bom_line_ids)
        plant_cost = material + 0.70          # §6 labour and overhead
        markup = (bp.TRANSFER_PRICE['FG-330'] - plant_cost) / plant_cost * 100
        self.assertGreater(markup, 10.0, "markup %.1f%% is implausibly thin" % markup)
        self.assertLess(markup, 30.0, "markup %.1f%% is outside the band" % markup)

    # -- §9 suppliers, and the planted tensions ------------------------------

    def test_every_supplier_exists(self):
        for code, _name, _city, _lead, _note in bp.SUPPLIERS:
            self.assertTrue(
                self.env['res.partner'].search([('ref', '=', code)], limit=1), code)

    def test_caps_are_dual_sourced_with_a_real_lead_time_gap(self):
        """§9: local against import, a 34-day gap and a large price gap, so the
        optimal order timing is genuinely non-obvious."""
        cap = self._product('PK-CAP-S')
        offers = self.env['product.supplierinfo'].search(
            [('product_tmpl_id', '=', cap.product_tmpl_id.id)])
        self.assertGreaterEqual(len(offers), 2, "caps must be dual-sourced")
        gap = max(offers.mapped('delay')) - min(offers.mapped('delay'))
        self.assertGreaterEqual(gap, 30, "lead-time gap is only %s days" % gap)
        self.assertLess(min(offers.mapped('price')), max(offers.mapped('price')))

    def test_the_import_route_carries_a_minimum_order_quantity(self):
        cap = self._product('PK-CAP-S')
        importer = self.env['res.partner'].search([('ref', '=', 'SUP-NCI')], limit=1)
        offer = self.env['product.supplierinfo'].search([
            ('product_tmpl_id', '=', cap.product_tmpl_id.id),
            ('partner_id', '=', importer.id)], limit=1)
        self.assertEqual(offer.min_qty, 5_000_000)

    def test_labels_are_sole_sourced_per_sku(self):
        """§9: a label stockout stops a line and there is no alternate."""
        label = self._product('PK-LBL-330')
        offers = self.env['product.supplierinfo'].search(
            [('product_tmpl_id', '=', label.product_tmpl_id.id)])
        self.assertEqual(len(offers), 1)

    # -- §8.3 quality --------------------------------------------------------

    def test_all_ten_quality_control_points_exist(self):
        for code, title, _note, _recall in bp.QUALITY_POINTS:
            self.assertTrue(
                self.env['quality.point'].search([('title', '=', title)], limit=1),
                "missing %s %s" % (code, title))

    def test_the_bromate_limit_matches_the_gulf_regulation(self):
        self.assertEqual(bp.BROMATE_LIMIT_PPB, 10, "GSO 1025 caps bromate at 10 ppb")

    # -- §12 people ------------------------------------------------------------

    def test_every_seeded_user_exists(self):
        for login, _name, _company, _groups, _purpose in bp.USERS:
            self.assertTrue(
                self.env['res.users'].with_context(active_test=False).search(
                    [('login', '=', login)], limit=1), login)

    def test_the_read_only_purchaser_cannot_write_a_purchase_order(self):
        """T-21's premise. ir.model.access rows are additive, so fahad.p must
        hold the bespoke group and must NOT hold Purchase / User."""
        fahad = self.env['res.users'].search([('login', '=', 'fahad.p')], limit=1)
        self.assertTrue(fahad._has_group('alshayeb_demo_water.group_purchase_readonly'))
        self.assertFalse(fahad._has_group('purchase.group_purchase_user'))

    def test_the_writing_purchaser_can(self):
        """T-20's premise, and the contrast that makes T-21 mean anything."""
        noura = self.env['res.users'].search([('login', '=', 'noura.p')], limit=1)
        self.assertTrue(noura._has_group('purchase.group_purchase_user'))

    def test_the_branch_manager_is_scoped_to_jeddah(self):
        """T-24's premise: the record domain intersection has to have a real
        user-side restriction to intersect with."""
        bandar = self.env['res.users'].search([('login', '=', 'bandar.s')], limit=1)
        self.assertTrue(bandar._has_group(
            'stock_security_warehouse.group_stock_warehouse_scoped'))
        self.assertEqual(bandar.allowed_warehouse_ids.mapped('code'), ['BRJED'])

    def test_finance_and_hr_users_exist_as_isolation_targets(self):
        """§13 X-03 and X-04: the data has to be there for isolation to mean
        anything. No Phase 1 agent may reach either."""
        omar = self.env['res.users'].search([('login', '=', 'omar.f')], limit=1)
        hr = self.env['res.users'].search([('login', '=', 'hr.admin')], limit=1)
        self.assertTrue(omar._has_group('account.group_account_manager'))
        self.assertTrue(hr._has_group('hr.group_hr_user'))

    # -- §12 service users -----------------------------------------------------

    def test_all_four_service_users_exist(self):
        for login, *_ in bp.SERVICE_USERS:
            self.assertTrue(
                self.env['res.users'].with_context(active_test=False).search(
                    [('login', '=', login)], limit=1), login)

    def test_no_service_user_is_an_administrator(self):
        for login, *_ in bp.SERVICE_USERS:
            user = self.env['res.users'].search([('login', '=', login)], limit=1)
            self.assertFalse(user._has_group('base.group_system'), login)

    def test_no_service_user_holds_accounting_hr_or_sales(self):
        """§12: none have Accounting, HR or Sales groups."""
        forbidden = ['account.group_account_user', 'account.group_account_manager',
                     'hr.group_hr_user', 'sales_team.group_sale_salesman']
        for login, *_ in bp.SERVICE_USERS:
            user = self.env['res.users'].search([('login', '=', login)], limit=1)
            for xmlid in forbidden:
                group = self.env.ref(xmlid, raise_if_not_found=False)
                if group:
                    self.assertFalse(user._has_group(xmlid),
                                     "%s holds %s" % (login, xmlid))

    def test_no_service_user_can_log_in(self):
        from odoo.exceptions import AccessDenied
        for login, *_ in bp.SERVICE_USERS:
            user = self.env['res.users'].search([('login', '=', login)], limit=1)
            if 'is_ai_service_user' not in user._fields:
                self.skipTest('ai_operations not installed alongside')
            self.assertTrue(user.is_ai_service_user, login)
            with self.assertRaises(AccessDenied):
                user._check_credentials({'type': 'password', 'password': 'x'},
                                        {'interactive': False})

    def test_the_inventory_agent_is_the_only_one_spanning_both_companies(self):
        """§12 and C §12: it is therefore the sharpest multi-company test."""
        spans = {login: len(company_keys)
                 for login, _n, _c, company_keys, _g in bp.SERVICE_USERS}
        self.assertEqual(spans['ai.inventory'], 2)
        for login in ('ai.procurement', 'ai.manufacturing', 'ai.quality'):
            self.assertEqual(spans[login], 1, login)

    # -- idempotence -----------------------------------------------------------

    def test_building_twice_creates_nothing_twice(self):
        Product = self.env['product.product'].with_context(active_test=False)
        before = Product.search_count([('default_code', 'like', 'FG-')])
        self.env['alshayeb.demo.builder'].build_all()
        after = Product.search_count([('default_code', 'like', 'FG-')])
        self.assertEqual(before, after)
