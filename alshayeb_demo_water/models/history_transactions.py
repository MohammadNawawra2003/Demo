"""The transactions Document A §14 sizes and the generator could not produce.

Session 7 built lots, purchase orders and the recall genealogy. It created no
``mrp.production``, no ``sale.order``, no invoice and no ``quality.check`` —
five of §14's eight object types had no code path at all, so the demo had lots
that were never manufactured and finished goods that were never sold.

Everything here is anchor-relative and driven by the same seasonal curve, so the
July peak and the Hijri drift show up in orders and production, not only in lot
counts. Every record carries a ``DEMO:`` origin, which is what makes the whole
generator safe to re-run.
"""

import datetime
import logging

from odoo import api, fields, models

from ..data import blueprint as bp
from ..data import seasonality as season

_logger = logging.getLogger(__name__)

#: §14: the last three months are invoiced in full and the earlier months stay
#: confirmed-but-uninvoiced. Accounting exists in Phase 1 only as an isolation
#: target, and posting fifteen months of journal items was the slowest step in
#: the whole build programme for no demonstrative gain.
INVOICED_MONTHS = 3

#: Orders older than this are historical production and are closed. Leaving the
#: whole eighteen months `confirmed` produced a plant with a 500-order backlog
#: of things it had supposedly already made, and it crowded every recent order
#: out of `manufacturing.get_open_mos`.
OPEN_WINDOW_DAYS = 30

#: How far back real manufacturing orders are generated.
#:
#: Not the whole eighteen months, and the reason is cost rather than taste.
#: Closing an order posts its finished goods, and with automated valuation that
#: is a quant, a valuation layer and an accounting entry each; across the full
#: window that took the install past twenty minutes and produced nothing a
#: reviewer could see that this does not. The deep history is carried by what it
#: is actually made of: the lots, the purchase orders, the sales and the quality
#: checks all span the full eighteen months. See DEVIATIONS.md.
MO_WINDOW_DAYS = 120


class AlshayebDemoHistoryTransactions(models.AbstractModel):
    _inherit = 'alshayeb.demo.history'

    # -- §6 the daily water-treatment MO ---------------------------------

    @api.model
    def _generate_treatment_orders(self, company, products, anchor, months, scale, rng):
        """§6: water treatment is "a continuous upstream process driven by one
        MO per day". The BoM existed and nothing ever ran it.

        Each run consumes raw water and produces one lot of treated water — the
        same lot the filling orders then consume, which is what gives
        ``trace_forward`` something to walk that was actually manufactured
        rather than asserted.
        """
        Production = self.env['mrp.production'].with_company(company)
        treated = products['PR-WATER-TRT']
        bom = self.env['mrp.bom'].search(
            [('product_tmpl_id', '=', treated.product_tmpl_id.id),
             ('company_id', '=', company.id)], limit=1)
        picking_type = self._treatment_picking_type(company)
        Lot = self.env['stock.lot']
        created = 0

        earliest = season._as_date(anchor) - datetime.timedelta(days=MO_WINDOW_DAYS)
        for day in self._sampled_days(anchor, months, scale):
            if season._as_date(day) < earliest:
                continue
            origin = 'DEMO:WT:%s' % day.isoformat()
            if Production.search([('origin', '=', origin)], limit=1):
                continue
            lot = Lot.search(
                [('product_id', '=', treated.id),
                 ('name', '=', season.treated_water_lot_name(day, 1))], limit=1)
            # §6 sizing: 765 m3/day of product water, in litres.
            values = {
                'product_id': treated.id,
                'product_qty': bp.WT_PRODUCT_M3_DAY * 1000.0,
                'company_id': company.id,
                'origin': origin,
                'date_start': fields.Datetime.to_datetime(day),
            }
            if bom:
                values['bom_id'] = bom.id
            if picking_type:
                values['picking_type_id'] = picking_type.id
            production = Production.create(values)
            if lot and 'lot_producing_ids' in production._fields:
                production.lot_producing_ids = [(6, 0, [lot.id])]
            created += 1
        return created

    # -- §14 manufacturing orders ----------------------------------------

    @api.model
    def _generate_manufacturing_orders(self, company, products, anchor, months,
                                       scale, rng):
        """One MO per SKU per production day, sized by the seasonal curve.

        Left **confirmed**, not done. A done MO posts stock and, with automated
        valuation, accounting -- eighteen months of that is precisely the cost
        §14 trimmed the accounting history to avoid, and it would also flood the
        quant table the AI tools read.
        """
        Production = self.env['mrp.production'].with_company(company)
        picking_type = self._filling_picking_type(company)
        created = 0

        earliest = season._as_date(anchor) - datetime.timedelta(days=MO_WINDOW_DAYS)
        for day in self._sampled_days(anchor, months, scale):
            if season._as_date(day) < earliest:
                continue
            for code, _name, _units, _litres, cartons, _price, line in bp.FINISHED_GOODS:
                planned = season.daily_cartons(day, cartons)
                if planned < 1:
                    continue
                origin = 'DEMO:MO:%s:%s' % (code, day.isoformat())
                if Production.search([('origin', '=', origin)], limit=1):
                    continue
                product = products[code]
                bom = self.env['mrp.bom'].search(
                    [('product_tmpl_id', '=', product.product_tmpl_id.id),
                     ('company_id', '=', company.id)], limit=1)
                values = {
                    'product_id': product.id,
                    'product_qty': float(int(planned)),
                    'company_id': company.id,
                    'origin': origin,
                    'date_start': fields.Datetime.to_datetime(day),
                }
                if bom:
                    values['bom_id'] = bom.id
                if picking_type:
                    values['picking_type_id'] = picking_type.id
                production = Production.create(values)
                lot = self.env['stock.lot'].search(
                    [('product_id', '=', product.id),
                     ('name', '=', season.finished_lot_name(
                         line, day, bp.LOT_SEQUENCE.get(code, 1)))], limit=1)
                if lot and 'lot_producing_ids' in production._fields:
                    production.lot_producing_ids = [(6, 0, [lot.id])]
                self._close_if_historical(production, day, anchor)
                created += 1
        return created

    @api.model
    def _close_if_historical(self, production, day, anchor):
        """Close an order that belongs to the past.

        Through the real buttons, and with ``skip_consumption``: the components
        are not staged, so the raw moves close at zero and nothing is consumed
        out of a stock the plant never held. What it does post is the finished
        goods, which is the point -- eighteen months of production that leaves
        no finished stock behind is not a history, it is a list.
        """
        cutoff = season._as_date(anchor) - datetime.timedelta(days=OPEN_WINDOW_DAYS)
        if season._as_date(day) >= cutoff:
            return False
        try:
            production.action_confirm()
            # Release anything Odoo reserved for this order and close the raw
            # moves at zero. Two reasons, and both matter:
            #
            # 1. `skip_consumption` skips the consumption *warning*, not the
            #    lot requirement -- a reserved move line on a tracked component
            #    still raises "You need to supply a Lot/Serial Number".
            # 2. The stock these orders would otherwise consume is §13's seeded
            #    stock. Historical production must not quietly eat the
            #    conditions the demo is built on.
            production.qty_producing = production.product_qty
            production._set_qty_producing()
            # AFTER _set_qty_producing, never before: that call is what writes
            # the consumed quantity onto the raw moves, so clearing the lines
            # first simply hands it a clean slate to fill in again.
            production.do_unreserve()
            for move in production.move_raw_ids:
                move.move_line_ids.unlink()
                move.quantity = 0.0
                move.picked = False
            production.with_context(
                skip_consumption=True, skip_backorder=True).button_mark_done()
        except Exception as exc:                # noqa: BLE001 - demo data
            _logger.warning("could not close %s: %s", production.origin, exc)
            return False
        return production.state == 'done'

    # -- §14 sales orders and the last three months of invoices ----------

    @api.model
    def _generate_sales(self, company, products, anchor, months, scale, rng):
        """C2 sells to its channels, weighted by §10's shares.

        The channel weighting is what makes the demand signal usable: a naive
        forecast over an unweighted customer list would not reproduce the
        modern-trade concentration that distorts it.
        """
        distribution = self.env['res.company'].search(
            [('name', '=', 'Naqaa Distribution Co.')], limit=1)
        if not distribution:
            return {'orders': 0, 'invoices': 0}
        Sale = self.env['sale.order'].with_company(distribution)
        customers = self._customers_by_channel()
        if not customers:
            return {'orders': 0, 'invoices': 0}

        invoice_cutoff = self._invoice_cutoff(anchor)
        orders = invoices = 0

        for day in self._sampled_days(anchor, months, scale):
            for channel, share in sorted(bp.CHANNEL_SHARES.items()):
                pool = customers.get(channel)
                if not pool:
                    continue
                # Deterministic pick: the same seed and anchor must choose the
                # same customer, so the choice is indexed rather than random.
                customer = pool[day.toordinal() % len(pool)]
                origin = 'DEMO:SO:%s:%s' % (channel, day.isoformat())
                if Sale.search([('origin', '=', origin)], limit=1):
                    continue
                lines = []
                for code, _n, _u, _l, cartons, price, _line in bp.FINISHED_GOODS:
                    quantity = int(season.daily_cartons(day, cartons) * share)
                    if quantity < 1:
                        continue
                    lines.append((0, 0, {
                        'product_id': products[code].id,
                        'product_uom_qty': quantity,
                        'price_unit': price,
                    }))
                if not lines:
                    continue
                order = Sale.create({
                    'partner_id': customer.id,
                    'company_id': distribution.id,
                    'origin': origin,
                    'date_order': fields.Datetime.to_datetime(day),
                    'order_line': lines,
                })
                order.action_confirm()
                orders += 1
                if day >= invoice_cutoff:
                    invoices += self._invoice_order(order, day)
        return {'orders': orders, 'invoices': invoices}

    @api.model
    def _invoice_order(self, order, day):
        """§14: only the last three months are invoiced, and posted."""
        try:
            invoice = order._create_invoices()
        except Exception:                       # noqa: BLE001 - demo data
            _logger.exception("could not invoice %s", order.name)
            return 0
        if not invoice:
            return 0
        invoice.invoice_date = day
        try:
            invoice.action_post()
        except Exception:                       # noqa: BLE001 - demo data
            _logger.exception("could not post %s", invoice.name)
            return 0
        return len(invoice)

    # -- §8.3 quality checks ---------------------------------------------

    @api.model
    def _generate_quality_checks(self, company, products, anchor, months, scale, rng):
        """A check per control point per production day, against the real QCPs.

        §14 sizes these at ~22,000 and there were none: the ten control points
        existed as records that nothing had ever tested against, so the quality
        history a recall investigation reads was empty.
        """
        Check = self.env['quality.check']
        points = self.env['quality.point'].search([('company_id', '=', company.id)])
        if not points:
            return 0
        treated = products['PR-WATER-TRT']
        created = 0

        for day in self._sampled_days(anchor, months, scale):
            lot = self.env['stock.lot'].search(
                [('product_id', '=', treated.id),
                 ('name', '=', season.treated_water_lot_name(day, 1))], limit=1)
            for point in points:
                # v19 carries `lot_ids` (many2many), not `lot_id`.
                domain = [('point_id', '=', point.id)]
                domain += ([('lot_ids', 'in', lot.id)] if lot
                           else [('lot_ids', '=', False)])
                if Check.search(domain, limit=1):
                    continue
                values = {
                    'point_id': point.id,
                    'product_id': treated.id,
                    'company_id': company.id,
                    'team_id': point.team_id.id,
                }
                if lot and 'lot_ids' in Check._fields:
                    values['lot_ids'] = [(6, 0, [lot.id])]
                check = Check.create(values)
                # Every check in the history passed; the one failure is S-09,
                # seeded deliberately so the recall has a single cause.
                if 'quality_state' in check._fields:
                    check.quality_state = 'pass'
                created += 1
        return created

    # -- helpers -----------------------------------------------------------

    @api.model
    def _sampled_days(self, anchor, months, scale):
        """The production days this run touches, at the given scale.

        Sampling every Nth day rather than shortening the window is what keeps
        the *shape*: both Ramadans, both Hajj seasons and the whole seasonal
        curve stay inside the sample, and only the density falls.
        """
        every_nth = max(1, int(round(1 / max(scale, 0.001))))
        for index, day in enumerate(season.days(anchor, months)):
            if index % every_nth:
                continue
            yield day

    @api.model
    def _invoice_cutoff(self, anchor):
        anchor = season._as_date(anchor)
        month = anchor.month - INVOICED_MONTHS
        year = anchor.year
        while month <= 0:
            month += 12
            year -= 1
        return datetime.date(year, month, 1)

    @api.model
    def _customers_by_channel(self):
        by_channel = {}
        for code, _name, channel, _company in bp.CUSTOMERS:
            partner = self.env['res.partner'].search([('ref', '=', code)], limit=1)
            if partner:
                by_channel.setdefault(channel, []).append(partner)
        return by_channel

    @api.model
    def _filling_picking_type(self, company):
        warehouse = self.env['stock.warehouse'].search(
            [('code', '=', 'WIP'), ('company_id', '=', company.id)], limit=1)
        return warehouse.manu_type_id

    @api.model
    def _treatment_picking_type(self, company):
        warehouse = self.env['stock.warehouse'].search(
            [('code', '=', 'WIP'), ('company_id', '=', company.id)], limit=1)
        return warehouse.manu_type_id
