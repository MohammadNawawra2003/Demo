# 2026-09-04 — Documents A–D: pre-freeze critical review and correction

**Type:** documentation. **No module code written, no tests run** — there is no code yet.
**Verification method:** every Odoo claim checked against shipped source on this server
(`/opt/odoo19/odoo`, `/opt/odoo19/enterprise`); Anthropic claims against the current API reference.

## Versions
| Doc | Before | After |
|---|---|---|
| A — Demo Company Blueprint | 1.0 | **1.2** |
| B — AI Operations Flow Design | 1.0 | **1.3** |
| C — Phase 1 Security Kernel Spec | 0.1 | **0.4** |
| D — Implementation Contract | 0.1 | **0.4** |

## Findings resolved
7 blockers · 11 high · 11 medium · 5 editorial. Review report: `scratchpad/ai_operations_prefreeze_review.md`
(session-scoped). Each correction is recorded in-document alongside the value it replaced.

## Architectural changes
1. **One runtime** for CHAT and CRON inside `ai_operations`; the Enterprise `ai` app is no longer the interactive
   runtime and `ai_operations_bridge` becomes optional. Dissolved four defects at once (dispatch shape, swallowed
   denial, `ai_tool_schema` drift, missing `session_id`) and made the platform Community-installable, since the
   chat surface is a `discuss.channel` and `discuss.channel` lives in `mail`.
2. **Generic provider layer** — `provider_code` / `model_code` through a **frozen** registry (`@ai_provider`),
   three-method interface (`get_models` / `complete` / `health_check`), adapter-owned credential names. The kernel
   contains no vendor string; CI check 16 enforces it. Anthropic is the Phase 1 adapter, not a kernel assumption.
3. **Bound breach escalates** (draft created + `approval_required` + manager activity); only a +100% ceiling denies.
4. **Approval permission fields and guard step 16 deleted** — there is no approval state machine.
5. **Secrets out of the ORM** — environment / `odoo.conf` only, because `ir.config_parameter` is
   `group_system`-only and a DB-stored key would have forced the first `sudo()` into the kernel.
6. **Kernel purged** of relations outside `base`/`mail` (CI check 15).
7. **Activity routing** configured per profile, fail closed via new `ASSIGNEE_UNRESOLVED`.
8. **Warehouse-scoped user security promoted out** to `stock_security_warehouse` (depends on `stock` only).

## Demo-data corrections (Document A)
- Treated water is **lot-tracked** (`WT-{YYMMDD}-{SEQ}`) — the recall scenario is untraceable without it.
- WT capacity **640→900 m³/day feed**, **1.20 process-water factor** on every BoM. The v1.0 plant could not
  physically make its stated 199.3M L/yr, and was 147% oversubscribed at the July peak.
- FG-330 transfer price **5.76 → 5.86**, bringing the markup inside the §3 14–26% band.
- Accounting history **~120k → ~18k** journal items; no Phase 1 agent may read `account.move`.
- `quality` → **`quality_control` + `quality_mrp` + `quality_mrp_workorder`**; MO/work-order checks need them.
- L1/L2 load relabelled (4,493 h is **per line**, not combined); WT utilisation is 89%, not "85% yield".
- "Reproducible byte for byte" → deterministic **business values** verified by checksum.

## Odoo 19 idiom corrections carried into the code samples
`odoo.osv.expression.AND` → `odoo.fields.Domain`; `_sql_constraints` list → `models.Constraint(...)`.
Both appear in samples that fourteen build sessions would have copied verbatim.

## Test matrix
93 unique ids. Added: T-09, T-19, T-39/T-40, T-57, T-69/T-70/T-71, T-72/T-73/T-74a–e, T-86/T-87, T-99, T-100.

## Files touched
`01-demo-company-blueprint.md` · `02-ai-operations-flow-design.md` · `03-phase1-security-kernel-spec.md` ·
`04-implementation-contract.md` · `05_progress.md` (new) · `prompts/SESSION_01_KERNEL_SKELETON_PROMPT.md` (new)

## Test results
None. No code exists. The matrix is specification, not results.
