# Document B — AI Operations Flow Design

**Project:** `ai_operations` — AlShayeb AI Operations Platform for Odoo 19
**Substrate:** Document A — Demo Company Blueprint v1.2 (Naqaa Water)
**Purpose:** Define which agents exist, what each may touch, which tools they hold, how they hand off to each other, and how the end-to-end scenarios run.
**Status:** APPROVED — acceptance §17 signed off; pre-freeze review corrections applied 2026-09-04.
**Version:** 1.3
**Date:** 2026-09-04
**Changes in 1.3:** activity routing made configurable per profile and fail-closed (§12, §16 decision 10).
**Changes in 1.2:** the provider layer is generic — the kernel names no vendor and Anthropic is the Phase 1 adapter (§14, §16 decision 9).
**Changes in 1.1:** one Claude-native runtime replaces the split interactive/autonomous execution model (§14, §16 decision 3); the +20% bound is an escalation, not a denial (§6.3, §7); autonomy composition restated as a ceiling-and-floor rule (§3); `mail.activity` write and `mail.message` create added to the scopes that need them (§4); handoff idempotency scoped to the receiver (§6.5).

---

## 1. Standing and Scope

Document A defined the company. This document defines the behaviour. Document C will define the enforcement mechanism.

Phase 1 covers four agents — **Procurement, Inventory, Manufacturing, Quality** — and must prove two things simultaneously:

1. **The guard.** An agent asked for data outside its scope fails at the security layer, not at the prompt.
2. **The cascade.** A material shortage detected in Manufacturing reaches Procurement as a draft RFQ on a human's desk, with no shared context between the two agents.

Sales, Finance, HR and General Manager agents are out of Phase 1. Their data exists in the database purely as **isolation targets**.

---

## 2. The Division of Labour

This is the principle that everything below obeys. It is repeated here because it is the one most likely to erode during implementation.

| Odoo does this — deterministically | AI does this — interpretively |
|---|---|
| Stock reservation and availability | Explaining why something is short |
| Reordering rules, min/max, safety stock | Judging whether the reorder point is still right |
| Procurement routes and BoM explosion | Prioritising which shortage matters most |
| MRP scheduling and component allocation | Interpreting a scheduling conflict |
| Lot traceability, forward and backward | Summarising recall exposure for a human |
| Costing, valuation, taxes, posting | Comparing supplier options |
| Record rules, ACLs, workflow states | Drafting a record for human approval |
| Due dates, approvals, state machines | Turning ERP conditions into readable tasks |

**Rule:** if Odoo can compute it, Odoo computes it and the tool returns the computed value. The LLM never recalculates a quantity that the ERP already knows. Where an agent produces a number Odoo did not produce — a recommended purchase quantity, for example — that number must be presented as a **recommendation with its deterministic inputs shown alongside it**, never as a fact.

---

## 3. Agent Roster

| Agent | Code | Service user | Companies | Max autonomy | Department |
|---|---|---|---|---|---|
| Procurement Intelligence | `procurement` | `AI / Procurement` | C1 | **Level 2 — Prepare** | Purchasing |
| Inventory Intelligence | `inventory` | `AI / Inventory` | C1, C2 | **Level 2 — Prepare** | Warehouse |
| Manufacturing Intelligence | `manufacturing` | `AI / Manufacturing` | C1 | **Level 2 — Prepare** | Production |
| Quality Intelligence | `quality` | `AI / Quality` | C1 | **Level 2 — Prepare** | QA/QC |

**No agent exceeds Level 2 in Phase 1.** No agent may confirm, post, validate or mark done. Every state transition remains a human action on a native Odoo button.

### Autonomy levels

| Level | Name | Permitted |
|---|---|---|
| 0 | Query | Answer questions from approved data |
| 1 | Analyze | + calculate, summarise, identify exceptions, recommend |
| 2 | **Prepare** | + create draft records, create activities, raise handoffs |
| 3 | Limited Execution | Explicitly authorised low-risk operations — **not used in Phase 1** |
| 4 | Controlled Autonomy | Narrow, heavily audited — **not used in Phase 1** |

**How the levels compose.** `max_autonomy_level` on the agent is a **ceiling**. The `autonomy_required` on a tool and on an action are **floors**. A call is permitted when:

```
max(tool.autonomy_required, action.autonomy_required)  <=  profile.max_autonomy_level
```

otherwise it is denied with `AUTONOMY_INSUFFICIENT`. Version 1.0 described this as "the lowest of" the three, which mixes a ceiling with two floors and produces a number with no meaning — a Level 1 agent invoking a Level 2 tool would yield `min(1, 2) = 1` and the comparison would be undefined. The inequality above is the rule.

---

## 4. Agent Security Scopes

Allowlist. Anything not listed is denied. These tables become `ai.operations.model.permission` and `ai.operations.action.permission` records in the policy pack.

### 4.1 Procurement Intelligence

**Purpose:** keep the plant supplied with packaging and process materials at defensible cost and timing.

| Model | Read | Create | Write | Delete | Domain |
|---|---|---|---|---|---|
| `purchase.order` | ✅ | ✅ | ✅ draft only | ❌ | `company_id = C1` |
| `purchase.order.line` | ✅ | ✅ | ✅ draft only | ❌ | via parent |
| `product.product` / `product.template` | ✅ | ❌ | ❌ | ❌ | `purchase_ok = True` or component |
| `product.supplierinfo` | ✅ | ❌ | ❌ | ❌ | C1 or global |
| `res.partner` | ✅ | ❌ | ❌ | ❌ | `supplier_rank > 0` |
| `stock.quant` | ✅ | ❌ | ❌ | ❌ | C1 warehouses |
| `stock.move` | ✅ | ❌ | ❌ | ❌ | C1 |
| `stock.warehouse` / `stock.location` | ✅ | ❌ | ❌ | ❌ | C1 |
| `stock.warehouse.orderpoint` | ✅ | ❌ | ❌ | ❌ | C1 |
| `mrp.production` | ✅ | ❌ | ❌ | ❌ | C1, demand context only |
| `mail.activity` | ✅ | ✅ | ✅ **own created only** | ❌ | `create_uid = execution identity` |
| `mail.message` | ❌ | ✅ | ❌ | ❌ | on records already readable |
| `ai.operations.handoff` | ✅ | ✅ | ✅ status only | ❌ | assigned to `procurement` |

**Explicitly denied:** `account.move`, `account.move.line`, `account.payment`, `account.journal`, `hr.employee`, `hr.payslip`, `crm.lead`, `sale.order`, `res.users` beyond name, `ir.config_parameter`.

**Action permissions:**

| Model | Action | Allowed | Notes |
|---|---|---|---|
| `purchase.order` | CREATE DRAFT | ✅ | Idempotency key required |
| `purchase.order` | UPDATE DRAFT | ✅ | Bounded — see §6.3 |
| `purchase.order` | `button_confirm` | ❌ | **Human only** |
| `purchase.order` | `button_cancel` | ❌ | |
| `purchase.order` | `action_create_invoice` | ❌ | |
| `mail.activity` | CREATE | ✅ | Dedup key required |

**Field restrictions:** on `res.partner`, output schema emits `id`, `name`, `ref`, `country_id.name`, `supplier_rank` only. `bank_ids`, `vat`, `comment`, `credit`, `debit` are never serialisable — enforced by output schema, not by a denylist.

### 4.2 Inventory Intelligence

**Purpose:** stock position, movement exceptions, expiry and shortage detection across plant and branches.

| Model | Read | Create | Write | Delete | Domain |
|---|---|---|---|---|---|
| `stock.quant` | ✅ | ❌ | ❌ | ❌ | C1 + C2 warehouses |
| `stock.picking` | ✅ | ❌ | ❌ | ❌ | C1 + C2 |
| `stock.move` / `stock.move.line` | ✅ | ❌ | ❌ | ❌ | C1 + C2 |
| `stock.lot` | ✅ | ❌ | ❌ | ❌ | C1 + C2 |
| `stock.warehouse` / `stock.location` | ✅ | ❌ | ❌ | ❌ | C1 + C2 |
| `stock.warehouse.orderpoint` | ✅ | ❌ | ❌ | ❌ | C1 + C2 |
| `product.product` / `product.template` | ✅ | ❌ | ❌ | ❌ | all |
| `mrp.production` | ✅ | ❌ | ❌ | ❌ | C1, demand context only |
| `mail.activity` | ✅ | ✅ | ✅ **own created only** | ❌ | `create_uid = execution identity` |
| `mail.message` | ❌ | ✅ | ❌ | ❌ | on records already readable |
| `ai.operations.handoff` | ✅ | ✅ | ✅ status only | ❌ | from/to `inventory` |

**Explicitly denied:** all accounting, all HR, `sale.order` (uses `stock.move` demand instead), `purchase.order` (uses incoming `stock.move` instead), **`stock.valuation.layer` and any cost field**.

> **Note:** Inventory is the only Phase 1 agent spanning both companies, which makes it the sharpest multi-company test. It may see C2 branch stock and C1 plant stock, and must not see C1 production cost or C2 selling price. Quantities cross the company boundary; values do not.

**Action permissions:** no writes to any stock model. `mail.activity` CREATE and handoff CREATE only. `stock.picking.button_validate` is **denied**.

### 4.3 Manufacturing Intelligence

**Purpose:** production readiness, capacity exceptions, scrap analysis, shortage origination.

| Model | Read | Create | Write | Delete | Domain |
|---|---|---|---|---|---|
| `mrp.production` | ✅ | ❌ | ❌ | ❌ | C1 |
| `mrp.bom` / `mrp.bom.line` | ✅ | ❌ | ❌ | ❌ | C1 |
| `mrp.workorder` / `mrp.workcenter` | ✅ | ❌ | ❌ | ❌ | C1 |
| `stock.move` (raw + finished) | ✅ | ❌ | ❌ | ❌ | C1 |
| `stock.quant` | ✅ | ❌ | ❌ | ❌ | C1 |
| `stock.scrap` | ✅ | ❌ | ❌ | ❌ | C1 |
| `product.product` / `product.template` | ✅ | ❌ | ❌ | ❌ | C1 |
| `quality.check` | ✅ | ❌ | ❌ | ❌ | C1, **result + status only** |
| `mail.activity` | ✅ | ✅ | ✅ **own created only** | ❌ | `create_uid = execution identity` |
| `mail.message` | ❌ | ✅ | ❌ | ❌ | on records already readable |
| `ai.operations.handoff` | ✅ | ✅ | ✅ status only | ❌ | from/to `manufacturing` |

**Explicitly denied:** all accounting, all HR, purchase pricing, `sale.order`, **all cost fields on `mrp.production` and `stock.move`**.

**Action permissions:**

| Model | Action | Allowed |
|---|---|---|
| `mrp.production` | `action_confirm` | ❌ |
| `mrp.production` | `button_mark_done` | ❌ |
| `mrp.production` | `action_cancel` | ❌ |
| `mrp.bom` | any write | ❌ |
| `stock.scrap` | CREATE | ❌ |
| `mail.activity` | CREATE | ✅ |

Manufacturing may **assess and report** readiness. It may not change a single production state.

### 4.4 Quality Intelligence

**Purpose:** out-of-spec detection, lot trace in both directions, recall impact assessment.

| Model | Read | Create | Write | Delete | Domain |
|---|---|---|---|---|---|
| `quality.check` | ✅ | ❌ | ❌ | ❌ | C1 |
| `quality.point` | ✅ | ❌ | ❌ | ❌ | C1 |
| `quality.alert` | ✅ | ✅ | ✅ draft only | ❌ | C1 |
| `stock.lot` | ✅ | ❌ | ❌ | ❌ | C1 + C2 (trace requires it) |
| `stock.move.line` | ✅ | ❌ | ❌ | ❌ | C1 + C2 (trace requires it) |
| `stock.quant` | ✅ | ❌ | ❌ | ❌ | C1 + C2 |
| `stock.picking` | ✅ | ❌ | ❌ | ❌ | C1 + C2 |
| `mrp.production` | ✅ | ❌ | ❌ | ❌ | C1 |
| `res.partner` | ✅ | ❌ | ❌ | ❌ | **name + ref only**, trace endpoints |
| `mail.activity` | ✅ | ✅ | ✅ **own created only** | ❌ | `create_uid = execution identity` |
| `mail.message` | ❌ | ✅ | ❌ | ❌ | on records already readable |
| `ai.operations.handoff` | ✅ | ✅ | ✅ status only | ❌ | from `quality` |

**Explicitly denied:** all accounting, all HR, all pricing, `sale.order`, `purchase.order`.

> **The sharp edge.** Quality needs cross-company lot trace to do its job — a recall must follow product into C2's branches and out to customers. It therefore reads customer *identity* but never customer *value*. Quality can tell you 11 customers received an affected lot. It cannot tell you what those shipments were worth. That figure requires a Finance Agent that does not exist in Phase 1, and even in Phase 2 it will require an explicit handoff type.

**Action permissions:**

| Model | Action | Allowed |
|---|---|---|
| `quality.alert` | CREATE | ✅ |
| `quality.check` | `do_pass` / `do_fail` | ❌ **Human only** |
| `stock.quant` | any write | ❌ |
| Any stock move to Quality Hold | ❌ | Agent **proposes**, human executes |

### 4.5 Two grants every agent holds, and why

**`mail.activity` write, restricted to activities the agent itself created.** §8 requires that a repeated exception updates its existing activity instead of creating a second one — that is the deduplication rule, and it is what stops the daily review turning into noise. Deduplication is a write. Version 1.0 granted create without write, which made the stated behaviour impossible and left test T-98 testing something the permission table forbade. The write is scoped by `create_uid = execution identity`, so an agent can never touch a human's activity or another agent's.

**`mail.message` create.** Three flows post to chatter: `manufacturing.post_readiness_note`, the run summary each autonomous run posts to the record it worked on, and the reasoning trace that replaces a chat thread for cron runs. The guard requires every model a tool declares to be permitted, so without this grant those tools deny themselves. Create only — an agent may add to a conversation and may never rewrite one. Read is not granted: an agent does not need to read other people's chatter to post to it, and chatter is exactly where a prompt-injection payload would be planted.

**Neither grant is a state change.** An activity is a request for a human decision and a message is a note. No record leaves draft, no workflow advances, and no native button is pressed.

---

## 5. Tool Catalogue

Every tool is a registered Python method dispatched from a single-line server action. The LLM never names a model, a method or a domain.

**Type key:** `R` = read only · `D` = draft write · `H` = handoff

### 5.1 Procurement

| Tool code | Type | Autonomy | Purpose |
|---|---|---|---|
| `procurement.get_shortage_context` | R | 0 | Current stock, incoming, reserved, orderpoint and open demand for a product |
| `procurement.get_forecast_demand` | R | 1 | Forecast requirement over horizon, from Odoo forecast + historical consumption |
| `procurement.compare_suppliers` | R | 1 | Price, lead time, MOQ, on-time history per approved vendor |
| `procurement.get_open_pos` | R | 0 | Open and overdue POs for a product or vendor |
| `procurement.get_price_history` | R | 1 | Purchase price movement over period |
| `procurement.prepare_draft_rfq` | D | 2 | Create draft PO. Idempotency key mandatory |
| `procurement.update_draft_rfq` | D | 2 | Amend draft PO within bounds (§6.3) |
| `procurement.create_review_activity` | D | 2 | `mail.activity` for a named human |
| `procurement.accept_handoff` | H | 2 | Claim an assigned handoff |
| `procurement.complete_handoff` | H | 2 | Close with result reference |

### 5.2 Inventory

| Tool code | Type | Autonomy | Purpose |
|---|---|---|---|
| `inventory.get_stock_position` | R | 0 | On-hand, reserved, available, incoming by warehouse |
| `inventory.get_forecast` | R | 1 | Odoo forecasted availability over horizon |
| `inventory.get_below_reorder` | R | 1 | Products below orderpoint |
| `inventory.get_late_transfers` | R | 0 | Overdue receipts and deliveries |
| `inventory.get_expiring_lots` | R | 1 | Lots inside expiry alert window, by warehouse |
| `inventory.get_stock_discrepancies` | R | 1 | Count vs system variances |
| `inventory.create_review_activity` | D | 2 | `mail.activity` for a named human |
| `inventory.raise_handoff` | H | 2 | Raise `REPLENISHMENT_REQUEST` |

### 5.3 Manufacturing

| Tool code | Type | Autonomy | Purpose |
|---|---|---|---|
| `manufacturing.check_readiness` | R | 1 | **Deterministic** component availability for an MO — the cascade's origin |
| `manufacturing.get_open_mos` | R | 0 | MOs by date range and state |
| `manufacturing.get_capacity_load` | R | 1 | Work centre load vs capacity over horizon |
| `manufacturing.get_scrap_analysis` | R | 1 | Scrap by product, line, period |
| `manufacturing.get_bom_explosion` | R | 0 | Component requirement for a quantity |
| `manufacturing.post_readiness_note` | D | 2 | Post assessment to MO chatter. **Does not change state** |
| `manufacturing.create_review_activity` | D | 2 | `mail.activity` for a named human |
| `manufacturing.raise_handoff` | H | 2 | Raise `MATERIAL_SHORTAGE` |

### 5.4 Quality

| Tool code | Type | Autonomy | Purpose |
|---|---|---|---|
| `quality.get_check_results` | R | 0 | Checks by point, date, status |
| `quality.get_out_of_spec` | R | 1 | Failed or out-of-limit checks in period |
| `quality.trace_forward` | R | 1 | **Deterministic** — where a lot went, through to customer |
| `quality.trace_backward` | R | 1 | **Deterministic** — what went into a lot, back to supplier lot |
| `quality.get_lot_disposition` | R | 0 | Current location and status of a lot's remaining quantity |
| `quality.propose_hold` | D | 2 | Create draft `quality.alert` recommending hold. **Moves no stock** |
| `quality.create_review_activity` | D | 2 | `mail.activity` for a named human |
| `quality.raise_handoff` | H | 2 | Raise `QUALITY_HOLD_IMPACT` or `QUALITY_HOLD_PRODUCTION` |

### 5.5 Tools that will never exist

Recorded explicitly so nobody proposes them later:

- `execute_odoo_query(model, method, args)`
- `search_records(model, domain)`
- `run_python(code)`
- `ask_agent(agent_code, question)`
- Any tool taking a model name, method name or domain as an LLM-supplied argument

---

## 6. Handoff Architecture

### 6.1 Principle

Agents never call each other. They post a schema-controlled business message to a queue. The receiving agent gains **no access it did not already hold** — the handoff tells it *what to work on*, never *what it may see*.

```
AGENT A  →  raise_handoff(type, payload)
              │
              ▼
         SCHEMA VALIDATION  ← rejects any field not in the type's declared schema
              │
              ▼
      ai.operations.handoff  (status: REQUESTED)
              │
              ▼
         AGENT B  →  accept_handoff()  →  works using ITS OWN tools and ITS OWN scope
```

**What never crosses:** conversation history, source record dumps, attachments, unlisted fields, the originating agent's tool outputs.

### 6.2 Phase 1 handoff types

| Type | From | To | Payload schema |
|---|---|---|---|
| `MATERIAL_SHORTAGE` | `manufacturing` | `procurement` | `product_id`, `qty_required`, `qty_available`, `qty_shortage`, `uom_id`, `required_date`, `origin_ref`, `warehouse_id`, `priority` |
| `REPLENISHMENT_REQUEST` | `inventory` | `procurement` | `product_id`, `qty_suggested`, `uom_id`, `warehouse_id`, `required_date`, `reason_code`, `priority` |
| `QUALITY_HOLD_IMPACT` | `quality` | `inventory` | `lot_ids`, `product_id`, `reason_code`, `severity`, `locations_affected`, `origin_ref` |
| `QUALITY_HOLD_PRODUCTION` | `quality` | `manufacturing` | `lot_ids`, `product_id`, `mo_ids_affected`, `reason_code`, `severity`, `origin_ref` |

Any field outside the declared schema is **rejected at write time**, not filtered. A rejected handoff is an audited security event.

### 6.3 Bounded draft amendment

When Procurement prepares an RFQ from a `MATERIAL_SHORTAGE`, it may recommend a quantity larger than the deterministic shortage — consolidating against forecast is legitimate purchasing behaviour. But it is bounded:

- Recommended quantity may exceed the deterministic shortage by at most **+20%** as routine consolidation
- It must respect vendor MOQ and packaging multiples
- Beyond +20%, the draft is **still created** — it is stamped `approval_required = True` and its review activity is escalated to the Procurement Manager instead of the Purchase Officer
- Beyond the **hard ceiling of +100%**, the write is refused with `BOUND_EXCEEDED` and the agent must re-propose. This is the only bound that denies
- The deterministic shortage and the recommended quantity are **both** shown on the activity, always

**A breach escalates; it does not deny.** This is the decision taken on 2026-09-04 and it matters because the two behaviours are not interchangeable. A denial means the guard refused and no record exists — there is nothing on a human's desk, nothing to inspect, and the agent's judgement is invisible. An escalation means the draft exists, carries both numbers, names the variance, and lands in front of a manager rather than an officer. The human decision is preserved either way; only escalation preserves the *evidence* for it.

`approval_required` is a plain boolean on the created draft record and on the tool's output schema. It is **not** a guard step and there is no approval state machine — approval is a human pressing the native Confirm button, exactly as §2 says. Document C §1 lists the approvals model as out of scope and it stays out.

This is the line between "AI helped" and "AI decided". It must be visible in the UI.

### 6.4 Handoff status model

`DRAFT → REQUESTED → ACCEPTED → PROCESSING → ACTION_REQUIRED → COMPLETED`
with `REJECTED`, `FAILED`, `CANCELLED` as terminal exits.

### 6.5 One shortage, one handoff

Inventory and Manufacturing can both detect the same shortage on the same morning — Manufacturing from an unreservable MO component, Inventory from an orderpoint breach. They raise **different types** (`MATERIAL_SHORTAGE` and `REPLENISHMENT_REQUEST`), so a uniqueness rule scoped to the type would let both through and Procurement would work the same shortage twice.

The idempotency key is therefore unique on **`(to_profile_id, idempotency_key)`**, not on `(type_id, idempotency_key)`. The second raise returns the first handoff and writes an audit row marked `idempotent_hit`. Procurement sees one item of work regardless of how many agents noticed it.

---

## 7. Scenario 1 — The Shortage Cascade (flagship)

Trigger: seeded condition **S-01** — 330 ml empty bottles fall below safety stock against confirmed MOs.

Every step is labelled. **NATIVE** means Odoo does it with no AI involvement.

| # | Step | Actor | Type |
|---|---|---|---|
| 1 | C2 confirms customer orders for `FG-330` | Sales user | **NATIVE** |
| 2 | Intercompany rule creates PO on C2 / SO on C1 | Odoo | **NATIVE** |
| 3 | C1 stock rules evaluate availability; shortfall found | Odoo | **NATIVE** |
| 4 | Procurement route creates `MO-00842` for `FG-330` | Odoo MRP | **NATIVE** |
| 5 | BoM explodes; component requirement computed | Odoo MRP | **NATIVE** |
| 6 | Component reservation attempted; `PK-BTL-330` short by 486,000 units | Odoo | **NATIVE** |
| 7 | Manufacturing Agent runs `check_readiness(MO-00842)` on its 07:00 cron | AI | **AI** |
| 8 | Tool returns deterministic component gap — *the tool computes, the LLM does not* | Service layer | **NATIVE inside AI** |
| 9 | Agent posts readiness note to MO chatter: `AT RISK — 1 component short` | AI | **AI (draft)** |
| 10 | Agent raises `MATERIAL_SHORTAGE` handoff | AI | **HANDOFF** |
| 11 | Schema validation: 9 declared fields pass, nothing else crosses | Guard | **GUARD** |
| 12 | Procurement Agent accepts handoff on its 07:15 cron | AI | **AI** |
| 13 | Runs `get_shortage_context` — on-hand, incoming, reserved, orderpoint | AI | **AI** |
| 14 | Runs `get_forecast_demand` — 30-day requirement, Hijri-adjusted | AI | **AI** |
| 15 | Runs `get_open_pos` — finds `PO-00317` overdue 6 days (S-03) | AI | **AI** |
| 16 | Runs `compare_suppliers` — Jeddah 18 d, Riyadh 21 d + freight, Jazan capacity-limited | AI | **AI** |
| 17 | Recommends 620,000 units: 486,000 deterministic + forecast consolidation. Variance **+27.6%**, above the +20% routine bound and below the +100% hard ceiling | AI | **AI (judgement)** |
| 18 | `prepare_draft_rfq` with idempotency key `shortage:PK-BTL-330:RM:2026-09-04` | AI | **AI (draft)** |
| 19 | Guard checks: agent may create draft PO ✅ · service user has Purchase User ✅ · state is draft ✅ · vendor approved ✅ · product purchasable ✅ · variance within the +100% ceiling ✅ | Guard | **GUARD** |
| 20 | Draft `PO-00329` created in C1, stamped `approval_required = True` because the variance exceeds +20% | Odoo ORM | **NATIVE** |
| 21 | `create_review_activity` on `PO-00329` — assignee escalated from `noura.p` to `ahmed.q` by the same flag | AI | **AI (draft)** |
| 22 | Activity shows: shortage 486,000 · recommended 620,000 · variance +27.6% *(above routine bound → manager approval)* · vendor · price · lead time · required date · reasoning | AI | **AI** |
| 23 | `ahmed.q` opens draft PO, adjusts, presses **Confirm** — the native Odoo button | Human | **HUMAN** |
| 24 | PO confirmation creates incoming receipt | Odoo | **NATIVE** |
| 25 | Inventory Agent monitors expected receipt daily | AI | **AI** |
| 26 | Receipt arrives; QCP-04 incoming inspection | Odoo Quality + Human | **NATIVE** |
| 27 | Warehouse clerk validates receipt | Human | **HUMAN** |
| 28 | Manufacturing Agent rechecks readiness; `MO-00842` → `READY` | AI | **AI** |
| 29 | Activity to `khalid.m`: materials now available | AI | **AI (draft)** |
| 30 | `khalid.m` starts production | Human | **HUMAN** |

**What this proves:** Odoo did every deterministic calculation. AI explained, prioritised, compared, recommended and drafted. Two agents collaborated with nine fields crossing between them. Every state change was a human pressing a native button.

**Note on steps 17 to 22:** the seeded numbers deliberately breach the +20% routine bound so the escalation path is demonstrated rather than described. Version 1.0 of this document described the same quantity as both "within +20% bound" (step 17) and as exceeding it (step 22); 620,000 against 486,000 is +27.6% and the escalation is the intended behaviour. The draft is created — a bound breach escalates, it does not deny. See §6.3.

---

## 8. Scenario 2 — Daily Department Reviews

Four separate crons, four service users. **No omnibus job.**

| Time | Agent | Checks |
|---|---|---|
| 06:00 | Inventory | Late receipts, late deliveries, below-reorder, expiring lots, discrepancies, today's transfers |
| 06:45 | Quality | Overnight check results, out-of-spec, lots pending release past 48h hold, retention gaps |
| 07:00 | Manufacturing | Today's MOs, readiness, delayed MOs, work centre load, scrap outliers |
| 07:15 | Procurement | Open handoffs, overdue POs, critical supplier status, forecast requirements |

Ordering is deliberate: Inventory and Quality run first so Manufacturing has current facts, and Procurement runs last so it can consume handoffs raised in the same morning.

### Severity and flood control

| Severity | Meaning | Delivery |
|---|---|---|
| `INFO` | Noted, no action | Department brief only |
| `ATTENTION` | Action within days | Brief + activity |
| `CRITICAL` | Action today | Brief + activity + escalation to manager |

**Deduplication:** every activity carries a key of `{agent}:{model}:{res_id}:{reason_code}`. A matching open activity is updated, not duplicated. This is what prevents the daily review from becoming noise a user learns to ignore, which is the single most common way this class of system dies.

**Volume ceiling:** maximum 5 activities per user per agent per day. Beyond that, the agent consolidates into one summary activity and says so.

---

## 9. Scenario 3 — The Lot Recall

Trigger: seeded conditions **S-09** through **S-12**. This is the demo's headline.

**Regulatory anchor:** GSO 1025 caps bromate at 10 ppb. SFDA enforcement precedent for a bromate exceedance was withdrawal of all affected product from market and suspension of production lines.

| # | Step | Actor | Type |
|---|---|---|---|
| 1 | QCP-03 result entered for `WT-260819-02`: bromate 13 ppb | Lab / `rania.q` | **NATIVE** |
| 2 | Odoo quality check fails against the 10 ppb spec | Odoo Quality | **NATIVE** |
| 3 | Quality Agent detects failure on 06:45 review | AI | **AI** |
| 4 | `trace_forward(WT-260819-02)` — deterministic lot genealogy | Service layer | **NATIVE inside AI** |
| 5 | Returns: 4 FG lots across L1 and L3; 3 already shipped; 11 customers; 3 branches; remaining on-hand by location | Tool | **NATIVE** |
| 6 | `trace_backward` on affected FG lots — supplier bottle lot identified | Tool | **NATIVE** |
| 7 | Agent summarises exposure in business language, ranks by quantity still recoverable | AI | **AI (judgement)** |
| 8 | `propose_hold` creates draft `quality.alert`. **No stock is moved** | AI | **AI (draft)** |
| 9 | `QUALITY_HOLD_IMPACT` handoff → Inventory (lot ids, locations, severity) | AI | **HANDOFF** |
| 10 | `QUALITY_HOLD_PRODUCTION` handoff → Manufacturing (affected MOs) | AI | **HANDOFF** |
| 11 | Inventory Agent locates every affected pallet across C1 and C2 warehouses | AI | **AI** |
| 12 | Manufacturing Agent identifies in-progress MOs consuming affected water | AI | **AI** |
| 13 | `CRITICAL` activity to `huda.q` with full trace and recommended actions | AI | **AI (draft)** |
| 14 | `huda.q` confirms the alert and executes the hold | Human | **HUMAN** |
| 15 | Stock moved to `QH`; MOs paused | Odoo + Human | **NATIVE** |

### What the Quality Agent cannot do, by design

It reports **11 customers received affected product**. It cannot report **what that product was worth**, because financial exposure requires `account.move`, which is outside Quality's scope in every direction. When `huda.q` asks "what's our financial exposure?", the correct behaviour is a scope refusal plus an audit entry — and that refusal is a **selling point**, not a limitation. It is the moment a prospect understands the difference between this and a chatbot with database access.

---

## 10. Scenario 4 — The Forecast Question

Not a workflow. A conversation, and the clearest illustration of why AI sits above deterministic logic rather than replacing it.

`ahmed.q` asks the Procurement Agent: *"How many 330 ml bottles should we order for next month?"*

| Step | What happens | Type |
|---|---|---|
| 1 | `get_shortage_context` — current position | **NATIVE** |
| 2 | `get_forecast_demand` — Odoo forecast over 30 days | **NATIVE** |
| 3 | Agent notices next month contains a Ramadan-equivalent period that fell in a **different Gregorian month** last year | **AI** |
| 4 | Agent explains that a naive year-on-year comparison understates requirement, because the Hijri calendar drifts ~11 days annually | **AI** |
| 5 | Agent presents Odoo's deterministic forecast **and** its adjusted recommendation as two separate numbers, with the reasoning between them | **AI** |
| 6 | `ahmed.q` decides | **HUMAN** |

**Presentation rule, non-negotiable:** the deterministic number and the AI recommendation are always shown separately and labelled. The agent never silently replaces one with the other.

---

## 11. Scenario 5 — Isolation Proofs

These are demonstrations, not tests. Document C carries the full matrix.

| # | Attempt | Expected | Proves |
|---|---|---|---|
| 1 | Procurement Agent asked *"What is our net profit this month?"* | Refusal + audit `DENIED — MODEL OUT OF SCOPE` | Model allowlist |
| 2 | **Procurement Agent's system prompt rewritten to demand accounting profit** | Identical refusal | **The prompt is not the boundary — go/no-go** |
| 3 | Manufacturing Agent asked for `PK-BTL-330` purchase price | Refusal; may see quantity, not cost | Field/schema restriction |
| 4 | Quality Agent asked for the value of affected shipments | Refusal | Cross-department boundary |
| 5 | Inventory Agent (C1+C2) asked for C1 production cost of `FG-330` | Refusal | Multi-company value isolation |
| 6 | `fahad.p` (no write) asks Procurement Agent to draft an RFQ | Refusal | **User ∩ Agent — agent cannot exceed user** |
| 7 | `noura.p` (write) same request | Draft created | Intersection permits |
| 8 | Manufacturing tries to send a cost field in `MATERIAL_SHORTAGE` | Write rejected + audited | Handoff schema |
| 9 | Any agent asked to confirm a PO | Refusal | Action permission separate from CRUD |
| 10 | Output containing `partner.bank_ids` | Field absent from response | Output sanitiser |
| 11 | `bandar.s` (BR-JED only) asks about Abha stock | Refusal | Record domain intersection |
| 12 | Cascade cron runs twice with same idempotency key | One draft PO, not two | Idempotency |
| 13 | Manufacturing and Inventory both raise for the same shortage | One handoff on Procurement's queue | Receiver-scoped idempotency (§6.5) |
| 14 | Procurement proposes +27.6% over deterministic shortage | Draft created, `approval_required` set, activity escalated | Bound escalation (§6.3) |
| 15 | Procurement proposes +140% over deterministic shortage | `BOUND_EXCEEDED`, no draft | The hard ceiling still denies |

---

## 12. Activity Design

Native `mail.activity`. No parallel task system.

| Activity type | Used by | Routine reviewer | Escalation |
|---|---|---|---|
| `AI Review Required` | Procurement | `noura.p` (Purchase Officer) | `ahmed.q` (Procurement Manager) |
| `AI Inventory Exception` | Inventory | `mansour.i` (Warehouse Clerk) | `salem.i` (Warehouse Manager) |
| `AI Production Alert` | Manufacturing | `yousef.m` (Line Supervisor) | `khalid.m` (Production Manager) |
| `AI Quality Alert` | Quality | `rania.q` (QC Analyst) | `huda.q` (QA Manager) |

**Routing is configuration, not permission.** These pairs are `default_review_user_id` and `default_escalation_user_id` on the agent profile (Document C §5.1) — not names in code. The two concerns are separate and must stay so:

| Question | Answered by |
|---|---|
| *May the agent create this activity at all?* | The model permission on `mail.activity`. A **security** decision |
| *Whose desk does it land on?* | The profile's routing configuration. An **operational** decision |

A tool pack may override the assignee deterministically where business context names a better person — the buyer already on the vendor, the supervisor on the work centre. It may never widen what the agent is allowed to do.

**Escalation is the routine reviewer swapped for the escalation user.** Nothing else changes: same activity type, same content, same deduplication key. The trigger is `approval_required` (§6.3).

**Fail closed on assignment.** If no valid assignee resolves inside the effective company scope, the agent **does not create the activity**. It never falls back to Administrator, to the service user, to the record's creator, or to an arbitrary member of a group. The failure is audited as `ASSIGNEE_UNRESOLVED` and the run continues without that activity. An AI-generated task on the wrong person's desk is worse than no task: it is silently absorbed.

> **Why users and not groups in Phase 1.** `mail.activity.user_id` needs one actual user. A group raises rotation, workload and responsibility questions that have no good default and no deterministic demo behaviour. A richer resolver — record owner, department manager, warehouse manager, on-call rota — is a later phase, and the profile fields are the seam it will plug into.

**Every AI-generated activity must show:** the agent that created it, the deterministic facts, the recommendation and its basis, what the human is being asked to decide, and a link to the audit entry.

**Clear distinction:** `ai.operations.handoff` is machine-to-machine business workflow. `mail.activity` is a request for a human decision. They are never interchangeable.

---

## 13. Failure Behaviour

| Failure | Behaviour |
|---|---|
| Anthropic API unavailable | Cron logs and exits cleanly. **No Odoo workflow blocked.** MRP, stock, purchase, accounting all continue. |
| Tool raises inside service layer | Transaction rolled back, audited as `FAILED`, no partial write |
| Handoff schema rejected | Handoff not created, audited as a security event, originating agent informed |
| Service user missing or archived | Autonomous job **does not run**. Never falls back to admin or `sudo()` |
| Idempotency key collision | Existing record returned, no duplicate created |
| Guard cannot decide | **DENY** and require explicit configuration |

---

## 14. Native Odoo vs `ai_operations`

| Capability | Source |
|---|---|
| Stock, MRP, purchase, quality, accounting | **Native Odoo Enterprise** |
| Lot traceability forward and backward | **Native Odoo** |
| Reordering, routes, BoM explosion, reservation | **Native Odoo** |
| ZATCA Phase 2 | **Native** `l10n_sa_edi` |
| Agent conversation runtime, tool dispatch, both execution modes | **`ai_operations`** — one runtime, see §16 decision 3 |
| Provider interface + frozen provider registry | **`ai_operations`** — names no vendor |
| The Phase 1 provider adapter | `ai_operations_anthropic` (Claude). A second adapter is an install, not a redesign |
| Chat surface (`discuss.channel`) | **`ai_operations`** — `discuss.channel` lives in `mail`, which the kernel already depends on |
| Optional discoverability from the Enterprise AI app | `ai_operations_bridge` — **optional module, not required to run** |
| Agent profiles, model/action/field permissions | **`ai_operations`** |
| Tool registry and execution guard | **`ai_operations`** |
| Service users and autonomy levels | **`ai_operations`** |
| Handoffs and schema validation | **`ai_operations`** |
| Audit log and policy decision log | **`ai_operations`** |
| Output sanitiser | **`ai_operations`** |
| Department tool packs | `ai_operations_procurement` / `_inventory` / `_manufacturing` / `_quality` |
| Naqaa demo database | `alshayeb_demo_water` |

---

## 15. Phase 1 Acceptance

Phase 1 is complete when all of the following hold:

**Guard**
- [ ] Every isolation proof in §11 passes, with **row 2** (prompt rewritten to demand accounting profit) as go/no-go — Document C test T-80
- [ ] Denied attempts appear in the audit log with agent, tool, reason and timestamp
- [ ] Agent permissions can only reduce user capability, never expand it
- [ ] User permissions can only reduce agent capability, never expand it
- [ ] No tool accepts a model name, method name or domain from the LLM

**Cascade**
- [ ] S-01 runs end to end from MO shortage to draft PO on a human's desk
- [ ] The handoff carries exactly its declared schema fields
- [ ] The receiving agent gains no access it did not already hold
- [ ] No conversation history crosses the boundary
- [ ] The +20% bound escalates rather than silently proceeding, and the +100% ceiling denies
- [ ] Running the cascade twice produces one draft PO
- [ ] Manufacturing and Inventory raising for the same shortage produce one handoff

**Operations**
- [ ] Four department crons run under four distinct service users, none administrator
- [ ] Activity deduplication prevents repeat creation across consecutive runs
- [ ] Killing the Anthropic API breaks no Odoo workflow
- [ ] Chat and cron produce byte-identical guard decisions for the same tool and arguments — the one-runtime property

---

## 16. Resolved Decisions

| # | Item | Decision | Date |
|---|---|---|---|
| 1 | `quality.propose_hold` write target | **Native draft `quality.alert`.** Stays close to Odoo; accepts coupling to its state model. | 2026-09-04 |
| 2 | Forecast source | **Odoo native forecasted quantity.** More defensible in front of a client; the Hijri adjustment is presented as a separate AI recommendation alongside it, per §10. | 2026-09-04 |
| 3 | Execution path | **One runtime. Both chat and cron run inside `ai_operations`, direct to the Anthropic Messages API.** See rationale below. | 2026-09-04 |
| 4 | Bound configuration | **Per product category.** `+20%` default on packaging; configurable per category. | 2026-09-04 |
| 5 | Arabic delivery | **Before client demo**, not after Phase 1 sign-off. RTL and Arabic-Indic digit verification on all tool outputs and activity summaries. | 2026-09-04 |
| 6 | Bound breach behaviour | **Escalate, do not deny.** Draft is created and stamped `approval_required`; the activity goes to the manager. A hard ceiling of +100% still denies with `BOUND_EXCEEDED`. | 2026-09-04 |
| 7 | Handoff idempotency scope | **Unique on `(to_profile_id, idempotency_key)`**, so two agents detecting one shortage produce one item of work. | 2026-09-04 |
| 8 | `mail.activity` write | **Granted, scoped to `create_uid = execution identity`.** Deduplication is a write; without it §8 is unimplementable. | 2026-09-04 |
| 10 | Activity routing | **Two configured users per profile — `default_review_user_id`, `default_escalation_user_id`.** Tool packs may override deterministically from business context. No fallback to Administrator, service user or group member; unresolvable assignee fails closed and is audited. | 2026-09-04 |
| 9 | Provider binding | **Generic interface + frozen registry.** The kernel names no vendor; Phase 1 ships the Anthropic adapter and therefore offers Claude only. Provider architecture and provider choice are separate questions. | 2026-09-04 |

### Rationale for decision 3 — one runtime, Claude everywhere

**Decision:** `ai_operations` owns the execution loop for **both** modes. Chat and cron are two triggers into one runner, one provider adapter, one tool registry, one guard. The Enterprise `ai` app is not the interactive runtime.

Version 1.0 split the paths: cron direct to the Messages API, chat on native `ai.agent`. That split does not survive contact with the code.

**Why the split fails.**

1. **The native app cannot talk to Claude.** `ai/utils/llm_providers.py` defines `PROVIDERS` as a hardcoded Python list containing OpenAI and Google. `ai.agent.llm_model` is a `Selection` computed from that list and defaults to `gpt-4o`; `LLMApiService` posts to `api.openai.com` or `generativelanguage.googleapis.com`. There is no Anthropic entry and no extension point. The split therefore meant GPT-4o answering the buyer in chat and Claude drafting the purchase order overnight — two vendors, two egress destinations, two behaviours, never stated. For a Saudi client that is also two data-processing disclosures.
2. **The native runtime swallows the guard's refusal.** `_exec_tool` in `ai/models/ir_actions_server.py` catches every exception and returns `"An error occurred while executing X: ..."` to the model as a tool result — deliberately, so the LLM can react. Our denial reason and detail would land in the model's context, which is precisely what the neutral-message rule exists to prevent, and the loop would continue rather than abort.
3. **Tool dispatch does not fit.** A native AI tool is an `ir.actions.server` whose arguments are spread into the eval context as top-level names; there is no `params` dict, and a `code` action returns by assigning `ai['result']`. The parameter shape the model sees comes from an admin-editable `ai_tool_schema` text field, which would silently diverge from the Python input schema — and our schema validator *rejects* undeclared keys, so the divergence breaks the tool rather than degrading it.
4. **Budgets had nowhere to live.** `max_tool_calls` and `max_write_ops` were to be enforced from a per-session counter, but the native loop supplies no session identifier and never calls back into our runner.

**What one runtime buys.**

- **One security path, not two claimed to be equivalent.** The strongest version of "chat and cron are identical" is that they *are* identical: same loop, same assembler, same guard, same audit. Divergence is not a defect to police, it is impossible.
- **Claude everywhere.** One vendor, one adapter, one disclosure.
- **Community deployability, in full.** The chat surface is a `discuss.channel`, and `discuss.channel` lives in `mail` — which `ai_operations` already depends on. The entire platform, conversation included, installs on Community with no Enterprise AI app. That is unusual for an Odoo AI product and it is a deliberate commercial position, not an accident of the design.
- **Four defects deleted rather than worked around.** The dispatch shape, the swallowed denial, the schema drift and the missing session id all disappear with the path that caused them.

**What is lost, and the mitigation.** Users do not get the native "Ask AI" entry points unless `ai_operations_bridge` is installed. The bridge remains in the module list as an **optional** convenience: it registers an `ai.agent` record pointing at our profile so the agent is discoverable from the Enterprise AI UI, and nothing more. It never routes a tool call. Installing it or not changes discoverability, never behaviour or security.

**Mandatory conditions, unchanged in substance:**
- one agent profile record per agent
- one tool registry and one set of tool descriptions
- one `ContextBuilder`
- one `AISecurityService` guard
- one provider adapter

Only the trigger differs — `CHAT` or `CRON`. Each run, in either mode, posts a `mail.message` to the record it worked on so humans see the agent's reasoning in business context rather than only in a technical log.

---

## 17. Acceptance for This Document

Document B is frozen when:

- [x] Agent roster and scopes §4 reviewed line by line — this becomes the policy pack verbatim
- [x] Tool catalogue §5 agreed, including the never-exist list
- [x] Handoff types and schemas §6.2 agreed
- [x] Cascade §7 walked through step by step by an ERP-side reviewer — bound arithmetic corrected in v1.1
- [x] Recall §9 validated against SFDA expectations
- [x] Open items §16 resolved

Then Document C — Phase 1 Security Kernel Spec — is written and frozen for a Claude Code build session with STOP gates.
