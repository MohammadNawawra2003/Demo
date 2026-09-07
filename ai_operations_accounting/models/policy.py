from odoo import api, models

PROFILE_CODE = 'accounting'


class AIOperationsAccountingPolicy(models.AbstractModel):
    _name = 'ai.operations.accounting.policy'
    _description = 'AI Operations Accounting Policy Wiring'

    def _register_hook(self):
        super()._register_hook()
        self._wire_assignments()

    @api.model
    def _wire_assignments(self):
        """Assign this pack's four read tools to the Accountant profile.

        This hook used to return False and say so at length: the agent was a
        roster entry with nothing to wire. George's 2026-09-07 decision made it
        operational, read-only, so it now does what every other pack does.
        """
        Tool = self.env['ai.operations.tool']
        Tool._sync_from_registry()
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
