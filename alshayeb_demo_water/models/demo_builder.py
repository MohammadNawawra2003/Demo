"""Build the Naqaa company from the Document A blueprint. Idempotent.

Document A §16 specifies static master data as XML. This builds it in Python
instead, from the tables in ``data/blueprint.py``, for one reason: the master
data is *derived*, not arbitrary. Six BoMs are the same six lines with different
numbers, and every one of those numbers has to agree with the water balance in
§7 and the transfer price in §6. Expressed as XML that is roughly two thousand
hand-maintained lines in which a single wrong digit is invisible; expressed as a
table plus a loop it is checkable by eye and testable by assertion.

See DEVIATIONS.md. Everything else about §16 holds: the module depends on no
`ai_operations`, installs standalone, and is a maintained deliverable with its
own version.
"""

import logging

from odoo import api, models

from ..data import blueprint as bp

_logger = logging.getLogger(__name__)


class AlshayebDemoBuilder(models.AbstractModel):
    _name = 'alshayeb.demo.builder'
    _description = 'Naqaa Demo Company Builder'

    # ------------------------------------------------------------------

    @api.model
    def build_all(self):
        self._enable_arabic()
        companies = self._build_companies()
        self._build_charts(companies)
        self._build_taxes(companies)
        category = self._build_product_category()
        self._build_warehouses(companies)
        products = self._build_products(companies, category)
        self._build_boms(companies, products)
        self._build_transfer_pricing(companies, products)
        self._build_work_centres(companies)
        self._build_partners(companies, products)
        self._build_quality_points(companies, products)
        self._build_people(companies)
        self._build_intercompany(companies, products)
        _logger.info("alshayeb_demo_water: Naqaa company built")
        return True

    # -- §2 language ----------------------------------------------------

    @api.model
    def _enable_arabic(self):
        """§2: Arabic is the primary UI language, English secondary.

        Activating the language is what makes the Arabic names written later
        reachable at all -- a translation written against an inactive language
        is stored and never rendered.
        """
        lang = self.env['res.lang'].with_context(active_test=False).search(
            [('code', '=', bp.LANG)], limit=1)
        if lang and not lang.active:
            self.env['base.language.install'].create({
                'lang_ids': [(6, 0, [lang.id])]}).lang_install()
            lang = self.env['res.lang'].search([('code', '=', bp.LANG)], limit=1)
        return lang

    def _translate(self, record, field, arabic):
        """Write the Arabic of a **translatable** field, leaving English alone.

        ⚠ The `translate` check is not defensive programming, it is the whole
        point. Writing a field in a language context only stores a *translation*
        when the field is translatable; on an ordinary field it is a plain write
        that replaces the value. `res.partner.name` is not translatable, so
        translating a company this way silently renamed it in every language and
        the next `search([('name', '=', 'Naqaa Water Manufacturing Co.')])`
        found nothing.
        """
        if not arabic or not record:
            return
        field_def = record._fields.get(field)
        if not field_def or not field_def.translate:
            return
        lang = self.env['res.lang'].search([('code', '=', bp.LANG)], limit=1)
        if not lang:
            return
        if record.with_context(lang=bp.LANG)[field] != arabic:
            record.with_context(lang=bp.LANG).write({field: arabic})

    # -- helpers --------------------------------------------------------

    def _get_or_create(self, model, domain, values):
        record = self.env[model].with_context(active_test=False).search(domain, limit=1)
        if record:
            return record
        return self.env[model].create(values)

    def _uom(self, name):
        mapping = {'Units': 'uom.product_uom_unit', 'kg': 'uom.product_uom_kgm',
                   'Litre': 'uom.product_uom_litre'}
        return self.env.ref(mapping.get(name, 'uom.product_uom_unit'))

    # -- §3 companies ---------------------------------------------------

    def _build_companies(self):
        country = self.env['res.country'].search([('code', '=', bp.COUNTRY)], limit=1)
        # active_test=False, or the unarchive below is unreachable: Odoo ships
        # every currency but the one in use archived, so a default search for
        # SAR returns an empty recordset on exactly the databases that need
        # unarchiving. The branch could only ever fire for a currency that was
        # already active -- the one case it is not needed -- and the company
        # was then created with the database default, USD. Every figure in
        # blueprint.py is authored in SAR, so this silently mislabelled them.
        currency = self.env['res.currency'].with_context(active_test=False).search(
            [('name', '=', bp.CURRENCY)], limit=1)
        if currency and not currency.active:
            currency.active = True

        companies = {}
        for key, name, parent_key in bp.COMPANIES:
            values = {'name': name}
            if country:
                values['country_id'] = country.id
            if currency:
                values['currency_id'] = currency.id
            if parent_key and parent_key in companies:
                values['parent_id'] = companies[parent_key].id
            company = self._get_or_create(
                'res.company', [('name', '=', name)], values)
            # §2: fiscal year is January-December, and the plant is in Sabya.
            # Written on every run rather than at create, so a database built
            # before this fix repairs itself on upgrade.
            fiscal = {}
            if company.fiscalyear_last_day != bp.FISCAL_YEAR_LAST_DAY:
                fiscal['fiscalyear_last_day'] = bp.FISCAL_YEAR_LAST_DAY
            if company.fiscalyear_last_month != bp.FISCAL_YEAR_LAST_MONTH:
                fiscal['fiscalyear_last_month'] = bp.FISCAL_YEAR_LAST_MONTH
            if key == 'c1' and not company.city:
                fiscal['city'] = bp.PLANT_CITY
            if fiscal:
                company.write(fiscal)
            self._translate(company.partner_id, 'name',
                            bp.ARABIC_COMPANY_NAMES.get(name))
            companies[key] = company
        return companies

    # -- §15 the finance skeleton ----------------------------------------

    @api.model
    def _build_charts(self, companies):
        """§15: journals, and separate stock input/output/valuation accounts
        per company.

        Not ``account.chart.template.try_loading``. That is the obvious call and
        it does not work here: Odoo itself warns "Incorrect usage of try_loading
        without a fully loaded registry" when it is invoked from a data-file
        ``<function>``, and the result is a company whose ``chart_template`` is
        stamped while **no journals are created at all** -- which is exactly how
        invoicing failed with "No journal could be found ... for any of those
        types: sale". Moving it to a post-init hook would fix the registry and
        break idempotency, because a hook fires on install only.

        So the skeleton is built explicitly. It is the seven accounts and four
        journals a demo actually needs, not a Saudi chart of accounts, and that
        is enough for §14's last three months of invoices and for X-04 to have
        posted entries to be denied.
        """
        Account = self.env['account.account']
        Journal = self.env['account.journal']
        built = {}
        for key in ('c1', 'c2'):
            company = companies[key]
            accounts = {}
            for code, name, account_type in bp.CHART_ACCOUNTS:
                account = Account.with_company(company).with_context(
                    active_test=False).search(
                    [('code', '=', code), ('company_ids', 'in', company.id)], limit=1)
                if not account:
                    account = Account.with_company(company).create({
                        'code': code, 'name': name, 'account_type': account_type,
                    })
                accounts[account_type] = account
            for code, name, journal_type in bp.CHART_JOURNALS:
                journal = Journal.with_company(company).search(
                    [('code', '=', code), ('company_id', '=', company.id)], limit=1)
                if journal:
                    continue
                values = {'name': name, 'code': code, 'type': journal_type,
                          'company_id': company.id}
                default = {'sale': 'income', 'purchase': 'expense'}.get(journal_type)
                if default and accounts.get(default):
                    values['default_account_id'] = accounts[default].id
                Journal.with_company(company).create(values)
            built[key] = accounts
        self._wire_account_properties(companies, built)
        return built

    @api.model
    def _wire_account_properties(self, companies, accounts):
        """Point the product category and the partners at those accounts.

        Company-dependent every one of them, so each write is made in the right
        company -- the same defect that priced a draft RFQ at zero.
        """
        category = self.env['product.category'].search([('name', '=', 'Naqaa')], limit=1)
        for key in ('c1', 'c2'):
            company = companies[key]
            book = accounts.get(key) or {}
            if category:
                scoped = category.with_company(company)
                for field, account_type in (
                        ('property_account_income_categ_id', 'income'),
                        ('property_account_expense_categ_id', 'expense'),
                        ('property_stock_valuation_account_id', 'asset_current'),
                        ('property_stock_account_input_categ_id', 'asset_current'),
                        ('property_stock_account_output_categ_id', 'asset_current')):
                    account = book.get(account_type)
                    if account and field in scoped._fields and not scoped[field]:
                        try:
                            scoped[field] = account.id
                        except Exception:       # noqa: BLE001 - demo data
                            _logger.debug("could not set %s", field)
            receivable = book.get('asset_receivable')
            payable = book.get('liability_payable')
            partners = self.env['res.partner'].search(
                ['|', ('customer_rank', '>', 0), ('supplier_rank', '>', 0)])
            for partner in partners:
                scoped = partner.with_company(company)
                if receivable and not scoped.property_account_receivable_id:
                    scoped.property_account_receivable_id = receivable.id
                if payable and not scoped.property_account_payable_id:
                    scoped.property_account_payable_id = payable.id

    # -- §2/§15 VAT ------------------------------------------------------

    @api.model
    def _build_taxes(self, companies):
        """§15: VAT 15% standard. l10n_sa supplies the taxes; this only asserts
        one exists per operating company and makes it the default, so a sales
        order raised by the demo carries the rate Document A states."""
        Tax = self.env['account.tax']
        Group = self.env['account.tax.group']
        country = self.env['res.country'].search([('code', '=', bp.COUNTRY)], limit=1)
        built = {}
        for key in ('c1', 'c2'):
            company = companies[key]
            # Any 15% sales tax already on the company counts -- l10n_sa ships
            # its own and installs them whenever a chart reaches this company,
            # and creating a second one collides on Odoo's name uniqueness
            # constraint rather than being merely redundant.
            tax = Tax.with_context(active_test=False).search(
                [('company_id', '=', company.id), ('type_tax_use', '=', 'sale'),
                 ('amount', '=', bp.VAT_RATE)], limit=1)
            name = '%s — %s' % (bp.VAT_TAX_NAME, company.name)
            if not tax:
                tax = Tax.with_context(active_test=False).search(
                    [('company_id', '=', company.id), ('name', '=', name)], limit=1)
            if tax:
                built[key] = tax
                continue
            # l10n_sa ships the Saudi taxes, but a chart of accounts is only
            # installed onto a company deliberately, and these companies are
            # built by this module. Without a chart there is no tax group, and
            # account.tax.group_id is required.
            group = Group.search([('company_id', '=', company.id)], limit=1)
            if not group:
                group = Group.create({
                    'name': name,
                    'company_id': company.id,
                    'country_id': country.id if country else False,
                })
            built[key] = Tax.create({
                'name': name,
                'amount': bp.VAT_RATE,
                'amount_type': 'percent',
                'type_tax_use': 'sale',
                'company_id': company.id,
                'tax_group_id': group.id,
                'country_id': country.id if country else False,
            })
        return built

    # -- §15 costing -----------------------------------------------------

    @api.model
    def _build_product_category(self):
        """§15 AVCO with automated real-time valuation, and §8.2 FEFO.

        Odoo puts all three on the product category, so Naqaa needs its own --
        the default category is `standard` costing with manual valuation, which
        is neither what §15 specifies nor what the rest of this codebase already
        assumes (DEVIATIONS.md calls `standard_price` "our AVCO cost").
        """
        # §5.2 costs run to three and four decimals -- a cap is SAR 0.022 and a
        # label SAR 0.010. Odoo's default Product Price precision is 2, and AVCO
        # rounds `standard_price` to it, so every packaging cost was silently
        # flattened (0.042 -> 0.04). Widen the precision before writing any cost.
        precision = self.env['decimal.precision'].search(
            [('name', '=', 'Product Price')], limit=1)
        if precision and precision.digits < 4:
            precision.digits = 4
            # decimal.precision is ormcached and the field's `digits` are read
            # through that cache, so without this the widened precision does
            # not apply until the next registry load -- and every cost written
            # later in this same run is still rounded to two places.
            self.env.registry.clear_cache()

        Category = self.env['product.category']
        category = Category.search([('name', '=', 'Naqaa')], limit=1)
        values = {'property_cost_method': 'average'}
        # Removal strategy is FEFO: every finished good carries an expiry and
        # §8.2 requires first-expiry-first-out, not first-in-first-out. FEFO
        # ships with product_expiry, not with stock.
        fefo = self.env.ref('product_expiry.removal_fefo', raise_if_not_found=False)
        if not fefo:
            fefo = self.env['product.removal'].search(
                [('method', '=', 'fefo')], limit=1)
        if fefo:
            values['removal_strategy_id'] = fefo.id
        if 'property_valuation' in Category._fields:
            values['property_valuation'] = 'real_time'
        if not category:
            category = Category.create(dict(values, name='Naqaa'))
        else:
            category.write(values)
        return category

    # -- §4 warehouses ---------------------------------------------------

    def _build_warehouses(self, companies):
        """§4 warehouses, and §15's step configuration.

        ⚠ Warehouse codes are truncated: ``SCRAP`` -> ``SCRP``, ``DC-JZN`` ->
        ``DCJZN``, ``BR-ABH`` -> ``BRABH`` and so on. ``stock.warehouse.code``
        is five characters in Odoo 19, so Document A's codes do not fit. See
        DEVIATIONS.md.
        """
        warehouses = {}
        for code, name, company_key in bp.WAREHOUSES:
            company = companies[company_key]
            warehouse = self._get_or_create(
                'stock.warehouse',
                [('code', '=', code), ('company_id', '=', company.id)],
                {'name': name, 'code': code, 'company_id': company.id})
            # §4/§15: incoming packaging is quarantined pending QC, so the raw
            # material store receives in two steps. This is what creates the
            # `RM/QC` input location -- without it §4's quarantine location
            # does not exist and QCP-04/QCP-05 have nowhere to happen.
            if code == 'RM' and warehouse.reception_steps != 'two_steps':
                warehouse.reception_steps = 'two_steps'
            # §15: multi-step delivery on C2 (pick + ship).
            if company_key == 'c2' and warehouse.delivery_steps != 'pick_ship':
                warehouse.delivery_steps = 'pick_ship'
            warehouses[code] = warehouse
        return warehouses

    # -- §5 products ------------------------------------------------------

    def _build_products(self, companies, category):
        products = {}
        # The operating company. `standard_price` is company-dependent, so a
        # cost written while the builder runs as the installing user lands on
        # THAT user's company and every Naqaa read returns 0.0 -- which is how a
        # draft RFQ came out priced at zero. Same defect the supplier pricing
        # had; written and repaired explicitly here.
        company = companies['c1']

        def _set_cost(product, cost):
            if cost and product.with_company(company).standard_price != cost:
                product.with_company(company).standard_price = cost

        def make(code, name, uom, cost=0.0, tracking='none', purchase_ok=False,
                 sale_ok=False, expiry=False, price=0.0):
            product = self.env['product.product'].with_context(
                active_test=False).search([('default_code', '=', code)], limit=1)
            if product:
                _set_cost(product, cost)
                # Repair on upgrade: a database built before the Naqaa category
                # existed has its products on Odoo's default one, which is
                # `standard` costing with no FEFO.
                if category and product.categ_id != category:
                    product.categ_id = category.id
                # Repair the expiry window too. product_expiry was not a
                # dependency until 19.0.1.3.0, so every database built before it
                # has finished goods with no expiry at all -- the builder
                # guarded on the field existing and skipped them silently.
                if expiry and 'use_expiration_date' in product.product_tmpl_id._fields:
                    template = product.product_tmpl_id
                    if not template.use_expiration_date:
                        template.use_expiration_date = True
                    for field, value in (('expiration_time', 365),
                                         ('alert_time', 90),
                                         ('removal_time', 30)):
                        if template[field] != value:
                            template[field] = value
                self._translate(product, 'name',
                                bp.ARABIC_PRODUCT_NAMES.get(code))
                products[code] = product
                return product
            values = {
                'name': name, 'default_code': code, 'is_storable': True,
                'type': 'consu', 'uom_id': self._uom(uom).id,
                'standard_price': cost, 'list_price': price,
                'purchase_ok': purchase_ok, 'sale_ok': sale_ok,
                'tracking': tracking,
            }
            if category:
                values['categ_id'] = category.id
            if expiry and 'use_expiration_date' in self.env['product.template']._fields:
                values['use_expiration_date'] = True
                values['expiration_time'] = 365      # §8.2 shelf life 12 months
                values['alert_time'] = 90            # alert at 90 days remaining
                # §8.2 "block at 30". `removal_time` is the days-before-expiry
                # at which FEFO stops handing the lot out, which is what
                # "blocked" means operationally in Odoo.
                values['removal_time'] = 30
            products[code] = self.env['product.product'].create(values)
            # create() writes standard_price against the CURRENT company; write
            # it again explicitly for the operating one.
            _set_cost(products[code], cost)
            self._translate(products[code], 'name',
                            bp.ARABIC_PRODUCT_NAMES.get(code))
            return products[code]

        # Finished goods: lot tracked with expiry, sold not purchased.
        for code, name, units, litres, _cartons, price, _line in bp.FINISHED_GOODS:
            make(code, name, 'Units', tracking='lot', sale_ok=True,
                 expiry=True, price=price)

        # Packaging: all purchased, most lot tracked so a recall traces back to
        # the supplier and not only forward to the customer (§8.2).
        for group in (bp.BOTTLES, bp.CLOSURES, bp.LABELS, bp.CARTONS,
                      bp.FILMS, bp.PALLETS):
            for code, name, uom, cost, _lead, tracked in group:
                make(code, name, uom, cost=cost, purchase_ok=True,
                     tracking='lot' if tracked else 'none')

        # Process materials. Treated water is lot tracked: without it
        # trace_forward has nothing to traverse and the recall demo cannot run.
        for code, name, uom, tracked, purchasable in bp.PROCESS_MATERIALS:
            make(code, name, uom, purchase_ok=purchasable,
                 tracking='lot' if tracked else 'none')
        for code, name, uom, cost, _lead in bp.SPARES:
            make(code, name, uom, cost=cost, purchase_ok=True)

        return products

    # -- §6 bills of material ---------------------------------------------

    def _bom_line(self, product, qty, scrap):
        """§6's Qty and Scrap % are separate columns, and Odoo 19 has no scrap
        field on ``mrp.bom.line``.

        The BoM therefore carries the documented **standard** quantity -- a
        carton of 330 ml is 40 bottles, not 40.2 -- and the scrap percentage
        stays in ``blueprint.SCRAP_PCT``, where the history generator applies it
        to *actual* consumption. That is also where it belongs: scrap is the gap
        between the standard and what the line really used, and a BoM that
        already includes it cannot express that gap at all.
        """
        return {'product_id': product.id, 'product_qty': qty}

    def _build_boms(self, companies, products):
        Bom = self.env['mrp.bom']
        company = companies['c1']
        boms = {}

        for code, _name, units, litres, _cartons, _price, _line in bp.FINISHED_GOODS:
            finished = products[code]
            existing = Bom.search([('product_tmpl_id', '=', finished.product_tmpl_id.id),
                                   ('company_id', '=', company.id)], limit=1)
            if existing:
                boms[code] = existing
                continue

            suffix = code.split('-')[1]
            net_litres = units * litres
            lines = [
                ('PR-WATER-TRT', round(net_litres * bp.PROCESS_WATER_FACTOR, 2), 0.0),
                ('PK-BTL-%s' % suffix, units, bp.SCRAP_PCT['bottle']),
                (bp.CAP_FOR[code], units, bp.SCRAP_PCT['cap']),
                ('PK-LBL-%s' % suffix, units, bp.SCRAP_PCT['label']),
                ('PK-FILM-SHR', bp.FILM_PER_CARTON[code], bp.SCRAP_PCT['film']),
                ('PK-CTN-%s' % suffix, 1, bp.SCRAP_PCT['carton']),
            ]
            boms[code] = Bom.create({
                'product_tmpl_id': finished.product_tmpl_id.id,
                'product_qty': 1,
                'type': 'normal',
                'company_id': company.id,
                'bom_line_ids': [(0, 0, self._bom_line(
                    products[component], qty, scrap))
                    for component, qty, scrap in lines],
            })

        # The daily treatment run: raw water in, one lot of treated water out.
        treated = products['PR-WATER-TRT']
        if not Bom.search([('product_tmpl_id', '=', treated.product_tmpl_id.id)], limit=1):
            boms['PR-WATER-TRT'] = Bom.create({
                'product_tmpl_id': treated.product_tmpl_id.id,
                'product_qty': 1000,
                'type': 'normal',
                'company_id': company.id,
                'bom_line_ids': [(0, 0, {
                    'product_id': products['PR-WATER-RAW'].id,
                    # ~85% RO yield (§6): 1000 L treated needs ~1176 L raw.
                    'product_qty': 1176,
                })],
            })
        return boms

    # -- §3/§6 the transfer price, derived ---------------------------------

    @api.model
    def _material_cost(self, bom):
        """BoM material cost at current component costs, in the BoM's company."""
        company = bom.company_id
        total = 0.0
        for line in bom.bom_line_ids:
            total += line.product_id.with_company(company).standard_price * line.product_qty
        return total / (bom.product_qty or 1.0)

    @api.model
    def _build_transfer_pricing(self, companies, products):
        """§3: cost-plus, per SKU, and the markup table is withheld from C2.

        Computed rather than typed. The price C2 pays is
        ``(material + labour/overhead) x (1 + markup)``, so it tracks a change
        in any component cost instead of drifting out of the §3 band the way a
        literal table did. The markup itself lives only here and on C1's side of
        the pricelist -- what C2 can see is one number per SKU, which is exactly
        the residual risk §3 accepts and documents.
        """
        Pricelist = self.env['product.pricelist']
        c1, c2 = companies['c1'], companies['c2']
        pricelist = Pricelist.with_context(active_test=False).search(
            [('name', '=', 'Naqaa Transfer Price'), ('company_id', '=', c2.id)],
            limit=1)
        if not pricelist:
            pricelist = Pricelist.create({
                'name': 'Naqaa Transfer Price',
                'company_id': c2.id,
                'currency_id': c2.currency_id.id,
            })

        Item = self.env['product.pricelist.item']
        priced = {}
        for code, markup in bp.TRANSFER_MARKUP.items():
            product = products.get(code)
            if not product:
                continue
            bom = self.env['mrp.bom'].search(
                [('product_tmpl_id', '=', product.product_tmpl_id.id),
                 ('company_id', '=', c1.id)], limit=1)
            if not bom:
                continue
            plant_cost = self._material_cost(bom) + bp.LABOUR_OVERHEAD_PER_CARTON
            # §6: the finished good's own cost. It was never written -- every FG
            # was created with the default cost of zero -- so C1 "knew" its
            # production cost only in the sense that the number was absent, and
            # X-01's whole contrast was zero against the transfer price.
            if product.with_company(c1).standard_price != plant_cost:
                product.with_company(c1).standard_price = plant_cost
            price = round(plant_cost * (1.0 + markup), 2)
            priced[code] = price
            item = Item.search([('pricelist_id', '=', pricelist.id),
                                ('product_tmpl_id', '=', product.product_tmpl_id.id)],
                               limit=1)
            values = {'compute_price': 'fixed', 'fixed_price': price,
                      'applied_on': '1_product',
                      'product_tmpl_id': product.product_tmpl_id.id}
            if item:
                item.write(values)
            else:
                Item.create(dict(values, pricelist_id=pricelist.id))
        return priced

    # -- §7 work centres ---------------------------------------------------

    def _build_work_centres(self, companies):
        company = companies['c1']
        # A work centre's calendar must belong to the same company, or Odoo's
        # _check_company refuses the create.
        calendar = company.resource_calendar_id
        if not calendar:
            calendar = self.env['resource.calendar'].create({
                'name': 'Naqaa Plant Hours', 'company_id': company.id})
            company.resource_calendar_id = calendar
        # §7 availability: filling lines 320 d x 20 h, water treatment
        # 350 d x 24 h. Two calendars, because they are genuinely two regimes
        # and a single one cannot express the WT constraint that the whole
        # capacity story in §7 turns on.
        wt_calendar = self._get_or_create(
            'resource.calendar',
            [('name', '=', 'Naqaa Water Treatment'), ('company_id', '=', company.id)],
            {'name': 'Naqaa Water Treatment', 'company_id': company.id,
             'hours_per_day': bp.WT_HOURS_PER_DAY})
        if calendar.hours_per_day != bp.LINE_HOURS_PER_DAY:
            calendar.hours_per_day = bp.LINE_HOURS_PER_DAY

        centres = {}
        for code, name, _kind in bp.WORK_CENTRES:
            centre_calendar = wt_calendar if code == 'WT' else calendar
            values = {'name': name, 'company_id': company.id, 'code': code,
                      'resource_calendar_id': centre_calendar.id}
            centre = self._get_or_create(
                'mrp.workcenter',
                [('name', '=', name), ('company_id', '=', company.id)], values)
            if centre.code != code:
                centre.code = code
            if centre.resource_calendar_id != centre_calendar:
                centre.resource_calendar_id = centre_calendar.id
            centres[code] = centre
        self._build_line_speeds(centres, company)
        return centres

    def _build_line_speeds(self, centres, company):
        """§7 rated speed, expressed the way Odoo 19 actually models it.

        ``mrp.workcenter`` has no speed field -- capacity lives on
        ``mrp.workcenter.capacity``, one row per product, which is the right
        shape anyway: a line rated at 30,000 bottles/hour does not produce
        30,000 *cartons* an hour, and the conversion is per SKU. So the bottles
        per hour in §7 become cartons per hour on each SKU that runs on the line.
        """
        Capacity = self.env['mrp.workcenter.capacity']
        for code, _name, units, _litres, _cartons, _price, line in bp.FINISHED_GOODS:
            centre = centres.get(line)
            bph = bp.WORK_CENTRE_BPH.get(line)
            if not centre or not bph:
                continue
            product = self.env['product.product'].with_context(
                active_test=False).search([('default_code', '=', code)], limit=1)
            if not product:
                continue
            cartons_per_hour = round(bph / float(units), 2)
            existing = Capacity.search(
                [('workcenter_id', '=', centre.id),
                 ('product_id', '=', product.id)], limit=1)
            if existing:
                if existing.capacity != cartons_per_hour:
                    existing.capacity = cartons_per_hour
                continue
            Capacity.create({
                'workcenter_id': centre.id,
                'product_id': product.id,
                'capacity': cartons_per_hour,
            })

    # -- §9 / §10 partners ---------------------------------------------------

    def _build_partners(self, companies, products):
        Partner = self.env['res.partner']
        country = self.env['res.country'].search([('code', '=', bp.COUNTRY)], limit=1)
        partners = {}

        for code, name, city, _lead, comment in bp.SUPPLIERS:
            partners[code] = self._get_or_create(
                'res.partner', [('ref', '=', code)],
                {'name': name, 'ref': code, 'city': city, 'comment': comment,
                 'country_id': country.id if country else False,
                 'supplier_rank': 1, 'company_type': 'company'})

        # §10: the channel is what the demand model weights by, and the company
        # is what the multi-company rules scope by. Both were being read from
        # the blueprint and dropped, which left every customer untagged and
        # company-less -- visible to everyone, belonging to no one.
        for code, name, channel, company_key in bp.CUSTOMERS:
            tag = self._get_or_create(
                'res.partner.category', [('name', '=', channel)],
                {'name': channel})
            partner = self._get_or_create(
                'res.partner', [('ref', '=', code)],
                {'name': name, 'ref': code,
                 'company_id': companies[company_key].id,
                 'country_id': country.id if country else False,
                 'customer_rank': 1, 'company_type': 'company',
                 'category_id': [(4, tag.id)]})
            # Repair on upgrade for partners built before either was written.
            if not partner.company_id:
                partner.company_id = companies[company_key].id
            if tag not in partner.category_id:
                partner.category_id = [(4, tag.id)]
            partners[code] = partner

        self._build_supplier_pricing(companies['c1'], partners, products)
        return partners

    def _build_supplier_pricing(self, company, partners, products):
        """§9's planted tensions: caps dual-sourced local against import with a
        34-day lead gap, labels sole-sourced per SKU, bottles freight-heavy.

        **The company is explicit, and that is not cosmetic.**
        ``product.supplierinfo.company_id`` defaults to the *installing user's*
        company, which is whatever company the administrator happens to be in --
        not Naqaa. The products themselves are company-less and so stay visible,
        but every supplier price landed on another company and the multi-company
        record rule hid all of it from every Naqaa user: ``compare_suppliers``
        returned an empty offer list for every product, with no error anywhere.
        Existing rows are corrected on the way past, because a database built
        before this fix cannot be repaired by creating records that already
        exist.
        """
        Supplierinfo = self.env['product.supplierinfo']
        sourcing = [
            ('SUP-JPI', ['PK-BTL-200', 'PK-BTL-330', 'PK-BTL-600', 'PK-BTL-1500'], 1.00, 18),
            ('SUP-RPC', ['PK-BTL-200', 'PK-BTL-330', 'PK-BTL-600'], 1.06, 21),
            ('SUP-JZP', ['PK-BTL-5000', 'PK-BTL-12000'], 1.00, 14),
            ('SUP-GCC', ['PK-CAP-S', 'PK-CAP-L'], 1.00, 21),
            ('SUP-NCI', ['PK-CAP-S', 'PK-CAP-L'], 0.78, 55),
            ('SUP-APH', ['PK-LBL-200', 'PK-LBL-330', 'PK-LBL-600',
                         'PK-LBL-1500', 'PK-LBL-5000', 'PK-LBL-12000'], 1.00, 12),
            ('SUP-SCG', ['PK-CTN-200', 'PK-CTN-330', 'PK-CTN-600',
                         'PK-CTN-1500', 'PK-CTN-5000', 'PK-CTN-12000'], 1.00, 8),
            ('SUP-GFT', ['PK-FILM-SHR', 'PK-FILM-STR'], 1.00, 14),
            ('SUP-AWP', ['PK-PAL'], 1.00, 10),
            ('SUP-ATS', ['SP-MEMB-RO', 'SP-LAMP-UV', 'SP-OZONE'], 1.00, 60),
            ('SUP-CGF', ['PR-ANTISCAL', 'PR-SANIT'], 1.00, 20),
        ]
        for supplier_code, product_codes, multiplier, lead in sourcing:
            partner = partners[supplier_code]
            for product_code in product_codes:
                product = products.get(product_code)
                if not product:
                    continue
                existing = Supplierinfo.with_context(active_test=False).search(
                    [('partner_id', '=', partner.id),
                     ('product_tmpl_id', '=', product.product_tmpl_id.id)],
                    limit=1)
                if existing:
                    if existing.company_id != company:
                        existing.company_id = company.id
                    if existing.currency_id != company.currency_id:
                        existing.currency_id = company.currency_id.id
                    continue
                Supplierinfo.create({
                    'company_id': company.id,
                    'partner_id': partner.id,
                    'product_tmpl_id': product.product_tmpl_id.id,
                    # Explicit for the same reason as company_id above, and it
                    # is the more visible of the two: currency_id defaults to
                    # the installing user's company currency, so every offer
                    # was written in USD while `price` is a SAR figure derived
                    # from standard_price. This is the number the RFQ line
                    # shows the customer -- PK-BTL-600 at 0.078.
                    'currency_id': company.currency_id.id,
                    'price': round(product.standard_price * multiplier, 4),
                    'delay': lead,
                    'min_qty': 5_000_000 if supplier_code == 'SUP-NCI' else 0,
                })

    # -- §8.3 quality control points -----------------------------------------

    def _build_quality_points(self, companies, products):
        Point = self.env['quality.point']
        picking_type = self.env['stock.picking.type'].search([
            ('company_id', '=', companies['c1'].id), ('code', '=', 'incoming')], limit=1)
        points = {}
        for code, title, note, _recall in bp.QUALITY_POINTS:
            existing = Point.search([('title', '=', title),
                                     ('company_id', '=', companies['c1'].id)], limit=1)
            if existing:
                points[code] = existing
                continue
            values = {
                'title': title,
                'company_id': companies['c1'].id,
                'note': '%s — %s' % (code, note),
            }
            if picking_type:
                values['picking_type_ids'] = [(6, 0, [picking_type.id])]
            points[code] = Point.create(values)
        return points

    # -- §12 people ------------------------------------------------------------

    def _build_people(self, companies):
        Users = self.env['res.users']
        readonly_group = self.env.ref(
            'alshayeb_demo_water.group_purchase_readonly', raise_if_not_found=False)
        scoped_group = self.env.ref(
            'stock_security_warehouse.group_stock_warehouse_scoped',
            raise_if_not_found=False)
        jeddah = self.env['stock.warehouse'].search([('code', '=', 'BRJED')], limit=1)

        people = {}
        for login, name, company_key, group_xmlids, purpose in bp.USERS:
            existing = Users.with_context(active_test=False).search(
                [('login', '=', login)], limit=1)
            company = companies[company_key]
            group_ids = []
            for xmlid in group_xmlids:
                if xmlid == 'READONLY_PURCHASE':
                    if readonly_group:
                        group_ids.append(readonly_group.id)
                elif xmlid == 'WAREHOUSE_SCOPED':
                    if scoped_group:
                        group_ids.append(scoped_group.id)
                else:
                    group = self.env.ref(xmlid, raise_if_not_found=False)
                    if group:
                        group_ids.append(group.id)
            if existing:
                # Repair rather than skip. Skipping is the same failure mode the
                # supplier pricing had: a user created before a group changed
                # never receives the change, and no amount of re-running fixes
                # it because the record already exists. Groups are ADDED, never
                # removed -- a privilege granted deliberately in the UI is not
                # this builder's to take away.
                missing = [gid for gid in group_ids
                           if gid not in existing.group_ids.ids]
                if missing:
                    existing.write({'group_ids': [(4, gid) for gid in missing]})
                if existing.lang != bp.LANG:
                    existing.lang = bp.LANG
                if login == 'bandar.s' and jeddah and not existing.allowed_warehouse_ids:
                    existing.allowed_warehouse_ids = [(6, 0, [jeddah.id])]
                people[login] = existing
                continue
            values = {
                'name': name, 'login': login, 'company_id': company.id,
                'company_ids': [(6, 0, [company.id])],
                'group_ids': [(4, gid) for gid in group_ids],
                # §2/§15: Arabic is the operational users' UI language.
                'lang': bp.LANG,
            }
            user = Users.create(values)
            if login == 'bandar.s' and jeddah:
                user.allowed_warehouse_ids = [(6, 0, [jeddah.id])]
            people[login] = user

        self._build_service_users(companies)
        return people

    def _build_service_users(self, companies):
        """§12. No Accounting, no HR, no Sales. None administrators. None able
        to log in: the mechanism is the absence of every credential."""
        Users = self.env['res.users']
        for login, name, _code, company_keys, group_xmlids in bp.SERVICE_USERS:
            existing = Users.with_context(active_test=False).search(
                [('login', '=', login)], limit=1)
            if existing:
                # Skipping the CREATE is right; skipping the hardening was not.
                # This module deliberately does not depend on ai_operations, so
                # it can be built first -- and then both of the things below are
                # silently absent and nothing ever repairs them, because this
                # loop used to `continue` here. See _harden_service_user.
                self._harden_service_user(existing)
                continue
            company_ids = [companies[key].id for key in company_keys]
            group_ids = []
            # AI Operations / User is mandatory for a service user: the guard
            # reads its own policy as the executing identity, and sudo() is
            # banned, so without it every autonomous run fails on configuration
            # rather than on permission.
            ai_user = self.env.ref('ai_operations.group_ai_user',
                                   raise_if_not_found=False)
            if ai_user:
                group_ids.append(ai_user.id)
            for xmlid in group_xmlids:
                group = self.env.ref(xmlid, raise_if_not_found=False)
                if group:
                    group_ids.append(group.id)
            user = Users.create({
                'name': name, 'login': login,
                'company_id': company_ids[0],
                'company_ids': [(6, 0, company_ids)],
                'group_ids': [(4, gid) for gid in group_ids],
            })
            self._harden_service_user(user)

    def _harden_service_user(self, user):
        """The two things that exist only once ``ai_operations`` is loaded.

        Both are conditional on the field or the xmlid resolving, and both used
        to be applied on CREATE only. That is a conditional which can fire only
        in the case where it is not needed: this module declares no dependency
        on ``ai_operations`` -- deliberately, because the demo database is the
        regression baseline and must install standalone -- so the order in which
        the two branches load is unconstrained, and installing this one first
        left every service identity

          * without ``is_ai_service_user``, so the login control that makes an
            agent identity unusable by a human was never armed, and
          * without ``group_ai_user``, which is mandatory: the guard reads its
            own policy as the executing identity and sudo() is banned.

        Re-asserting them on every build is what makes the repair reachable. A
        generator may dedupe what it ADDS; it must never skip what it REPAIRS.
        Both writes are idempotent and one-way -- the flag is only ever set,
        never cleared, so this can never re-open a login.
        """
        ai_user = self.env.ref('ai_operations.group_ai_user',
                               raise_if_not_found=False)
        if ai_user and ai_user not in user.group_ids:
            user.write({'group_ids': [(4, ai_user.id)]})
        if 'is_ai_service_user' in user._fields and not user.is_ai_service_user:
            # Strip the credential Odoo may have set, then mark it, so the
            # constraint on res.users has nothing to object to.
            self.env.cr.execute(
                "UPDATE res_users SET password = NULL WHERE id = %s", (user.id,))
            user.invalidate_recordset()
            user.is_ai_service_user = True
