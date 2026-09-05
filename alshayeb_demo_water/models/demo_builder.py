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
        companies = self._build_companies()
        self._build_warehouses(companies)
        products = self._build_products(companies)
        self._build_boms(companies, products)
        self._build_work_centres(companies)
        self._build_partners(companies, products)
        self._build_quality_points(companies, products)
        self._build_people(companies)
        _logger.info("alshayeb_demo_water: Naqaa company built")
        return True

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
        currency = self.env['res.currency'].search([('name', '=', bp.CURRENCY)], limit=1)
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
            companies[key] = self._get_or_create(
                'res.company', [('name', '=', name)], values)
        return companies

    # -- §4 warehouses ---------------------------------------------------

    def _build_warehouses(self, companies):
        warehouses = {}
        for code, name, company_key in bp.WAREHOUSES:
            company = companies[company_key]
            warehouses[code] = self._get_or_create(
                'stock.warehouse',
                [('code', '=', code), ('company_id', '=', company.id)],
                {'name': name, 'code': code, 'company_id': company.id})
        return warehouses

    # -- §5 products ------------------------------------------------------

    def _build_products(self, companies):
        products = {}

        def make(code, name, uom, cost=0.0, tracking='none', purchase_ok=False,
                 sale_ok=False, expiry=False, price=0.0):
            product = self.env['product.product'].with_context(
                active_test=False).search([('default_code', '=', code)], limit=1)
            if product:
                products[code] = product
                return product
            values = {
                'name': name, 'default_code': code, 'is_storable': True,
                'type': 'consu', 'uom_id': self._uom(uom).id,
                'standard_price': cost, 'list_price': price,
                'purchase_ok': purchase_ok, 'sale_ok': sale_ok,
                'tracking': tracking,
            }
            if expiry and 'use_expiration_date' in self.env['product.template']._fields:
                values['use_expiration_date'] = True
                values['expiration_time'] = 365      # §8.2 shelf life 12 months
                values['alert_time'] = 90            # alert at 90 days remaining
            products[code] = self.env['product.product'].create(values)
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
                'bom_line_ids': [(0, 0, {
                    'product_id': products[component].id,
                    'product_qty': qty,
                }) for component, qty, _scrap in lines],
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

        centres = {}
        for code, name, _kind in bp.WORK_CENTRES:
            centres[code] = self._get_or_create(
                'mrp.workcenter',
                [('name', '=', name), ('company_id', '=', company.id)],
                {'name': name, 'company_id': company.id,
                 'resource_calendar_id': calendar.id})
        return centres

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

        for code, name, _channel, _company_key in bp.CUSTOMERS:
            partners[code] = self._get_or_create(
                'res.partner', [('ref', '=', code)],
                {'name': name, 'ref': code,
                 'country_id': country.id if country else False,
                 'customer_rank': 1, 'company_type': 'company'})

        self._build_supplier_pricing(partners, products)
        return partners

    def _build_supplier_pricing(self, partners, products):
        """§9's planted tensions: caps dual-sourced local against import with a
        34-day lead gap, labels sole-sourced per SKU, bottles freight-heavy."""
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
                if Supplierinfo.search([('partner_id', '=', partner.id),
                                        ('product_tmpl_id', '=', product.product_tmpl_id.id)],
                                       limit=1):
                    continue
                Supplierinfo.create({
                    'partner_id': partner.id,
                    'product_tmpl_id': product.product_tmpl_id.id,
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
            if existing:
                people[login] = existing
                continue
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
            values = {
                'name': name, 'login': login, 'company_id': company.id,
                'company_ids': [(6, 0, [company.id])],
                'group_ids': [(4, gid) for gid in group_ids],
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
            if Users.with_context(active_test=False).search(
                    [('login', '=', login)], limit=1):
                continue
            company_ids = [companies[key].id for key in company_keys]
            group_ids = []
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
            # Strip the credential Odoo may have set, then mark it, so the
            # constraint on res.users has nothing to object to.
            self.env.cr.execute(
                "UPDATE res_users SET password = NULL WHERE id = %s", (user.id,))
            user.invalidate_recordset()
            if 'is_ai_service_user' in user._fields:
                user.is_ai_service_user = True
