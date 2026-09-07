"""Document A §3: the intercompany link, and the security test it exists for.

> C1 knows the true production cost per carton. C2 knows only the transfer
> price. The Distribution Sales Agent must be able to compute its own margin and
> must be technically unable to reach C1's production cost.

Document A calls that "the hardest security test in the platform". It had **no
data**: there was no intercompany rule, no transit route, no transfer-priced
record, and therefore nothing for X-01 to contrast. An isolation proof against
an empty database proves nothing.

This builds the link the way Odoo builds it -- a resupply route from C1's
finished goods to C2's distribution centre, and a transfer-priced sale between
the two companies -- so the cost sits on one side of a real document and the
price on the other.
"""

import logging

from odoo import api, models

from ..data import blueprint as bp

_logger = logging.getLogger(__name__)

#: §13 X-01: the record pair whose two numbers must never meet.
X01_ORIGIN = 'DEMO:X-01'
X01_PRODUCT = 'FG-330'
X01_CARTONS = 5_000


class AlshayebDemoIntercompany(models.AbstractModel):
    _inherit = 'alshayeb.demo.builder'

    # ------------------------------------------------------------------

    @api.model
    def _build_intercompany(self, companies, products):
        """§3's intercompany configuration, and the X-01 record pair."""
        result = {}
        result['rule'] = self._enable_intercompany_rules(companies)
        result['resupply'] = self._build_resupply_routes(companies)
        result['x01'] = self._seed_transfer_priced_sale(companies, products)
        return result

    # -- §3 intercompany rules -------------------------------------------

    @api.model
    def _enable_intercompany_rules(self, companies):
        """C1 sales order -> C2 purchase order.

        The field that switches this on moved more than once across Odoo
        versions, so it is set by whichever name the installed schema actually
        carries rather than by the one a given release happened to use.
        """
        Company = self.env['res.company']
        enabled = []
        candidates = (
            ('rule_type', 'sale_purchase'),
            ('intercompany_generate_purchase_order', True),
            ('intercompany_document_state', 'posted'),
        )
        for key in ('c1', 'c2'):
            company = companies[key]
            for field, value in candidates:
                if field in Company._fields:
                    try:
                        company[field] = value
                        enabled.append('%s.%s' % (key, field))
                    except Exception:           # noqa: BLE001 - demo data
                        _logger.debug("could not set %s on %s", field, company.name)
        if not enabled:
            _logger.info(
                "alshayeb_demo_water: no intercompany field on res.company in "
                "this install; the transfer-priced records below still carry "
                "the §3 contrast X-01 needs.")
        return enabled

    # -- §3/§4 the transit route -----------------------------------------

    @api.model
    def _build_resupply_routes(self, companies):
        """§4: the branches resupply from DC-JZN, and DC-JZN from the plant.

        ``resupply_wh_ids`` is Odoo's own inter-warehouse mechanism and it
        creates the transit locations §3 describes; writing it is the whole
        configuration.
        """
        Warehouse = self.env['stock.warehouse']
        plant = Warehouse.search(
            [('code', '=', 'FG'), ('company_id', '=', companies['c1'].id)], limit=1)
        centre = Warehouse.search(
            [('code', '=', 'DCJZN'), ('company_id', '=', companies['c2'].id)], limit=1)
        if not centre:
            return []
        wired = []
        # Branches resupply from the distribution centre.
        for code in ('BRABH', 'BRKHM', 'BRJED'):
            branch = Warehouse.search(
                [('code', '=', code), ('company_id', '=', companies['c2'].id)],
                limit=1)
            if not branch or 'resupply_wh_ids' in branch._fields is False:
                continue
            if centre not in branch.resupply_wh_ids:
                try:
                    branch.resupply_wh_ids = [(4, centre.id)]
                    wired.append(code)
                except Exception:               # noqa: BLE001 - demo data
                    _logger.debug("could not resupply %s from DCJZN", code)
        # The distribution centre resupplies from the plant. Cross-company, so
        # Odoo may refuse it depending on the intercompany configuration; the
        # X-01 contrast below does not depend on it.
        if plant and 'resupply_wh_ids' in centre._fields:
            try:
                if plant not in centre.resupply_wh_ids:
                    centre.resupply_wh_ids = [(4, plant.id)]
                    wired.append('DCJZN')
            except Exception:                   # noqa: BLE001 - demo data
                _logger.debug("could not resupply DCJZN from the plant")
        return wired

    # -- §13 X-01 ----------------------------------------------------------

    @api.model
    def _seed_transfer_priced_sale(self, companies, products):
        """The record pair X-01 is about.

        C1 sells FG-330 to C2 at the §3 transfer price. C1's own production cost
        for the same carton is on the product, in C1's company. Two numbers,
        two companies, one product -- and the whole point is that a C2 identity
        can reach exactly one of them.
        """
        product = products.get(X01_PRODUCT)
        c1, c2 = companies['c1'], companies['c2']
        if not product:
            return False
        Sale = self.env['sale.order'].with_company(c1)
        existing = Sale.search([('origin', '=', X01_ORIGIN)], limit=1)
        if existing:
            return existing.id

        pricelist = self.env['product.pricelist'].with_context(
            active_test=False).search(
            [('name', '=', 'Naqaa Transfer Price'), ('company_id', '=', c2.id)],
            limit=1)
        item = self.env['product.pricelist.item'].search(
            [('pricelist_id', '=', pricelist.id),
             ('product_tmpl_id', '=', product.product_tmpl_id.id)], limit=1) \
            if pricelist else None
        if not item:
            return False

        order = Sale.create({
            'partner_id': c2.partner_id.id,
            'company_id': c1.id,
            'origin': X01_ORIGIN,
            'order_line': [(0, 0, {
                'product_id': product.id,
                'product_uom_qty': X01_CARTONS,
                # The transfer price, explicitly: this is the only figure C2
                # ever sees, and §3 accepts that it encodes C1's cost to within
                # an estimate. The markup table is what stays on this side.
                'price_unit': item.fixed_price,
            })],
        })
        order.action_confirm()
        return order.id

    # -- assertions the demo relies on ------------------------------------

    @api.model
    def x01_contrast(self, companies=None):
        """The two numbers, for a test or a demonstration.

        Returned rather than asserted here, so the security suite can prove the
        gap is real *and* that a C2 identity cannot read the left-hand one.
        """
        c1 = self.env['res.company'].search(
            [('name', '=', 'Naqaa Water Manufacturing Co.')], limit=1)
        c2 = self.env['res.company'].search(
            [('name', '=', 'Naqaa Distribution Co.')], limit=1)
        product = self.env['product.product'].with_context(
            active_test=False).search([('default_code', '=', X01_PRODUCT)], limit=1)
        if not (c1 and c2 and product):
            return {}
        order = self.env['sale.order'].with_company(c1).search(
            [('origin', '=', X01_ORIGIN)], limit=1)
        return {
            'production_cost': product.with_company(c1).standard_price,
            'transfer_price': order.order_line[:1].price_unit if order else 0.0,
            'markup': bp.TRANSFER_MARKUP.get(X01_PRODUCT),
        }
