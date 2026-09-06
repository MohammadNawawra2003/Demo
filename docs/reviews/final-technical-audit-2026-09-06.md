# Final technical audit — AI Operations / Naqaa Water

**Date:** 2026-09-06 · **Audited commit:** `7a4f37d` on `development` and `stage`
**Verdict:** **READY FOR MAIN**, with two product decisions outstanding and one measured limitation
recorded.

Nothing in this audit changed behaviour. Every claim below was re-verified, not carried over from an
earlier report.

---

## 1. `check_bound` zero baseline — **PRODUCT DECISION, unchanged**

**Implementation:** `security_service.check_bound` computes `if not deterministic: variance = 0.0`.
A recommendation of any size against a system-computed figure of **0** is therefore neither escalated
nor refused, and the draft is stamped `ai_approval_required = False`.

**What the frozen contract says.** C §5.3 defines the bands and nothing else:

| variance | outcome |
|---|---|
| ≤ `variance_bound_pct` (20) | proceeds |
| > bound, ≤ `variance_ceiling_pct` (100) | proceeds, `approval_required = True`, escalated |
| > ceiling | denied, `BOUND_EXCEEDED` |

**The contract is silent on a zero baseline.** It assumes a computed figure exists — "the shortage
Odoo computed". Nothing states what "variance against nothing" means. The one adjacent rule, C §5.3's
bound *resolution*, fails closed when no bound record exists — but that governs the **bound**, not the
**baseline**.

**So the current behaviour is an implementation choice, not a contract requirement.** Avoiding a
division by zero is correct; the side effect — treating *"no computed basis at all"* as *"no
variance"* — is not something the spec decided.

**Is it safe at Level 2?** Yes, in the narrow sense. Level 2 is Prepare: the artefact is a **draft**
a human must confirm, and the audit records the run. The worst case is a draft nobody wanted, which a
human declines. It is not an unauthorised commitment.

**But it defeats the bound exactly where judgement matters most.** Naqaa's computed shortage for
PK-BTL-330 *is* 0, so the flagship scenario is precisely this case, and the guardrail is silent on it.

**Recommendation (needs George's ruling — not applied):** treat an absent or zero deterministic
baseline as *"no computed basis"* and set `approval_required = True` — escalate, do not deny. That
matches the spec's own philosophy ("the bound escalates, the ceiling denies"; "a denial leaves
nothing on a human's desk"). It is a one-line change plus a test. **Not made here**, because choosing
business policy the contract did not decide is not an auditor's call.

## 2. `core.describe_scope` and `res.company` — **NON-BLOCKING, documented**

`core.describe_scope` is the only tool declaring `res.company`, and **no policy pack grants a
permission on it**. Verified across all four packs. The tool is therefore denied
(`MODEL_NOT_PERMITTED`) for every shipped profile.

It is also **inert in practice**: tools materialise disabled, no pack assigns it, and
`ai_operations_demo_data` deliberately does not grant it — granting `res.company` to make a
diagnostic work would be widening a policy to suit a tool.

**Left as is.** Nothing in the specification requires every profile to run the diagnostic, and no
prepared scenario uses it. If it is ever wanted, the minimum correct change is one
`ai.operations.model.permission` record per pack with `perm_read` on `res.company` — read-only, and
the company set is already known to the agent through `ExecutionContext`.

## 3. Fahad sees both agents — **PRODUCT DECISION, architecture working as designed**

`ai_widget_profiles()` returns `search([('allow_interactive','=',True), ('partner_id','!=',False)])`.
The company record rule filters it. So any holder of `group_ai_user` is offered every active
interactive profile **in their own companies**.

**There is no per-user agent eligibility in the architecture.** `ai.operations.agent.profile` has
`company_ids`, `service_user_id` and the two routing users — and no "allowed users" concept anywhere.
Access to *use* an agent is decided per call by the guard, not by a list.

**This is (A): intended product behaviour.** Fahad seeing Manufacturing Intelligence is the company
scope plus the group, exactly as designed, and every call he makes is still intersected. He remains
read-only on Purchase and the guard proved it.

**No change made.** Restricting a persona to one agent would require a new per-user eligibility
concept — new architecture, and a product decision, not a demo-data fix.

## 4. Full-volume performance — **measured, NON-BLOCKING, optimisation DEFERRED**

### Guard overhead is negligible

Measured on staging, each figure the **complete** path (guard → tool → serialiser → audit), mean of
five runs:

| tool | mean |
|---|---|
| `procurement.find_product` | 10.2 ms |
| `procurement.get_open_pos` | 9.9 ms |
| `procurement.get_shortage_context` | 16.7 ms |
| `procurement.compare_suppliers` | 12.9 ms |
| `manufacturing.get_open_mos` | 10.4 ms |
| `manufacturing.check_readiness` | 20.4 ms |
| audit query (80 DENIED rows) | 0.5 ms |

Staging holds 3 purchase orders, 1 manufacturing order and 0 quants, so this measures **kernel
overhead**, not scaling.

### Scaling — a real finding

Controlled local test: 60,000 `stock.quant` rows inserted inside a transaction and **rolled back**.
Staging untouched.

| tool | 0 quants | 60,000 quants |
|---|---|---|
| `get_shortage_context` | 21.2 ms | **1264.2 ms** |
| `check_readiness` | 25.2 ms | **1203.4 ms** |
| `get_open_pos` | 12.1 ms | 13.7 ms |

**Cause:** both quant-scanning tools `search()` `stock.quant` with no limit and sum in Python;
`check_readiness` does it once per component. `get_open_pos` is flat because it carries `limit=50`.

Roughly linear — at Naqaa's stated ~250k-record target these calls plausibly reach several seconds,
and a run makes several of them.

**Not fixed here.** The fix is an SQL aggregation (`_read_group`) instead of fetch-and-sum — a
behaviour-preserving optimisation, but still a change to working production code during a signoff
audit. **Recorded with numbers so it is not rediscovered by a customer.**

**Full-volume generator run: DEFERRED, not performed.** The 250k-record history generator was not
run: staging is a 1 GB trial and filling it would harm the demo. Kernel correctness does not depend
on volume — it is proven by 481 tests — and the demo's data is small by design.

## 5. Anthropic credential — **DEPLOYMENT LIMITATION, runbook below**

**No safer mechanism exists on this project.** Re-verified: Odoo.sh Project Settings has no
environment-variable or secrets section, and `/opt/odoo.sh/odoosh/bin/` contains no secrets tooling
(`dumpstacks`, `import-database`, `push`, `restart`, `sql-access`, `storage` only).

The key lives in `[options]` of `/home/odoo/.config/odoo/odoo.conf`, whose own header states it *"is
loaded by Odoo.sh workers"*. Odoo keeps unknown keys (`config.py:906-918`) and `config.options` is a
`ChainMap` including them (`config.py:164-170`), so `config.get('ai_anthropic_token')` resolves in the
web worker. No ORM, no database, no git, and only the option **name** is ever logged. CI check 11
stays green and this is C §5.10's own second permitted location.

⚠ **Correction to an earlier note in this repository.** It said a new build resets the file. Observed
today: the key was written at **08:55 UTC** and was still present at **12:50 UTC** on build
`7a4f37d`, after roughly fifteen pushes and rebuilds. So it **persists across rebuilds of a staging
branch**. Persistence across a container replacement or branch reset is *not* proven, so treat it as
**observed, not guaranteed**.

### Runbook

**When to re-enter:** if `grep -c '^ai_anthropic_token' /home/odoo/.config/odoo/odoo.conf` returns 0
after a build, or the agent starts answering *"I am unavailable right now."*

**Enter it** (from a normal terminal, never a shared session — the value is never echoed, never in
shell history, never on a command line):

```
ssh <build>@<project>-<branch>-<build>.dev.odoo.com
read -rs -p "Anthropic key: " K && printf '\nai_anthropic_token = %s\n' "$K" >> /home/odoo/.config/odoo/odoo.conf && unset K && echo OK
odoosh-restart          # process restart; a NEW BUILD would need the key re-entered
```

**Verify without printing it:**

```
grep -c '^ai_anthropic_token' /home/odoo/.config/odoo/odoo.conf          # expect 1
grep "unknown option 'ai_anthropic_token'" ~/logs/odoo.log | tail -1     # names the option, never the value
```

The file is `chmod 600`. Do not `cat` it.

**Production recommendation:** this is fine for staging and is contract-compliant, but a production
deployment should use a platform with real secrets management, or accept `ir.config_parameter` with
its documented dump exposure. That remains **DL-001**, still open.

## 6. Security — **PASS**

Re-checked against the code at `7a4f37d`, not against earlier reports.

| Invariant | Evidence |
|---|---|
| No `sudo()` | `grep -rn "\.sudo("` over all `ai_operations*` non-test code: **no hits** |
| No secret in the repository | `git grep` for key patterns: only a fake literal in a test asserting it is *not* leaked |
| Autonomy ≤ Level 2 | `PHASE1_MAX_AUTONOMY = AutonomyLevel.PREPARE`, enforced by `_check_phase1_autonomy_ceiling` |
| AI cannot confirm an order | no tool calls `button_confirm`; `prepare_draft_rfq` creates and stops; asserted by test |
| LLM cannot choose model/method/domain | `PROHIBITED_PARAM_NAMES` rejects `model`, `method`, `domain`, `filter`, `code`, `sql`, `expression`, `query` **at registration** — it rejected one of my own tools during this work |
| Only registered tools execute | `registry_spec()` lookup; an unknown name reaches the guard and is denied |
| Output allowlisted | serialiser emits declared schema fields only; undeclared fields are dropped and logged |
| Denial neutral to the user | the surface answers a refused run with `NEUTRAL_DENIAL` and discards the model's prose |
| Exact reason audit-only | `USER_ACL_DENIED` + detail on the row, verified on staging |
| Company isolation | record rules on profile, model permission and action permission; proven when the same rule hid Naqaa data from an admin scoped to another company |
| Service users | no credential, not administrators, constraint-enforced |

**481 Python tests, 0 failed.** No ACL, record-rule or guard change was made during this audit.

## 7. Idempotency — **PASS, with an explicit trade-off**

Identity, per Document D §13 and now implemented literally:

```
{profile_code}:{company_id}:{purpose}:{product_ref}:{location_ref}:{date}
```

Observed on staging: `procurement:212:draft_rfq:PK-BTL-330:976:2026-09-06`.

- The **LLM no longer supplies the key** — the parameter is gone from `PrepareDraftRfqInput`.
- Same intent replayed → the original order is returned, `idempotent_hit: True`.
- Different **date** → distinct. Different **vendor** → distinct. Different **company** → isolated,
  both in the key and on `unique(company_id, ai_idempotency_key)`.

⚠ **Quantity is deliberately not part of identity.** The contract omits it, so the same product,
vendor and date with a different quantity **returns the existing order**. This is replay protection,
not business duplicate detection: it does not stop a legitimate reorder on another day, and it does
not judge whether a second order is commercially sensible. **An explicit trade-off, not a hidden
defect.** Adding quantity would be a contract change and needs a ruling.

## 8. Modules and dependencies — **PASS**

| module | version | depends |
|---|---|---|
| `ai_operations` | 19.0.1.16.0 | **base, mail** — the frozen rule holds |
| `ai_operations_anthropic` | 19.0.1.2.0 | ai_operations |
| `ai_operations_procurement` | 19.0.1.4.0 | ai_operations, purchase, stock |
| `ai_operations_manufacturing` | 19.0.1.2.0 | ai_operations, ai_operations_procurement, mrp, stock |
| `ai_operations_inventory` | 19.0.1.1.0 | ai_operations, stock |
| `ai_operations_quality` | 19.0.1.1.0 | ai_operations, stock, mrp |
| `ai_operations_chat_widget` | 19.0.1.2.0 | ai_operations, web |
| `ai_operations_demo_data` | 19.0.1.8.0 | the packs + alshayeb_demo_water |
| `alshayeb_demo_water` | 19.0.1.2.0 | purchase, stock, mrp, **quality_mrp**, **quality_mrp_workorder**, sale_management, account, l10n_sa, hr, stock_security_warehouse |
| `stock_security_warehouse` | 19.0.1.0.0 | stock |

- **No production module depends on a demo module.** Verified by grep, not by reading.
- **Enterprise-only dependencies are isolated** in `alshayeb_demo_water`, the demo module.
  `ai_operations_quality` touches only `stock.*`, `mrp.production`, `product.product` and
  `res.partner` despite its name — it does **not** require the Enterprise `quality` app.
- **No demo record is hardcoded in production logic**; the demo module resolves everything by
  business key.
- **Community claim substantiated for the packs, not only the kernel:** kernel, all four packs, the
  adapter, the widget and `stock_security_warehouse` install on a Community-only addons path and pass
  **380 tests, 0 failed**. That is CI check 14, run rather than asserted.

## 9. Tests actually run in this audit

| suite | scope | result |
|---|---|---|
| Python, 10 modules | full platform + demo data (Enterprise addons path) | **481 tests, 0 failed, 0 errors** |
| Python, Community gate | kernel + 4 packs + adapter + widget + warehouse, **no Enterprise** | **380 tests, 0 failed, 0 errors** |
| JS / hoot | `ai_operations_chat_widget`, real Chrome on Odoo.sh staging | **9 passed, `[HOOT] Test suite succeeded`** |
| Clean install | whole chain into an empty database | verified earlier this session |
| Upgrade | existing database through every version bump | verified continuously |

**Not run, and why:** the 250k-record history generator (would fill a 1 GB trial and harm the demo);
mobile hoot preset (no scenario depends on it); anything against production (out of scope by
instruction).

## 10. Release classification

| # | Finding | Class |
|---|---|---|
| 1 | `check_bound` zero baseline neither escalates nor refuses | **PRODUCT DECISION** |
| 2 | `core.describe_scope` unusable for every shipped profile | **NON-BLOCKING** (documented, inert) |
| 3 | Any `group_ai_user` sees every active profile in their companies | **PRODUCT DECISION** (architecture as designed) |
| 4 | Quant-scanning tools degrade ~60× at 60k quants | **NON-BLOCKING**, optimisation **DEFERRED** |
| 5 | Odoo.sh has no secrets mechanism; key lives in `odoo.conf` | **NON-BLOCKING** deployment limitation; **DL-001** still a **PRODUCT DECISION** for production |
| 6 | Idempotency ignores quantity | **NON-BLOCKING**, explicit contract trade-off |
| 7 | Full-volume generator never run | **DEFERRED** |

**No blockers.**
