from odoo import api, fields, models

from ..services.enums import AutonomyLevel, RiskLevel, to_selection
from ..services.validators import validate_state_restriction


class AIOperationsActionPermission(models.Model):
    """Business actions, separately from CRUD -- Document C 5.3.

    CRUD is insufficient: the real risk lives in business methods. An agent
    that may write a draft purchase order must still be unable to confirm it.
    """

    _name = 'ai.operations.action.permission'
    _description = 'AI Operations Action Permission'
    _order = 'profile_id, id'

    profile_id = fields.Many2one(
        'ai.operations.agent.profile', required=True, ondelete='cascade', index=True)
    model_id = fields.Many2one('ir.model', required=True, ondelete='cascade')
    model_name = fields.Char(related='model_id.model', store=True, string='Model Name')

    action_code = fields.Char(help="e.g. CREATE_DRAFT, UPDATE_DRAFT, CONFIRM.")
    method_name = fields.Char(
        help="Developer-registered only. A write with an unregistered method "
             "name is rejected. Never LLM-supplied.",
    )
    allowed = fields.Boolean(default=False)

    autonomy_required = fields.Selection(
        to_selection(AutonomyLevel),
        default=str(AutonomyLevel.QUERY.value),
        help="Floor. Compared against the profile's ceiling.",
    )
    state_restriction = fields.Char(
        help="Written 'field=value', as on the model permission.",
    )

    max_amount = fields.Float(
        help="Currency is taken from the record under evaluation.",
    )
    max_quantity = fields.Float()

    variance_bound_pct = fields.Float(
        default=20.0,
        help="Routine bound. A breach ESCALATES -- the draft is created and "
             "stamped for manager approval. It never denies.",
    )
    variance_ceiling_pct = fields.Float(
        default=100.0,
        help="Hard ceiling. A breach DENIES with BOUND_EXCEEDED and writes nothing.",
    )

    product_category_ref = fields.Char(
        help="XML id or category code, resolved by the tool pack. A Char rather "
             "than a Many2one because 'product' is not a kernel dependency.",
    )
    risk_level = fields.Selection(to_selection(RiskLevel))

    @api.constrains('state_restriction')
    def _check_state_restriction(self):
        for permission in self:
            validate_state_restriction(permission.state_restriction)
