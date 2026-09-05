# AI Operations — AlShayeb AI Operations Platform for Odoo 19

A security kernel that happens to run AI.

The selling proposition is one sentence: **the prompt is not the boundary.** An agent asked for
data outside its scope fails at an ORM permission check — and fails identically when its own system
prompt has been rewritten to demand that data.

```
EFFECTIVE = USER_PERMISSION
          ∩ AGENT_PERMISSION
          ∩ TOOL_PERMISSION
          ∩ ACTION_POLICY
          ∩ COMPANY_SCOPE
```

The agent layer can only ever **subtract** from what the person running it could already do.
`sudo()` is banned in this codebase and grepped for in CI.

## Status

| | |
|---|---|
| Phase | 1 of 1 specified — Session **1 of 14** complete |
| Target | Odoo 19.0, Odoo.sh (`mohammadnawawra2003-demo`) |
| Kernel dependencies | `base`, `mail` — **nothing else, ever** |
| Session 1 suite | **54 tests, 0 failed, 0 errors**, on a bare Community database |

Specification: Documents A–D in `docs/`. Review: `docs/reviews/`.
They are **freeze-ready, not frozen** — see `DEVIATIONS.md` for what this build changed and why.

## Modules

| Module | Depends | State |
|---|---|---|
| `ai_operations` | `base`, `mail` | **Session 1 built** — groups, agent profile, model & action permissions |
| `ai_operations_anthropic` | `ai_operations` | Session 5 |
| `ai_operations_procurement` / `_inventory` / `_manufacturing` / `_quality` | `ai_operations` + domain apps | Sessions 8–11 |
| `ai_operations_bridge` | `ai_operations`, `ai` | Optional. Discoverability only; routes no tool call |
| `stock_security_warehouse` | `stock` — and nothing else | Separate product, ships alongside |
| `alshayeb_demo_water` | domain apps — **not** `ai_operations` | Sessions 6–7 |

## What Session 1 delivers

- `services/enums.py` — the single source of truth for every selection. `AuditLevel` has no `NONE`:
  it could only ever mean "disable the security log".
- `services/exceptions.py` — `AIAccessDenied` whose `str()` is the neutral message **by
  construction**, so no call site can leak the reason by forgetting to neutralise it.
- `services/validators.py` — the domain validator (`ast.literal_eval`, never `eval`) and the
  `field=value` state-restriction parser.
- Four security groups with the Document C §11 separation.
- `ai.operations.agent.profile`, `.model.permission`, `.action.permission` with every constraint.
- ACLs, company record rules, views, menus.

Not in this session, on purpose: tools, the guard, the serialiser, any provider adapter, any
business logic, any tool pack, the demo data. Document C §17 puts the access-control model first
because it must stop changing before anything is debugged on top of it.

## Running the tests

```bash
odoo-bin -d <db> \
  --addons-path=<odoo>/addons,<odoo>/odoo/addons,<this repo> \
  -i ai_operations --test-enable --test-tags=/ai_operations --stop-after-init
```

The addons path deliberately excludes `enterprise/`: the kernel must install and pass on
**Community** (CI check 14), and a bare database (CI check 3). Both are verified this way.

## The CI gate

| # | Check | Session 1 |
|---|---|---|
| 1 | No `.sudo()` call anywhere | ✅ |
| 3 | Installs and passes on a **bare database** | ✅ |
| 4 | No import of `odoo.addons.ai` outside the bridge | ✅ |
| 10 | No selection list declared outside `enums.py` | ✅ |
| 12 | Odoo 19 idioms only — no `_sql_constraints`, no `expression.AND` | ✅ |
| 14 | Installs and passes on **Odoo Community** | ✅ |
| 15 | No relational field targets a model outside `base` / `mail` | ✅ |
| 16 | The kernel names no vendor, endpoint or credential variable | ✅ |

Checks 2, 5–9, 11, 13 and 17 apply to code that does not exist yet.
