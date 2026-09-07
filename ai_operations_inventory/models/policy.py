from odoo import api, models

PROFILE_CODE = 'inventory'


class AIOperationsInventoryPolicy(models.AbstractModel):
    _name = 'ai.operations.inventory.policy'
    _description = 'AI Operations inventory Policy Wiring'

    def _register_hook(self):
        super()._register_hook()
        self._wire_assignments()

    @api.model
    def _wire_assignments(self):
        """Assign this pack's tools to its profile.

        Not XML, because tool records are materialised at loading STEP 9 --
        after every data file has loaded -- so an XML ref to one cannot resolve.
        The assignment is created disabled-by-default only in the sense that the
        TOOL is: enabling remains a Technical Administrator's act.

        This pack shipped without this hook, which meant its profile received no
        assignment rows at all and guard step 4 denied every one of its tools
        with TOOL_NOT_ASSIGNED. Two of Document B's four agents could not execute
        a single tool as shipped.
        """
        Tool = self.env['ai.operations.tool']
        Tool._sync_from_registry()
        # active_test=False: policy packs ship their profile INACTIVE (an active
        # one needs company scope and routing users no pack can know), so a
        # plain search finds nothing and the pack wires no assignments at all.
        # Procurement and manufacturing only worked because the demo module
        # activates them before the next registry load.
        profile = self.env['ai.operations.agent.profile'].with_context(
            active_test=False).search([('code', '=', PROFILE_CODE)], limit=1)
        if not profile:
            return
        Assignment = self.env['ai.operations.tool.assignment']
        for tool in Tool.search([('code', 'like', PROFILE_CODE + '.%')]):
            if Assignment.search([('profile_id', '=', profile.id),
                                  ('tool_id', '=', tool.id)], limit=1):
                continue
            Assignment.create({'profile_id': profile.id, 'tool_id': tool.id})
