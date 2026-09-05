import logging

from odoo import api, fields, models
from odoo.exceptions import ValidationError

from ..services.enums import DenialReason
from ..services.exceptions import AIAccessDenied
from ..services.registry import all_tools, get_tool, has_tool

_logger = logging.getLogger(__name__)


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
    # No Many2many to ir.model, deliberately. ir.model grants base.group_user
    # 0,0,0,0 in Odoo 19 -- it is administrator-only metadata -- so a relation
    # to it makes this record unreadable by the very roles meant to configure
    # it, and the AI administrators are deliberately NOT Odoo administrators.
    # The declared names are the whole point of the field, and a Char carries
    # them with no privilege at all. The guard never used the relation: it
    # checks spec.models from the registry and the stored model_name on the
    # permission records.
    models_used_names = fields.Char(
        string='Models Used', compute='_compute_from_registry',
        help="The models this tool declares, from the decorator.")
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
    # Materialisation: the registry is the source of truth, these records
    # are its mirror.
    # ------------------------------------------------------------------

    def _register_hook(self):
        super()._register_hook()
        self._sync_from_registry()

    @api.model
    def _sync_from_registry(self):
        """Create a configuration record for every registered tool.

        Every field describing what a tool *does* is computed from the decorator
        and readonly, under Document C 5.5's rule that admins configure tools and
        never author them. An administrator who first has to hand-create the
        record is authoring it, and an XML record per tool would duplicate the
        registry in a second place -- exactly the drift this design rejects when
        it refuses the native app's editable ai_tool_schema.

        **Records are created DISABLED.** Registration makes a tool
        configurable, never available: enabling stays a Technical
        Administrator's deliberate act, and it still needs an assignment before
        any agent can call it. So this materialises configuration surface, not
        capability.

        Runs at ``loading.py`` STEP 9, once per registry load, after every module
        has imported -- so tool packs registering after the kernel are picked up
        without a migration per session.

        A tool removed from the code keeps its record, flagged ``registered =
        False`` and unable to be enabled (T-04). Deleting it would silently drop
        its assignments; leaving it makes the orphan visible.
        """
        codes = set(all_tools())
        if not codes:
            return
        existing = set(
            self.with_context(active_test=False).search([]).mapped('code'))
        missing = sorted(codes - existing)
        if not missing:
            return
        try:
            # Two workers can load a registry at once; the unique(code)
            # constraint decides, and the loser must not poison the cursor.
            with self.env.cr.savepoint():
                self.create([
                    {'code': code, 'name': self._default_tool_name(code),
                     'enabled': False}
                    for code in missing
                ])
            _logger.info("ai_operations: materialised %d tool(s): %s",
                         len(missing), ', '.join(missing))
        except Exception:                     # noqa: BLE001 - see docstring
            _logger.info(
                "ai_operations: tool materialisation skipped, another process "
                "got there first")

    @api.model
    def _default_tool_name(self, code):
        """'procurement.prepare_draft_rfq' -> 'Prepare Draft Rfq'."""
        return code.split('.')[-1].replace('_', ' ').title()

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
