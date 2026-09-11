---
title: ai_operations — progress log
tags: [product, ai, progress]
status: active
updated: 2026-09-08
---

# `ai_operations` — Progress Log

Product docs: `01-demo-company-blueprint.md` (A) · `02-ai-operations-flow-design.md` (B) ·
`03-phase1-security-kernel-spec.md` (C) · `04-implementation-contract.md` (D).
Code: **twelve modules, 643 passing tests / 0 failed / 0 errors** at `e6aa8ce`, which is the head of
both `development` and `stage`. Measured 2026-09-08 across all twelve modules on one database, on a
frozen tree in a single run.
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

**The customer demo is not complete.** The code is final and staging is unblocked, but the two
reset-to-finish A-to-Z runs against the candidate commit have not been performed, so no build is
DEMO READY.
The checkpoint carries the acceptance bar and exactly what is missing.

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
  **Narrowed 2026-09-08: it is reachable; durability is unproven, not disproven.** `_credential()` is unchanged and
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

  **What is still open is durability — as an unproven guarantee, not an observed failure.** The
  `odoo.conf` fallback works on Odoo.sh. **Persistence across multiple rebuilds has been observed**
  — the key was written at 08:55 UTC and was still present at 12:50 UTC on build `7a4f37d`, across
  roughly fifteen pushes and rebuilds of the staging branch — **but no supported durability
  guarantee has been established.** Odoo.sh documents no contract for the file, so persistence
  across a container replacement or a branch reset is untested and must not be relied on.
  **Credential durability therefore remains an open deployment limitation**, and the runbook in
  `docs/reviews/final-technical-audit-2026-09-06.md` §5 gives the check and the re-entry procedure
  for the case where it does not survive. The three permanent routes DL-001 lists — move off
  Odoo.sh, accept database storage and withdraw the "never in ORM" constraint, or add a network
  secrets service — are all unchanged and none is chosen.

---

## 2026-09-08 — checkpoint

Every figure below was measured on this machine today, not recalled.

| | |
|---|---|
| `development` | **`e6aa8ce`** — equal to `origin/development`. `495d211` (the unblocking migration), `915b318` and `e129278` are all still in history; nothing squashed or reverted |
| `stage` | **`e6aa8ce`** — equal to `origin/stage` and to `development`. The current candidate, and the only hash a staging run should be validated against. It moved off `e129278` because staging hit a real bug in the reset — see *Two traps the staging runs found* |
| `main` | `2ac3aa3` — untouched, equal to `origin/main` |
| Working tree | clean |
| Modules | **12** |
| Tests | **643 passing, 0 failed, 0 errors**, all twelve modules on one database — 628 baseline + 15 for the reset model. Measured on a frozen tree, single run, no concurrent edits |
| CI controls | **16 pass, 0 fail, 2 skip** of seventeen — `tools/ci_checks.sh`; skips are 3 and 14, both needing a database |
| Accountant | operational, read-only. 4 tools, QUERY, 3 `perm_read` models, 0 action permissions |
| General Manager | operational, read-only. 6 tools, QUERY, 11 `perm_read` models, 0 action permissions, 7 finance scalars |
| Scenario fixture | built and green — `ai_operations_demo_data/models/e2e_scenario.py`, 8 guard tests |
| Demo reset | built and green — `ai.operations.demo.reset` in `ai_operations_demo_data` (**19.0.1.15.0**), 15 tests now run as a real user rather than uid 1. Marker-driven, no `sudo()`, each step in its own savepoint; makes the second demo run the same demo as the first |
| Demo runbook | **draft** — `docs/GEORGE_FULL_AI_OPERATIONS_DEMO.md`; every staging-only value marked PENDING STAGING VERIFICATION |
| Permission matrix | **draft** — `docs/SCENARIO_PERMISSION_MATRIX.md`; not yet exercised on staging |
| Credential on Odoo.sh | `odoo.conf` fallback **works**; persistence observed across ~15 rebuilds, **not guaranteed**; durability is an open deployment limitation (DL-009) |
| Staging build | **unblocked** on 2026-09-08 after eight commits of backlog, and first deployed at `495d211` — real module upgrade, 0 errors, `ai_operations_gm` installed for the first time. ⚠ It had never been "waiting on a rebuild": every build was *failing*. See below. That `495d211` build is **early/partial validation only** — it predates the reset model, so it is explicitly **not** a DEMO READY build. Final validation runs against the current candidate, `e6aa8ce` |

### Why staging never moved — the builds were failing, not queued

The working assumption for two days was that Odoo.sh had simply not rebuilt. It had. **Every build
of the branch was aborting**, and the platform kept serving the previous one, which is why the
symptom looked like a stuck queue.

The record is `ai_operations_procurement/migrations/19.0.1.6.0/pre-adopt-activity-permission.py`,
which carries the failure verbatim:

```
psycopg2.errors.UniqueViolation: duplicate key value violates unique constraint
"ai_operations_model_permission_model_permission_uniq"
DETAIL:  Key (profile_id, model_id)=(319, 166) already exists.
ParseError: while parsing ai_operations_procurement/data/policy_pack.xml:189
```

**Cause: a manual hotfix from the previous day colliding with the permanent fix for the same bug.**
During George's 2026-09-07 session someone created the `mail.activity` permission row by hand in the
UI at 14:11, to get past the refusal while the session was live. A row made that way carries **no
external id**. When `22f3ee2` then shipped that same permission properly inside the pack, the
packaged record collided with the untracked one, and the `ParseError` aborts the whole registry
load — so the failure was never confined to one record.

`495d211` is the fix: it deletes only the *unowned* duplicate — a row with no `ir.model.data` behind
it — so the pack's own record can be created and maintained normally. The rights are identical
either way; what changes is that the row is owned by the module rather than by whoever typed it.
**`495d211` is approved and must remain in history — it is not to be squashed, reverted or rebased
away.** `ai_operations_manufacturing` carries the same class of fix at `migrations/19.0.1.2.0`, from
the other direction, and both should be expected to fire on the next build.

The version gap is real, so the migration will run: `ai_operations_procurement` is **19.0.1.5.0** at
build `4ee86b7` and **19.0.1.6.0** at `origin/stage`.

### Two traps the staging runs found, both of which made a green suite lie

Neither was caught by 643 passing tests. Both are worth carrying beyond this project.

**1. Odoo runs tests as uid 1, and uid 1 bypasses `ir.model.access` entirely.** The reset died on
staging with an `AccessError`: `ir.model.access` granted `unlink` on `ai.operations.handoff` to *no
group at all*. **Fifteen tests had passed while the thing they asserted was impossible for a real
administrator to perform.** The suite now runs the reset as `base.user_admin`.

> **The general rule, and it is not specific to this reset: a test that asserts something is
> *permitted* proves nothing while it runs as uid 1.** Only a test running as a real user with real
> groups tests an ACL. Tests asserting something is *forbidden* are not affected — uid 1 would pass
> those too, but they are not the ones that silently lie.

This is the same class as the `sudo()` ban and the B3 write-path rule in `decision-log.md` DL-006:
name the identity that performs the write, or the design is wrong rather than the ACL.

**2. A refusal the customer sees is not always the kernel refusing.** The frozen neutral string
appears only when a tool is actually **called** and the guard denies it. For **six of the seven**
forbidden prompts, the agent holds no tool for that model at all, so nothing ever reaches the guard
— the model simply declines politely.

**Nothing leaks, and the isolation is real.** Holding no tool for a model *is* a boundary — but it is
an **earlier** boundary than the guard, not a stronger one, and the difference matters. They are two
layers of the same intersection: holding no tool removes the capability before anything runs; the
guard is what catches a model that tries anyway — a hallucinated tool name, a renamed tool, a future
pack that adds one. `EFFECTIVE` is an intersection precisely so that neither layer has to be trusted
alone, and calling the tool-absence "stronger" invites the reading that the guard is redundant. It is
not.

**Both things are true at once: the isolation is real, and the demonstration is weak.** What the
customer sees in those six cases is the model's *prose*, and **the model's politeness is not a
security control at all** — the control is that no tool exists to call. The demonstration is weak
because the audience cannot distinguish *"the system prevented this"* from *"the assistant chose not
to"*, and that distinction is exactly what is being sold. The runbook's section 8 has been corrected
so the distinction is stated rather than blurred, and so the one prompt that does reach the guard is
the one used to demonstrate it.

### The ACL sweep the handoff bug prompted

If `ai.operations.handoff` granted `unlink` to no group at all, the obvious question is whether any
other kernel model has the same hole. Swept, and `_abstract` was verified on each candidate rather
than assumed — audit, execution, security, activity, serializer, provider, the policy models and
`demo.reset` itself are AbstractModels and need no ACL.

Three **stored** kernel models grant `unlink` to no group:

| Model | Verdict |
|---|---|
| `ai.operations.audit.log` | **Deliberate.** Append-only, and this is the B3 rule working as designed |
| `ai.operations.handoff` | **The bug.** Fixed — this is what broke the reset on staging |
| `ai.operations.budget` | **Newly named, unruled.** Same posture, never flagged before |

**`ai.operations.budget` is not a demo blocker** — the reset does not touch it and nothing needs to
delete one. But whether *"nobody may delete a budget"* is intended or accidental is a Document C
question that has never been asked. It now has a name, which is the point of recording it.

### Untracked drift on the staging database — a second, worse instance

The 14:11 permission row was not the only record on staging that no shipped configuration created.

⚠ **A `TEST_AGENT` agent profile is ACTIVE on the staging database with `max_write_ops = 3`.** The
packs ship exactly six profile codes — `accounting`, `gm`, `inventory`, `manufacturing`,
`procurement`, `quality` — and `TEST_AGENT` is in none of them. A search of the entire working tree
returns nothing: it appears in no policy pack, no demo module, no test, no fixture and no migration.
**Nothing in this repository could have created it.**

It is materially worse than the 14:11 row. That one was a *duplicate of a legitimate permission*,
so the rights it granted were the rights the pack intended. This is a **write-capable agent profile
with no counterpart in the product at all**, live on the database the customer demo will be shown
from. Two separate sessions verified the absence independently before it was recorded here.

**Ruled 2026-09-08: inspect, then deactivate — do not delete.** In order: identify its database
relationships, its tool assignments and model permissions, and its origin if that can be determined;
then **deactivate the untracked profile and any untracked assignments** rather than deleting
broadly, and preserve the evidence in the staging notes. Deleting the profile could cascade through
its assignments, and deleting write-capable drift blindly while real-provider runs are in flight is
the wrong order. **It must not remain active for the final customer demo unless explicitly
justified.** No blanket cleanup: the migration that unblocked the build makes the argument well and
it applies here too — a script that silently discards configuration is worse than a failed build, so
remove only what a traceback or an explicit ruling names.

**How it came to exist is a finding in its own right,** separate from the demo. If a test run
against that database can leave behind an active agent profile carrying a write budget, that is a
defect in how tests reach a shared database, not merely an untidy row.

**No rollback point exists.** `~/backup.daily` on the staging container is empty and `pg_dump` is
blocked by an Odoo.sh role restriction (*"permission denied for view pg_settings"*). The 2026-09-08
upgrade was performed without a backup, on the judgement that the database is synthetic and
regenerable. That judgement is defensible, but it means any further write to that database is
expensive to undo, and a real dump is a UI action nobody has taken.

⚠ **Nobody has swept the staging database for other hand-created rows from that session.** Audit row
594 was a `POLICY_CHANGE` and the 14:11 row is documented, but if a build fails on a *different*
`UniqueViolation`, this is the class of cause to look at first. Untracked drift of this kind is
invisible to a green local suite, because it exists only on that one database.

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

What exists is a **deterministic local fixture** and two draft documents around it:
`ai_operations_demo_data/models/e2e_scenario.py` builds one scenario SKU with exactly one component
short by design — 8,000 bottles against a 12,000 requirement, on the one component with two real
vendors so the supplier comparison has a decision to show — plus a contrast order that is fully
covered from stock, so the demo also shows an agent reporting sufficiency and creating no work.
Idempotent, and guarded by 8 regression tests. **That is the only part that is finished; everything
that needs a real staging run is not.**

- **The final staging scenario has not been run.** Staging was stranded at `4ee86b7` for two days
  because its builds were *failing*, not queued — see *Why staging never moved* above — and was
  first unblocked at `495d211` on 2026-09-08. That build is early/partial validation only: it
  predates the reset model, so the two reset-to-finish runs cannot be performed on it.

**The acceptance bar, so that "done" has one meaning.** A DEMO READY verdict requires all of it, in
order, and no part of it may be assumed from a green local suite:

1. `development` = `stage` = the candidate commit, currently `e6aa8ce`.
2. Deploy that exact hash to staging, once.
3. Verify **installed** module versions against manifest versions — this is the check that catches
   the whole failing-build class, and `ai_operations_demo_data` at **19.0.1.15.0** is the quickest
   single proof that the build carrying the working reset actually took.
4. Verify the permission records **in the database**, not in the XML.
5. reset → **A-to-Z run #1** → reset → **A-to-Z run #2**.

Two conditions on step 5 that the test suite cannot prove for you, both of which look like success
if you do not check them:

- **The reset must return a non-zero summary on the first call and zero on the second.** A reset
  that reports *zero deletions on run 1* is not a clean database — it is the multi-company failure
  mode, where record rules scoped the sweep to the caller's active companies and it matched nothing.
  It reports success and deletes nothing. This is the same company-switcher trap that produced
  George's empty screenshot, and on staging it is indistinguishable from a genuine no-op unless the
  summary is read.
- **`summary['steps_failed']` must be empty on both calls.** Each reset step now runs in its own
  savepoint, so a step that cannot run no longer aborts the whole reset. That is the right
  behaviour, but it means a *partial* reset can report success on every other step.
  `steps_failed` is the only place that shows, so a non-empty list is a failed reset even when the
  deletion counts look healthy.
- **Run #2 must pass from the runbook alone, with no developer intervention.** If run #2 needs a
  shell, the reset has not done its job, whatever the suite says — the point of the second run is
  that someone who did not build the demo can present it.

⚠ **One watch item, not a gate.** Every profile carries `max_daily_tokens = 200,000`, and the reset
deliberately does **not** clear `tokens_today` — spent tokens are not residue in the sense the reset
is about, and 200k is generous for two runs. But **if run #2 ever fails with `BUDGET_EXCEEDED`
rather than a refusal, that is the first place to look.** Locally `tokens_today` is 0 on all six
profiles; the staging figure has not been read.

Until step 5 is complete against the candidate commit under every condition above, no build is
DEMO READY. Everything
run against `495d211` is early bug-finding and is explicitly **not** wasted — but the proof has to be
repeated on the final build.
- **The Arabic prompt runbook is a draft, not a verified document.**
  `docs/GEORGE_FULL_AI_OPERATIONS_DEMO.md` exists and every prompt in it was checked against a local
  database built from this commit, but everything that can only come from a real staging run — order
  and MO references, every AI reply, every audit row, both full-run results — is marked
  **PENDING STAGING VERIFICATION** and left blank.
- **The forbidden-prompt proof is written but not run.** `docs/SCENARIO_PERMISSION_MATRIX.md` sets
  out what each agent must refuse; no recorded staging run has yet exercised it.
- **The two reset-to-finish staging runs are not done.**
- **The real-provider two-run proof is pending.** The only live-provider tests are the two in
  `ai_operations_anthropic/tests/test_live.py`, tagged `-standard`, which no normal suite runs.

No production deployment. No merge to `main`. No screenshots, no PDF.

## 2026-09-11 — UAT: the Accountant drafts bills and journal entries (DL-010)

Staging UAT, `omar.f`: a rent-bill image with "draft a bill" was answered correctly — "I have no
write function". The owner had tried to enable it by hand (three unowned rows); a capability is a
tool, not a row. Ruling and design: `decision-log.md` DL-010.

- Staging: unowned action permissions 10, 11 and model permission 74 deleted via ORM (audited),
  on the owner's instruction.
- `ai_operations_accounting` 19.0.1.3.0 — `find_partners`, `find_accounts`,
  `prepare_draft_vendor_bill`, `prepare_draft_journal_entry`; `account.move.ai_idempotency_key`;
  pack at autonomy 2 / 2 writes / `CREATE_DRAFT` with `max_amount` 100,000; migration 19.0.1.3.0
  (pre: unowned collisions; post: profile + `perm_account_move_a`).
- `ai_operations` 19.0.1.30.0 — Max Amount column on the agent form; `move_id` in WRITE audit rows.
- `ai_operations_demo_data` 19.0.1.23.0 — Accountant off `READ_ONLY_AGENTS`, four tools enabled;
  reset deletes agent drafts by key.
- `alshayeb_demo_water` 19.0.1.9.0 — purchase VAT + operating-expense accounts `610000`–`650000`.
- **Verified (local, 2026-09-11):** baseline DB built from `e634e0c`; stage's drift re-planted
  (unowned `account.account` C/W, unowned `CREATE_DRAFT`, `perm_account_move_a` write); `-u` of all
  twelve with the suite → **786 tests**, migration removed every unowned row, profile 2/2,
  `perm_account_move_a` read+create only, 100,000 ceiling, eight tools enabled, purchase VAT on
  `610000`–`650000` in both companies. The one failure there was the executor test written with
  `assertRaises`, which rolls back its own savepoint (it erased the audit rows it asserted); rewritten
  with try/except → accounting + demo_data **147/147**; Community-only accounting **30/30**; CI 16/16.
- Review (odoo-code-reviewer) fixed: bill ceiling now on `amount_total_signed` (company currency);
  reset uses a flushing savepoint; post-migration also moves the kernel-default 3 writes and the
  policy version; `__export__` ids count as unowned; executor-path + replay-ACL tests added. Not
  taken: an empty Max Amount still means no ceiling (kernel behaviour); `ai_idempotency_key` keeps
  the procurement name.
- ⚠️ Found, not caused: a fresh local install of the demo fails at `_build_quality_points` when
  Enterprise's "Main Quality Team" carries a company (local Enterprise 2026-06-19); on staging the
  team is shared, so staging is unaffected.
