"""Clear the way for the permissions this version ships, on a hand-edited database.

The same failure class as ``ai_operations_procurement/migrations/19.0.1.6.0``.
On 2026-09-10 the Accountant was given ``account.account`` and a free-text
"draft bill" action by hand in the UI, trying to make it record a bill. A row
made that way carries no external id, so:

* ``perm_account_account_a`` would collide on
  ``ai_operations_model_permission_model_permission_uniq`` and abort the whole
  registry load -- every build of the branch failing at one record; and
* an unowned ``CREATE_DRAFT`` row on ``account.move`` has no unique constraint
  to collide on, but ``check_action`` reads ``limit=1``, so it could be the row
  the guard finds instead of the pack's one -- the one carrying the amount
  ceiling. A ceiling that a stray row can shadow is not a ceiling.

Deleted: only unowned rows, only on the Accountant, only on those two exact
shapes. A blanket sweep would discard somebody's deliberate configuration. An
``__export__`` id -- the one a UI export stamps -- is not ownership, and such a
row would still collide, so it counts as unowned.
"""


def migrate(cr, version):
    cr.execute("""
        DELETE FROM ai_operations_model_permission mp
        USING ai_operations_agent_profile p, ir_model m
        WHERE mp.profile_id = p.id
          AND mp.model_id = m.id
          AND p.code = 'accounting'
          AND m.model = 'account.account'
          AND NOT EXISTS (
              SELECT 1 FROM ir_model_data d
              WHERE d.model = 'ai.operations.model.permission'
                AND d.res_id = mp.id
                AND d.module != '__export__')
    """)
    cr.execute("""
        DELETE FROM ai_operations_action_permission ap
        USING ai_operations_agent_profile p, ir_model m
        WHERE ap.profile_id = p.id
          AND ap.model_id = m.id
          AND p.code = 'accounting'
          AND m.model = 'account.move'
          AND ap.action_code = 'CREATE_DRAFT'
          AND NOT EXISTS (
              SELECT 1 FROM ir_model_data d
              WHERE d.model = 'ai.operations.action.permission'
                AND d.res_id = ap.id
                AND d.module != '__export__')
    """)
