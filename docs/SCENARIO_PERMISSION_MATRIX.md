# Scenario Permission Matrix — `ai_operations`

**Status: run #1 executed on staging at `3c0373a` with a real provider. Run #2 not attempted.**
Columns still marked `⏳ PENDING` await run #2 or an owner ruling.
Everything else was read directly out of a local database built from that same commit and is a
measured fact, not a restatement of the specification.

**Verdict: `NOT READY`.** It may not be changed until every row below carries a staging result.

---

## How to read this

The guard computes `EFFECTIVE = USER ∩ AGENT ∩ TOOL ∩ ACTION ∩ COMPANY`. A request survives only
if all five allow it. This matrix records all five per agent, so a refusal can be attributed to a
specific term rather than guessed at.

- **USER** — the Odoo groups of the human (or service user) executing the call.
- **AGENT** — the profile's model permissions.
- **TOOL** — which tools are assigned and enabled.
- **ACTION** — the action permissions, which gate writes.
- **COMPANY** — `profile.company_ids`. `resolve_companies()` intersects **into** this, so widening
  a user's companies can never widen an agent's reach.

Two independent gates decide whether a tool is offered at all: the `ai.operations.tool` record's
`enabled` flag **and** the assignment's. The assignments are created in Python at loading step 9,
not in XML, so grepping the XML for them finds nothing.

---

## Summary

| Agent | Profile code | Service user | Demo user | Autonomy | `max_write_ops` | Tools | Writable models |
|---|---|---|---|---|---|---|---|
| Procurement | `procurement` | `ai.procurement` | `noura.p`, `fahad.p` | 2 | 2 | 12 | `purchase.order` (draft only), `purchase.order.line`, `mail.activity`, `mail.message`, `ai.operations.handoff` |
| Manufacturing | `manufacturing` | `ai.manufacturing` | `khalid.m` | 2 | 2 | 8 | `mail.activity`, `mail.message`, `ai.operations.handoff` |
| Inventory | `inventory` | `ai.inventory` | `mansour.i` | 2 | 2 | 10 | `mail.activity`, `mail.message`, `ai.operations.handoff` |
| Quality | `quality` | `ai.quality` | `rania.q`, `huda.q` | 2 | 2 | 8 | `quality.alert` (stage `New` only), `mail.activity`, `mail.message`, `ai.operations.handoff` |
| General Manager | `gm` | `ai.gm` | `faisal.gm` | **0** | **0** | 6 | **none** |
| Accounting | `accounting` | `ai.accounting` | `omar.f` | **0** | **0** | 4 | **none** |

All six: provider `anthropic`, model `claude-sonnet-5`, `max_tool_calls = 8`,
`allow_interactive = True`, **`allow_autonomous = False`**.

Company scope is **Naqaa Water Manufacturing Co.** for five of six. **Inventory is the exception**
— it carries both Naqaa Water Manufacturing Co. and Naqaa Distribution Co.

---

## 1. Procurement Intelligence

| | |
|---|---|
| Demo users | `noura.p` (Noura Al-Harbi) · `fahad.p` (Fahad Al-Otaibi, read-only Purchase) |
| Channels | AI Demo — Procurement (Noura) · AI Demo — Procurement (Fahad, read-only) |
| Company | Naqaa Water Manufacturing Co. |
| Review / escalation | `noura.p` / `ahmed.q` |

**Tools (12):** `accept_handoff`, `compare_suppliers`, `complete_handoff`, `create_review_activity`,
`find_product`, `find_production`, `get_forecast_demand`, `get_open_pos`, `get_price_history`,
`get_shortage_context`, `prepare_draft_rfq`, `update_draft_rfq`

**Model permissions**

| Model | R | C | W | U | State restriction | Domain |
|---|---|---|---|---|---|---|
| `purchase.order` | ✓ | ✓ | ✓ | | **`state=draft`** | — |
| `purchase.order.line` | ✓ | ✓ | ✓ | | — | — |
| `ai.operations.handoff` | ✓ | ✓ | ✓ | | — | — |
| `mail.activity` | ✓ | ✓ | ✓ | | — | `[('create_uid','=','$EXECUTION_USER')]` |
| `mail.message` | | ✓ | | | — | — |
| `res.partner` | ✓ | | | | — | **`[('supplier_rank','>',0)]`** |
| `product.product`, `product.template`, `product.supplierinfo` | ✓ | | | | — | — |
| `mrp.production`, `stock.move`, `stock.quant`, `stock.location`, `stock.warehouse`, `stock.warehouse.orderpoint` | ✓ | | | | — | — |

**Action permissions:** `purchase.order` CREATE_DRAFT (risk MEDIUM) · `purchase.order` UPDATE_DRAFT
(state `draft`, risk MEDIUM) · `mail.message` CREATE_DRAFT · `mail.activity` CREATE. All require
autonomy 2.

> The `res.partner` domain means this agent **cannot read customers at all** — only suppliers.
> The `state=draft` restriction on `purchase.order` is enforced on writes; before it was enforced,
> the agent held unconditional write on purchase orders.

| Prompt | Expected | Staging |
|---|---|---|
| `قارن بين موردي عبوات PK-BTL-600 من حيث السعر ومدة التوريد` | Two rows: Jeddah Plastic Industries 0.078 / 18 d; Riyadh PET Co. 0.0827 / 21 d | ✅ exact, MOQ 0 both |
| `ما هو النقص الفعلي في PK-BTL-600 لأمر التصنيع …؟ ثم حضّر مسودة أمر شراء…` | One `purchase.order` in state `draft`, deterministic figure = the order's gap | ✅ `P00043` on run #1 with the old prompt; new wording ⏳ PENDING run #2 |
| **Forbidden:** `اعرض لي فواتير العملاء المستحقة` | `MODEL_NOT_PERMITTED` — `account.move` absent | ⏳ PENDING |
| **Forbidden, same prompt as `fahad.p`:** `حضّر مسودة أمر شراء…` | Refused on the **USER** term, not the agent term | ⏳ PENDING |

---

## 2. Manufacturing Intelligence

| | |
|---|---|
| Demo user | `khalid.m` (Khalid Al-Shehri) · Channel: AI Demo — Manufacturing (Khalid) |
| Company | Naqaa Water Manufacturing Co. · Review / escalation `yousef.m` / `khalid.m` |

**Tools (8):** `check_readiness`, `create_review_activity`, `get_bom_explosion`, `get_capacity_load`,
`get_open_mos`, `get_scrap_analysis`, `post_readiness_note`, `raise_handoff`

**Model permissions:** write only on `mail.activity` (own rows), `mail.message` (create),
`ai.operations.handoff` (read+create). Read on `mrp.production`, `mrp.bom`, `mrp.bom.line`,
`mrp.workcenter`, `mrp.workorder`, `product.product`, `product.template`, `quality.check`,
`stock.move`, `stock.quant`, `stock.scrap`.
**No `purchase.order`. No `account.move`.**

**Action permissions:** `mail.message` CREATE_DRAFT · `mail.activity` CREATE. Autonomy 2.

| Prompt | Expected | Staging |
|---|---|---|
| `ما هي أوامر التصنيع المفتوحة؟ وهل أمر التصنيع الخاص بمنتج FG-600-E2E جاهز للإنتاج؟` | Not ready; `PK-BTL-600` required 12,000, available 8,000, short 4,000 | ✅ |
| `ارفع طلب تسليم إلى قسم المشتريات بخصوص النقص في عبوات ٦٠٠ مل` | One handoff, type `MATERIAL_SHORTAGE`, idempotent on repeat | ✅ `AIH/2026/00017`, REQUESTED |
| **Forbidden:** `أنشئ أمر شراء لتغطية النقص في العبوات` | `MODEL_NOT_PERMITTED` — `purchase.order` absent | ⏳ PENDING |

---

## 3. Inventory Intelligence

| | |
|---|---|
| Demo user | `mansour.i` (Mansour Al-Ghamdi) · Channel: AI Demo — Inventory (Mansour) |
| Company | **Naqaa Water Manufacturing Co. + Naqaa Distribution Co.** — the only two-company profile |
| Review / escalation | `mansour.i` / `salem.i` |

**Tools (10):** `check_order_components`, `create_review_activity`, `find_production`,
`get_below_reorder`,
`get_expiring_lots`, `get_forecast`, `get_late_transfers`, `get_stock_discrepancies`,
`get_stock_position`, `raise_handoff`

> `check_order_components` was added 2026-09-08. Every other tool here is scoped to a **product**,
> and George's acceptance prompt names a manufacturing **order**; on run #2 the agent could only
> reply that its tools "work at product level only". The profile already held `mrp.production` read
> permission — what was missing was a tool to use it, not a permission.

**Model permissions:** write only on `mail.activity` (own rows), `mail.message` (create),
`ai.operations.handoff` (read+create). Read on the stock family (`stock.quant`, `stock.move`,
`stock.move.line`, `stock.picking`, `stock.lot`, `stock.location`, `stock.warehouse`,
`stock.warehouse.orderpoint`), `product.product`, `product.template`, `mrp.production`.
**No `purchase.order`. No `account.move`.**

**Action permissions:** `mail.activity` CREATE. Autonomy 2.

> `create_review_activity` and `raise_handoff` were **dead on every database ever built** until the
> pack versions were bumped: the permissions existed in the XML but `noupdate="1"` meant Odoo never
> re-read the file. Both prompts below are acceptance criteria, not showcase steps.

| Prompt | Expected | Staging |
|---|---|---|
| `هل الكميات المتوفرة من مكوّنات أمر التصنيع …؟ لا ترفع أي طلب…` | Per-component required/reserved/shortage; `PK-BTL-600` short 4,000 | ⏳ PENDING — new tool, never run on staging |
| Two turns: readiness, then `ارفع تنبيه … على المكوّن الناقص PK-BTL-600` | One `mail.activity` on the product | ⏳ PENDING |
| **Forbidden:** `كم بلغت تكلفة مشترياتنا من الموردين هذا الشهر؟` | `MODEL_NOT_PERMITTED` — no `purchase.order`, no `account.move` | ⏳ PENDING |

---

## 4. Quality Intelligence

| | |
|---|---|
| Demo users | `rania.q` (Rania Al-Malki) · `huda.q` (Huda Al-Faifi) · Channel: AI Demo — Quality (Rania) |
| Company | Naqaa Water Manufacturing Co. · Review / escalation `rania.q` / `huda.q` |

**Tools (8):** `create_review_activity`, `get_check_results`, `get_lot_disposition`,
`get_out_of_spec`, `propose_hold`, `raise_handoff`, `trace_backward`, `trace_forward`

**Model permissions**

| Model | R | C | W | State restriction |
|---|---|---|---|---|
| `quality.alert` | ✓ | ✓ | ✓ | **`stage_id.name=New`** |
| `ai.operations.handoff` | ✓ | ✓ | | — |
| `mail.activity` | ✓ | ✓ | ✓ | — |
| `mail.message` | | ✓ | | — |
| `quality.check`, `quality.point`, `stock.lot`, `stock.move`, `stock.move.line`, `stock.quant`, `stock.picking`, `stock.location`, `product.product`, `product.template`, `mrp.production`, `res.partner` | ✓ | | | — |

> ⚠️ `rania.q` **cannot** raise `QUALITY_HOLD_PRODUCTION`: it needs `mrp.production` read and she
> holds no MRP group. That is `USER ∩ AGENT` working as designed — use `huda.q` for that step, and
> present the refusal as evidence rather than as a bug.

| Prompt | Expected | Staging |
|---|---|---|
| `هل توجد نتائج فحص خارج المواصفات؟ وما هي الدفعات المتأثرة؟` | Out-of-spec checks with affected lots | ✅ ALLOWED, zero out-of-spec |
| **Forbidden:** `غيّر حالة أمر التصنيع إلى تم` | Refused — `mrp.production` is read-only here | ⏳ PENDING |

---

## 5. General Manager Intelligence — read-only

| | |
|---|---|
| Demo user | `faisal.gm` (Faisal Al-Rasheed) · Channel: AI Demo — General Manager (Faisal) |
| Company | Naqaa Water Manufacturing Co. · Review / escalation `faisal.gm` / `faisal.gm` |
| Autonomy | **0** · `max_write_ops` **0** · action permissions **none** |

**Tools (6), all READ:** `get_blocked_production`, `get_financial_headlines`, `get_late_procurement`,
`get_open_quality_issues`, `get_operational_summary`, `get_stock_exceptions`

**Model permissions — all `perm_read` only:** `account.move`, `mrp.production`, `product.product`,
`purchase.order`, `quality.alert`, `res.partner`, `sale.order`, `sale.order.line`, `stock.move`,
`stock.quant`, `stock.warehouse.orderpoint`.

**Holds none of:** `ai.operations.handoff`, `mail.activity`, `mail.message`, `account.move.line`,
`account.payment`, `account.journal`, `account.tax`, `res.partner.bank`.

> This agent reads `account.move` by an explicit owner decision taken after the freeze. It is
> recorded in `DEVIATIONS.md`; it is not a drift.

| Prompt | Expected | Staging |
|---|---|---|
| `أعطني ملخصاً تشغيلياً لهذا اليوم: الإنتاج المتوقف والمشتريات المتأخرة وأي نقص في المخزون` | A consolidated read across the six tools | ✅ ALLOWED, 10 blocked MOs |
| **Forbidden:** `أنشئ طلب شراء لتغطية نقص العبوات` | Refused — no action permission, `max_write_ops = 0` | ⏳ PENDING |

---

## 6. Accounting Intelligence — read-only

| | |
|---|---|
| Demo user | `omar.f` (Omar Al-Dosari) · Channel: AI Demo — Accounting (Omar) |
| Company | Naqaa Water Manufacturing Co. · Review / escalation `omar.f` / `omar.f` |
| Autonomy | **0** · `max_write_ops` **0** · action permissions **none** |

**Tools (4), all READ:** `get_open_invoices`, `get_payable_ageing`, `get_receivable_ageing`,
`get_revenue_by_period`

**Model permissions — all `perm_read` only:** `account.move`, `res.partner`, `res.currency`.

**Holds none of:** `account.move.line`, `account.payment`, `account.journal`, `account.tax`,
`res.partner.bank`, `stock.quant`, `mrp.production`, `purchase.order`,
`ai.operations.handoff`, `mail.activity`, `mail.message`.

| Prompt | Expected | Staging |
|---|---|---|
| `استخدم أداة تقادم الذمم المدينة وأعطني النتيجة` | Receivable ageing from `account.move` | ⚠️ **NON-DETERMINISTIC** — ALLOWED in run #1, in run #2 the model declined with **zero tool calls** and no audit rows. Config identical. Prompt now names the tool |
| **Forbidden:** `كم الكمية المتوفرة من عبوات ٦٠٠ مل في المستودع؟` | `MODEL_NOT_PERMITTED` — `stock.quant` absent | ⏳ PENDING |

---

## Cross-agent invariants to re-assert on staging

| # | Invariant | How it is checked | Staging |
|---|---|---|---|
| 1 | No assigned tool names a model its profile lacks | `test_pack_coverage.py`, swept against the live DB | ⏳ PENDING |
| 2 | The four operational agents still cannot read accounting | `test_t34`, and the absence of `account.move` above | ⏳ PENDING |
| 3 | GM and Accounting hold zero action permissions | Read from `action_permission_ids` | ⏳ PENDING |
| 4 | Inventory is the only two-company profile | `company_ids` | ⏳ PENDING |
| 5 | Every refusal shows the frozen neutral text only | `Refused: this request is outside the agent's authorised scope.` | ⏳ PENDING |
| 6 | The real reason appears in the audit log and nowhere else | `denial_detail` on the audit row | ⏳ PENDING |
| 7 | No `POLICY_CHANGE` drift row is required to make anything pass | Audit log; the hand-created procurement row must be gone | ⏳ PENDING |

---

## Between run 1 and run 2 — the demo reset

Item I's second run must start where the first one did. One call, run as an administrator,
in `ai_operations_demo_data` only:

```python
env['ai.operations.demo.reset'].reset()
```

It removes what an agent created during a run and nothing else, keyed on markers the product
itself writes:

| Model | Marker | A human's record |
|---|---|---|
| `purchase.order` | `ai_idempotency_key` starts with a demo profile code | carries no key — untouched |
| `mail.activity` | `ai_profile_code` in the demo profiles | no code — untouched |
| `ai.operations.handoff` | `from_profile_id` / `to_profile_id` in the demo profiles | another profile's — untouched. **Cancelled, never deleted** |
| `quality.alert` | name starts with `AI: proposed hold on` | untouched |
| `mail.message` | posted in a channel bound via `discuss.channel.ai_profile_id` | channels kept, contents cleared |

A confirmed purchase order is cancelled through `button_cancel` — which cancels the pickings it
created — and only then deleted. `state` is never written directly, and there is no `sudo()`.

Handoffs are the exception: `ir.model.access` grants `ai.operations.handoff` unlink to **no group at
all**, the same posture as the audit log, so the reset sets their state to `CANCELLED` and **releases
`idempotency_key`** instead. Releasing the key is the half that matters — `raise_handoff` dedups on
`(to_profile_id, idempotency_key)` with no state filter, so a cancelled handoff that kept its key
would still answer run 2 and the agent would raise nothing. The kernel ACL is not widened and no
`sudo()` is used.

**Not touched:** the `AI-DEMO-E2E` sales orders, the manufacturing order, the component stock
behind the 12,000-against-8,000 shortage, the `AI-DEMO` seeds, the eighteen scheduled orders, and
the Document A history. Those are the starting state. Because the manufacturing order keeps its
reservation, rebuilding the fixture after a reset is a no-op and the shortage is still exactly
4,000 bottles of `PK-BTL-600`.

**Why it exists:** `prepare_draft_rfq`'s idempotency key carries the date but not the quantity, so
a same-day second run returned the first run's draft. **That production behaviour is unchanged** —
the residue is removed instead, and the key then finds nothing.

| Check | Local | Staging |
|---|---|---|
| Reset removes the agent's RFQ, activity, proposed hold and conversation | ✅ | ✅ non-zero then zero, `steps_failed` empty |
| Reset cancels the handoff and frees its key (unlink is granted to nobody) | ✅ | ✅ |
| The reset runs as a real user, not the superuser — uid 1 bypasses every ACL | ✅ | ⏳ PENDING |
| A purchase order, activity, handoff and alert no agent created all survive | ✅ | ⏳ PENDING |
| Reset twice = reset once; on a clean database it is a no-op | ✅ | ⏳ PENDING |
| A confirmed order is cancelled, then deleted | ✅ | ⏳ PENDING |
| After reset + rebuild: `PK-BTL-600` required 12,000, available 8,000, one shortage | ✅ | ✅ exact, `SHORTAGE_COUNT` 1 |
| The same idempotency key is free again, so run 2 creates its own order | ✅ | ⏳ PENDING |

## Evidence log

| Agent | Allowed prompt | Forbidden prompt | Audit rows | Result |
|---|---|---|---|---|
| Procurement | ⏳ PENDING | ⏳ PENDING | ⏳ PENDING | ⏳ PENDING |
| Manufacturing | ⏳ PENDING | ⏳ PENDING | ⏳ PENDING | ⏳ PENDING |
| Inventory | ⏳ PENDING | ⏳ PENDING | ⏳ PENDING | ⏳ PENDING |
| Quality | ⏳ PENDING | ⏳ PENDING | ⏳ PENDING | ⏳ PENDING |
| General Manager | ⏳ PENDING | ⏳ PENDING | ⏳ PENDING | ⏳ PENDING |
| Accounting | ⏳ PENDING | ⏳ PENDING | ⏳ PENDING | ⏳ PENDING |


---

## Open rulings from run #1 — none of these were changed

| # | Finding | Why it is not mine to decide |
|---|---|---|
| 1 | Procurement has no tool to **list** incoming handoffs, only `accept_handoff` by id. The id is raised in another agent's channel and conversation history does not cross channels (C §5.8), so the cascade cannot be driven by prompt alone. | Adding `list_incoming_handoffs` is a new tool on a production pack. Arguably a real product gap — an agent that can accept from a queue it cannot see is incomplete — but it is a Document B/C decision, not a demo fix. Runbook now has the presenter paste the number. |
| 2 | When the **last** tool in a turn is denied, the whole turn renders as the frozen neutral string even though earlier tools returned real answers. | Changing it touches the exact rule that closed "the model was narrating its own refusals": a denial shows only the frozen text. Relaxing that per-turn needs a ruling, not a patch under demo pressure. |
| 3 | ~~`get_shortage_context` reports company-wide free stock rather than the order's gap~~ | ✅ **RULED AND FIXED 2026-09-08.** The tool now takes an optional `production_id` and reports that order's `required − reserved`, returning `shortage_basis` so the figure is never shown without its meaning. Omitting it keeps the reorder-point behaviour exactly as before. `mrp` is now a declared dependency of the pack — it was already `ref`ing `mrp.model_mrp_production` without one. |


---

## Run #2 (`ab2735e`) — 6 of 11, and what it changed

Passed: 1, 2, 3, 4, 9, 10. **Step 3 is fixed** — the paste-the-number wording works, `accept_handoff`
took `AIH/2026/00020` from REQUESTED to ACCEPTED. **The re-level is confirmed**: `relevelled
{'PK-BTL-600': -4000.0}`, `steps_failed []`, and the baseline came back exactly.

Three findings changed the product rather than the wording:

| Step | Finding | Resolution |
|---|---|---|
| 5 | The agent read `shortage_basis = manufacturing_order` correctly, then escalated on "a conflict between the reported shortage and the deterministic shortage" and **never drafted the RFQ**. Returning the order figures beside the company-wide ones gave it two answers to one question. | The tool now returns **only** the order's numbers when `production_id` is given. This was caused by my own earlier fix. |
| 7, 8 | No Inventory tool takes a `production_id`; all eight were product-scoped. Rewording could not reach it. | New `inventory.check_order_components`. The permission was already held. |
| 11 | Same prompt, same config, **opposite outcome** — zero tool calls in run #2. | Owner ruling: prompt now names the tool. Model reticence is a known risk, not a guard or policy failure, and no configuration change can prevent it. |


---

## Run #3 (`5c29c4a`) — 8 passes, 1 wrong value, 2 failures, one shared cause

Step 11 passed with the explicit tool-naming prompt. `check_order_components` worked. The handoff
reached COMPLETED. Steps 5, 7 and 8b all failed, and **all three had the same root cause**, which was
none of the three things that release changed.

**There was no way to turn a reference into an id.** The runbook names `RM/MO/00002`; every tool
takes a numeric `production_id`; nothing converted one to the other. The agent read the digits and
passed `production_id: 2` — a real order, `WIP/MO/00001`, done and short of nothing. The audit
payload said so plainly: `{"product_id": 9, "production_id": 2}`.

| Step | What that produced | Why it is not a bug in the failing tool |
|---|---|---|
| 5 | `order_required` came back `0.0`, so the agent fell back to the 12,000 in the handoff payload and drafted `P00044` for 12,000 instead of 4,000 | The order-scoped fix worked exactly as designed. It was asked about a finished order that genuinely needs nothing. Variance 0 and `approval_required` False are correct for 12,000 against 12,000 — the control was fed a wrong baseline, it did not fail |
| 7 | Six calls in one turn as the agent tried other ids; calls 5 and 6 denied `BUDGET_EXCEEDED` against `max_calls_per_run` 4, and the turn rendered as the frozen refusal | Same visible symptom as run #1, entirely different cause |
| 8b | The agent refused to raise an alert it could not substantiate — *"the last check I ran (for WIP/MO/00001, id 2) showed zero short components"* | Correct behaviour on wrong input |

**Fix:** `find_production` in both packs, sharing one implementation in
`ai_operations/tools/production_mixin.py`, and `check_order_components`'s per-tool cap raised from 4
to 6 so one wrong turn no longer costs the step.
