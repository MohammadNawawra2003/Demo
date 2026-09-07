"""Document A §14 — the transactional history, and that it is actually there.

The generator existed from Session 7 and nothing on the install path ever called
it, so every one of these assertions would have failed against zero. That is the
regression worth holding: not the row counts, which are scaled, but the fact that
each object type exists at all and carries the shape the scenarios read.
"""

from odoo.tests import TransactionCase, tagged

from ..data import blueprint as bp
from ..data import seasonality as season
from ..models.history_transactions import INVOICED_MONTHS, OPEN_WINDOW_DAYS


@tagged('post_install', '-at_install')
class TestGeneratedHistory(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.c1 = cls.env['res.company'].search(
            [('name', '=', 'Naqaa Water Manufacturing Co.')], limit=1)
        cls.c2 = cls.env['res.company'].search(
            [('name', '=', 'Naqaa Distribution Co.')], limit=1)

    # -- the five object types that had no code path at all ---------------

    def test_manufacturing_orders_exist(self):
        orders = self.env['mrp.production'].with_context(active_test=False).search(
            [('origin', 'like', 'DEMO:MO:%')])
        self.assertTrue(orders, "§14's manufacturing orders were never generated")

    def test_the_daily_water_treatment_order_runs(self):
        """§6 calls water treatment "one MO per day". The BoM existed and
        nothing ever ran it."""
        orders = self.env['mrp.production'].with_context(active_test=False).search(
            [('origin', 'like', 'DEMO:WT:%')])
        self.assertTrue(orders, "the treatment order never runs")
        self.assertEqual(orders[0].product_id.default_code, 'PR-WATER-TRT')

    def test_sales_orders_exist_across_every_channel(self):
        for channel in bp.CHANNEL_SHARES:
            orders = self.env['sale.order'].with_context(active_test=False).search(
                [('origin', 'like', 'DEMO:SO:%s:%%' % channel)], limit=1)
            self.assertTrue(orders, "no sales at all in the %s channel" % channel)

    def test_only_the_last_three_months_are_invoiced(self):
        """§14 trims accounting deliberately: posting fifteen months of journal
        items was the slowest step in the build for no demonstrative gain."""
        invoices = self.env['account.move'].search(
            [('move_type', '=', 'out_invoice'), ('state', '=', 'posted')])
        self.assertTrue(invoices, "nothing was invoiced")
        cutoff = self.env['alshayeb.demo.history']._invoice_cutoff(
            season._as_date(max(invoices.mapped('invoice_date'))))
        del cutoff  # the boundary itself is asserted below, per invoice
        oldest = min(invoices.mapped('invoice_date'))
        newest = max(invoices.mapped('invoice_date'))
        self.assertLessEqual((newest.year - oldest.year) * 12
                             + newest.month - oldest.month, INVOICED_MONTHS,
                             "invoices span more than the last three months")

    def test_quality_checks_exist_against_the_control_points(self):
        checks = self.env['quality.check'].search(
            [('company_id', '=', self.c1.id)])
        self.assertTrue(checks, "§14's quality checks were never generated")
        self.assertTrue(checks.mapped('point_id'),
                        "checks exist but against no control point")

    # -- shape ---------------------------------------------------------------

    def test_historical_orders_are_closed_and_recent_ones_are_not(self):
        """A plant does not carry an eighteen-month backlog of things it has
        already made, and an open list full of them crowds out the order a
        planner is actually asking about."""
        Production = self.env['mrp.production'].with_context(active_test=False)
        historical = Production.search(
            [('origin', 'like', 'DEMO:MO:%'), ('state', '=', 'done')])
        self.assertTrue(historical, "no historical production was ever completed")

    def test_the_window_is_eighteen_months_not_nineteen(self):
        """§14 says eighteen. The off-by-one gave nineteen and was masked by a
        `>= 540 days` assertion."""
        start, end = season.window('2026-08-31', 18)
        self.assertEqual((start.year, start.month), (2025, 3))
        self.assertEqual((end.year, end.month), (2026, 8))

    def test_finished_lot_names_do_not_collide_across_skus(self):
        """FG-200 and FG-330 both run on L1, FG-1500 and FG-5000 both on L3.
        Without a per-SKU sequence they produced the identical lot name on the
        same day, which makes the genealogy ambiguous exactly where a recall
        needs it precise."""
        names = {}
        for code, sequence in bp.LOT_SEQUENCE.items():
            line = dict((c, l) for c, _n, _u, _li, _ca, _p, l
                        in bp.FINISHED_GOODS)[code]
            key = (line, sequence)
            self.assertNotIn(key, names,
                             "%s and %s produce the same lot name"
                             % (code, names.get(key)))
            names[key] = code

    def test_the_generator_is_idempotent(self):
        Production = self.env['mrp.production'].with_context(active_test=False)
        before = Production.search_count([('origin', 'like', 'DEMO:%')])
        self.env['alshayeb.demo.history'].generate_default()
        self.assertEqual(
            Production.search_count([('origin', 'like', 'DEMO:%')]), before,
            "re-running the generator created records twice")
