from odoo import Command
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestWarehouseScope(TransactionCase):
    """Warehouse scoping is ordinary Odoo authorisation.

    It matters to the AI platform only because it makes ``USER ∩ AGENT`` honest:
    a branch manager asking the Inventory Agent about another branch's stock
    fails on the **user** side of the intersection, not on a condition invented
    for an AI test.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env['res.company'].create({'name': 'Naqaa Test'})
        cls.wh_jeddah = cls.env['stock.warehouse'].create({
            'name': 'Jeddah Branch', 'code': 'BRJED', 'company_id': cls.company.id})
        cls.wh_abha = cls.env['stock.warehouse'].create({
            'name': 'Abha Branch', 'code': 'BRABH', 'company_id': cls.company.id})

        cls.product = cls.env['product.product'].create({
            'name': 'Naqaa 330ml', 'is_storable': True})

        cls.scoped_user = cls.env['res.users'].create({
            'name': 'Bandar (Jeddah only)', 'login': 'ssw.bandar',
            'company_id': cls.company.id,
            'company_ids': [Command.set([cls.company.id])],
            'group_ids': [
                Command.link(cls.env.ref('stock.group_stock_user').id),
                Command.link(cls.env.ref(
                    'stock_security_warehouse.group_stock_warehouse_scoped').id)],
            'allowed_warehouse_ids': [Command.set([cls.wh_jeddah.id])],
        })
        cls.unscoped_user = cls.env['res.users'].create({
            'name': 'Salem (all warehouses)', 'login': 'ssw.salem',
            'company_id': cls.company.id,
            'company_ids': [Command.set([cls.company.id])],
            'group_ids': [Command.link(cls.env.ref('stock.group_stock_manager').id)],
        })

        cls.quant_jeddah = cls.env['stock.quant'].create({
            'product_id': cls.product.id,
            'location_id': cls.wh_jeddah.lot_stock_id.id, 'quantity': 100})
        cls.quant_abha = cls.env['stock.quant'].create({
            'product_id': cls.product.id,
            'location_id': cls.wh_abha.lot_stock_id.id, 'quantity': 50})

    # -- the scoping itself -------------------------------------------------

    def test_a_scoped_user_sees_only_their_warehouse(self):
        visible = self.env['stock.quant'].with_user(self.scoped_user).search([
            ('product_id', '=', self.product.id)])
        self.assertIn(self.quant_jeddah, visible)
        self.assertNotIn(self.quant_abha, visible)

    def test_an_unscoped_user_sees_everything(self):
        """The rules are group rules: a user outside the group is untouched."""
        visible = self.env['stock.quant'].with_user(self.unscoped_user).search([
            ('product_id', '=', self.product.id)])
        self.assertIn(self.quant_jeddah, visible)
        self.assertIn(self.quant_abha, visible)

    def test_locations_outside_the_scope_are_hidden(self):
        visible = self.env['stock.location'].with_user(self.scoped_user).search([])
        self.assertIn(self.wh_jeddah.lot_stock_id, visible)
        self.assertNotIn(self.wh_abha.lot_stock_id, visible)

    def test_virtual_locations_stay_visible(self):
        """Hiding them would break receipts, deliveries, scrap and adjustments."""
        supplier_location = self.env.ref('stock.stock_location_suppliers')
        visible = self.env['stock.location'].with_user(self.scoped_user).search([
            ('id', '=', supplier_location.id)])
        self.assertTrue(visible, "virtual locations carry no warehouse")

    def test_transfers_are_scoped_by_their_operation_type(self):
        picking = self.env['stock.picking'].create({
            'picking_type_id': self.wh_abha.out_type_id.id,
            'location_id': self.wh_abha.lot_stock_id.id,
            'location_dest_id': self.env.ref('stock.stock_location_customers').id,
        })
        visible = self.env['stock.picking'].with_user(self.scoped_user).search([
            ('id', '=', picking.id)])
        self.assertFalse(visible)

    def test_an_empty_allow_list_denies_rather_than_permits(self):
        """Fail closed: no warehouses configured means no stock, not all stock."""
        self.scoped_user.allowed_warehouse_ids = [Command.clear()]
        visible = self.env['stock.quant'].with_user(self.scoped_user).search([
            ('product_id', '=', self.product.id)])
        self.assertFalse(visible)

    # -- the trap from Document A §12 ---------------------------------------

    def test_lots_are_deliberately_not_scoped(self):
        """stock.lot.location_id is False whenever a lot spans more than one
        location, so a rule keyed on it would hide exactly the lots a recall is
        about -- and break quality.trace_forward."""
        rules = self.env['ir.rule'].search([('model_id.model', '=', 'stock.lot')])
        ours = rules.filtered(
            lambda r: r.id in self.env['ir.model.data'].search([
                ('module', '=', 'stock_security_warehouse'),
                ('model', '=', 'ir.rule')]).mapped('res_id'))
        self.assertFalse(ours, "this addon must never scope stock.lot")

    def test_a_lot_spanning_two_warehouses_still_resolves(self):
        lot_product = self.env['product.product'].create({
            'name': 'Tracked Water', 'is_storable': True, 'tracking': 'lot'})
        lot = self.env['stock.lot'].create({
            'name': 'WT-260819-02', 'product_id': lot_product.id})
        for warehouse in (self.wh_jeddah, self.wh_abha):
            self.env['stock.quant'].create({
                'product_id': lot_product.id, 'lot_id': lot.id,
                'location_id': warehouse.lot_stock_id.id, 'quantity': 10})
        self.assertFalse(
            lot.location_id,
            "premise: a multi-location lot has no single location_id")
        self.assertTrue(
            self.env['stock.lot'].with_user(self.scoped_user).search(
                [('id', '=', lot.id)]),
            "the recall target must remain visible to a scoped user")

    def test_the_scoped_user_still_sees_only_their_own_quantity_of_that_lot(self):
        lot_product = self.env['product.product'].create({
            'name': 'Tracked Water 2', 'is_storable': True, 'tracking': 'lot'})
        lot = self.env['stock.lot'].create({
            'name': 'WT-260819-03', 'product_id': lot_product.id})
        for warehouse, qty in ((self.wh_jeddah, 10), (self.wh_abha, 90)):
            self.env['stock.quant'].create({
                'product_id': lot_product.id, 'lot_id': lot.id,
                'location_id': warehouse.lot_stock_id.id, 'quantity': qty})
        quants = self.env['stock.quant'].with_user(self.scoped_user).search([
            ('lot_id', '=', lot.id)])
        self.assertEqual(sum(quants.mapped('quantity')), 10)

    def test_this_addon_knows_nothing_about_ai(self):
        """It ships alongside the platform and depends on neither direction."""
        manifest = self.env['ir.module.module'].search([
            ('name', '=', 'stock_security_warehouse')], limit=1)
        self.assertTrue(manifest)
        self.assertNotIn(
            'ai_operations',
            manifest.dependencies_id.mapped('name'),
            "warehouse scoping is Odoo authorisation, not an AI concern")
