from odoo import api, fields, models
from odoo.exceptions import ValidationError

from ..services.enums import (
    PHASE1_MAX_AUTONOMY,
    AuditLevel,
    AutonomyLevel,
    to_selection,
)


class AIOperationsAgentProfile(models.Model):
    """The central policy record -- Document C 5.1.

    Standalone: no relation to ``ai.agent``, and no Many2one anywhere on this
    model targets a model outside ``base`` or ``mail`` (CI check 15). That is
    what keeps the kernel installable on a bare database and on Community.
    """

    _name = 'ai.operations.agent.profile'
    _description = 'AI Operations Agent Profile'
    _order = 'name'

    name = fields.Char(required=True)
    code = fields.Char(required=True, index=True, help="Stable identifier, e.g. 'procurement'.")
    description = fields.Text()
    active = fields.Boolean(default=True)

    company_ids = fields.Many2many(
        'res.company', string='Companies',
        help="The agent's company scope. Intersected with the executing user's "
             "allowed companies at run time.",
    )

    # DEVIATION (review finding H4). Document C 9.3 requires "a discuss.channel
    # between the employee and the profile's partner", but C 5.1's field list
    # has no partner. res.partner is in base, so this holds the base+mail rule.
    partner_id = fields.Many2one(
        'res.partner', string='Agent Partner', ondelete='restrict',
        help="Identity the agent posts under on its chat channel (Session 12).",
    )

    service_user_id = fields.Many2one(
        'res.users', string='Service User', ondelete='restrict',
        help="Autonomous execution identity. Never an administrator.",
    )
    allow_interactive = fields.Boolean(default=True)
    allow_autonomous = fields.Boolean(default=False)

    max_autonomy_level = fields.Selection(
        to_selection(AutonomyLevel), required=True,
        default=str(AutonomyLevel.QUERY.value),
        help="Ceiling. A call is permitted when "
             "max(tool.autonomy_required, action.autonomy_required) <= this.",
    )

    model_permission_ids = fields.One2many(
        'ai.operations.model.permission', 'profile_id', string='Model Permissions')
    action_permission_ids = fields.One2many(
        'ai.operations.action.permission', 'profile_id', string='Action Permissions')

    max_tool_calls = fields.Integer(default=12, help="Loop cap for one run.")
    max_write_ops = fields.Integer(default=3, help="Write budget for one run.")
    timeout_seconds = fields.Integer(default=120)

    max_daily_tokens = fields.Integer(
        default=2000000,
        help="0 means unlimited and requires an explicit decision-log entry.",
    )
    # Counted on ai.operations.budget, not here: the runtime increments it as
    # the executing identity, and that identity must never hold write on the
    # record carrying max_autonomy_level. See models/budget.py.
    tokens_today = fields.Integer(
        compute='_compute_tokens_today', string="Tokens Used Today")

    provider_code = fields.Selection(
        selection='_selection_provider_code',
        help="Resolved through the frozen provider registry. Phase 1 offers "
             "only what is installed.")
    model_code = fields.Selection(
        selection='_selection_model_code',
        help="From the selected adapter's declared list. Never free text: a "
             "typo must be a configuration error at save time, not a runtime "
             "failure at 07:00.")

    tool_assignment_ids = fields.One2many(
        'ai.operations.tool.assignment', 'profile_id', string='Tool Assignments')

    default_review_user_id = fields.Many2one(
        'res.users', string='Routine Reviewer', ondelete='restrict',
        help="Routine activity assignee. Routing is operational configuration, "
             "not a permission.",
    )
    default_escalation_user_id = fields.Many2one(
        'res.users', string='Escalation User', ondelete='restrict',
        help="Assignee when a recommendation exceeds the routine variance bound.",
    )

    audit_level = fields.Selection(
        to_selection(AuditLevel), required=True, default=AuditLevel.STANDARD.value,
        help="Verbosity of ALLOWED rows only. It never suppresses a row.",
    )
    policy_version = fields.Char(required=True, default='1.0.0')
    last_security_review = fields.Date()
    security_approved_by_id = fields.Many2one(
        'res.users', string='Security Reviewed By', ondelete='restrict',
        help="Who signed off the last security review of this profile. "
             "Unrelated to action approval, which does not exist.",
    )

    @api.model
    def _selection_provider_code(self):
        from ..services.provider import provider_selection
        return provider_selection()

    @api.model
    def _selection_model_code(self):
        from ..services.provider import model_selection
        return model_selection()

    def _compute_tokens_today(self):
        Budget = self.env['ai.operations.budget']
        for profile in self:
            profile.tokens_today = Budget.tokens_used_today(profile) if profile.id else 0

    _code_uniq = models.Constraint(
        'unique(code)',
        'An agent profile with this code already exists.',
    )

    # ------------------------------------------------------------------
    # Constraints -- every one fails closed.
    # ------------------------------------------------------------------

    @api.constrains('provider_code', 'model_code')
    def _check_provider(self):
        from ..services.provider import get_provider, has_provider
        for profile in self:
            if not profile.provider_code:
                continue
            if not has_provider(profile.provider_code):
                raise ValidationError(
                    "No provider adapter named %r is installed. Installing one "
                    "is a deployment act, not a configuration change."
                    % profile.provider_code)
            declared = {code for code, _label in get_provider(profile.provider_code).models}
            if profile.model_code and profile.model_code not in declared:
                raise ValidationError(
                    "%r is not a model declared by the %r adapter."
                    % (profile.model_code, profile.provider_code))

    @api.constrains('max_autonomy_level')
    def _check_phase1_autonomy_ceiling(self):
        for profile in self:
            if int(profile.max_autonomy_level) > PHASE1_MAX_AUTONOMY:
                raise ValidationError(
                    "Phase 1 permits no agent above level %s (Prepare). "
                    "Levels 3 and 4 are not implemented."
                    % int(PHASE1_MAX_AUTONOMY)
                )

    @api.constrains('allow_autonomous', 'service_user_id')
    def _check_autonomous_needs_service_user(self):
        for profile in self:
            if profile.allow_autonomous and not profile.service_user_id:
                raise ValidationError(
                    "An autonomous agent requires a service user. It must never "
                    "fall back to the administrator or to sudo()."
                )

    @api.constrains('service_user_id')
    def _check_service_user(self):
        for profile in self:
            user = profile.service_user_id
            if not user:
                continue
            if user._has_group('base.group_system'):
                raise ValidationError(
                    "An agent may never run as administrator: the service user "
                    "must not be in Settings / Administration."
                )
            if user.share:
                raise ValidationError("A service user must be an internal user.")

    @api.constrains('active', 'company_ids',
                    'default_review_user_id', 'default_escalation_user_id')
    def _check_activation_requirements(self):
        for profile in self:
            if not profile.active:
                continue
            if not profile.company_ids:
                raise ValidationError(
                    "An active agent profile requires a company scope."
                )
            if not profile.default_review_user_id or not profile.default_escalation_user_id:
                raise ValidationError(
                    "An active agent profile requires both a routine reviewer "
                    "and an escalation user. Activity routing fails closed: an "
                    "AI task on the wrong desk is worse than no task."
                )

    @api.constrains('default_review_user_id', 'default_escalation_user_id',
                    'service_user_id', 'company_ids')
    def _check_routing_users(self):
        for profile in self:
            routing = (
                ('Routine reviewer', profile.default_review_user_id),
                ('Escalation user', profile.default_escalation_user_id),
            )
            for label, user in routing:
                if not user:
                    continue
                if user.share:
                    raise ValidationError("%s must be an internal user." % label)
                if profile.service_user_id and user == profile.service_user_id:
                    raise ValidationError(
                        "%s must not be the profile's own service user -- an "
                        "activity addressed to the agent itself is a task "
                        "nobody owns." % label
                    )
                if user._has_group('base.group_system'):
                    raise ValidationError(
                        "%s must not be an administrator -- an AI-generated task "
                        "addressed to the administrator is a task nobody owns."
                        % label
                    )
                if profile.company_ids and not (user.company_ids & profile.company_ids):
                    raise ValidationError(
                        "%s must belong to a company inside the agent's scope."
                        % label
                    )
