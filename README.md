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
| Phase | 1 of 1 specified — Session **7 of 14** complete |
| Target | Odoo 19.0, Odoo.sh (`mohammadnawawra2003-demo`) |
| Kernel dependencies | `base`, `mail` — **nothing else, ever** |
| Suite | **287 tests, 0 failed, 0 errors** across five modules |
| Matrix ids covered | T-01…T-08, T-09, T-10…T-23, T-25, T-41…T-45, T-60…T-74a, T-86, T-100 |

Specification: Documents A–D in `docs/`. Review: `docs/reviews/`.
They are **freeze-ready, not frozen** — see `DEVIATIONS.md` for what this build changed and why.

## Modules

| Module | Depends | State |
|---|---|---|
| `ai_operations` | `base`, `mail` | **Session 1 built** — groups, agent profile, model & action permissions |
| `ai_operations_anthropic` | `ai_operations` | **built** — the Phase 1 provider adapter |
| `ai_operations_procurement` / `_inventory` / `_manufacturing` / `_quality` | `ai_operations` + domain apps | Sessions 8–11 |
| `ai_operations_bridge` | `ai_operations`, `ai` | Optional. Discoverability only; routes no tool call |
| `stock_security_warehouse` | `stock` — and nothing else | **built** — 10 tests |
| `alshayeb_demo_water` | domain apps — **not** `ai_operations` | **master data built** (Session 6); history is Session 7 |

## What Session 5 delivers

- `services/provider.py` — the interface and a **frozen** registry. A tool is a bounded capability
  behind the guard; a provider adapter is the egress point for the fully assembled context, so a
  runtime-registerable one would be an exfiltration primitive with full authorisation behind it.
- `services/execution.py` — **the** loop. Chat and cron are two triggers into one runner, so
  divergence is impossible rather than policed. Denials reach the model as a fixed neutral string.
- `ai_operations_anthropic` — the Phase 1 adapter. Every vendor string lives here; the kernel has
  none. The credential comes from the environment or `odoo.conf`, never the ORM.
- `ai.operations.budget` — the daily token counter, deliberately off the policy record.
- Service users that carry no usable credential and cannot authenticate at all.

### Running the live test (optional, costs a few tokens)

```bash
odoo-bin -d <db> --test-enable --test-tags=ai_live --stop-after-init
```

Excluded from every normal run. The rest of the adapter is covered offline.

## What Session 4 delivers

- `services/serializer.py` — the output sanitiser. It works by **omission**: a schema declares what
  may be emitted and nothing else can be. `bank_ids` is not excluded, it is unreachable. Every
  relational hop re-checks the model permission on the *target* model, so a dotted path cannot walk
  out of the agent's scope one dot at a time.
- `services/blocklist.py` — defence in depth, never the defence. A hit means an output schema is
  wrong, so it raises, audits as a security event, and fails the build.

## What Session 3 delivers

- `services/security_service.py` — the guard, Document C §7. Every `check_*` returns `None` or
  raises; none returns a boolean, because a boolean invites `if not check(): pass`.
- `services/context.py` — `ExecutionContext`, frozen. `ctx.model()` exists so the permitted path is
  shorter to type than the unpermitted one.
- `ai.operations.audit.log` — **append-only**: one row per event, `write()` and `unlink()` refuse.
  The row opens *before* the guard runs, so a denial can never escape unlogged.
- Record rules: a user reads only their own audit entries; the Auditor reads everything.

## What Session 2 delivers

- `services/schema.py` — declarative schemas, zero dependencies. Validation is **rejection**: an
  undeclared key raises rather than being dropped, because silently normalising an attempted leak
  into a success is the failure mode this design exists to prevent. `to_json_schema()` is the only
  path a tool's parameter shape reaches the LLM, so what the model is told cannot drift from what
  the validator accepts.
- `services/registry.py` — the `@ai_tool` decorator. Rejects at **registration**, not at review: a
  parameter named `model`/`method`/`domain`, `models=['*']`, a missing schema, a signature that
  isn't `(ctx, params)`, or a missing docstring all prevent module load.
- `ai.operations.tool` / `ai.operations.tool.assignment` — configuration records that mirror the
  decorator and cannot outrun it. A tool record whose code has no registry entry **cannot be
  enabled**. No assignment means no access; there is no default grant.
- `core.describe_scope` — one Level-0 read tool, so the registry is exercised by something real.

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
