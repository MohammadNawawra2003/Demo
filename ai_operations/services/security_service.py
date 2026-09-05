import uuid

from odoo import api, models
from odoo.exceptions import AccessError, UserError
from odoo.fields import Domain

from .context import ExecutionContext, RunBudget
from .enums import (
    Decision,
    DenialReason,
    ExecutionMode,
    TriggerType,
)
from .exceptions import AIAccessDenied
from .validators import validate_domain, validate_state_restriction

#: Which ORM operation each action code needs.
ACTION_OPERATION = {
    'CREATE_DRAFT': 'create',
    'UPDATE_DRAFT': 'write',
    'DELETE': 'unlink',
}

PERM_FIELD = {
    'read': 'perm_read',
    'create': 'perm_create',
    'write': 'perm_write',
    'unlink': 'perm_unlink',
}


class AISecurityService(models.AbstractModel):
    """The guard. Document C 7 lives here and nowhere else.

    Every ``check_*`` returns ``None`` or raises ``AIAccessDenied``. None of them
    returns a boolean, because a boolean invites ``if not check(): pass``.

    Steps 1-9, 11-12 and 19 run inside :meth:`authorize`, which is everything
    knowable before a tool has resolved any record. Steps 10, 13 and 14 are
    record-level and run through :meth:`check_records`, which the tool reaches
    via ``ctx.check_records()`` once it has ids. Steps 15-18 are reached through
    ``ctx.check_variance()`` and the action check. See DEVIATIONS.md.
    """

    _name = 'ai.operations.security'
    _description = 'AI Operations Security Service'

    # ==================================================================
    # Entry point
    # ==================================================================

    @api.model
    def authorize(self, tool_code, params, profile,
                  execution_mode=ExecutionMode.INTERACTIVE.value,
                  trigger=TriggerType.CHAT.value,
                  session_id=None, correlation_id=None, handoff_id=None,
                  budget=None, idempotency_key=None):
        """Return a frozen ExecutionContext, or raise AIAccessDenied AFTER the
        denial has been written to the audit log."""
        audit = self.env['ai.operations.audit']
        correlation_id = correlation_id or uuid.uuid4().hex
        session_id = session_id or correlation_id

        audit.open_entry(
            tool_code=tool_code, profile=profile, user=self.env.user,
            execution_mode=execution_mode, trigger=trigger,
            session_id=session_id, correlation_id=correlation_id,
            service_user=profile.service_user_id if profile else None,
        )

        try:
            ctx = self._authorize(
                tool_code, params, profile, execution_mode, trigger,
                session_id, correlation_id, handoff_id, budget, idempotency_key)
        except AIAccessDenied as denial:
            audit.record_decision(
                correlation_id, Decision.DENIED, profile=profile,
                reason=denial.reason, detail=denial.detail,
                tool_code=tool_code, models_accessed=denial.model,
                input_args=params if isinstance(params, dict) else None)
            raise

        audit.record_decision(
            correlation_id, Decision.ALLOWED, profile=profile,
            tool_code=tool_code, models_accessed=','.join(ctx.models_declared)
            if hasattr(ctx, 'models_declared') else None,
            input_args=params if isinstance(params, dict) else None)
        return ctx

    def _authorize(self, tool_code, params, profile, execution_mode, trigger,
                   session_id, correlation_id, handoff_id, budget,
                   idempotency_key):
        Tool = self.env['ai.operations.tool']

        spec = Tool.registry_spec(tool_code)                      # 1
        record = Tool.record_for(tool_code)                       # 2
        self.check_profile(profile)                               # 3
        assignment = record.assignment_for(profile)               # 4
        self.check_token_ceiling(profile)                         # 5

        action_floor = self._action_floor(profile, spec)
        self.check_autonomy(profile, spec, action_floor)          # 6

        identity = self.resolve_identity(profile, execution_mode)  # 7
        company_ids = self.resolve_companies(profile, identity)    # 8

        validated = self.check_schema(spec, params)                # 9

        for model_name, operations in self._required_operations(spec).items():
            for operation in operations:
                self.check_model(profile, model_name, operation)   # 11, 12

        budget = budget or RunBudget(
            max_tool_calls=profile.max_tool_calls or 12,
            max_write_ops=profile.max_write_ops or 3)
        budget.max_tool_calls = min(
            budget.max_tool_calls,
            assignment.max_calls_per_run or budget.max_tool_calls)
        budget.consume_tool_call()                                 # 19

        env = self.env(user=identity, context={
            **self.env.context,
            'allowed_company_ids': list(company_ids),
        })

        ctx = ExecutionContext(
            env=env,
            profile=profile.with_env(env),
            execution_user=identity,
            execution_mode=execution_mode,
            trigger=trigger,
            company_ids=tuple(company_ids),
            autonomy=int(profile.max_autonomy_level),
            tool_code=tool_code,
            correlation_id=correlation_id,
            session_id=session_id,
            audit_id=0,
            policy_version=profile.policy_version,
            idempotency_key=idempotency_key,
            handoff_id=handoff_id,
            budget=budget,
        )
        object.__setattr__(ctx, 'validated_params', validated)
        object.__setattr__(ctx, 'models_declared', spec.models)
        return ctx

    # ==================================================================
    # Individual checks -- each independently testable
    # ==================================================================

    def check_profile(self, profile):
        """Step 3."""
        if not profile or not profile.exists() or not profile.active:
            raise AIAccessDenied(
                DenialReason.PROFILE_INACTIVE,
                detail='profile missing or archived')

    def check_token_ceiling(self, profile):
        """Step 5. Fails closed: over budget, the run stops."""
        if not profile.max_daily_tokens:
            return
        used = self.env['ai.operations.budget'].tokens_used_today(profile)
        if used >= profile.max_daily_tokens:
            raise AIAccessDenied(
                DenialReason.BUDGET_EXCEEDED,
                detail='daily token ceiling reached (%s of %s)'
                       % (used, profile.max_daily_tokens))

    def check_autonomy(self, profile, spec, action_floor=0):
        """Step 6. A ceiling against floors, never a min()."""
        required = max(int(spec.autonomy), int(action_floor or 0))
        if required > int(profile.max_autonomy_level):
            raise AIAccessDenied(
                DenialReason.AUTONOMY_INSUFFICIENT,
                detail='needs level %s, profile ceiling is %s'
                       % (required, profile.max_autonomy_level),
                tool_code=spec.code)

    def resolve_identity(self, profile, execution_mode):
        """Step 7. Never sudo, never a fallback."""
        if execution_mode == ExecutionMode.AUTONOMOUS.value:
            service_user = profile.service_user_id
            if not service_user or not service_user.active:
                raise AIAccessDenied(
                    DenialReason.NO_SERVICE_USER,
                    detail='service user missing or archived')
            return service_user
        return self.env.user

    def resolve_companies(self, profile, user):
        """Step 8. Empty intersection denies."""
        allowed = set(user.company_ids.ids)
        scope = set(profile.company_ids.ids)
        effective = [cid for cid in profile.company_ids.ids if cid in allowed] \
            if scope else list(allowed)
        if not effective:
            raise AIAccessDenied(
                DenialReason.COMPANY_OUT_OF_SCOPE,
                detail='user and agent company scopes do not intersect')
        return effective

    def check_schema(self, spec, params):
        """Step 9."""
        from .exceptions import AISchemaError
        try:
            return spec.input_schema.validate(params or {})
        except AISchemaError as error:
            raise AIAccessDenied(
                DenialReason.SCHEMA_INVALID,
                detail=str(error), tool_code=spec.code) from error

    def check_model(self, profile, model_name, operation):
        """Steps 11 and 12. Allowlist onto a deny baseline."""
        permission = self._permission_for(profile, model_name)
        if not permission:
            raise AIAccessDenied(
                DenialReason.MODEL_NOT_PERMITTED,
                detail='%s is not in the allowlist' % model_name,
                model=model_name)
        if not permission[PERM_FIELD[operation]]:
            raise AIAccessDenied(
                DenialReason.OPERATION_NOT_PERMITTED,
                detail='%s not permitted on %s' % (operation, model_name),
                model=model_name)

    def check_records(self, ctx, model_name, record_ids, operation='read'):
        """Steps 10, 13 and 14.

        Step 10 is deliberately first: resolving ids under the execution user's
        own environment catches a hallucinated id and a user-level ACL denial in
        one operation, before any agent logic runs. A record the user cannot see
        does not exist as far as the rest of the guard is concerned.
        """
        self.check_model(ctx.profile, model_name, operation)
        record_ids = list(record_ids or [])
        if not record_ids:
            return ctx.env[model_name].browse()

        Model = ctx.env[model_name].with_user(ctx.execution_user)
        try:
            records = Model.browse(record_ids)
            records.check_access(operation)                        # 10
            existing = records.exists()
        except (AccessError, UserError) as error:
            raise AIAccessDenied(
                DenialReason.USER_ACL_DENIED,
                detail='execution user cannot %s %s' % (operation, model_name),
                model=model_name) from error

        if len(existing) != len(set(record_ids)):
            raise AIAccessDenied(
                DenialReason.USER_ACL_DENIED,
                detail='one or more ids do not resolve for this user',
                model=model_name)

        agent_domain = self.agent_domain(ctx.profile, model_name)   # 13
        if agent_domain:
            allowed = existing.filtered_domain(agent_domain)
            if len(allowed) != len(existing):
                raise AIAccessDenied(
                    DenialReason.RECORD_OUT_OF_DOMAIN,
                    detail='record outside the agent domain for %s' % model_name,
                    model=model_name)

        # 14. A res.company record IS its own company; everything else carries one.
        if model_name == 'res.company':
            out_of_scope = [r.id for r in existing if r.id not in ctx.company_ids]
        elif 'company_id' in existing._fields:
            out_of_scope = [
                r.id for r in existing
                if r.company_id and r.company_id.id not in ctx.company_ids]
        else:
            out_of_scope = []
        if out_of_scope:
            raise AIAccessDenied(
                DenialReason.COMPANY_OUT_OF_SCOPE,
                detail='record company outside the effective scope',
                model=model_name)
        return existing

    def check_action(self, ctx, model_name, action_code, records=None):
        """Step 15. Business actions, separately from CRUD."""
        permission = self.env['ai.operations.action.permission'].search([
            ('profile_id', '=', ctx.profile.id),
            ('model_name', '=', model_name),
            ('action_code', '=', action_code),
        ], limit=1)
        if not permission or not permission.allowed:
            raise AIAccessDenied(
                DenialReason.ACTION_NOT_PERMITTED,
                detail='%s on %s is not permitted' % (action_code, model_name),
                model=model_name)
        if permission.autonomy_required and \
                int(permission.autonomy_required) > int(ctx.autonomy):
            raise AIAccessDenied(
                DenialReason.AUTONOMY_INSUFFICIENT,
                detail='%s needs autonomy %s' % (action_code,
                                                 permission.autonomy_required),
                model=model_name)
        if records is not None and permission.state_restriction:
            field_path, expected = validate_state_restriction(
                permission.state_restriction)
            for record in records:
                if str(self._traverse(record, field_path)) != expected:
                    raise AIAccessDenied(
                        DenialReason.ACTION_NOT_PERMITTED,
                        detail='%s requires %s' % (action_code,
                                                   permission.state_restriction),
                        model=model_name)
        return permission

    def check_bound(self, ctx, deterministic, proposed, model_name=None,
                    action_code=None, category_ref=None):
        """Steps 16 and 17. The ceiling denies; the routine bound escalates.

        Returns ``(variance_pct, approval_required)``.
        """
        permission = self._bound_permission(ctx, model_name, action_code, category_ref)
        if not permission:
            raise AIAccessDenied(
                DenialReason.BOUND_EXCEEDED,
                detail='no variance bound configured; the guard fails closed',
                model=model_name)

        if not deterministic:
            variance = 0.0
        else:
            variance = (float(proposed) - float(deterministic)) / float(deterministic) * 100.0

        audit = self.env['ai.operations.audit']
        if variance > permission.variance_ceiling_pct:              # 16
            audit.record_variance(ctx.correlation_id, variance, False)
            raise AIAccessDenied(
                DenialReason.BOUND_EXCEEDED,
                detail='variance %.1f%% exceeds the ceiling of %.1f%%'
                       % (variance, permission.variance_ceiling_pct),
                model=model_name)

        approval_required = variance > permission.variance_bound_pct  # 17
        audit.record_variance(ctx.correlation_id, variance, approval_required)
        return variance, approval_required

    # ==================================================================
    # Helpers
    # ==================================================================

    def agent_domain(self, profile, model_name):
        """AND of the agent domain and its state restriction. Never OR."""
        permission = self._permission_for(profile, model_name)
        if not permission:
            return []
        domain = Domain(validate_domain(permission.domain) or [])
        if permission.state_restriction:
            field_path, expected = validate_state_restriction(
                permission.state_restriction)
            domain &= Domain([(field_path, '=', expected)])
        return list(domain) if not domain.is_true() else []

    def max_records(self, profile, model_name):
        """The extraction cap for this model, or the default."""
        permission = self._permission_for(profile, model_name)
        return permission.max_records if permission else 200

    def _permission_for(self, profile, model_name):
        """Read the policy as the executing identity.

        ``sudo()`` is banned, so the guard reads its own configuration as
        whoever is running -- which means the executing identity must hold
        AI Operations / User (read on the policy tables). When it does not,
        Odoo raises AccessError, and that message names a model. Converting it
        to a neutral denial here is not cosmetic: the runner hands a tool's
        exception text back to the model, so an escaping AccessError would
        publish part of the permission model into the LLM's context.
        """
        try:
            return self.env['ai.operations.model.permission'].search([
                ('profile_id', '=', profile.id),
                ('model_name', '=', model_name),
                ('active', '=', True),
            ], limit=1)
        except AccessError as error:
            raise AIAccessDenied(
                DenialReason.MODEL_NOT_PERMITTED,
                detail='executing identity cannot read the policy: %s' % error,
                model=model_name) from error

    def _bound_permission(self, ctx, model_name, action_code, category_ref):
        Action = self.env['ai.operations.action.permission']
        base = [('profile_id', '=', ctx.profile.id)]
        if model_name:
            base.append(('model_name', '=', model_name))
        if action_code:
            base.append(('action_code', '=', action_code))
        if category_ref:
            specific = Action.search(base + [
                ('product_category_ref', '=', category_ref)], limit=1)
            if specific:
                return specific
        return Action.search(base + [
            '|', ('product_category_ref', '=', False),
            ('product_category_ref', '=', '')], limit=1)

    def _action_floor(self, profile, spec):
        if not spec.actions:
            return 0
        floors = self.env['ai.operations.action.permission'].search([
            ('profile_id', '=', profile.id),
            ('model_name', 'in', [model for model, _ in spec.actions]),
            ('action_code', 'in', [action for _, action in spec.actions]),
        ]).mapped('autonomy_required')
        return max([int(f) for f in floors if f] or [0])

    def _required_operations(self, spec):
        required = {model_name: {'read'} for model_name in spec.models}
        for model_name, action_code in spec.actions:
            required.setdefault(model_name, {'read'})
            operation = ACTION_OPERATION.get(action_code)
            if operation:
                required[model_name].add(operation)
        return required

    def _traverse(self, record, field_path):
        value = record
        for part in field_path.split('.'):
            value = value[part]
        return value
