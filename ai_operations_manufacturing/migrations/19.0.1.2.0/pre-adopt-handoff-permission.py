"""Hand the handoff permission over from the demo module to this pack.

Manual Test 3 found that this pack shipped ``manufacturing.raise_handoff`` and
the ``MATERIAL_SHORTAGE`` type but no model permission on
``ai.operations.handoff``, so the guard refused the pack's own tool.
``ai_operations_demo_data`` compensated by creating the row in Python, which
means it carries **no external id**. The pack now ships the record properly, and
on any database that ran the demo module the two collide on
``unique(profile_id, model_id)``.

Delete only the unowned duplicate — a row with no ``ir.model.data`` behind it —
so the pack's own record can be created and thereafter maintained normally. A
row someone created deliberately in the UI would also be unowned, but for this
exact profile and this exact model the demo module is the only thing that ever
made one, and the pack immediately recreates it with the same rights.
"""


def migrate(cr, version):
    cr.execute("""
        DELETE FROM ai_operations_model_permission mp
        USING ai_operations_agent_profile p, ir_model m
        WHERE mp.profile_id = p.id
          AND mp.model_id = m.id
          AND p.code = 'manufacturing'
          AND m.model = 'ai.operations.handoff'
          AND NOT EXISTS (
              SELECT 1 FROM ir_model_data d
              WHERE d.model = 'ai.operations.model.permission'
                AND d.res_id = mp.id)
    """)
