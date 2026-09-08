"""Reword the Accountant's own description, because the model reads it.

``build_system_prompt`` returns ``profile.description`` verbatim -- it IS the
system prompt. The original ended "it holds no permission on any of the models
those actions need", and on staging the agent dropped the qualifier and
answered, three times in seven runs, that it "has no permission to use
accounting tools" and "is designed without permissions to run any tool". It
then called nothing at all, while holding four assigned and enabled tools.

Nothing was wrong with the configuration. The sentence was.

The General Manager profile, which is read-only in exactly the same way and has
never once refused, says "no WRITE capability of any kind" -- the restriction is
scoped to writing and cannot be read as a statement about tools. This rewrites
the Accountant to that shape and leads with what it CAN do.

``policy_pack.xml`` is ``noupdate="1"``, so the corrected text reaches a fresh
install and would never reach an existing database without this. Scoped to a
description that still matches the original, so a deliberate customisation is
left alone.
"""

NEW = (
    "Read-only financial reporting. You have four working tools and you "
    "should use them: receivable ageing, payable ageing, unpaid customer "
    "invoices, and invoiced revenue by period. Answer financial questions by "
    "calling them. You have no WRITE capability of any kind -- you cannot "
    "post a journal entry, validate a payment, change a reconciliation, "
    "change a tax or touch bank data -- but reading and reporting is exactly "
    "what you are for."
)


def migrate(cr, version):
    """Rewrite the stale prompt, whichever stale version this database holds.

    Two are known. The pre-amendment text shipped by 79ee90f, when the agent
    genuinely had nothing:

        "Financial reporting and analysis. PHASE 2: this agent holds no tools
         and no model permissions in Phase 1. ..."

    and the later text, which still ended "it holds no permission on any of the
    models those actions need."

    The first is the one actually on staging, and it is worse than a dropped
    qualifier: it tells the model it holds no tools and no permissions in the
    same request that hands it four tool definitions. c7d3ccf gave the agent its
    tools and left the sentence behind.

    ``PHASE 2:`` is the anchor -- no other profile carries it and nobody would
    write it deliberately. A description matching neither pattern is somebody's
    own and is left alone.
    """
    cr.execute("""
        UPDATE ai_operations_agent_profile
           SET description = %s
         WHERE code = 'accounting'
           AND (description LIKE %s
                OR description LIKE %s
                OR description LIKE %s)
    """, (NEW, '%PHASE 2%', '%holds no tools%', '%holds no permission%'))
