from odoo import api, models

PROFILE_CODE = 'procurement'


class AIOperationsProcurementPolicy(models.AbstractModel):
    _name = 'ai.operations.procurement.policy'
    _description = 'AI Operations procurement Policy Wiring'

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
        """
        Tool = self.env['ai.operations.tool']
        Tool._sync_from_registry()
        profile = self.env['ai.operations.agent.profile'].search(
            [('code', '=', PROFILE_CODE)], limit=1)
        if not profile:
            return
        Assignment = self.env['ai.operations.tool.assignment']
        for tool in Tool.search([('code', 'like', PROFILE_CODE + '.%')]):
            if Assignment.search([('profile_id', '=', profile.id),
                                  ('tool_id', '=', tool.id)], limit=1):
                continue
            Assignment.create({'profile_id': profile.id, 'tool_id': tool.id})
