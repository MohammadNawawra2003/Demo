from odoo import fields, models


class MrpProduction(models.Model):
    _inherit = 'mrp.production'

    ai_idempotency_key = fields.Char(index=True, copy=False)

    _ai_idempotency_key_uniq = models.Constraint(
        'unique(company_id, ai_idempotency_key)',
        'An AI-generated manufacturing record already exists for this key.',
    )
