"""Give an existing database what policy_pack.xml gives a fresh one (DL-010).

The pack is ``noupdate="1"``. On upgrade Odoo creates the two NEW records
(``perm_account_account_a``, ``action_create_draft_move``) and leaves the
existing profile and ``perm_account_move_a`` exactly as 19.0.1.2.0 shipped them:
read-only. The drafting tools would then ship, be assigned, and be refused on
every call -- at guard step 15 for autonomy and on ``perm_create``.

Scoped like the 19.0.1.2.0 migration: a profile value moves only while it still
holds what the previous version shipped, so a deliberate change survives.

``perm_account_move_a`` is set to the pack's exact values instead. That row is
owned by this module, and on staging it had been hand-edited to ``perm_write``
during the same attempt to get a bill recorded. No tool here updates or deletes
a move, so a write grant would be a risk with no use.
"""

from odoo import SUPERUSER_ID, api

PREVIOUS = (
    "Read-only financial reporting. You have four working tools and you "
    "should use them: receivable ageing, payable ageing, unpaid customer "
    "invoices, and invoiced revenue by period. Answer financial questions by "
    "calling them. You have no WRITE capability of any kind -- you cannot "
    "post a journal entry, validate a payment, change a reconciliation, "
    "change a tax or touch bank data -- but reading and reporting is exactly "
    "what you are for."
)

CURRENT = (
    "Financial reporting and draft bookkeeping. To report, call your tools: "
    "receivable ageing, payable ageing, unpaid customer invoices, and invoiced "
    "revenue by period. To record, prepare drafts: a vendor bill, for example "
    "from a bill image the user attaches, or a journal entry. Find the vendor "
    "with find_partners and the account codes with find_accounts first, then "
    "call the draft tool once. You cannot post: every draft waits for an "
    "accountant to review and confirm it, so say so, and report the totals "
    "Odoo computed next to the document's. You cannot register a payment, "
    "reconcile, change a tax or touch bank data."
)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {'active_test': False})
    profile = env['ai.operations.agent.profile'].search(
        [('code', '=', 'accounting')], limit=1)
    if profile:
        values = {}
        if profile.max_autonomy_level == '0':
            values['max_autonomy_level'] = '2'
        # 0 is what the demo wrote for a read-only agent; 3 is the kernel
        # default the 19.0.1.2.0 pack shipped by not setting the field.
        if profile.max_write_ops in (0, 3):
            values['max_write_ops'] = 2
        if (profile.description or '').strip() == PREVIOUS:
            values['description'] = CURRENT
        if (profile.policy_version or '').startswith('1.1.'):
            values['policy_version'] = '1.2.0'
        if values:
            profile.write(values)

    grant = env.ref('ai_operations_accounting.perm_account_move_a',
                    raise_if_not_found=False)
    if grant:
        grant.write({'perm_read': True, 'perm_create': True,
                     'perm_write': False, 'perm_unlink': False})
