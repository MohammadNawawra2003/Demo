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
            handoff_id=handoff_id,
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
        # After the company scope, deliberately. Company is the coarser and more
        # fundamental boundary, and a caller outside it should keep hearing so
        # rather than being told about an eligibility list that would not have
        # helped them either.
        self.check_eligibility(profile, identity)                  # 8b

        validated = self.check_schema(spec, params)                # 9

        for model_name, operations in self._required_operations(spec).items():
            for operation in operations:
                self.check_model(profile, model_name, operation)   # 11, 12

        budget = budget or RunBudget(
            max_tool_calls=profile.max_tool_calls or 12,
            max_write_ops=profile.max_write_ops or 3)
        # The assignment's cap bounds THIS TOOL, not the run. Folding it into
        # the run's own cap made every later tool inherit the tightest cap any
        # earlier tool happened to carry, and min() never recovers.
        budget.consume_tool_call(                                  # 19
            tool_code, assignment.max_calls_per_run or 0)

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

    def check_eligibility(self, profile, identity):
        """Step 8b. Whether this identity may use this agent at all.

        Eligibility was never modelled: any group_ai_user holder was offered
        every active profile in their companies, so a procurement clerk was
        offered the Accounting agent. The record rule on the profile now scopes
        DISCOVERY, and this scopes EXECUTION -- because a rule cannot see a
        direct execution.run(), a discuss.channel that is already bound to a
        profile, or a caller who obtained the record some other way.

        It only ever subtracts. An eligible identity still faces every other
        term of USER n AGENT n TOOL n ACTION n COMPANY unchanged.

        Two identities are eligible without being listed, and both are
        deliberate: the profile's own service user, because an autonomous run
        has no human to assign, and a security administrator, because the
        person configuring the agent has to be able to test it.
        """
        if self.is_eligible(profile, identity):
            return
        raise AIAccessDenied(
            DenialReason.PROFILE_NOT_ELIGIBLE,
            detail='%s is not an allowed user of agent %s' % (
                identity.login, profile.code))

    def is_eligible(self, profile, identity):
        """The same question, as a boolean, for the surfaces that open a chat.

        A door asks "may I show this?" and the guard asks "may I run this?".
        Same answer, two callers, one definition -- so the selector, the open
        action and the runtime cannot drift apart.
        """
        if not identity or not profile:
            return False
        if identity.id == profile.service_user_id.id:
            return True
        if identity._has_group('ai_operations.group_ai_security_admin'):
            return True
        # Read the ids, never the records. Instantiating an x2many filters it on
        # ``active``, which fetches the res.users rows -- the same trap that made
        # every narrow-user tool call crash on company_ids instead of refusing.
        # See scoped_company_ids() on the profile for the full story.
        return identity.id in profile.with_context(active_test=False).user_ids.ids

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

    def resolve_mode(self, trigger):
        """Which mode a trigger runs in. ONE place decides this.

        Document C §9's table has two triggers and two modes, and the mapping
        was inline in ``run()``. ``HANDOFF`` arrived post-freeze and was mapped
        to AUTONOMOUS beside CRON, on the reasoning that neither has a human in
        it. That was true of the cron and became untrue of the handoff the
        moment arrival stopped entering the agent by itself: a handoff run is
        now something a person starts, so it is interactive for the same reason
        a chat is, and the identity is the person who started it.

        Only ``CRON`` is autonomous. That is the whole rule, and it lives here
        rather than in the runner so that the guard and the runner cannot
        disagree about what mode a run is in.
        """
        return (ExecutionMode.AUTONOMOUS.value
                if trigger == TriggerType.CRON.value
                else ExecutionMode.INTERACTIVE.value)

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
        # Plain ids, not records: see agent_profile.scoped_company_ids(). Reading
        # the m2m here raised AccessError for exactly the users this step exists
        # to bound -- the ones whose companies are narrower than the agent's.
        scoped = profile.scoped_company_ids()
        effective = [cid for cid in scoped if cid in allowed] \
            if scoped else list(allowed)
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

        # 10b. The model permission's own state restriction. Document B §4.1
        # writes "✅ draft only" for purchase.order, and that was decorative: the
        # field was declared on ai.operations.model.permission and validated at
        # write time, and then no code path ever read it. Only the ACTION
        # permission's variant was enforced, so a tool amending an existing
        # record was bounded by nothing. Read-only operations are exempt --
        # restricting a *read* to draft would hide the confirmed orders every
        # analysis tool legitimately reports on.
        if operation != 'read':
            self._check_permission_state(ctx, model_name, operation, existing)

        agent_domain = self.agent_domain(ctx.profile, model_name, ctx)  # 13
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

    def check_create(self, ctx, model_name, action_code=None, **action_kwargs):
        """Authorise a create BEFORE the tool decides whether to perform one.

        ``check_records`` needs ids, and a create has none yet, so the only
        user-level check on a creating tool used to be the ORM refusing the
        write itself. That is sound while the tool always writes -- and every
        creating tool here has a replay guard in front of it, which returns an
        existing record and never reaches the ORM. Authorisation then depended
        on whether the work had already been done: the same caller asking the
        same question was refused on a fresh database and served on one where
        somebody else had already created the record.

        Authorisation is a property of the caller and the request, never of
        what the database happens to hold. Call this first, above the
        idempotency lookup.
        """
        self.check_model(ctx.profile, model_name, 'create')        # agent
        if action_code:
            self.check_action(ctx, model_name, action_code, **action_kwargs)
        try:
            ctx.env[model_name].with_user(ctx.execution_user).check_access('create')
        except (AccessError, UserError) as error:
            raise AIAccessDenied(
                DenialReason.USER_ACL_DENIED,
                detail='execution user cannot create %s' % model_name,
                model=model_name) from error

    def _check_permission_state(self, ctx, model_name, operation, records):
        """Enforce ``state_restriction`` on the model permission itself."""
        permission = self._permission_for(ctx.profile, model_name)
        if not permission or not permission.state_restriction or not records:
            return
        field_path, expected = validate_state_restriction(
            permission.state_restriction)
        for record in records:
            if str(self._traverse(record, field_path)) != expected:
                raise AIAccessDenied(
                    DenialReason.STATE_NOT_PERMITTED,
                    detail='%s on %s requires %s' % (
                        operation, model_name, permission.state_restriction),
                    model=model_name)

    def check_action(self, ctx, model_name, action_code, records=None,
                     amount=None, quantity=None):
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
        # §5.3's amount and quantity ceilings. They stored a number, audited
        # changes to it, rendered it on the form -- and denied nothing. An
        # operator configuring "this agent may draft up to SAR 50,000" was
        # protected by exactly nothing, which is worse than having no field:
        # §5.4 rejects a whole field-permission model on that same argument.
        if permission.max_amount and amount and float(amount) > permission.max_amount:
            raise AIAccessDenied(
                DenialReason.ACTION_NOT_PERMITTED,
                detail='%s exceeds the %s ceiling of %s'
                       % (action_code, model_name, permission.max_amount),
                model=model_name)
        if permission.max_quantity and quantity \
                and float(quantity) > permission.max_quantity:
            raise AIAccessDenied(
                DenialReason.ACTION_NOT_PERMITTED,
                detail='%s exceeds the %s quantity ceiling of %s'
                       % (action_code, model_name, permission.max_quantity),
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

        # A missing baseline is not a variance of zero. There is no percentage
        # to compute against nothing, so the number stays 0.0 -- inventing one
        # would only trip the ceiling on a figure nobody measured.
        no_baseline = not deterministic
        if no_baseline:
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

        # Odoo computing a shortage of 0 is not the same as the agent proposing
        # nothing. With no computed basis there is nothing to justify the
        # recommendation against, so a human decides -- which is what the
        # routine bound is for. It escalates and never denies: the ceiling is
        # the only bound that denies, and a missing baseline is not a ceiling
        # breach. Proposing nothing against nothing is not a judgement call and
        # must not land on a manager's desk.
        #
        # The specification defines the bands and is silent on a zero baseline;
        # this is George's ruling of 2026-09-06, recorded in the decision log.
        if no_baseline and float(proposed) > 0.0:
            approval_required = True

        audit.record_variance(ctx.correlation_id, variance, approval_required)
        return variance, approval_required

    # ==================================================================
    # Helpers
    # ==================================================================

    EXECUTION_USER_PLACEHOLDER = '$EXECUTION_USER'

    def _resolve_placeholders(self, domain, ctx):
        if not domain or ctx is None:
            return domain
        resolved = []
        for leaf in domain:
            if (isinstance(leaf, (list, tuple)) and len(leaf) == 3
                    and leaf[2] == self.EXECUTION_USER_PLACEHOLDER):
                resolved.append((leaf[0], leaf[1], ctx.execution_user.id))
            else:
                resolved.append(leaf)
        return resolved

    def agent_domain(self, profile, model_name, ctx=None):
        """AND of the agent domain and its state restriction. Never OR.

        ``$EXECUTION_USER`` in a domain value is substituted for the id of the
        identity the run is executing as. It exists for exactly one requirement:
        Document B §4.5 scopes the ``mail.activity`` write to
        ``create_uid = execution identity``, and the domain validator is
        ``literal_eval``-only by design -- a domain that can call is a domain
        that can escalate. A literal placeholder the guard resolves keeps the
        validator closed and still expresses the one dynamic value the
        specification needs.
        """
        permission = self._permission_for(profile, model_name)
        if not permission:
            return []
        domain = Domain(self._resolve_placeholders(
            validate_domain(permission.domain) or [], ctx))
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
        """What the guard will demand of the profile, per model.

        ``models`` means the tool reads the model, so every entry requires
        ``read``. ``actions`` means it performs a named operation, and a model
        that appears ONLY there requires only that operation -- it does not
        also require read.

        That distinction is not cosmetic. Every model used to be given an
        implicit ``read``, which made a create-only permission impossible to
        satisfy: ``manufacturing.post_readiness_note`` posts to an order's
        chatter and never reads a message, the pack grants ``mail.message``
        create-only on purpose, and the tool was therefore denied
        ``OPERATION_NOT_PERMITTED`` on every call it ever received. The
        alternative was granting an agent read access to all chatter to let it
        write one note, which is a real widening for a bookkeeping reason.

        The allowlist still binds: an action-only model must still have a
        permission row, and that row must still carry the operation's flag.
        """
        required = {model_name: {'read'} for model_name in spec.models}
        for model_name, action_code in spec.actions:
            required.setdefault(model_name, set())
            operation = ACTION_OPERATION.get(action_code)
            if operation:
                required[model_name].add(operation)
        return required

    def _traverse(self, record, field_path):
        """Walk a dotted field path, denying rather than exploding.

        A missing field used to raise KeyError, which escapes the guard as an
        unexpected error and is audited as ERROR rather than DENIED -- a
        fail-OPEN path in the one place a state restriction is supposed to
        close. `quality.alert` is exactly this case: it has no `state` field.
        """
        value = record
        for part in (field_path or '').split('.'):
            if not part:
                break
            fields_map = getattr(value, '_fields', {})
            if part not in fields_map and not hasattr(value, part):
                raise AIAccessDenied(
                    DenialReason.STATE_NOT_PERMITTED,
                    detail='%r has no field %r; the state restriction cannot be '
                           'evaluated and the guard fails closed'
                           % (getattr(value, '_name', value), part))
            field = fields_map.get(part)
            # A restriction is written in English -- `stage_id.name=New` is
            # Document C §5.2's own example -- and `name` is translatable. Read
            # it in en_US or the whole restriction silently stops matching the
            # moment a user's language changes, which for this client is Arabic
            # by default. A state restriction that depends on the reader's
            # locale is not a restriction.
            if field is not None and getattr(field, 'translate', False):
                value = value.with_context(lang='en_US')[part]
            else:
                value = value[part]
        return value
