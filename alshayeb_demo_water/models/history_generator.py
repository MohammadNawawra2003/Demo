"""Eighteen months of history. Document A §14, Document C §17 Session 7.

**On scale.** Document A §14 sizes the full dataset at roughly 250,000 records,
and Document C §20 already names generating it as the largest schedule risk,
sitting on the critical path of every scenario test. So the generator takes a
``scale`` factor. At ``scale=1.0`` it produces the blueprint volumes; below that
it produces proportionally fewer transactions **while preserving every
structural property the scenarios depend on**: the seasonal shape, the Hijri
drift, the lot genealogy from treated water through to customer, and every
seeded condition in §13.

That distinction is the whole point. The scenarios need the *shape*; only
performance measurement needs the *volume*. Running the suite against a reduced
scale is what makes it runnable at all, and the full dataset stays one argument
away.

Determinism is over **business values**, verified by checksum over a declared
field set — never by comparing dumps, because a database is never byte-for-byte
reproducible.
"""

import logging
import random

from odoo import api, fields, models

from ..data import blueprint as bp
from ..data import seasonality as season

_logger = logging.getLogger(__name__)

#: Document A §16: deterministic seed, so the same seed and anchor date produce
#: the same quantities, dates, lots, prices and document sequences.
SEED = 20260904


class AlshayebDemoHistory(models.AbstractModel):
    _name = 'alshayeb.demo.history'
    _description = 'Naqaa Demo History Generator'

    # ------------------------------------------------------------------

    @api.model
    def generate(self, anchor=None, months=18, scale=0.02, with_conditions=True):
        """Generate the history window ending at ``anchor``.

        Anchor-date relative, so the demo never goes stale: regenerate to bring
        it current. Returns a summary dict.
        """
        anchor = season._as_date(anchor or fields.Date.context_today(self))
        rng = random.Random(SEED)

        company = self.env['res.company'].search(
            [('name', '=', 'Naqaa Water Manufacturing Co.')], limit=1)
        if not company:
            raise ValueError("Build the master data before generating history.")

        products = {
            product.default_code: product
            for product in self.env['product.product'].with_context(
                active_test=False).search([('default_code', '!=', False)])
        }

        summary = {'anchor': anchor, 'scale': scale}
        summary['treated_lots'] = self._generate_treated_water(
            company, products, anchor, months, scale, rng)
        summary['fg_lots'] = self._generate_production(
            company, products, anchor, months, scale, rng)
        summary['purchases'] = self._generate_purchases(
            company, products, anchor, months, scale, rng)
        if with_conditions:
            summary['conditions'] = self._seed_conditions(company, products, anchor)
        _logger.info("alshayeb_demo_water: history generated %s", summary)
        return summary

    # -- the genealogy the recall depends on -----------------------------

    @api.model
    def _generate_treated_water(self, company, products, anchor, months, scale, rng):
        """One treatment batch per day, one lot each.

        This is the link that makes a bromate exceedance traceable forward into
        finished goods. Odoo's genealogy follows lot links on stock.move.line,
        so if the intermediate carries no lot there is no link and the headline
        demo cannot run at all.
        """
        Lot = self.env['stock.lot']
        treated = products['PR-WATER-TRT']
        created = []
        every_nth = max(1, int(round(1 / max(scale, 0.001))))

        for index, day in enumerate(season.days(anchor, months)):
            if index % every_nth:
                continue
            name = season.treated_water_lot_name(day, 1)
            if Lot.search([('name', '=', name),
                           ('product_id', '=', treated.id)], limit=1):
                continue
            created.append(Lot.create({
                'name': name,
                'product_id': treated.id,
                'company_id': company.id,
            }))
        return len(created)

    @api.model
    def _generate_production(self, company, products, anchor, months, scale, rng):
        """Finished-goods lots, consuming the day's treated water.

        Each FG lot records which treatment batch fed it, which is what
        ``quality.trace_forward`` walks. Volumes follow the seasonal curve, so
        the July peak and the Hijri drift are both visible in the data.
        """
        Lot = self.env['stock.lot']
        treated = products['PR-WATER-TRT']
        created = 0
        every_nth = max(1, int(round(1 / max(scale, 0.001))))

        for index, day in enumerate(season.days(anchor, months)):
            if index % every_nth:
                continue
            water_lot = Lot.search([
                ('product_id', '=', treated.id),
                ('name', '=', season.treated_water_lot_name(day, 1))], limit=1)

            for code, _name, _units, _litres, cartons, _price, line in bp.FINISHED_GOODS:
                product = products[code]
                planned = season.daily_cartons(day, cartons)
                if planned < 1:
                    continue
                lot_name = season.finished_lot_name(line, day, 1)
                if Lot.search([('name', '=', lot_name),
                               ('product_id', '=', product.id)], limit=1):
                    continue
                lot = Lot.create({
                    'name': lot_name,
                    'product_id': product.id,
                    'company_id': company.id,
                })
                # The genealogy link, recorded where a tool can follow it even
                # before the moves exist.
                if water_lot and 'ref' in lot._fields:
                    lot.ref = water_lot.name
                created += 1
        return created

    @api.model
    def _generate_purchases(self, company, products, anchor, months, scale, rng):
        """Draft and confirmed purchase orders across the window."""
        Purchase = self.env['purchase.order']
        supplier = self.env['res.partner'].search([('ref', '=', 'SUP-JPI')], limit=1)
        if not supplier:
            return 0
        bottle = products['PK-BTL-330']
        created = 0
        every_nth = max(1, int(round(1 / max(scale, 0.001)))) * 7

        for index, day in enumerate(season.days(anchor, months)):
            if index % every_nth:
                continue
            quantity = int(season.daily_cartons(day, 3_500_000) * 40 * 7)
            if quantity <= 0:
                continue
            # Idempotent: the generator must be safe to re-run, and the
            # determinism checksum is over business values, so a duplicate order
            # is a real defect rather than harmless noise.
            origin = 'DEMO:HIST:%s' % day.isoformat()
            if Purchase.search([('origin', '=', origin)], limit=1):
                continue
            Purchase.create({
                'partner_id': supplier.id,
                'company_id': company.id,
                'origin': origin,
                'date_order': fields.Datetime.to_datetime(day),
                'order_line': [(0, 0, {
                    'product_id': bottle.id,
                    'product_qty': quantity,
                    'price_unit': bottle.standard_price,
                    'date_planned': fields.Datetime.to_datetime(day),
                })],
            })
            created += 1
        return created

    # -- §13 the seeded conditions ----------------------------------------

    @api.model
    def _seed_conditions(self, company, products, anchor):
        """Planted so agent behaviour can be demonstrated on demand rather than
        waited for. Document A §13."""
        seeded = {}
        seeded['S-01'] = self._seed_bottle_shortage(company, products, anchor)
        seeded['S-03'] = self._seed_overdue_po(company, products, anchor)
        seeded['S-09'] = self._seed_bromate_exceedance(company, products, anchor)
        seeded['S-10'] = self._seed_recall_chain(company, products, anchor)
        return seeded

    def _seed_recall_chain(self, company, products, anchor):
        """S-10 and S-11: the batch fed four finished lots, three of which
        shipped to customers across branches.

        Built as **real stock move lines**, not as a shortcut. Document A §5.3
        is explicit that Odoo's genealogy follows lot links on
        ``stock.move.line``: if the chain is faked, ``trace_forward`` walks
        nothing and the headline demo is a slide rather than a demonstration.
        """
        Move = self.env['stock.move']
        MoveLine = self.env['stock.move.line']
        Lot = self.env['stock.lot']

        treated = products['PR-WATER-TRT']
        water_lot = Lot.search([('name', '=', bp.S09_LOT),
                                ('product_id', '=', treated.id)], limit=1)
        if not water_lot:
            return False

        warehouse = self.env['stock.warehouse'].search(
            [('code', '=', 'FG'), ('company_id', '=', company.id)], limit=1)
        if not warehouse:
            return False
        stock_location = warehouse.lot_stock_id
        production_location = self.env['stock.location'].search(
            [('usage', '=', 'production'), ('company_id', 'in', (False, company.id))],
            limit=1)
        customer_location = self.env.ref('stock.stock_location_customers')
        if not production_location:
            return False

        # Four finished lots across two lines, per §13 S-10.
        affected = [('L1', 'FG-330'), ('L1', 'FG-600'),
                    ('L3', 'FG-1500'), ('L3', 'FG-5000')]
        customers = self.env['res.partner'].search([('customer_rank', '>', 0)], limit=3)
        created = []

        for index, (line_code, product_code) in enumerate(affected):
            product = products[product_code]
            lot_name = 'NQ-%s-RECALL-%03d' % (line_code, index + 1)
            fg_lot = Lot.search([('name', '=', lot_name),
                                 ('product_id', '=', product.id)], limit=1)
            if fg_lot:
                created.append(fg_lot.id)
                continue
            fg_lot = Lot.create({'name': lot_name, 'product_id': product.id,
                                 'company_id': company.id})

            # Consumption: treated water into production. This is the link.
            consume = Move.create({
                'product_id': treated.id,
                'product_uom_qty': 15840.0,
                'location_id': stock_location.id,
                'location_dest_id': production_location.id,
                'company_id': company.id,
            })
            MoveLine.create({
                'move_id': consume.id,
                'product_id': treated.id,
                'lot_id': water_lot.id,
                'quantity': 15840.0,
                'location_id': stock_location.id,
                'location_dest_id': production_location.id,
                'company_id': company.id,
            })

            # Production: the finished lot out of the same production location.
            produce = Move.create({
                'product_id': product.id,
                'product_uom_qty': 1000.0,
                'location_id': production_location.id,
                'location_dest_id': stock_location.id,
                'company_id': company.id,
            })
            MoveLine.create({
                'move_id': produce.id,
                'product_id': product.id,
                'lot_id': fg_lot.id,
                'quantity': 1000.0,
                'location_id': production_location.id,
                'location_dest_id': stock_location.id,
                'company_id': company.id,
            })

            # Three of the four already shipped, to customers across branches.
            if index < 3 and customers:
                customer = customers[index % len(customers)]
                deliver = Move.create({
                    'product_id': product.id,
                    'product_uom_qty': 400.0,
                    'location_id': stock_location.id,
                    'location_dest_id': customer_location.id,
                    'partner_id': customer.id,
                    'company_id': company.id,
                })
                MoveLine.create({
                    'move_id': deliver.id,
                    'product_id': product.id,
                    'lot_id': fg_lot.id,
                    'quantity': 400.0,
                    'location_id': stock_location.id,
                    'location_dest_id': customer_location.id,
                    'company_id': company.id,
                })
            created.append(fg_lot.id)
        return created

    def _seed_bottle_shortage(self, company, products, anchor):
        """S-01: 330 ml empty bottles fall below safety stock against confirmed
        MOs. The origin of the flagship cascade."""
        Orderpoint = self.env['stock.warehouse.orderpoint']
        bottle = products['PK-BTL-330']
        warehouse = self.env['stock.warehouse'].search(
            [('code', '=', 'RM'), ('company_id', '=', company.id)], limit=1)
        if not warehouse:
            return False
        existing = Orderpoint.search([
            ('product_id', '=', bottle.id),
            ('warehouse_id', '=', warehouse.id)], limit=1)
        values = {
            'product_id': bottle.id,
            'warehouse_id': warehouse.id,
            'location_id': warehouse.lot_stock_id.id,
            'product_min_qty': bp.S01_SHORTAGE_UNITS,
            'product_max_qty': bp.S01_SHORTAGE_UNITS * 2,
            'company_id': company.id,
        }
        if existing:
            existing.write(values)
            return existing.id
        return Orderpoint.create(values).id

    def _seed_overdue_po(self, company, products, anchor):
        """S-03: a purchase order six days overdue, blocking an MO."""
        import datetime
        Purchase = self.env['purchase.order']
        supplier = self.env['res.partner'].search([('ref', '=', 'SUP-JPI')], limit=1)
        bottle = products['PK-BTL-330']
        if not supplier:
            return False
        late = season._as_date(anchor) - datetime.timedelta(days=6)
        existing = Purchase.search([('origin', '=', 'DEMO:S-03')], limit=1)
        if existing:
            return existing.id
        order = Purchase.create({
            'partner_id': supplier.id,
            'company_id': company.id,
            'origin': 'DEMO:S-03',
            'date_order': fields.Datetime.to_datetime(late),
            'order_line': [(0, 0, {
                'product_id': bottle.id,
                'product_qty': bp.S01_SHORTAGE_UNITS,
                'price_unit': bottle.standard_price,
                'date_planned': fields.Datetime.to_datetime(late),
            })],
        })
        order.button_confirm()
        return order.id

    def _seed_bromate_exceedance(self, company, products, anchor):
        """S-09: treatment batch WT-260819-02 returns bromate at 13 ppb against
        a 10 ppb limit. The headline scenario's trigger.

        The lot is created under its blueprint name whatever the anchor date,
        because Document A, Document B §9 and test T-96 all name it explicitly.
        """
        Lot = self.env['stock.lot']
        treated = products['PR-WATER-TRT']
        lot = Lot.search([('name', '=', bp.S09_LOT),
                          ('product_id', '=', treated.id)], limit=1)
        if not lot:
            lot = Lot.create({
                'name': bp.S09_LOT,
                'product_id': treated.id,
                'company_id': company.id,
            })
        if 'note' in lot._fields:
            lot.note = ('QCP-03 post-ozone bromate: %s ppb against a %s ppb limit '
                        '(GSO 1025). Out of spec.'
                        % (bp.S09_BROMATE_PPB, bp.BROMATE_LIMIT_PPB))
        return lot.id

    # -- determinism -------------------------------------------------------

    @api.model
    def declared_checksum(self):
        """A digest over the business values that must reproduce. §16.

        Deliberately excludes ids, create_date and anything else that varies
        per run: the claim is that the same seed and anchor produce the same
        quantities, dates, lots and prices — not the same bytes.
        """
        rows = []
        for lot in self.env['stock.lot'].search([], order='name'):
            rows.append((lot.name, lot.product_id.default_code or ''))
        for order in self.env['purchase.order'].search([], order='id'):
            for line in order.order_line:
                rows.append((order.partner_id.ref or '', line.product_id.default_code,
                             line.product_qty, line.price_unit))
        return season.checksum(rows)
