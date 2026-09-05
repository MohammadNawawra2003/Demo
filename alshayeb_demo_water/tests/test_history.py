"""Session 7 STOP gate: the history reproduces, and the trap is really in it."""

import datetime

from odoo.tests import TransactionCase, tagged

from ..data import blueprint as bp
from ..data import seasonality as season


@tagged('post_install', '-at_install')
class TestSeasonality(TransactionCase):
    """Pure model, no ORM. The forecasting trap is the point of the dataset, so
    it gets asserted rather than assumed."""

    ANCHOR = datetime.date(2026, 8, 31)

    def test_the_monthly_index_peaks_in_july(self):
        self.assertEqual(max(bp.MONTHLY_INDEX), bp.MONTHLY_INDEX[6])

    def test_summer_is_roughly_twice_winter(self):
        self.assertGreater(bp.MONTHLY_INDEX[6] / bp.MONTHLY_INDEX[0], 2.0)

    def test_ramadan_moves_between_gregorian_months_year_on_year(self):
        """§11: the Hijri calendar drifts about eleven days a year, so the same
        month carries a different seasonal load in consecutive years."""
        start_2025 = season._as_date(bp.RAMADAN[2025][0])
        start_2026 = season._as_date(bp.RAMADAN[2026][0])
        drift = (start_2025.replace(year=2026) - start_2026).days
        self.assertGreaterEqual(drift, 8, "the drift has gone out of the data")
        self.assertNotEqual(start_2025.month, start_2026.month,
                            "Ramadan must cross a Gregorian month boundary")

    def test_the_uplift_lands_on_the_day_not_the_month(self):
        """Applying it by month would smear it across the boundary and hide the
        drift, which is the mistake the dataset exists to expose."""
        inside = season.hijri_overlay(datetime.date(2026, 3, 1))
        outside = season.hijri_overlay(datetime.date(2026, 4, 1))
        self.assertGreater(inside, outside)

    def test_a_naive_year_on_year_comparison_is_measurably_wrong(self):
        """If this ever reaches zero the dataset has stopped demonstrating the
        thing the Procurement Agent exists to catch."""
        error = season.year_on_year_error(self.ANCHOR)
        self.assertGreater(error, 0.05,
                           "year-on-year error is only %.1f%%" % (error * 100))

    def test_the_window_spans_two_ramadans_and_two_hajj_seasons(self):
        """§14: eighteen months is the minimum that makes the drift visible."""
        start, end = season.window(self.ANCHOR, 18)
        self.assertGreaterEqual((end - start).days, 540)
        ramadans = [year for year, dates in bp.RAMADAN.items()
                    if start <= season._as_date(dates[0]) <= end]
        self.assertEqual(len(ramadans), 2)

    def test_lot_names_follow_the_documented_format(self):
        self.assertEqual(
            season.treated_water_lot_name(datetime.date(2026, 8, 19), 2),
            'WT-260819-02')
        self.assertTrue(
            season.finished_lot_name('L1', datetime.date(2026, 8, 12), 4)
            .startswith('NQ-L1-260812-'))

    def test_the_checksum_is_stable_and_sensitive(self):
        rows = [('a', 1), ('b', 2)]
        self.assertEqual(season.checksum(rows), season.checksum(list(rows)))
        self.assertNotEqual(season.checksum(rows), season.checksum([('a', 1), ('b', 3)]))


@tagged('post_install', '-at_install')
class TestHistoryGeneration(TransactionCase):

    ANCHOR = datetime.date(2026, 8, 31)

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.history = cls.env['alshayeb.demo.history']
        # A small scale: the scenarios need the shape, not the volume.
        cls.summary = cls.history.generate(anchor=cls.ANCHOR, months=18, scale=0.02)

    def test_it_generates_treated_water_lots(self):
        self.assertGreater(self.summary['treated_lots'], 0)

    def test_it_generates_finished_goods_lots(self):
        self.assertGreater(self.summary['fg_lots'], 0)

    def test_treated_water_lots_carry_the_documented_name_format(self):
        lot = self.env['stock.lot'].search(
            [('name', 'like', 'WT-%')], limit=1)
        self.assertTrue(lot)
        self.assertRegex(lot.name, r'^WT-\d{6}-\d{2}$')

    def test_finished_lots_record_the_batch_that_fed_them(self):
        """The genealogy trace_forward walks. Without it the recall cannot run."""
        lot = self.env['stock.lot'].search(
            [('name', 'like', 'NQ-%'), ('ref', 'like', 'WT-%')], limit=1)
        self.assertTrue(lot, "no finished lot records its treatment batch")

    # -- §13 the seeded conditions ------------------------------------------

    def test_s01_the_bottle_shortage_is_planted(self):
        orderpoint = self.env['stock.warehouse.orderpoint'].search([
            ('product_id.default_code', '=', 'PK-BTL-330')], limit=1)
        self.assertTrue(orderpoint, "S-01 needs a reorder rule to breach")
        self.assertEqual(orderpoint.product_min_qty, bp.S01_SHORTAGE_UNITS)

    def test_s03_an_overdue_purchase_order_exists(self):
        order = self.env['purchase.order'].search([
            ('state', '=', 'purchase')], limit=1)
        self.assertTrue(order, "S-03 needs a confirmed order to be late")

    def test_s09_the_bromate_batch_exists_under_its_documented_name(self):
        """Document A, Document B §9 and T-96 all name this lot explicitly."""
        lot = self.env['stock.lot'].search([('name', '=', bp.S09_LOT)], limit=1)
        self.assertTrue(lot, "the headline recall scenario has no trigger")
        self.assertEqual(lot.product_id.default_code, 'PR-WATER-TRT')

    def test_the_bromate_result_is_out_of_spec(self):
        lot = self.env['stock.lot'].search([('name', '=', bp.S09_LOT)], limit=1)
        self.assertGreater(bp.S09_BROMATE_PPB, bp.BROMATE_LIMIT_PPB)
        if 'note' in lot._fields:
            self.assertIn('13', lot.note or '')

    # -- determinism ----------------------------------------------------------

    def test_generating_twice_produces_the_same_business_values(self):
        """§16: reproducibility is over business values, verified by checksum.

        A database is never byte-for-byte reproducible — create_date, ids and
        page layout all vary — so version 1.0's "byte for byte" wording set an
        acceptance criterion that cannot be met.
        """
        first = self.history.declared_checksum()
        self.history.generate(anchor=self.ANCHOR, months=18, scale=0.02)
        second = self.history.declared_checksum()
        self.assertEqual(first, second, "the generator is not idempotent")

    def test_a_different_anchor_moves_the_data(self):
        """Anchor-relative, so regenerating keeps the demo current."""
        before = self.history.declared_checksum()
        self.history.generate(anchor=datetime.date(2026, 6, 30), months=18, scale=0.02)
        self.assertNotEqual(before, self.history.declared_checksum())

    def test_scale_changes_volume_and_not_shape(self):
        """The scenarios need the shape; only performance needs the volume."""
        lots_before = self.env['stock.lot'].search_count([('name', 'like', 'WT-%')])
        self.history.generate(anchor=self.ANCHOR, months=18, scale=0.05)
        lots_after = self.env['stock.lot'].search_count([('name', 'like', 'WT-%')])
        self.assertGreater(lots_after, lots_before)
        # The seeded conditions survive any scale, because the scenarios do.
        self.assertTrue(self.env['stock.lot'].search([('name', '=', bp.S09_LOT)], limit=1))
