from odoo import api, fields, models


class AIOperationsBudget(models.Model):
    """The daily spend counter, kept off the policy record on purpose.

    Document C 5.1 puts ``tokens_today`` / ``tokens_date`` on the agent profile.
    That cannot work here: the runtime must increment the counter as the
    **executing identity**, ``sudo()`` is banned, and the profile is the record
    carrying ``max_autonomy_level`` and the permission lines. Granting an
    ordinary user write on the profile to let them count tokens would hand them
    write on the policy that governs them -- the same trap as the audit log
    (review finding B3).

    So the counter lives here. This model holds a profile reference, a date and
    an integer, and nothing else: there is nothing sensitive to protect, so
    ordinary agent users may increment it while the policy record stays
    read-only to them.
    """

    _name = 'ai.operations.budget'
    _description = 'AI Operations Daily Budget Counter'
    _order = 'date desc'
    _rec_name = 'date'

    profile_id = fields.Many2one(
        'ai.operations.agent.profile', required=True, ondelete='cascade', index=True)
    date = fields.Date(required=True, index=True, default=fields.Date.context_today)
    tokens_used = fields.Integer(default=0)

    _profile_date_uniq = models.Constraint(
        'unique(profile_id, date)',
        'One budget counter per agent per day.',
    )

    @api.model
    def tokens_used_today(self, profile):
        counter = self.search([
            ('profile_id', '=', profile.id),
            ('date', '=', fields.Date.context_today(self)),
        ], limit=1)
        return counter.tokens_used if counter else 0

    @api.model
    def add_tokens(self, profile, tokens):
        """Increment today's counter, creating it on first use."""
        if not tokens:
            return 0
        today = fields.Date.context_today(self)
        counter = self.search([
            ('profile_id', '=', profile.id), ('date', '=', today)], limit=1)
        if counter:
            counter.tokens_used += tokens
        else:
            counter = self.create({
                'profile_id': profile.id, 'date': today, 'tokens_used': tokens})
        return counter.tokens_used
