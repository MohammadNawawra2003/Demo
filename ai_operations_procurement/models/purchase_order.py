from odoo import fields, models


class PurchaseOrder(models.Model):
    """Document D §13. The idempotency key is namespaced.

    Uniqueness is on ``(company_id, ai_idempotency_key)``. A globally unique
    bare key would collide the moment two of the three demo companies, or two
    profiles, hit the same purpose, product, location and date — and the second
    write would silently receive the first's record.
    """

    _inherit = 'purchase.order'

    ai_idempotency_key = fields.Char(index=True, copy=False)
    ai_approval_required = fields.Boolean(
        copy=False,
        help="An AI recommendation on this record exceeded the routine variance "
             "bound and requires manager approval. A plain flag: there is no "
             "approval state machine, and approval is a human pressing Confirm.")
    ai_deterministic_qty = fields.Float(
        copy=False,
        help="What Odoo computed. Shown beside the recommendation, never merged "
             "with it.")
    ai_variance_pct = fields.Float(copy=False)

    _ai_idempotency_key_uniq = models.Constraint(
        'unique(company_id, ai_idempotency_key)',
        'An AI-generated purchase order already exists for this key.',
    )
