import json

from odoo import api, fields, models
from odoo.exceptions import ValidationError

from ..services.enums import DenialReason, HandoffState, to_selection
from ..services.exceptions import AIAccessDenied


class AIOperationsHandoffType(models.Model):
    """Document C 5.7. The payload schema is developer-defined and readonly."""

    _name = 'ai.operations.handoff.type'
    _description = 'AI Operations Handoff Type'
    _order = 'code'

    code = fields.Char(required=True, index=True)
    name = fields.Char(required=True)
    from_profile_ids = fields.Many2many(
        'ai.operations.agent.profile', 'ai_handoff_type_from_rel',
        'type_id', 'profile_id', string='May Be Raised By')
    to_profile_id = fields.Many2one(
        'ai.operations.agent.profile', string='Received By')
    payload_schema = fields.Text(
        required=True,
        help="The declared field set, as JSON. Developer-defined: an "
             "administrator who could widen it could widen what crosses "
             "between two agents.")
    priority_default = fields.Selection(
        [('0', 'Low'), ('1', 'Normal'), ('2', 'High'), ('3', 'Urgent')],
        default='1')
    active = fields.Boolean(default=True)

    _code_uniq = models.Constraint('unique(code)', 'Handoff type codes are unique.')

    def declared_fields(self):
        self.ensure_one()
        try:
            return set(json.loads(self.payload_schema or '{}'))
        except ValueError as error:
            raise ValidationError(
                "Handoff type %s has an unreadable payload schema." % self.code
            ) from error


class AIOperationsHandoff(models.Model):
    """Document C 5.8.

    Agents never call each other. They post a schema-controlled business message
    to a queue, and the receiving agent gains **no access it did not already
    hold**: the handoff says what to work on, never what may be seen.

    What never crosses: conversation history, source record dumps, attachments,
    unlisted fields, the originating agent's tool outputs.
    """

    _name = 'ai.operations.handoff'
    _description = 'AI Operations Handoff'
    _order = 'id desc'

    name = fields.Char(required=True, copy=False, default='New')
    type_id = fields.Many2one('ai.operations.handoff.type', required=True,
                              ondelete='restrict')
    from_profile_id = fields.Many2one('ai.operations.agent.profile',
                                      ondelete='set null')
    to_profile_id = fields.Many2one('ai.operations.agent.profile', required=True,
                                    index=True, ondelete='restrict')
    payload = fields.Json()

    # Reference only, never dereferenced by the receiver. If Procurement cannot
    # read mrp.production, a handoff naming MO-00842 does not let it.
    source_model = fields.Char()
    source_res_id = fields.Integer()
    result_model = fields.Char()
    result_res_id = fields.Integer()

    priority = fields.Selection(
        [('0', 'Low'), ('1', 'Normal'), ('2', 'High'), ('3', 'Urgent')],
        default='1')
    required_date = fields.Date()
    state = fields.Selection(to_selection(HandoffState), required=True,
                             default=HandoffState.DRAFT.value, index=True)
    correlation_id = fields.Char(index=True)
    idempotency_key = fields.Char(index=True)
    company_id = fields.Many2one('res.company', ondelete='set null')

    #: Review finding B1. Uniqueness is scoped to the RECEIVER, not the type.
    #:
    #: Manufacturing and Inventory can both detect the same shortage on the same
    #: morning, and they raise different types (MATERIAL_SHORTAGE and
    #: REPLENISHMENT_REQUEST). A constraint scoped to type_id would let both
    #: through and Procurement would work one shortage twice -- which is exactly
    #: what Document B §11 row 13 claims cannot happen and what T-57 tests.
    _receiver_key_uniq = models.Constraint(
        'unique(to_profile_id, idempotency_key)',
        'This work is already on that agent queue.',
    )

    @api.model_create_multi
    def create(self, vals_list):
        for values in vals_list:
            if values.get('name', 'New') == 'New':
                values['name'] = self.env['ir.sequence'].next_by_code(
                    'ai.operations.handoff') or 'AIH/NEW'
        records = super().create(vals_list)
        records._validate_payload()
        return records

    def write(self, vals):
        result = super().write(vals)
        if 'payload' in vals or 'type_id' in vals:
            self._validate_payload()
        return result

    def _validate_payload(self):
        """Rejection, never filtering.

        Filtering would silently normalise an attempted leak into a success, so
        a field outside the declared schema fails the write and raises a
        security event instead.
        """
        for handoff in self:
            declared = handoff.type_id.declared_fields()
            supplied = set(handoff.payload or {})
            undeclared = supplied - declared
            if undeclared:
                raise AIAccessDenied(
                    DenialReason.HANDOFF_SCHEMA_VIOLATION,
                    detail='undeclared field(s) %s on %s'
                           % (', '.join(sorted(undeclared)), handoff.type_id.code),
                    model='ai.operations.handoff')
            missing = declared - supplied
            if missing:
                raise AIAccessDenied(
                    DenialReason.HANDOFF_SCHEMA_VIOLATION,
                    detail='missing declared field(s) %s' % ', '.join(sorted(missing)),
                    model='ai.operations.handoff')

    @api.constrains('type_id', 'from_profile_id', 'to_profile_id')
    def _check_pairing(self):
        for handoff in self:
            handoff_type = handoff.type_id
            if handoff_type.to_profile_id and \
                    handoff.to_profile_id != handoff_type.to_profile_id:
                raise ValidationError(
                    "%s is received by %s, not %s."
                    % (handoff_type.code, handoff_type.to_profile_id.code,
                       handoff.to_profile_id.code))
            if handoff_type.from_profile_ids and handoff.from_profile_id and \
                    handoff.from_profile_id not in handoff_type.from_profile_ids:
                raise ValidationError(
                    "%s may not be raised by %s."
                    % (handoff_type.code, handoff.from_profile_id.code))
