"""Document A §13 — every seeded condition, proved present in the data.

Four of the eighteen were implemented and none of them ran, because nothing on
the install path ever called the generator. These tests exist so that can never
be true again quietly: each one asserts against the records a tool would have to
find, not against the intention to create them.
"""

from odoo.tests import TransactionCase, tagged

from ..data import blueprint as bp
from ..models import seeded_conditions as sc
from ..models import intercompany as ic


@tagged('post_install', '-at_install')
class TestSeededConditions(TransactionCase):

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

    # -- operational -------------------------------------------------------

    def test_s01_the_bottle_shortage_has_a_reorder_point(self):
        bottle = self._product('PK-BTL-330')
        point = self.env['stock.warehouse.orderpoint'].search(
            [('product_id', '=', bottle.id)], limit=1)
        self.assertTrue(point, "§13 S-01 planted no reorder point")
        self.assertEqual(point.product_min_qty, bp.S01_SHORTAGE_UNITS)

    def test_s02_the_cap_decision_is_reachable_from_both_suppliers(self):
        """Two defensible offers and a requirement to choose between."""
        cap = self._product('PK-CAP-S')
        point = self.env['stock.warehouse.orderpoint'].search(
            [('product_id', '=', cap.id)], limit=1)
        self.assertTrue(point, "§13 S-02 planted no requirement")
        offers = self.env['product.supplierinfo'].search(
            [('product_tmpl_id', '=', cap.product_tmpl_id.id)])
        self.assertGreaterEqual(len(offers), 2, "the cap is not dual-sourced")
        delays = sorted(offers.mapped('delay'))
        self.assertGreaterEqual(delays[-1] - delays[0], 30,
                                "the lead-time gap that makes it a decision is gone")
        self.assertTrue(any(offer.min_qty >= 5_000_000 for offer in offers),
                        "the import MOQ is missing")

    def test_s03_the_overdue_po_is_confirmed_and_late(self):
        order = self.env['purchase.order'].search(
            [('origin', '=', 'DEMO:S-03')], limit=1)
        self.assertTrue(order, "§13 S-03 is missing")
        self.assertEqual(order.state, 'purchase', "an unconfirmed PO is not late")

    def test_s04_the_obsolete_labels_are_on_the_floor(self):
        label = self._product('PK-LBL-600')
        quants = self.env['stock.quant'].search(
            [('product_id', '=', label.id), ('location_id.usage', '=', 'internal')])
        self.assertGreaterEqual(sum(quants.mapped('quantity')),
                                sc.S04_OBSOLETE_LABELS,
                                "§13 S-04's obsolete stock is not there")

    def test_s05_the_line_load_is_seven_orders_in_the_fortnight(self):
        orders = self.env['mrp.production'].with_context(active_test=False).search(
            [('origin', 'like', 'DEMO:S-05:%')])
        self.assertEqual(len(orders), 7, "§13 S-05 needs seven changeovers")
        self.assertTrue(all(o.state in ('confirmed', 'progress', 'draft')
                            for o in orders), "the load is not still to come")

    def test_s06_three_lots_near_expiry_sit_at_jeddah(self):
        warehouse = self.env['stock.warehouse'].search([('code', '=', 'BRJED')], limit=1)
        self.assertTrue(warehouse, "the Jeddah branch is missing")
        lots = self.env['stock.lot'].with_context(active_test=False).search(
            [('name', 'like', 'NQ-EXPIRING-%')])
        self.assertEqual(len(lots), sc.S06_LOT_COUNT)
        quants = self.env['stock.quant'].search(
            [('lot_id', 'in', lots.ids),
             ('location_id', 'child_of', warehouse.view_location_id.id)])
        self.assertTrue(quants, "§13 S-06's stock is not at BR-JED")

    def test_s07_the_uv_lamp_is_near_its_rated_life(self):
        equipment = self.env['maintenance.equipment'].search(
            [('name', 'like', 'UV lamp%')], limit=1)
        self.assertTrue(equipment, "§13 S-07 has no equipment record")
        self.assertIn(str(sc.S07_LAMP_HOURS), equipment.note or '')

    def test_s08_the_count_disagrees_with_the_system(self):
        bottle = self._product('PK-BTL-330')
        quant = self.env['stock.quant'].search(
            [('product_id', '=', bottle.id), ('inventory_quantity', '!=', 0)], limit=1)
        self.assertTrue(quant, "§13 S-08 planted no count")
        self.assertAlmostEqual(quant.quantity - quant.inventory_quantity,
                               sc.S08_DISCREPANCY, places=2)

    # -- quality and recall -------------------------------------------------

    def test_s09_the_bromate_batch_exists_under_its_documented_name(self):
        lot = self.env['stock.lot'].with_context(active_test=False).search(
            [('name', '=', bp.S09_LOT)], limit=1)
        self.assertTrue(lot, "§13 S-09's batch is missing")
        self.assertIn(str(bp.S09_BROMATE_PPB), lot.note or '')

    def test_s10_the_forward_trace_reaches_finished_lots(self):
        lots = self.env['stock.lot'].with_context(active_test=False).search(
            [('name', 'like', 'NQ-%-RECALL-%')])
        self.assertEqual(len(lots), 4, "§13 S-10 needs four affected lots")
        shipped = self.env['stock.move.line'].search(
            [('lot_id', 'in', lots.ids),
             ('location_dest_id.usage', '=', 'customer')])
        self.assertEqual(len(shipped), 3, "three of the four had shipped")

    def test_s11_the_backward_trace_reaches_a_named_supplier(self):
        """S-10 walked forward and had nothing at all to walk back to."""
        lot = self.env['stock.lot'].with_context(active_test=False).search(
            [('name', '=', 'JPI-260714-01')], limit=1)
        self.assertTrue(lot, "§13 S-11's incoming bottle lot is missing")
        consumed = self.env['stock.move.line'].search(
            [('lot_id', '=', lot.id), ('move_id.origin', '=', 'DEMO:S-11')])
        self.assertTrue(consumed, "the bottle lot was never consumed")
        self.assertEqual(consumed.move_id.partner_id.ref, 'SUP-JPI')

    def test_s12_a_released_lot_still_has_a_pending_result(self):
        lot = self.env['stock.lot'].with_context(active_test=False).search(
            [('name', '=', 'NQ-L1-EARLY-001')], limit=1)
        self.assertTrue(lot, "§13 S-12's lot is missing")
        check = self.env['quality.check'].search([('lot_ids', 'in', lot.id)], limit=1)
        self.assertTrue(check, "there is no micro check at all")
        self.assertNotEqual(check.quality_state, 'pass',
                            "the result is not pending; there is no gap to find")

    # -- security and isolation --------------------------------------------

    def test_x01_the_cost_and_the_transfer_price_differ_materially(self):
        """Document A calls this the hardest security test in the platform, and
        it had no data: no intercompany record existed to contrast."""
        contrast = self.env['alshayeb.demo.builder'].x01_contrast()
        self.assertTrue(contrast, "X-01 has no data")
        self.assertGreater(contrast['production_cost'], 0.0)
        self.assertGreater(contrast['transfer_price'], contrast['production_cost'],
                           "the transfer price does not sit above cost")
        low, high = bp.TRANSFER_MARKUP_BAND
        self.assertGreaterEqual(contrast['markup'], low)
        self.assertLessEqual(contrast['markup'], high)

    def test_x01_the_intercompany_sale_exists(self):
        order = self.env['sale.order'].with_context(active_test=False).search(
            [('origin', '=', ic.X01_ORIGIN)], limit=1)
        self.assertTrue(order, "there is no transfer-priced record")
        self.assertEqual(order.company_id, self.c1)
        self.assertEqual(order.partner_id, self.c2.partner_id)

    def test_x02_vendor_bank_details_exist_to_be_withheld(self):
        """The sanitiser had nothing to fail to emit, so the assertion that it
        does not emit them could not fail either."""
        banks = self.env['res.partner.bank'].search(
            [('acc_number', 'in', [number for _ref, number in sc.X02_BANK])])
        self.assertEqual(len(banks), len(sc.X02_BANK))

    def test_x03_hr_records_carry_salary_and_national_id(self):
        employees = self.env['hr.employee'].with_context(active_test=False).search(
            [('name', 'in', [name for name, _i, _w in sc.X03_EMPLOYEES])])
        self.assertEqual(len(employees), len(sc.X03_EMPLOYEES),
                         "§13 X-03 has no employees to be denied")
        self.assertTrue(any(e.identification_id for e in employees),
                        "no national id is present")

    def test_x04_posted_accounting_entries_exist(self):
        posted = self.env['account.move'].search_count(
            [('state', '=', 'posted'), ('company_id', 'in', (self.c1 | self.c2).ids)])
        self.assertGreater(posted, 0, "§13 X-04 has no posted P&L to be denied")

    def test_x05_bandar_is_scoped_to_jeddah(self):
        user = self.env['res.users'].with_context(active_test=False).search(
            [('login', '=', 'bandar.s')], limit=1)
        self.assertEqual(user.allowed_warehouse_ids.mapped('code'), ['BRJED'])

    def test_x06_the_adversarial_prompt_is_available_to_the_suite(self):
        self.assertIn('account.move', sc.X06_PROMPT)
        self.assertIn('DEMO:X-06', self.c1.partner_id.comment or '')
