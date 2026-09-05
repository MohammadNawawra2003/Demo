# Session 1 — `ai_operations` kernel skeleton

**Paste this file to resume. It is the whole contract for one session.**

## Open
1. `/opt/odoo19/vault/Products/ai_operations/05_progress.md` — where we left off, MANUAL STEPS.
2. Documents **C v0.4** (`03-phase1-security-kernel-spec.md`) and **D v0.4** (`04-implementation-contract.md`).
   C is what to build; D is what the code must look like. **They are frozen — deviations are a Change Request.**
3. Skills sweep: `grep -n "^## " /root/.claude/projects/-opt-odoo19/memory/odoo19_skills.md`, then read only the
   matching §§. **§178 is mandatory reading** (the Enterprise `ai` app; why we own the runtime).
   Also §§ on security ladders, v19 breaking changes, testing on the shared server.
4. `vault/30_Systems/Odoo-Build-System/odoo_build_standards.md` — FROZEN, binding.

## Precondition — confirm before writing a line
This session's deliverable is a kernel that depends on **`base` and `mail` only**. If any instruction in this
prompt appears to require `hr`, `product`, `stock`, `purchase`, `mrp`, `quality*` or `ai`, that is a defect in
the prompt, not permission to add a dependency. **Stop and ask.**

## Do — Document C §17 Session 1, Document D §16 definition of done
Build under `/opt/odoo19/products/internal/ai_operations/`:

- Module skeleton + manifest exactly as D §3.1 — `'depends': ['base', 'mail']`, nothing else, ever.
- `services/enums.py` and `services/exceptions.py` complete (D §4, §5). Note two things that are easy to get
  wrong: `AuditLevel` has **no `NONE`**, and `AIAccessDenied.__str__` returns `NEUTRAL_DENIAL` **by
  construction** — the reason, model and detail live on attributes and reach only the audit log.
- Five security groups with the D §11 separation (User · Approver · Auditor · Security Admin · Technical Admin).
- `ai.operations.agent.profile` (C §5.1), `ai.operations.model.permission` (C §5.2),
  `ai.operations.action.permission` (C §5.3), with **all** constraints:
  - `max_autonomy_level > 2` raises · `allow_autonomous` without `service_user_id` raises
  - `service_user_id` in `base.group_system` raises
  - review/escalation users: required, internal, in company scope, not the service user, not `group_system`
  - domain validator rejects a lambda, a callable and unparseable text (`ast.literal_eval`, never `eval`)
  - `state_restriction` parses as `field=value` — a bare value is invalid
- ACLs + record rules + views + menus.
- Use the **Odoo 19 idioms**: `models.Constraint(...)`, `odoo.fields.Domain`. Not `_sql_constraints`, not
  `odoo.osv.expression`.

## STOP gate — do not start Session 2 until every line is true
- [ ] `ai_operations` installs on a **bare database** and on **Odoo Community**
- [ ] No `Many2one` in the kernel targets a model outside `base` / `mail` (CI check 15)
- [ ] `str(AIAccessDenied(...))` is the neutral message; the reason is on the attribute
- [ ] Every constraint above fires in a test that asserts the specific failure
- [ ] Auditor group can read and cannot write; Security Admin cannot enable a tool; Technical Admin cannot
      alter a permission
- [ ] CI checks 1, 3, 4, 10, 12, 14, 15 green
- [ ] Test method names carry their matrix ids (D §2, §14)

## Close
Run `/close-session`. Tick the Session 1 row in C §17 **only** if the STOP gate passed on a dev clone.

## Do NOT, in this session
Tools · the guard · the serialiser · any provider adapter · any business logic · any tool pack · the demo data.
C §17 puts the access-control model first on purpose: it must stop changing before anything is debugged on top
of it.
