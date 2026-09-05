from odoo import api, fields, models

from ..services.enums import DataClassification, to_selection
from ..services.validators import validate_domain, validate_state_restriction


class AIOperationsModelPermission(models.Model):
    """What an agent may touch, and how -- Document C 5.2.

    Allowlist, absolutely. ``ir.model.access`` is already deny-by-default, so
    this layers an allowlist onto a deny baseline. A denylist would break
    silently the day a module is installed.
    """

    _name = 'ai.operations.model.permission'
    _description = 'AI Operations Model Permission'
    _order = 'profile_id, id'

    profile_id = fields.Many2one(
        'ai.operations.agent.profile', required=True, ondelete='cascade', index=True)
    model_id = fields.Many2one('ir.model', required=True, ondelete='cascade')
    model_name = fields.Char(related='model_id.model', store=True, string='Model Name')

    perm_read = fields.Boolean(default=False)
    perm_create = fields.Boolean(default=False)
    perm_write = fields.Boolean(default=False)
    perm_unlink = fields.Boolean(default=False)

    domain = fields.Char(
        help="Agent record domain. Literal only -- parsed with ast.literal_eval, "
             "never eval. Combined with Odoo's record rules using AND.",
    )
    state_restriction = fields.Char(
        help="Written 'field=value', e.g. 'state=draft' or 'stage_id.name=New'. "
             "A bare value is invalid: these models do not agree on a field name.",
    )

    max_records = fields.Integer(default=200, help="Caps mass extraction.")
    allow_read_group = fields.Boolean(default=False)

    data_classification = fields.Selection(
        to_selection(DataClassification),
        help="Stored, unenforced in Phase 1.",
    )
    active = fields.Boolean(default=True)

    _model_permission_uniq = models.Constraint(
        'unique(profile_id, model_id)',
        'One permission record per model per profile.',
    )

    @api.constrains('domain')
    def _check_domain(self):
        for permission in self:
            validate_domain(permission.domain)

    @api.constrains('state_restriction')
    def _check_state_restriction(self):
        for permission in self:
            validate_state_restriction(permission.state_restriction)
