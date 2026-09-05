from odoo import fields, models


class ResUsers(models.Model):
    """Warehouse-level scoping for a user.

    Every stock record rule Odoo 19 ships -- ``stock_quant_rule``,
    ``stock_move_rule``, ``stock_picking_rule``, ``stock_move_line_rule`` -- is
    **company**-scoped. There is no native warehouse scoping, and it is a
    requirement at nearly every client, so it lives in its own addon rather than
    buried in demo fixtures or bolted onto an AI security kernel.
    """

    _inherit = 'res.users'

    allowed_warehouse_ids = fields.Many2many(
        'stock.warehouse', 'res_users_stock_warehouse_rel', 'user_id', 'warehouse_id',
        string='Allowed Warehouses',
        help="Only meaningful for users in the Warehouse-Scoped group. Empty "
             "means the scoping denies everything, which is the fail-closed "
             "direction.")
