---
title: ai_operations — progress log
tags: [product, ai, progress]
status: active
updated: 2026-09-04
---

# `ai_operations` — Progress Log

Product docs: `01-demo-company-blueprint.md` (A) · `02-ai-operations-flow-design.md` (B) ·
`03-phase1-security-kernel-spec.md` (C) · `04-implementation-contract.md` (D).
Code: **none yet** — Session 1 has not started. Build sequence: Document C §17 (14 sessions, STOP gate each).

**Phase status:** documentation → **A–D freeze-ready**. Next: Session 1 (kernel skeleton).

---

## 2026-09-04 — Session: pre-freeze critical review of A–D

**Scope.** Documentation only. **No module code was written, and no tests were run** — there is no code yet.
Every Odoo and Anthropic claim asserted below was verified against shipped source on this server
(`/opt/odoo19/odoo`, `/opt/odoo19/enterprise`) or against the current Claude API reference, not from memory.

### COMPLETED
- Full critical review of Documents A–D → **7 blockers, 11 high, 11 medium, 5 editorial**. Report:
  `scratchpad/ai_operations_prefreeze_review.md` (session-scoped; findings are folded into the docs below).
- All findings resolved across the four documents, each correction stating what the prior version said and why
  it moved, so the freeze record carries the reasoning rather than only the result.
- **A → v1.2** · **B → v1.3** · **C → v0.4** · **D → v0.4**. Input/substrate chain consistent across all four.
- Test matrix: **93 unique ids**, no duplicates, every `DenialReason` covered.

### Decisions taken (George, this session) — see also each document's decision register
| # | Decision |
|---|---|
| 1 | **One runtime.** `ai_operations` owns the loop for both CHAT and CRON. The Enterprise `ai` app is not the interactive runtime; the bridge becomes optional. Consequence: the chat surface is a `discuss.channel`, which lives in `mail` — **the whole platform runs on Odoo Community** |
| 2 | **Provider layer is generic.** `provider_code` / `model_code` resolved through a **frozen** provider registry; the kernel names no vendor, no endpoint, no credential variable. Phase 1 ships `ai_operations_anthropic` only |
| 3 | **Bound breach escalates, never denies.** Draft is created and stamped `approval_required`, activity goes to the manager. A +100% hard ceiling still denies with `BOUND_EXCEEDED` |
| 4 | **Approval permission fields deleted** along with guard step 16. There is no approval state machine; approval is a human pressing the native Confirm button |
| 5 | **API key lives in the environment / `odoo.conf`**, never the database. The adapter owns the variable name |
| 6 | **Treated water is lot-tracked** — without it `trace_forward` has nothing to traverse and the recall demo cannot run |
| 7 | **WT capacity raised** to 900 m³/day feed + a 1.20 process-water factor on every BoM |
| 8 | **Accounting history trimmed** to three months invoiced (~18k journal items, was ~120k) |
| 9 | **Kernel purged** of every relation outside `base`/`mail` |
| 10 | **Activity routing** = `default_review_user_id` / `default_escalation_user_id` per profile, fail closed via the new `ASSIGNEE_UNRESOLVED` |
| 11 | **Warehouse-scoped user security promoted out** to a standalone `stock_security_warehouse` addon — Odoo authorisation, not an AI concern |

### The blockers, and what they were
1. **Treated water was not lot-tracked** → the headline recall scenario and T-96 could not run.
2. **The plant could not make its own stated output** — WT at 546 m³/day × 365 = exactly the annual requirement,
   zero CIP/rinse/downtime allowance, and 147% of rated capacity at the July peak. WT, not line changeovers, is
   the real binding constraint; §7 now says so.
3. **Autonomy composition was `min(ceiling, floor, floor)`** — meaningless; now `max(floors) <= ceiling`.
4. **The +20% bound contradicted itself three ways** inside the flagship cascade (step 17 called +27.6% "within
   bound", step 22 said it breached, T-37 made it a denial while steps 18–22 needed the draft to exist).
5. **The API key could not be read without `sudo()`** — `ir.config_parameter` is `group_system`-only and
   `get_param()` calls `check_access('read')`, while `sudo()` is banned and CI-grepped.
6. **The kernel broke its own `base + mail` rule** — `department_id`→`hr`, `agent_id`→`ai`,
   `product_category_id`→`product`. Bare-database CI would have failed on day one of Session 1.
7. **The Enterprise `ai` app cannot talk to Claude** — `PROVIDERS` is a hardcoded OpenAI/Google list. The split
   runtime meant GPT-4o in chat and Claude on cron, never stated.

### NOT DONE, and why
- **No code.** By design — this session's contract was review and correction of the specification.
- **No tests run.** There is nothing to test. The 93 matrix ids are specification, not results.
- Documents are **freeze-*ready*, not frozen**. Freeze is George's sign-off action on the §21 / §17 checklists.

### DEVIATIONS
None from a frozen spec — nothing was frozen. Every change is recorded in-document with its prior value.

### NEW RISKS
| Risk | Where |
|---|---|
| Demo history generation (~250k records through the ORM with AVCO) sits on the critical path of every scenario test. Split into Sessions 6 and 7, but it remains the largest schedule risk | C §20 |
| `base.group_system` can still widen a service user's ORM rights by editing `ir.model.access` / `ir.rule`. Bounded by the agent allowlist, not eliminated. Inherent to Odoo | C §20 |
| Provider change alters data egress, not permissions — a residency/contractual question for a Saudi client, deliberately outside the parity rule | C §6.3, §20 |

### STATE FOR NEXT SESSION
A–D internally consistent, freeze-ready. Session 1 = kernel skeleton, groups, `agent.profile`,
`model.permission`, `action.permission`, ACLs, views. **STOP gate before Session 2.**
Paste-one-file resume: `prompts/SESSION_01_KERNEL_SKELETON_PROMPT.md`.

### MANUAL STEPS (George)
1. **Sign the freeze** — Document C §21 and Document D §17 checklists; A §19 and B §17 are already ticked.
2. **Provision `ODOO_AI_ANTHROPIC_TOKEN`** in the dev environment before Session 5 (never in the database).
3. **Confirm the Enterprise licence position** — the demo DB needs `quality_mrp` / `quality_mrp_workorder`;
   the *platform* itself must keep installing on Community (CI check 14).
4. Decide whether `stock_security_warehouse` gets its own repo now or is extracted after Phase 1.

### Session log (raw, this session)
- [x] Review of A–D against shipped Odoo 19 source · [x] A v1.1 · [x] B v1.1 · [x] C v0.2 · [x] D v0.2
- [x] Provider abstraction → C v0.3, D v0.3, B v1.2
- [x] Two freeze decisions → A v1.2, B v1.3, C v0.4, D v0.4
- [x] Cross-check: 93 unique test ids, no stale idioms, version chain aligned
- [x] Lessons captured to both stores (skills §178 + `20_Wiki/Odoo/`)
