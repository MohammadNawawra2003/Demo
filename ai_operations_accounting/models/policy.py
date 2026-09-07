from odoo import api, models

PROFILE_CODE = 'accounting'


class AIOperationsAccountingPolicy(models.AbstractModel):
    _name = 'ai.operations.accounting.policy'
    _description = 'AI Operations accounting Policy Wiring'

    def _register_hook(self):
        super()._register_hook()
        self._wire_assignments()

    @api.model
    def _wire_assignments(self):
        """There is nothing to wire, and that is the point.

        Every other pack assigns the tools it registers. This one registers
        none, so this hook exists to say so explicitly rather than to leave a
        reader wondering whether the file was forgotten. When Phase 2 gives the
        Accountant its tools, this becomes the same three lines the other packs
        have.
        """
        return False
