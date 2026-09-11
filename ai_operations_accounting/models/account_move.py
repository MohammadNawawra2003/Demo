from odoo import fields, models


class AccountMove(models.Model):
    """The marker an agent-drafted bill or entry carries.

    Same shape as ``purchase.order.ai_idempotency_key`` in the procurement pack:
    the key is built by the tool from the business facts, never taken from the
    model, and it is what makes the same request twice produce one draft. The
    demo reset finds agent drafts by it and by nothing else.
    """
    _inherit = 'account.move'

    ai_idempotency_key = fields.Char(index=True, copy=False, readonly=True)

    _ai_idempotency_key_uniq = models.Constraint(
        'unique(company_id, ai_idempotency_key)',
        'An agent already drafted this entry for this company.',
    )
