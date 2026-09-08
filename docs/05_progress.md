---
title: ai_operations — progress log
tags: [product, ai, progress]
status: active
updated: 2026-09-08
---

# `ai_operations` — Progress Log

Product docs: `01-demo-company-blueprint.md` (A) · `02-ai-operations-flow-design.md` (B) ·
`03-phase1-security-kernel-spec.md` (C) · `04-implementation-contract.md` (D).
Code: **twelve modules, 628 passing tests / 0 failed / 0 errors** at `4e6e9cd`, which is the head of
both `development` and `stage`. Measured 2026-09-08 across all twelve modules on one database.
The bare-database kernel run is **361 tests / 0 failed**. Two further tests live in
`ai_operations_anthropic/tests/test_live.py`, tagged `-standard`, and never run in a normal suite —
which is the whole of the gap between the static count and the reported one.
Build sequence: Document C §17 (14 sessions, STOP gate each) — all fourteen built.

**Phase status:** **Documents A, B, C and D are closed against the implementation, then amended** —
three post-freeze owner decisions of 2026-09-07 changed the roster after the freeze, and C and D each
carry that amendment at their head. Compatibility deviations are recorded in `DEVIATIONS.md`; the
seventeen frozen CI controls are executable at `tools/ci_checks.sh` (**16 pass, 0 fail, 2 skip** —
the two skips need a database, and seven of the rest are held by the suite, not by the grep).
The Community claim is scoped, not global — see the support matrix in the 2026-09-08 checkpoint
at the foot of this file. **One item remains open: the credential's durability
on Odoo.sh.**

**The customer demo is not complete.** A deterministic local fixture exists; the staging run, the
Arabic prompt runbook and the real-provider proof do not. The checkpoint says exactly what is missing.

---

## 2026-09-04 — Session: pre-freeze critical review of A–D

> *Historical entry. This section records the state on 2026-09-04, when the specification existed and
> no module code did. Its "no code yet" scope, its counts and its manual steps describe that day, not
> today — for current state read the 2026-09-08 checkpoint at the foot of this file.*

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
| 1 | **One runtime.** `ai_operations` owns the loop for both CHAT and CRON. The Enterprise `ai` app is not the interactive runtime; the bridge becomes optional. Consequence: the chat surface is a `discuss.channel`, which lives in `mail` — **the kernel and the whole conversational half run on Odoo Community**. Corrected 2026-09-08: that holds for the Community tier, not for every module; the `quality_mrp`-dependent packs and the demo database are Enterprise (Document C §4) |
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

---

## 2026-09-07 — Documents A, B, C and D closed against the code

**Scope.** Four gap audits, each followed by implementation, tests and a push to
`development` and `stage`. `main` untouched throughout. Production untouched.

**Test count: 499 → 599.** Every count below was measured on a fresh install onto a bare
database as well as on the upgrade path.

### Document A — the demo company

The decisive finding was one line: `data_xml/build.xml` called `build_all` and nothing
else, so `alshayeb.demo.history.generate` — written in Session 7 — had **never been
invoked by anything**. Every installed database had zero manufacturing orders, zero sales
orders, zero invoices, zero quality checks and about twelve stock moves, and **fourteen of
§13's eighteen seeded conditions were absent, including every security condition except
X-05**. The isolation proofs were passing against an empty database.

Also closed: `product_expiry` was never a dependency, so §5.1's expiry and §8.2's FEFO were
*silently inert on every database ever built*; `Product Price` precision was 2, flattening
§5.2's costs (a cap is SAR 0.022 and was stored as 0.02); and §3's transfer price is now
derived from the BoM, because the literal table put five of six SKUs outside the documented
14–26% band and priced FG-200 **below plant cost**.

### Document B — the flow design

Acceptance went from **7 of 16 to 16 of 16**. Nineteen of §5's thirty-four tools existed;
`create_review_activity` was missing from all four packs, so §12's entire activity design
was implemented in the kernel and reachable by nothing, and the cascade ended at a draft
that reached no one's desk. Three of four handoff types did not exist. **Inventory and
Quality could not execute a single tool** — neither pack wired its assignments, so guard
step 4 denied everything.

### Documents C and D — the kernel and the contract

Six specified security properties were believed true and were not implemented. **Neither
registry was ever frozen.** **A policy could change and the log would not say so** —
`policy_version` was stamped on every row and never incremented anywhere. **`record_write`
had zero callers**, so what an agent changed was not recoverable. And all seventeen CI
checks D calls "a build failure, not a warning" existed only as prose; four of them fail on
correct code as written.

**Resolved — the CI checks now run.** `tools/ci_checks.sh` executes them, and its own arithmetic
is: **17 controls → 2 skipped (3 and 14, both needing a database) → 15 runnable → 16 result
lines**, because check 16 splits into 16a (no vendor name) and 16b (no credential variable) — as
written its `-i _TOKEN` clause matched `max_daily_tokens`. Last run **16 pass, 0 fail, 2 skip**.
The four that failed on correct code — 1, 4, 11 and 16 — were each a grep for a *word* rather
than a *call*, and run in corrected form with the original kept in the comment beside them.
Checks 7 and 8 stopped being prose and became `test_matrix_coverage.py`; check 7 failed on 25
ids, of which seven had no test at all — T-35, T-38, T-40, T-77, T-82, T-90 and T-91, the last
two being the whole of the Resilience acceptance section.

⚠ **A green script is not a green suite,** and it says so itself: checks 5, 6, 7, 8, 9, 13 and 17
are asserted by the test suite and by the registration guards in `registry.py` / `provider.py`,
not by the grep. Both have to be run.

⚠ **Check 14 is narrower than it reads.** It asserts every pack installs on Community, and four
modules now cannot. Its true scope is the tier table — see the support matrix in the 2026-09-08
checkpoint. The script skips it rather than asserting something false.

### Owner decisions this session
| # | Decision |
|---|---|
| 12 | **History runs at reduced scale**, not §14's literal counts — measured at 600 MB–1.2 GB against a 1 GB build cap. Shape over volume |
| 13 | **§16's XML layout is not adopted**; the Python builders stay, because they repair drift on upgrade |
| 14 | **§13 S-01 wins over the zero baseline** — the live demo walks the non-zero shortage path; DL-008 still holds and stays tested |
| 15 | **All four agents activated** in the demo, per §3's roster and §8's four crons |
| 16 | **An automated test per §11 isolation proof**, row 2 included — it is the go/no-go and was not the test the specification names |
| 17 | **The Accountant agent joins the roster with no tools and no scope.** Document B §1 puts Finance out of Phase 1 and §11 rows 1, 2 and 4 are built on accounting being unreachable. Giving it `account.move` would remove the property the platform is sold on — **superseded by owner amendment 2026-09-07, row 18** |

### Owner amendments after the freeze — 2026-09-07

George reviewed the platform on staging himself, got stuck, and gave direct product feedback.
Two roster decisions follow from it. Both amend documents that were already frozen, so both are
recorded rather than absorbed into a commit.

| # | Decision |
|---|---|
| 18 | **The Accountant becomes operational, read-only. Supersedes 17.** Amends Document B §1, C §4, D §3. Four aggregate read tools — receivable ageing, payable ageing, open customer invoices, revenue by month — at QUERY only. `perm_read` on `account.move`, `res.partner` and `res.currency`; no `perm_create`/`perm_write`/`perm_unlink` anywhere; **no action permission at all**, so guard step 15 has nothing to allow. No posting, no payment validation or registration, no reversal, no reconciliation change, no tax change, no bank data — each prohibited by the absence of the model it needs, and each carrying its own test. Row 17's argument was not wrong, it was aimed elsewhere: every isolation row it cited is about the four **operational** agents being refused financial data, and none of them gains a permission here. `test_accounting_roster.py` now asserts that per agent, by name |
| 19 | **A read-only General Manager**, new module `ai_operations_gm`. Amends Document B §1, which put a GM outside Phase 1. Six read tools — an operational summary across the five departments, stock exceptions, blocked production with the blocking component, late procurement, open quality issues, and company financial headlines — all `ToolCategory.READ` at `AutonomyLevel.QUERY`. Eleven `model.permission` rows, every one `perm_read`; **zero action permissions**; nothing on `ai.operations.handoff`, `mail.activity` or `mail.message`, so it cannot create work for anyone; write budget 0 as the demo builds it. The finance surface is one tool returning **seven scalars** — currency, receivable outstanding / overdue / overdue-count, payable outstanding / overdue / overdue-count — with no per-invoice, per-partner or per-line variant, and no revenue, margin or cash figure. It depends on `quality_mrp` so the GM can see open quality issues, which is what puts it in the Enterprise tier |

Neither change touches the four operational agents. `EFFECTIVE = USER ∩ AGENT ∩ TOOL ∩ ACTION ∩
COMPANY` still narrows both: a general manager whose own Odoo login cannot read invoices gets
nothing from the finance tool even though the profile permits the model, asserted against a real
user with real groups rather than argued from the design.

> *Rows 18 and 19 continue this log's own register. The decisions themselves are recorded in
> `DEVIATIONS.md` § "Owner decisions after the freeze" as items 2 and 3, and mirrored in the
> post-freeze amendment block at the head of Documents C and D. Item 1 of that series — the
> refusals George hit were a deploy defect, not a security one; nine of the twenty-one shipped
> tools had never worked because four pack versions were never bumped under `noupdate="1"` — is a
> defect record rather than a decision and stays in `DEVIATIONS.md`.*

### Open, needing a ruling
- ~~**Document D contradicts itself**: §3.2 makes `quality_mrp` mandatory for two packs and
  check 14 requires Community installability. Quality is Enterprise-only.~~
  **Ruled 2026-09-08: the dependency stays, check 14 narrows to the Community tier.** The claim
  worth defending is that the product runs without the Enterprise *AI app* (checks 4 and 13, which
  still cover every module), not that a quality pack can live without the quality app. Document C
  §4 and Document D §3.2 / §15 now carry the tier table; the kernel, the adapter, the chat widget
  and the procurement, inventory and accounting packs are Community, and manufacturing, quality,
  GM, `alshayeb_demo_water` and `ai_operations_demo_data` are Enterprise. **The full Naqaa demo
  therefore requires Enterprise.**
- ~~**The credential still has no home on Odoo.sh** (C §5.10). Unchanged since 2026-09-06.~~
  **Narrowed 2026-09-08: it is reachable, it is not durable.** `_credential()` is unchanged and
  reads the environment variable `ODOO_AI_ANTHROPIC_TOKEN`, then the `odoo.conf` key
  `ai_anthropic_token`, and nothing else — no `ir.config_parameter`, no `sudo()`, guarded by a test
  that scans every non-test Python file in every `ai_operations*` module (DL-001). **On Odoo.sh the
  second fallback is the one that works:** the key sits in `[options]` of
  `/home/odoo/.config/odoo/odoo.conf`, a file whose own header says it is loaded by the Odoo.sh
  workers, and since Odoo keeps unknown config keys, `config.get('ai_anthropic_token')` resolves in
  the web and cron workers. No ORM, no database, no git, no logged value.

  **There is no Odoo.sh secret store, and none is claimed.** Project Settings was inspected in full
  on 2026-09-05: no Environment Variables, Variables or Secrets section exists, and the platform
  environment carries only `ODOO_STAGE`, `ODOO_VERSION` and `PGPASSWORD`.

  **What is still open is durability.** `odoo.conf` is baked into the container image, so every
  build resets it and the key must be re-entered by hand. The three permanent routes DL-001 lists —
  move off Odoo.sh, accept database storage and withdraw the "never in ORM" constraint, or add a
  network secrets service — are all unchanged and none is chosen. ⚠ `docs/decision-log.md` DL-001
  still describes the credential as unreachable from a worker; that is the older reading, written
  before the `odoo.conf` path was confirmed.

---

## 2026-09-08 — checkpoint

No code shipped this session. Every figure below was measured on this machine today, not recalled.

| | |
|---|---|
| `development` | this commit — documentation only. The last **code** commit is `4e6e9cd` |
| `stage` | equal to `development`, same commit |
| `main` | `2ac3aa3` — untouched, equal to `origin/main` |
| Working tree | clean |
| Modules | **12** |
| Tests | **628 passing, 0 failed, 0 errors**, all twelve modules on one database |
| CI controls | **16 pass, 0 fail, 2 skip** of seventeen — `tools/ci_checks.sh`; skips are 3 and 14, both needing a database |
| Accountant | operational, read-only. 4 tools, QUERY, 3 `perm_read` models, 0 action permissions |
| General Manager | operational, read-only. 6 tools, QUERY, 11 `perm_read` models, 0 action permissions, 7 finance scalars |
| Scenario fixture | built and green — `ai_operations_demo_data/models/e2e_scenario.py`, 8 guard tests |
| Staging build | last observed at `4ee86b7`, **seven commits behind `origin/stage`** — five of them code, including the permission fix, both new agents and the scenario fixture. None has ever been built there |

**Support matrix.** Read from the twelve `depends` lists, with `quality_mrp` and
`quality_mrp_workorder` confirmed present only under `enterprise/`:

| Tier | Modules |
|---|---|
| **Community** (7) | `ai_operations` · `ai_operations_anthropic` · `ai_operations_chat_widget` · `ai_operations_procurement` · `ai_operations_inventory` · `ai_operations_accounting` · `stock_security_warehouse` |
| **Enterprise** (5) | `ai_operations_manufacturing`, `ai_operations_quality`, `ai_operations_gm` — each on `quality_mrp` · `alshayeb_demo_water` — `quality_mrp` + `quality_mrp_workorder` · `ai_operations_demo_data` — transitively, through the four above |

So: the kernel, the runtime, the chat surface, the provider adapter and the procurement, inventory
and accounting packs install on Odoo Community. **The full Naqaa demo does not — it is
Enterprise-tier**, and so are the manufacturing, quality and GM packs.

### Not done — the demo is not ready to show

What exists is a **deterministic local fixture** and nothing beyond it:
`ai_operations_demo_data/models/e2e_scenario.py` builds one scenario SKU with exactly one component
short by design — 8,000 bottles against a 12,000 requirement, on the one component with two real
vendors so the supplier comparison has a decision to show — plus a contrast order that is fully
covered from stock, so the demo also shows an agent reporting sufficiency and creating no work.
Idempotent, and guarded by 8 regression tests. **That is the only finished part.**

- **The real staging scenario has not been run.** Staging is four commits behind, so nothing after
  `4ee86b7` — the permission fix, both new agents, the fixture — has ever been built there.
- **The Arabic prompt runbook is not written.** `ai_operations_demo_data/README.md` names four
  scenarios and defers the exact messages to "the handover notes"; no such file exists anywhere in
  the repo. Nobody could present this cold.
- **The forbidden-prompt proof is not done** — there is no written list of what must be refused and
  no recorded run of it.
- **The two reset-to-finish staging runs are not done.**
- **The real-provider two-run proof is pending.** The only live-provider tests are the two in
  `ai_operations_anthropic/tests/test_live.py`, tagged `-standard`, which no normal suite runs.

No production deployment. No merge to `main`. No screenshots, no PDF.
