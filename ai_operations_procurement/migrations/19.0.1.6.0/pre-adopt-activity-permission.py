"""Hand the ``mail.activity`` permission over to this pack on a hotfixed database.

Same failure as ``ai_operations_manufacturing/migrations/19.0.1.2.0``, from the
other direction. `22f3ee2` shipped ``perm_mail_activity_p`` in the pack after
George's demo refused ``procurement.create_review_activity``. But by then the
row already existed on staging: someone had created it by hand in the UI on
2026-09-07 at 14:11 to get past the refusal during the session, and a row made
that way carries **no external id**.

So the upgrade that was supposed to deliver the fix could not run at all:

    psycopg2.errors.UniqueViolation: duplicate key value violates unique
    constraint "ai_operations_model_permission_model_permission_uniq"
    DETAIL:  Key (profile_id, model_id)=(319, 166) already exists.
    ParseError: while parsing ai_operations_procurement/data/policy_pack.xml:189

That aborts the whole registry load, which means **every build of this branch
failed at this record** and the platform kept serving the previous one. The
symptom looked like "Odoo.sh is not deploying"; the cause was a manual hotfix
from the day before colliding with the permanent fix for the same bug.

Delete only the unowned duplicate — a row with no ``ir.model.data`` behind it —
so the pack's own record can be created and maintained normally thereafter. The
rights are identical either way, so nothing an agent can do changes; what changes
is that the row is owned by the module instead of by whoever typed it.

Scoped to this one profile and this one model on purpose. A blanket "delete every
unowned permission row" would also delete a client's deliberate customisation,
and a deploy script that silently discards configuration is worse than a failed
build.
"""


def migrate(cr, version):
    cr.execute("""
        DELETE FROM ai_operations_model_permission mp
        USING ai_operations_agent_profile p, ir_model m
        WHERE mp.profile_id = p.id
          AND mp.model_id = m.id
          AND p.code = 'procurement'
          AND m.model = 'mail.activity'
          AND NOT EXISTS (
              SELECT 1 FROM ir_model_data d
              WHERE d.model = 'ai.operations.model.permission'
                AND d.res_id = mp.id)
    """)
