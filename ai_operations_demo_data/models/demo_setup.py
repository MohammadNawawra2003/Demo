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

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

#: The operating company. Naqaa 'c1' in Document A §3.
COMPANY = 'Naqaa Water Manufacturing Co.'

#: Anthropic is the only adapter installed. The model is one the adapter
#: declares, so the profile's own constraint validates it at write time.
PROVIDER = 'anthropic'
MODEL = 'claude-sonnet-5'

#: Document B §3: Inventory is the only Phase 1 agent spanning both companies,
#: which is what makes it the sharpest multi-company test -- it may see C2
#: branch stock and C1 plant stock, and must not see C1 production cost or C2
#: selling price. Scoping it to C1 alone removed the test.
COMPANY_SCOPE = {
    'procurement': ('c1',),
    'inventory': ('c1', 'c2'),
    'manufacturing': ('c1',),
    'quality': ('c1',),
    # Both read-only agents stay inside C1. A cross-company executive view is a
    # bigger question than George asked, and "must not see another company's
    # information" is easiest to guarantee by not granting the company.
    'gm': ('c1',),
    'accounting': ('c1',),
}

#: The read-only agents added by the owner's 2026-09-07 decision. They are
#: configured like the others EXCEPT that their autonomy stays at the QUERY
#: floor: _configure_profile writes '2' for an operational agent, and writing
#: that here would silently promote a read-only executive agent to draft-write
#: the moment the demo module ran.
READ_ONLY_AGENTS = ('gm', 'accounting')
DISTRIBUTION_COMPANY = 'Naqaa Distribution Co.'

#: profile code -> (reviewer login, escalation login, service user login)
#: Document B 12's table, verbatim: routine reviewer, escalation user, service
#: user. Every pair was previously wrong or unset -- procurement escalated to
#: the warehouse manager, and inventory and quality had no routing at all, which
#: the fail-closed rule turned into "no activity is ever created" rather than
#: into a visible misroute.
ROUTING = {
    'procurement': ('noura.p', 'ahmed.q', 'ai.procurement'),
    'inventory': ('mansour.i', 'salem.i', 'ai.inventory'),
    'manufacturing': ('yousef.m', 'khalid.m', 'ai.manufacturing'),
    'quality': ('rania.q', 'huda.q', 'ai.quality'),
    # Read-only agents create no activity and raise no handoff, so the routing
    # users below are never actually used. They are set because §5.1 requires an
    # active profile to carry them, and leaving them empty would fail closed for
    # a reason that has nothing to do with these agents.
    'gm': ('faisal.gm', 'faisal.gm', 'ai.gm'),
    'accounting': ('omar.f', 'omar.f', 'ai.accounting'),
}

#: profile code -> [(tool code, max calls per run)]
#: Least privilege: exactly the tools the four scenarios call, nothing else.
#:
#: NOT here: ``core.describe_scope``. It declares ``res.company``, and neither
#: pack grants a model permission on it, so the guard denies it for every
#: profile as shipped. Assigning it would be a grant that can only ever produce
#: a denial, and granting res.company to make it work would be widening
#: permissions to make a demo look better. Reported, not worked around.
#: Document B 5's catalogue, in full. This was a five-and-three whitelist, which
#: disabled quality.trace_forward -- the headline of scenario 3 -- and
#: procurement.get_forecast_demand, which is the whole of scenario 4. Least
#: privilege is what the GUARD enforces per call; withholding a documented tool
#: from its own agent is not least privilege, it is an incomplete demo.
ASSIGNMENTS = {
    'procurement': [
        ('procurement.find_product', 4),
        ('procurement.get_shortage_context', 4),
        ('procurement.get_forecast_demand', 4),
        ('procurement.compare_suppliers', 4),
        ('procurement.get_open_pos', 4),
        ('procurement.get_price_history', 4),
        ('procurement.prepare_draft_rfq', 2),
        ('procurement.update_draft_rfq', 2),
        ('procurement.create_review_activity', 4),
        ('procurement.accept_handoff', 4),
        ('procurement.complete_handoff', 4),
    ],
    'inventory': [
        ('inventory.get_stock_position', 4),
        ('inventory.get_forecast', 4),
        ('inventory.get_below_reorder', 4),
        ('inventory.get_late_transfers', 4),
        ('inventory.get_expiring_lots', 4),
        ('inventory.get_stock_discrepancies', 4),
        ('inventory.create_review_activity', 4),
        ('inventory.raise_handoff', 2),
    ],
    'manufacturing': [
        ('manufacturing.check_readiness', 4),
        ('manufacturing.get_open_mos', 4),
        ('manufacturing.get_capacity_load', 4),
        ('manufacturing.get_scrap_analysis', 4),
        ('manufacturing.get_bom_explosion', 4),
        ('manufacturing.post_readiness_note', 4),
        ('manufacturing.create_review_activity', 4),
        ('manufacturing.raise_handoff', 2),
    ],
    'quality': [
        ('quality.get_check_results', 4),
        ('quality.get_out_of_spec', 4),
        ('quality.trace_forward', 4),
        ('quality.trace_backward', 4),
        ('quality.get_lot_disposition', 4),
        ('quality.propose_hold', 2),
        ('quality.create_review_activity', 4),
        ('quality.raise_handoff', 2),
    ],
    # Six reads and four reads. Not one write, not one handoff, not one
    # activity -- the two agents added on 2026-09-07 report and nothing else.
    'gm': [
        ('gm.get_operational_summary', 4),
        ('gm.get_stock_exceptions', 4),
        ('gm.get_blocked_production', 4),
        ('gm.get_late_procurement', 4),
        ('gm.get_open_quality_issues', 4),
        ('gm.get_financial_headlines', 4),
    ],
    'accounting': [
        ('accounting.get_receivable_ageing', 4),
        ('accounting.get_payable_ageing', 4),
        ('accounting.get_open_invoices', 4),
        ('accounting.get_revenue_by_period', 4),
    ],
}

#: profile code -> (agent partner name, [employee logins who get a channel])
#: fahad.p is on the procurement channel deliberately: he is READ ONLY on
#: purchase (Document A §12), so the same request Noura may make is refused for
#: him at guard step 10. That is the denial scenario, and it comes from Naqaa's
#: own seeded least privilege rather than from a weakened profile.
CHANNELS = {
    'procurement': ('AI / Procurement Intelligence', ['noura.p', 'fahad.p']),
    'inventory': ('AI / Inventory Intelligence', ['mansour.i']),
    'manufacturing': ('AI / Manufacturing Intelligence', ['khalid.m']),
    'quality': ('AI / Quality Intelligence', ['rania.q']),
    'gm': ('AI / General Manager Intelligence', ['faisal.gm']),
    'accounting': ('AI / Accounting Intelligence', ['omar.f']),
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
    ('inventory', 'mansour.i'): 'AI Demo — Inventory (Mansour)',
    ('manufacturing', 'khalid.m'): 'AI Demo — Manufacturing (Khalid)',
    ('quality', 'rania.q'): 'AI Demo — Quality (Rania)',
    ('gm', 'faisal.gm'): 'AI Demo — General Manager (Faisal)',
    ('accounting', 'omar.f'): 'AI Demo — Accounting (Omar)',
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
        self._configure_crons()
        self._grant_ai_group()
        channels = self._build_channels(profiles)
        self._seed_scenario_records(company)
        self._seed_production_schedule(company)
        # After the schedule, deliberately: the scenario sizes its top-ups
        # against the reservations the schedule has just made.
        self.env['ai.operations.e2e.scenario'].build()
        self._focus_on_naqaa(company)
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
        companies = company
        if 'c2' in COMPANY_SCOPE.get(code, ('c1',)):
            distribution = self.env['res.company'].search(
                [('name', '=', DISTRIBUTION_COMPANY)], limit=1)
            companies = company | distribution
        profile.write({
            'company_ids': [(6, 0, companies.ids)],
            'default_review_user_id': reviewer.id,
            'default_escalation_user_id': escalation.id,
            'service_user_id': service.id,
            'partner_id': self._agent_partner(code).id,
            'provider_code': PROVIDER,
            'model_code': MODEL,
            'allow_interactive': True,
            'allow_autonomous': False,
            # A read-only agent stays at the QUERY floor and gets no write
            # budget. Writing '2' and 2 here for every profile would have
            # promoted the General Manager and the Accountant to draft-write
            # on the first demo build -- configuration quietly outrunning the
            # policy pack, which is the exact failure guard step 15 exists to
            # catch and which nobody would have noticed in a list view.
            'max_autonomy_level': '0' if code in READ_ONLY_AGENTS else '2',
            'max_tool_calls': 8,
            'max_write_ops': 0 if code in READ_ONLY_AGENTS else 2,
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
    def _demo_users(self):
        """The employees the scenarios run as."""
        logins = {login for _partner, logins in CHANNELS.values() for login in logins}
        # §12's reviewers and escalation users too. An activity lands on their
        # desk and they open the agent that raised it, and the runtime writes
        # its audit row as the executing identity -- which needs the group. The
        # QA Manager was the case that found this: she is the person §9 step 14
        # names, and she could not run the agent that produced her own alert.
        logins |= {login for routing in ROUTING.values() for login in routing[:2]}
        return [self._user(login) for login in sorted(logins)]

    #: Document B §8's deliberate order: Inventory and Quality run first so
    #: Manufacturing has current facts, and Procurement runs last so it can
    #: consume the handoffs raised the same morning.
    CRON_TIMES = {
        'Inventory': (6, 0, 'inventory'),
        'Quality': (6, 45, 'quality'),
        'Manufacturing': (7, 0, 'manufacturing'),
        'Procurement': (7, 15, 'procurement'),
    }

    #: §8's checklists. A cron that passes no entry_prompt opens its run with an
    #: empty user message, so the daily review had an entry point and no agenda.
    CRON_AGENDA = {
        'inventory': "Daily inventory review. Check, in order: late receipts "
            "and deliveries, products below their reorder point, lots inside "
            "the expiry alert window, and count discrepancies.",
        'quality': "Daily quality review. Check overnight results, anything out "
            "of spec, and lots pending release past the 48 hour hold.",
        'manufacturing': "Daily production review. Check today's orders and "
            "their readiness, delayed orders, work centre load and scrap.",
        'procurement': "Daily procurement review. Work the open handoffs on "
            "your queue first, then overdue orders and forecast requirements.",
    }

    @api.model
    def _configure_crons(self):
        """Put §8's hour on each daily review.

        The packs set it too, but their records are ``noupdate="1"`` -- correct,
        because an administrator who has armed and retimed a cron should not
        have that overwritten by an upgrade -- which means a database built
        before the times existed keeps whatever it had. This runs on every
        upgrade and repairs exactly that, and it leaves ``active`` alone: arming
        the cron stays a deliberate act once a credential exists.
        """
        import datetime
        Cron = self.env['ir.cron'].with_context(active_test=False)
        today = fields.Datetime.now()
        configured = []
        for label, (hour, minute, code) in self.CRON_TIMES.items():
            cron = Cron.search(
                [('name', 'like', 'AI Operations: %s%%' % label)], limit=1)
            if not cron:
                continue
            wanted = (today + datetime.timedelta(days=1)).replace(
                hour=hour, minute=minute, second=0, microsecond=0)
            if not cron.nextcall or (cron.nextcall.hour, cron.nextcall.minute) \
                    != (hour, minute):
                cron.nextcall = wanted
            if 'entry_prompt' not in (cron.code or ''):
                cron.code = "model.run(%r, 'CRON', entry_prompt=%r)" % (
                    code, self.CRON_AGENDA[code])
            configured.append(label)
        return configured

    @api.model
    def _grant_ai_group(self):
        """The employees who will do the manual testing need to reach the
        platform at all. group_ai_user only -- it grants read on the policy the
        guard enforces against them, and nothing else.

        ``admin`` is on this list for the demo, and only for the demo. The
        product's own separation of duties is deliberate: an administrator
        configures the platform and is not an agent user, so the systray
        launcher is absent for them and every agent is out of reach. That is
        correct, and in a review it reads as a broken build -- the first person
        to open this database opened it as admin and reported no access. A
        reviewer is not a security boundary, so the demo module grants the
        group here. The packs, which are what production installs, are
        untouched.
        """
        group = self.env.ref('ai_operations.group_ai_user')
        users = self._demo_users()
        admin = self.env.ref('base.user_admin', raise_if_not_found=False)
        if admin:
            users.append(admin)
        for user in users:
            if group not in user.group_ids:
                user.write({'group_ids': [(4, group.id)]})

    @api.model
    def _focus_on_naqaa(self, company):
        """Land the demo's users inside Naqaa, not beside it.

        Naqaa is a second company in a database that already has one, and every
        record this module seeds is scoped to it. A user whose active company is
        still 'My Company' is shown an empty Manufacturing list, an empty
        Purchase list and no agent data at all -- correctly, by the multi-company
        rules, which is what makes it so misleading. It has already been
        reported once as missing data when the data was merely invisible.

        The Naqaa employees are built inside the company already, so in practice
        this moves ``admin``. Access is added, never replaced: whoever installed
        this keeps every company they had.
        """
        for user in self._demo_users() + [
                u for u in [self.env.ref('base.user_admin',
                                         raise_if_not_found=False)] if u]:
            if company not in user.company_ids:
                user.write({'company_ids': [(4, company.id)]})
            if user.company_id != company:
                user.company_id = company.id

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
