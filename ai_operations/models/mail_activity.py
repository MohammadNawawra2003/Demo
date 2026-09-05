from odoo import api, fields, models


class MailActivity(models.Model):
    """Review finding H2, closed.

    Document B §8 requires every AI-generated activity to carry a key of
    ``{agent}:{model}:{res_id}:{reason_code}`` so a repeated exception **updates**
    its existing activity instead of creating a second one — the deduplication
    that stops the daily review becoming noise a user learns to ignore, which is
    described as the single most common way this class of system dies. T-98
    tests it.

    But no field was specified anywhere: not in the kernel model list, not in the
    tool-pack conventions. And ``mail.activity`` ships nothing usable — no ref,
    key, origin or external-id field, and no unique constraint. Matching on
    ``summary`` would be fragile and, in an Arabic-default database,
    language-dependent.

    The kernel depends on ``mail``, so it owns the field.
    """

    _inherit = 'mail.activity'

    ai_dedup_key = fields.Char(
        index=True, copy=False,
        help="{agent}:{model}:{res_id}:{reason_code}. A matching open activity "
             "is updated, never duplicated.")
    ai_profile_code = fields.Char(index=True, copy=False)
    ai_reason_code = fields.Char(copy=False)
    ai_occurrence_count = fields.Integer(
        default=1, copy=False,
        help="How many times this exception has recurred without being actioned. "
             "Visible so a human can see persistence rather than volume.")


class MailActivityType(models.Model):
    _inherit = 'mail.activity.type'

    ai_generated = fields.Boolean(
        default=False,
        help="Marks the activity types this platform creates, so a human can "
             "filter its work from everybody else's.")
