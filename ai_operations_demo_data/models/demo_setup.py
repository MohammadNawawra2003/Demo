"""Turn the shipped policy packs into a testable deployment. NON-PRODUCTION.

**Why Python and not XML.** Everything here is a relationship between records
this module does not own and cannot reference by XML id: Naqaa's companies and
users are built in Python by ``alshayeb_demo_water`` and carry no external ids,
and the profiles ship inactive precisely because a policy pack cannot know which
company or which reviewer a deployment will use. Static XML could only reference
them by database id, which differs between every database this has to run on.
So records are resolved by **business key** -- a login, a company name, a profile
code, a tool code -- and every write is a get-or-set.

**Idempotent by construction.** Nothing here creates a record it can find, and
every field write is the same write on a second run. Install, upgrade and
re-run all converge on the same state.

**It configures; it never bypasses.** No ``sudo()``, no direct writes to
business models, no hand-made handoff or audit rows, no autonomy above level 2,
and not one permission that the four prepared scenarios do not need. The
denial scenario is denied by the policy this file writes, not by a special case.
"""

import logging

from odoo import api, models

_logger = logging.getLogger(__name__)

#: The operating company. Naqaa 'c1' in Document A §3.
COMPANY = 'Naqaa Water Manufacturing Co.'

#: Anthropic is the only adapter installed. The model is one the adapter
#: declares, so the profile's own constraint validates it at write time.
PROVIDER = 'anthropic'
MODEL = 'claude-sonnet-5'

#: profile code -> (reviewer login, escalation login, service user login)
ROUTING = {
    'procurement': ('ahmed.q', 'salem.i', 'ai.procurement'),
    'manufacturing': ('khalid.m', 'salem.i', 'ai.manufacturing'),
}

#: profile code -> [(tool code, max calls per run)]
#: Least privilege: exactly the tools the four scenarios call, nothing else.
#:
#: NOT here: ``core.describe_scope``. It declares ``res.company``, and neither
#: pack grants a model permission on it, so the guard denies it for every
#: profile as shipped. Assigning it would be a grant that can only ever produce
#: a denial, and granting res.company to make it work would be widening
#: permissions to make a demo look better. Reported, not worked around.
ASSIGNMENTS = {
    'procurement': [
        ('procurement.get_shortage_context', 4),
        ('procurement.get_open_pos', 4),
        ('procurement.compare_suppliers', 4),
        ('procurement.prepare_draft_rfq', 2),
    ],
    'manufacturing': [
        ('manufacturing.check_readiness', 4),
        ('manufacturing.raise_handoff', 2),
    ],
}

#: profile code -> (agent partner name, [employee logins who get a channel])
#: fahad.p is on the procurement channel deliberately: he is READ ONLY on
#: purchase (Document A §12), so the same request Noura may make is refused for
#: him at guard step 10. That is the denial scenario, and it comes from Naqaa's
#: own seeded least privilege rather than from a weakened profile.
CHANNELS = {
    'procurement': ('AI / Procurement Intelligence', ['noura.p', 'fahad.p']),
    'manufacturing': ('AI / Manufacturing Intelligence', ['khalid.m']),
}

#: The two source records the scenarios read, and the keys that make them
#: idempotent. SEED_ORIGIN is what makes them recognisable in a list view.
SEED_ORIGIN = 'AI-DEMO'
SEED_COMPONENT = 'PK-BTL-330'
SEED_FINISHED = 'FG-330'
SEED_VENDOR = 'Jeddah Plastic Industries'

CHANNEL_NAMES = {
    ('procurement', 'noura.p'): 'AI Demo — Procurement (Noura)',
    ('procurement', 'fahad.p'): 'AI Demo — Procurement (Fahad, read-only)',
    ('manufacturing', 'khalid.m'): 'AI Demo — Manufacturing (Khalid)',
}


class AIOperationsDemoSetup(models.AbstractModel):
    _name = 'ai.operations.demo.setup'
    _description = 'AI Operations Demo Configuration Builder (non-production)'

    # ------------------------------------------------------------------

    @api.model
    def build_all(self):
        company = self._company()
        profiles = {}
        for code in ROUTING:
            profiles[code] = self._configure_profile(code, company)
        self._enable_tools()
        for code, profile in profiles.items():
            self._assign_tools(profile, code)
        self._grant_ai_group()
        self._compensate_pack_defects(profiles)
        channels = self._build_channels(profiles)
        self._seed_scenario_records(company)
        _logger.info(
            "ai_operations_demo_data: %d profile(s) active, %d channel(s) bound",
            len(profiles), len(channels))
        return True

    # -- resolution by business key --------------------------------------

    @api.model
    def _company(self):
        company = self.env['res.company'].search([('name', '=', COMPANY)], limit=1)
        if not company:
            raise ValueError(
                "%s does not exist. Install alshayeb_demo_water first." % COMPANY)
        return company

    @api.model
    def _user(self, login):
        user = self.env['res.users'].with_context(active_test=False).search(
            [('login', '=', login)], limit=1)
        if not user:
            raise ValueError(
                "Naqaa user %r is missing. This module configures Naqaa; it does "
                "not create business identities." % login)
        return user

    @api.model
    def _profile(self, code):
        profile = self.env['ai.operations.agent.profile'].with_context(
            active_test=False).search([('code', '=', code)], limit=1)
        if not profile:
            raise ValueError("Agent profile %r is missing; its pack is not installed." % code)
        return profile

    # -- configuration ----------------------------------------------------

    @api.model
    def _configure_profile(self, code, company):
        """Everything C §5.1 demands of an *active* profile, and no more.

        ``allow_autonomous`` stays False: the cron is the only autonomous
        trigger, it ships inactive, and turning it on is a deliberate act once a
        credential exists. Setting it here would arm a daily vendor call on a
        staging database.
        """
        reviewer, escalation, service = (self._user(login)
                                         for login in ROUTING[code])
        profile = self._profile(code)
        profile.write({
            'company_ids': [(6, 0, company.ids)],
            'default_review_user_id': reviewer.id,
            'default_escalation_user_id': escalation.id,
            'service_user_id': service.id,
            'partner_id': self._agent_partner(code).id,
            'provider_code': PROVIDER,
            'model_code': MODEL,
            'allow_interactive': True,
            'allow_autonomous': False,
            'max_autonomy_level': '2',
            'max_tool_calls': 8,
            'max_write_ops': 2,
            'max_daily_tokens': 200000,
            'audit_level': 'FULL',
            'active': True,
        })
        return profile

    @api.model
    def _agent_partner(self, code):
        """The identity the agent speaks as in its channel. C §9.3."""
        name = CHANNELS[code][0]
        partner = self.env['res.partner'].with_context(active_test=False).search(
            [('name', '=', name)], limit=1)
        if not partner:
            partner = self.env['res.partner'].create({'name': name})
        return partner

    @api.model
    def _enable_tools(self):
        """Tools materialise disabled at registry load. Enable only ours.

        The sync call is not belt-and-braces. ``ai.operations.tool`` fills itself
        from the Python registry in ``_register_hook``, which Odoo runs at
        ``loading.py`` STEP 9 -- **after** every module's data files. On a
        database where the packs are already installed the records are there
        from the previous registry load, but on a first-time install of the
        whole chain this data file runs before any tool record exists, and every
        assignment below would fail on a missing tool. Calling the kernel's own
        materialiser first is idempotent and is exactly what STEP 9 will do
        again a moment later.
        """
        self.env['ai.operations.tool']._sync_from_registry()
        wanted = {code for pairs in ASSIGNMENTS.values() for code, _ in pairs}
        Tool = self.env['ai.operations.tool'].with_context(active_test=False)
        # The packs wire an assignment for EVERY tool they register, in
        # _register_hook (see ai_operations_procurement/models/policy.py), and
        # that hook runs at STEP 9 -- after this data file. So an assignment
        # this module disables now is recreated enabled a moment later, and
        # assignment.enabled is not a gate this module can hold.
        #
        # tool.enabled is. build_tool_definitions() offers a tool only when the
        # tool record AND the assignment are enabled, so disabling every tool
        # outside the scenario set is what actually bounds what the model is
        # ever shown -- for every profile, not just these two.
        surplus = Tool.search([('enabled', '=', True), ('code', 'not in', list(wanted))])
        if surplus:
            _logger.info("ai_operations_demo_data: disabling %d tool(s) outside "
                         "the demo scope: %s", len(surplus),
                         ', '.join(surplus.mapped('code')))
            surplus.write({'enabled': False})
        tools = self.env['ai.operations.tool'].with_context(
            active_test=False).search([('code', 'in', list(wanted))])
        missing = wanted - set(tools.mapped('code'))
        if missing:
            raise ValueError(
                "tool(s) %s are not registered; a pack is missing." % sorted(missing))
        tools.filtered(lambda t: not t.enabled).write({'enabled': True})
        return tools

    @api.model
    def _assign_tools(self, profile, code):
        """Converge on exactly the scenario grants.

        An assignment this module did not make is **disabled, never deleted**:
        the promise is least privilege, and a database that has been poked at by
        hand must still end up with the advertised grant. Disabling is
        reversible and destroys nothing, which deleting a record someone else
        created would not be.
        """
        Assignment = self.env['ai.operations.tool.assignment']
        Tool = self.env['ai.operations.tool']
        wanted = {tool_code for tool_code, _ in ASSIGNMENTS[code]}
        stale = profile.tool_assignment_ids.filtered(
            lambda a: a.tool_id.code not in wanted and a.enabled)
        if stale:
            _logger.info("ai_operations_demo_data: disabling %d assignment(s) "
                         "outside the demo scope on %s: %s", len(stale),
                         code, ', '.join(stale.tool_id.mapped('code')))
            stale.write({'enabled': False})
        for tool_code, max_calls in ASSIGNMENTS[code]:
            tool = Tool.with_context(active_test=False).search(
                [('code', '=', tool_code)], limit=1)
            values = {'enabled': True, 'max_calls_per_run': max_calls}
            existing = Assignment.search(
                [('profile_id', '=', profile.id), ('tool_id', '=', tool.id)], limit=1)
            if existing:
                existing.write(values)
            else:
                Assignment.create(dict(values, profile_id=profile.id, tool_id=tool.id))

    @api.model
    def _grant_ai_group(self):
        """The employees who will do the manual testing need to reach the
        platform at all. group_ai_user only -- it grants read on the policy the
        guard enforces against them, and nothing else."""
        group = self.env.ref('ai_operations.group_ai_user')
        logins = {login for _partner, logins in CHANNELS.values() for login in logins}
        for login in logins:
            user = self._user(login)
            if group not in user.group_ids:
                user.write({'group_ids': [(4, group.id)]})

    @api.model
    def _build_channels(self, profiles):
        """A named chat per (agent, employee), bound the way the product binds it.

        Not ``_get_or_create_chat``: that one builds a chat for *the calling
        user*, and this runs as the installer. The record shape is identical --
        a two-member ``chat`` -- and ``ai_profile_id`` is the same field
        ``action_open_chat`` sets, so the button keeps working and finds these.
        """
        Channel = self.env['discuss.channel']
        built = Channel
        for code, profile in profiles.items():
            _partner_name, logins = CHANNELS[code]
            for login in logins:
                name = CHANNEL_NAMES[(code, login)]
                channel = Channel.search([('name', '=', name)], limit=1)
                if not channel:
                    employee = self._user(login)
                    # install_mode is Odoo's own data-loading flag: without it
                    # discuss_channel.create() adds whoever is installing as a
                    # third member (mail/.../discuss_channel.py, "always add
                    # current user"), and a 'chat' refuses a third member. The
                    # conversation is the employee and the agent, nobody else.
                    channel = Channel.with_context(install_mode=True).create({
                        'name': name,
                        'channel_type': 'chat',
                        'channel_member_ids': [
                            (0, 0, {'partner_id': employee.partner_id.id}),
                            (0, 0, {'partner_id': profile.partner_id.id}),
                        ],
                    })
                channel.ai_profile_id = profile.id
                built |= channel
        return built

    # -- compensating for a reported production defect --------------------

    @api.model
    def _compensate_pack_defects(self, profiles):
        """⚠ REPORTED DEFECT, compensated here and NOT fixed in production.

        ``ai_operations_manufacturing`` ships the ``manufacturing.raise_handoff``
        tool and the ``MATERIAL_SHORTAGE`` handoff type, but its policy pack
        grants no model permission on ``ai.operations.handoff``. The guard
        therefore denies its own pack's handoff tool with
        ``MODEL_NOT_PERMITTED: ai.operations.handoff is not in the allowlist``,
        which makes the handoff feature unreachable as shipped.

        This module adds the missing permission so the handoff scenario can be
        tested. It is deliberately **here and not in the pack**: changing a
        production policy pack is a decision for the approver, not something a
        demo module should do quietly. The fix, once approved, is two records in
        ``ai_operations_manufacturing/data/policy_pack.xml`` -- read and create
        on ``ai.operations.handoff`` -- after which this method becomes a no-op
        and should be deleted.
        """
        Permission = self.env['ai.operations.model.permission']
        model = self.env['ir.model']._get('ai.operations.handoff')
        profile = profiles['manufacturing']
        existing = Permission.with_context(active_test=False).search(
            [('profile_id', '=', profile.id), ('model_id', '=', model.id)], limit=1)
        if existing:
            return existing
        _logger.warning(
            "ai_operations_demo_data: adding the ai.operations.handoff "
            "permission the manufacturing pack does not ship -- see the "
            "reported defect in README.md")
        return Permission.create({
            'profile_id': profile.id,
            'model_id': model.id,
            'perm_read': True,
            'perm_create': True,
        })

    # -- the two source records the scenarios read ------------------------

    @api.model
    def _seed_scenario_records(self, company):
        """One RFQ and one manufacturing order, and only if absent.

        ``alshayeb_demo_water`` seeds **master data only** -- companies,
        products, BoMs, warehouses, vendors, people. The 18 months of
        transactions are Session 7's separate history generator, which is not
        run on install and is far too expensive for a staging database whose
        builds are capped at 1 GB. So a freshly installed Naqaa has zero
        purchase orders and zero manufacturing orders, and scenarios 1 and 3
        would have nothing to read.

        These two records are the smallest thing that fixes that. Both are
        drafts, both carry a demo origin so they are recognisable and
        idempotent, and neither is confirmed -- nothing here posts stock or
        accounting.
        """
        product = self._product(SEED_COMPONENT)
        finished = self._product(SEED_FINISHED)
        self._seed_rfq(company, product)
        self._seed_production(company, finished)

    @api.model
    def _product(self, default_code):
        product = self.env['product.product'].with_context(
            active_test=False).search([('default_code', '=', default_code)], limit=1)
        if not product:
            raise ValueError(
                "Naqaa product %r is missing; alshayeb_demo_water is not "
                "installed or is incomplete." % default_code)
        return product

    @api.model
    def _seed_rfq(self, company, product):
        Purchase = self.env['purchase.order']
        existing = Purchase.search([('origin', '=', SEED_ORIGIN)], limit=1)
        if existing:
            return existing
        vendor = self.env['res.partner'].search(
            [('name', '=', SEED_VENDOR)], limit=1)
        if not vendor:
            raise ValueError("Naqaa vendor %r is missing." % SEED_VENDOR)
        return Purchase.create({
            'partner_id': vendor.id,
            'company_id': company.id,
            'origin': SEED_ORIGIN,
            'order_line': [(0, 0, {
                'product_id': product.id,
                'product_qty': 250000,
                'price_unit': 0.055,
            })],
        })

    @api.model
    def _seed_production(self, company, finished):
        Production = self.env['mrp.production']
        existing = Production.search([('origin', '=', SEED_ORIGIN)], limit=1)
        if existing:
            return existing
        bom = self.env['mrp.bom'].search(
            [('product_tmpl_id', '=', finished.product_tmpl_id.id)], limit=1)
        values = {
            'product_id': finished.id,
            'product_qty': 120000,
            'company_id': company.id,
            'origin': SEED_ORIGIN,
        }
        if bom:
            values['bom_id'] = bom.id
        return Production.create(values)
