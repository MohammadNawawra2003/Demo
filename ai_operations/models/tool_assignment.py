from odoo import fields, models


class AIOperationsToolAssignment(models.Model):
    """Which profile may call which tool -- Document C 5.6.

    No assignment means no access. There is no default grant.
    """

    _name = 'ai.operations.tool.assignment'
    _description = 'AI Operations Tool Assignment'
    _order = 'profile_id, tool_id'
    _rec_name = 'tool_id'

    profile_id = fields.Many2one(
        'ai.operations.agent.profile', required=True, ondelete='cascade', index=True)
    tool_id = fields.Many2one(
        'ai.operations.tool', required=True, ondelete='cascade', index=True)
    enabled = fields.Boolean(default=True)
    max_calls_per_run = fields.Integer(
        help="Optional per-run cap for this tool, tighter than the profile's.")

    _assignment_uniq = models.Constraint(
        'unique(profile_id, tool_id)',
        'This tool is already assigned to this profile.',
    )
