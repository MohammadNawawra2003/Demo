from odoo import api, fields, models
from odoo.exceptions import AccessError, ValidationError

from ..services.enums import DenialReason
from ..services.exceptions import AIAccessDenied
from ..services.registry import get_tool, has_tool


class AIOperationsTool(models.Model):
    """The Odoo-side configuration record. The executable code lives in Python.

    Document C 5.5. Admins may configure a tool. They may never author one:
    everything that decides what the tool *does* is computed from the
    ``@ai_tool`` decorator and readonly here, and a record whose code has no
    registry entry cannot be enabled at all.

    There are no server actions. The LLM's tool calls arrive as JSON in our own
    loop and dispatch straight into the registry, so there is no editable Python
    body and no admin-editable parameter schema that could drift from the one
    the validator enforces.
    """

    _name = 'ai.operations.tool'
    _description = 'AI Operations Tool'
    _order = 'code'

    name = fields.Char(required=True)
    code = fields.Char(
        required=True, index=True,
        help="Must match an @ai_tool registration in Python.")

    registered = fields.Boolean(
        compute='_compute_from_registry',
        help="Whether this code has a Python registry entry.")
    description = fields.Text(
        compute='_compute_from_registry',
        help="Sent to the LLM as the tool description. Comes from the Python "
             "docstring, so it cannot drift from the code it describes.")
    category = fields.Char(compute='_compute_from_registry')
    autonomy_required = fields.Integer(compute='_compute_from_registry')
    models_used = fields.Many2many(
        'ir.model', compute='_compute_from_registry',
        help="Computed from the decorator. The guard checks every one of these.")
    models_used_names = fields.Char(
        compute='_compute_from_registry',
        help="The declared model names, readable without ir.model access.")
    actions_used = fields.Char(compute='_compute_from_registry')
    idempotent = fields.Boolean(compute='_compute_from_registry')

    max_results = fields.Integer(default=200)
    timeout_seconds = fields.Integer()
    enabled = fields.Boolean(
        default=False,
        help="No tool is available until a Technical Administrator enables it.")
    version = fields.Char()

    assignment_ids = fields.One2many(
        'ai.operations.tool.assignment', 'tool_id', string='Assignments')

    _code_uniq = models.Constraint(
        'unique(code)',
        'A tool with this code already exists.',
    )

    @api.depends('code')
    def _compute_from_registry(self):
        IrModel = self.env['ir.model']
        for tool in self:
            spec = None
            if tool.code and has_tool(tool.code):
                spec = get_tool(tool.code)

            tool.registered = bool(spec)
            tool.description = spec.description if spec else False
            tool.category = spec.category if spec else False
            tool.autonomy_required = spec.autonomy if spec else 0
            tool.idempotent = spec.idempotent if spec else False
            tool.actions_used = ', '.join(
                '%s:%s' % (model, action) for model, action in spec.actions
            ) if spec else False

            # ir.model grants base.group_user 0,0,0,0 in Odoo 19 -- no read at
            # all. An ordinary agent user may read this record, so resolving the
            # names to ir.model must degrade rather than raise. The declared
            # names remain visible in models_used_names either way; the guard
            # never reads this field.
            if spec:
                try:
                    tool.models_used = IrModel.search(
                        [('model', 'in', list(spec.models))])
                except AccessError:
                    tool.models_used = IrModel.browse()
            else:
                tool.models_used = IrModel.browse()
            tool.models_used_names = ', '.join(spec.models) if spec else False

    @api.constrains('enabled', 'code')
    def _check_enabled_tool_is_registered(self):
        for tool in self:
            if tool.enabled and not has_tool(tool.code):
                raise ValidationError(
                    "Tool %r cannot be enabled: it has no @ai_tool registration in "
                    "Python. A tool record without executable code behind it is a "
                    "configuration surface with nothing under it." % tool.code
                )

    # ------------------------------------------------------------------
    # Guard support. Each check is independent so the security service can
    # sequence them with its own steps in between, and so each one is
    # testable against its own matrix id.
    # ------------------------------------------------------------------

    @api.model
    def registry_spec(self, tool_code):
        """Guard step 1. Raises AIAccessDenied(UNKNOWN_TOOL)."""
        return get_tool(tool_code)

    @api.model
    def record_for(self, tool_code):
        """Guard step 2. Raises AIAccessDenied(TOOL_DISABLED)."""
        record = self.search([('code', '=', tool_code)], limit=1)
        if not record or not record.enabled:
            raise AIAccessDenied(
                DenialReason.TOOL_DISABLED,
                detail='no enabled tool record for %r' % tool_code,
                tool_code=tool_code,
            )
        return record

    def assignment_for(self, profile):
        """Guard step 4. Raises AIAccessDenied(TOOL_NOT_ASSIGNED).

        No assignment means no access. There is no default grant.
        """
        self.ensure_one()
        assignment = self.env['ai.operations.tool.assignment'].search([
            ('profile_id', '=', profile.id),
            ('tool_id', '=', self.id),
        ], limit=1)
        if not assignment or not assignment.enabled:
            raise AIAccessDenied(
                DenialReason.TOOL_NOT_ASSIGNED,
                detail='%r is not assigned to profile %r' % (self.code, profile.code),
                tool_code=self.code,
            )
        return assignment
