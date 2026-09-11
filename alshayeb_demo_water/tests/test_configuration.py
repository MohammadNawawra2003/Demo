"""Document A's configuration baseline — §2, §4, §8.2, §10, §12, §15.

These are the settings that decide how the ERP *behaves*, as opposed to what
records exist. They are easy to leave out and invisible when you do: a database
with every product and no AVCO looks identical in a list view and values stock
differently, and one with no FEFO hands out the wrong lot for a year before
anybody notices.
"""

from odoo.tests import TransactionCase, tagged

from ..data import blueprint as bp


@tagged('post_install', '-at_install')
class TestNaqaaConfiguration(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.c1 = cls.env['res.company'].search(
            [('name', '=', 'Naqaa Water Manufacturing Co.')], limit=1)
        cls.c2 = cls.env['res.company'].search(
            [('name', '=', 'Naqaa Distribution Co.')], limit=1)

    def _product(self, code):
        return self.env['product.product'].with_context(active_test=False).search(
            [('default_code', '=', code)], limit=1)

    # -- §2 identity ------------------------------------------------------

    def test_every_company_is_in_the_blueprint_currency(self):
        """§2. Every figure in blueprint.py is authored in SAR -- the trade
        price per carton, the unit costs, FREIGHT_SAR_PER_PALLET. The company
        currency is what decides whether they are *rendered* as SAR, so a
        database in USD prints a SAR figure wearing a dollar sign and the
        agent's Arabic answer disagrees with the purchase order it produced.

        This failed silently for the life of the module: `_build_companies`
        searched for SAR without `active_test=False`, and Odoo ships every
        unused currency archived, so the search found nothing and the company
        was created on the database default.
        """
        for company in (self.c1, self.c2):
            self.assertTrue(company, "a Naqaa company is missing")
            self.assertEqual(
                company.currency_id.name, bp.CURRENCY,
                "%s is in %s, not %s -- every blueprint figure is authored in "
                "%s" % (company.name, company.currency_id.name,
                        bp.CURRENCY, bp.CURRENCY))

    def test_the_blueprint_currency_is_active(self):
        """The unarchive branch in `_build_companies` exists precisely for the
        archived case and used to be unreachable, so assert the outcome it is
        responsible for rather than trusting the branch is there."""
        currency = self.env['res.currency'].with_context(active_test=False).search(
            [('name', '=', bp.CURRENCY)], limit=1)
        self.assertTrue(currency, "%s does not exist at all" % bp.CURRENCY)
        self.assertTrue(currency.active,
                        "%s is archived, so nothing can be priced in it"
                        % bp.CURRENCY)

    def test_every_supplier_offer_is_in_the_blueprint_currency(self):
        """The supplier price is the most customer-visible number in the whole
        demo -- PK-BTL-600 at 0.078 is what the agent quotes and what the RFQ
        line prints. `currency_id` defaults to the installing user's company
        currency, so fixing the company alone still left every offer in USD:
        a fresh build with the company fix in place reproduced exactly that.
        """
        offers = self.env['product.supplierinfo'].with_context(
            active_test=False).search([('company_id', 'in', (self.c1 | self.c2).ids)])
        self.assertTrue(offers, "no supplier offers exist at all")
        wrong = offers.filtered(lambda o: o.currency_id.name != bp.CURRENCY)
        self.assertFalse(
            wrong,
            "%s supplier offers are not in %s: %s" % (
                len(wrong), bp.CURRENCY,
                sorted({o.currency_id.name for o in wrong})))

    # -- §15 costing and valuation ---------------------------------------

    def test_costing_is_avco(self):
        """DEVIATIONS.md already calls standard_price "our AVCO cost". It was
        not AVCO: every product sat on Odoo's default `standard` category."""
        category = self.env['product.category'].search([('name', '=', 'Naqaa')], limit=1)
        self.assertTrue(category, "the Naqaa product category does not exist")
        self.assertEqual(category.property_cost_method, 'average')

    def test_every_naqaa_product_is_on_the_naqaa_category(self):
        category = self.env['product.category'].search([('name', '=', 'Naqaa')], limit=1)
        for code in ('FG-330', 'PK-BTL-330', 'PR-WATER-TRT'):
            self.assertEqual(self._product(code).categ_id, category,
                             "%s is not on the Naqaa category" % code)

    # -- §8.2 FEFO and the expiry window ---------------------------------

    def test_removal_strategy_is_fefo(self):
        """§8.2. Every finished good carries an expiry, so first-in-first-out
        is the wrong strategy and would ship the wrong lot."""
        category = self.env['product.category'].search([('name', '=', 'Naqaa')], limit=1)
        self.assertTrue(category.removal_strategy_id,
                        "no removal strategy is set at all")
        self.assertEqual(category.removal_strategy_id.method, 'fefo')

    def test_finished_goods_alert_at_90_days_and_block_at_30(self):
        for code, _n, _u, _l, _c, _p, _line in bp.FINISHED_GOODS:
            # The expiry fields live on product.template, not on the variant.
            template = self._product(code).product_tmpl_id
            self.assertTrue(template.use_expiration_date, "%s has no expiry" % code)
            self.assertEqual(template.expiration_time, 365, "%s shelf life" % code)
            self.assertEqual(template.alert_time, 90, "%s alert" % code)
            self.assertEqual(template.removal_time, 30, "%s block" % code)

    # -- §4 / §15 warehouse steps ----------------------------------------

    def test_the_raw_material_store_receives_in_two_steps(self):
        """§4's `RM/QC` quarantine only exists if reception is multi-step.
        Without it QCP-04 and QCP-05 have nowhere to happen."""
        warehouse = self.env['stock.warehouse'].search(
            [('code', '=', 'RM'), ('company_id', '=', self.c1.id)], limit=1)
        self.assertEqual(warehouse.reception_steps, 'two_steps')
        self.assertTrue(warehouse.wh_input_stock_loc_id,
                        "there is no incoming inspection location")

    def test_distribution_delivers_in_two_steps(self):
        """§15: multi-step delivery on C2 (pick + ship)."""
        for code in ('DCJZN', 'BRABH', 'BRKHM', 'BRJED'):
            warehouse = self.env['stock.warehouse'].search(
                [('code', '=', code), ('company_id', '=', self.c2.id)], limit=1)
            self.assertEqual(warehouse.delivery_steps, 'pick_ship',
                             "%s delivers in one step" % code)

    # -- §2 identity ------------------------------------------------------

    def test_arabic_is_installed_and_is_the_operational_users_language(self):
        """§2 names Arabic the primary UI language. A translation written
        against an inactive language is stored and never rendered."""
        lang = self.env['res.lang'].search([('code', '=', bp.LANG)], limit=1)
        self.assertTrue(lang, "Arabic is not installed")
        for login in ('noura.p', 'khalid.m', 'huda.q'):
            user = self.env['res.users'].with_context(active_test=False).search(
                [('login', '=', login)], limit=1)
            self.assertEqual(user.lang, bp.LANG, "%s is not in Arabic" % login)

    def test_products_carry_arabic_names(self):
        """`product.template.name` is translatable, so the Arabic is a
        translation and the English survives beside it."""
        for code, arabic in bp.ARABIC_PRODUCT_NAMES.items():
            product = self._product(code)
            self.assertTrue(product, "%s is missing" % code)
            self.assertEqual(product.with_context(lang=bp.LANG).name, arabic,
                             "%s has no Arabic name" % code)

    def test_translating_never_destroys_the_english_name(self):
        """The failure this guards against actually happened: `res.partner.name`
        is NOT translatable, so writing it in an Arabic context is a plain write
        that replaces the value. Every company was renamed in all languages and
        `search([('name', '=', 'Naqaa Water Manufacturing Co.')])` stopped
        finding anything, which took the dependent module down on install."""
        for name in bp.ARABIC_COMPANY_NAMES:
            company = self.env['res.company'].search([('name', '=', name)], limit=1)
            self.assertTrue(company, "%s was renamed out of existence" % name)
            self.assertEqual(company.with_context(lang=bp.LANG).name, name,
                             "%s lost its English name to a translation" % name)
        product = self._product('FG-330')
        self.assertEqual(product.with_context(lang='en_US').name, 'Naqaa 330 ml')

    def test_the_fiscal_year_is_january_to_december(self):
        for company in (self.c1, self.c2):
            self.assertEqual(company.fiscalyear_last_day, 31)
            self.assertEqual(company.fiscalyear_last_month, '12')

    def test_vat_is_fifteen_percent(self):
        for company in (self.c1, self.c2):
            tax = self.env['account.tax'].with_context(active_test=False).search(
                [('company_id', '=', company.id), ('type_tax_use', '=', 'sale'),
                 ('amount', '=', bp.VAT_RATE)], limit=1)
            self.assertTrue(tax, "%s has no 15%% sales tax" % company.name)

    def test_supplier_bills_carry_input_vat_through_their_accounts(self):
        """DL-010. A bill line takes its tax from its account, so without these
        a bill the Accountant drafts comes out at its pre-tax amount."""
        for company in (self.c1, self.c2):
            tax = self.env['account.tax'].with_context(active_test=False).search(
                [('company_id', '=', company.id), ('type_tax_use', '=', 'purchase'),
                 ('amount', '=', bp.VAT_RATE)], limit=1)
            self.assertTrue(tax, "%s has no 15%% purchase tax" % company.name)
            for code, name in bp.OPEX_ACCOUNTS:
                account = self.env['account.account'].with_company(company).search(
                    [('code', '=', code), ('company_ids', 'in', company.id)], limit=1)
                self.assertTrue(account, "%s has no %s" % (company.name, name))
                self.assertIn(tax, account.tax_ids,
                              "%s on %s carries no input VAT" % (code, company.name))

    # -- §7 capacity ------------------------------------------------------

    def test_the_lines_carry_their_rated_speed(self):
        """§7's speeds were arithmetic in the blueprint and nowhere in the ERP,
        so neither planted capacity constraint was visible to a planner.

        mrp.workcenter has no speed field in Odoo 19; capacity is per product on
        mrp.workcenter.capacity. A line rated in bottles per hour therefore
        becomes cartons per hour on each SKU that runs on it.
        """
        for code, _name, units, _l, _c, _p, line in bp.FINISHED_GOODS:
            bph = bp.WORK_CENTRE_BPH.get(line)
            self.assertTrue(bph, "%s runs on unrated line %s" % (code, line))
            centre = self.env['mrp.workcenter'].search(
                [('code', '=', line), ('company_id', '=', self.c1.id)], limit=1)
            self.assertTrue(centre, "work centre %s is missing" % line)
            capacity = self.env['mrp.workcenter.capacity'].search(
                [('workcenter_id', '=', centre.id),
                 ('product_id', '=', self._product(code).id)], limit=1)
            self.assertTrue(capacity, "%s has no rated speed on %s" % (code, line))
            self.assertAlmostEqual(capacity.capacity, round(bph / float(units), 2),
                                   places=2, msg="%s rated speed" % code)

    def test_every_work_centre_carries_its_document_a_code(self):
        for code, name, _kind in bp.WORK_CENTRES:
            centre = self.env['mrp.workcenter'].search(
                [('name', '=', name), ('company_id', '=', self.c1.id)], limit=1)
            self.assertEqual(centre.code, code, "%s has no code" % name)

    def test_water_treatment_runs_a_different_calendar_from_the_lines(self):
        """§7: lines 320 d x 20 h, water treatment 350 d x 24 h. One calendar
        cannot express the WT constraint the whole capacity story turns on."""
        wt = self.env['mrp.workcenter'].search(
            [('name', '=', 'Water Treatment'), ('company_id', '=', self.c1.id)], limit=1)
        line = self.env['mrp.workcenter'].search(
            [('name', '=', 'Small PET Line A'), ('company_id', '=', self.c1.id)], limit=1)
        self.assertNotEqual(wt.resource_calendar_id, line.resource_calendar_id)
        self.assertEqual(wt.resource_calendar_id.hours_per_day, bp.WT_HOURS_PER_DAY)
        self.assertEqual(line.resource_calendar_id.hours_per_day, bp.LINE_HOURS_PER_DAY)

    # -- §10 customers ----------------------------------------------------

    def test_every_customer_is_tagged_with_its_channel_and_owned_by_c2(self):
        """Both were read from the blueprint and dropped, leaving every
        customer untagged and company-less: visible to everyone, owned by
        no one."""
        for code, _name, channel, _company_key in bp.CUSTOMERS:
            partner = self.env['res.partner'].search([('ref', '=', code)], limit=1)
            self.assertTrue(partner, "%s is missing" % code)
            self.assertEqual(partner.company_id, self.c2, "%s company" % code)
            self.assertIn(channel, partner.category_id.mapped('name'),
                          "%s is not tagged %r" % (code, channel))

    def test_all_five_channels_have_the_accounts_document_a_names(self):
        """§10 names six wholesalers, two hotel groups and two industrial
        camps. Four of the five channels were short."""
        counts = {}
        for _code, _name, channel, _company in bp.CUSTOMERS:
            counts[channel] = counts.get(channel, 0) + 1
        self.assertGreaterEqual(counts.get('traditional', 0), 6)
        self.assertGreaterEqual(counts.get('horeca', 0), 4)
        self.assertGreaterEqual(counts.get('institutional', 0), 4)
        self.assertGreaterEqual(counts.get('charity', 0), 3)
        self.assertEqual(sorted(counts), sorted(bp.CHANNEL_SHARES))

    def test_the_channel_shares_are_a_distribution(self):
        self.assertAlmostEqual(sum(bp.CHANNEL_SHARES.values()), 1.0, places=6)

    # -- §12 the builder must repair, not skip ----------------------------

    def test_a_user_who_lost_a_group_gets_it_back_on_rebuild(self):
        """`_build_people` used to skip any user that already existed, so a
        group added to the blueprint never reached a database built before it
        -- the same failure DEVIATIONS.md fixed for supplier pricing."""
        user = self.env['res.users'].with_context(active_test=False).search(
            [('login', '=', 'khalid.m')], limit=1)
        group = self.env.ref('mrp.group_mrp_manager')
        user.write({'group_ids': [(3, group.id)]})
        self.assertNotIn(group, user.group_ids)

        self.env['alshayeb.demo.builder'].build_all()

        self.assertIn(group, user.group_ids,
                      "rebuilding did not restore the group")
