# What is now stale in the existing user guide

Input for the guide rewrite. This lists **only what changed** between the guide's
material and commit `75829b6`, so the rewrite does not have to re-derive it.

The guide itself is deliberately **not** regenerated here — that is being done
separately. The authoritative sources for the rewrite are:

- `docs/GEORGE_FULL_AI_OPERATIONS_DEMO.md` — the Arabic runbook, with the exact
  proven prompts and expected answers
- `docs/SCENARIO_PERMISSION_MATRIX.md` — per-agent permissions and refusals
- `~/ai_operations-screenshots/SCREENSHOT_INDEX.md` — the 20-image pack

---

## 1. Agents that changed what they are

| Item | Was | Now |
|---|---|---|
| **Accountant** | Described as a Phase 2 placeholder holding no tools and no model permissions | **Operational, read-only.** Four tools. Its own profile description said the old thing, and because that description *is* the system prompt, the agent obeyed it and refused its own tools in 3 of 7 runs. Fixed by migration. |
| **General Manager** | Absent | A shipped module, `ai_operations_gm`. Read-only, cross-department summary. Any agent roster without it is incomplete. |
| Both | — | Read-only is enforced by configuration — autonomy 0, write budget 0, zero action permissions — not by instruction. Say it that way. |

## 2. Tools that did not exist before

- `procurement.find_production` / `inventory.find_production` — resolve a human
  reference like `RM/MO/00002` to the id every other tool needs. Without it the
  agent read digits out of the reference and worked on the wrong order.
- `procurement.find_handoff` — scoped to the caller's own queue.
- `inventory.check_order_components` — answers "is this order short?" per line.
- `procurement.get_shortage_context` — gained `production_id` and
  `shortage_basis`. **When scoped to an order it now returns only that order's
  figures.** It used to return company-wide numbers alongside them, and the
  agent treated the pair as a conflict and escalated instead of drafting.

## 3. Behaviour a reader would get wrong

- **Inventory review activities land on the receipt (`stock.picking`), not the
  product.** An activity requires write access on its target; the old target was
  one the Inventory persona could never write, so the tool was unusable by the
  agent that owned it.
- **The tool-call budget bounds one message, not the conversation.** The old
  message told users to start a new conversation, which does nothing. It now
  says to ask for one thing at a time.
- **A refusal raised before the tool loop is still audited.** Token-ceiling
  denials used to reach the user with no audit row at all.
- **An agent can now run for a user narrower than its own company scope.** The
  Inventory agent spans two companies and its demo persona sits in one; every
  call used to crash rather than refuse.

## 4. The demo is now re-runnable — this is new

`ai.operations.demo.reset` restores the scenario to its starting state, including
levelling stock back after a real run has received goods. Any instruction that
says the demo can only be run once per database, or that a fresh database is
needed for a second run, is stale.

Handoffs are **cancelled**, not deleted, and their idempotency keys released. Two
CANCELLED rows in the handoff list after a reset are expected.

## 5. Runbook steps were renumbered

- Old step 3 was doing step 5's work — 13 tool calls where 2 were intended. It is
  now bounded.
- Old step 8a was deleted: it produced zero tool calls in five consecutive runs
  and proved nothing.
- The refusal scene needs its **specific** prompt to be reproducible; a general
  forbidden question does not reliably reach the same guard check.

Renumber against the current runbook rather than patching the old numbers.

## 6. Every record reference changed, and so did the currency

Staging was **rebuilt from scratch** on `89a7964`, and the screenshot pack with
it. Old references are gone:

| | Current (staging) | Current (screenshot pack) |
|---|---|---|
| Sales order | regenerated | `S00662` |
| Manufacturing order | `RM/MO/00002` | `RM/MO/00002` |
| Draft purchase order | `P00023` / `P00024` | **`P00023`** |
| The headline total | **312.00 SAR** | **312.00 SAR** |
| Shortage | `PK-BTL-600`, 12,000 / 8,000 / **4,000 short** | same |
| Supplier offers | Jeddah 0.0780 SAR / 18d · Riyadh 0.0827 SAR / 21d | same |

Any figure, screenshot, or reference from an earlier pack should be replaced
wholesale rather than checked one by one. **Record ids move on every rebuild** —
companies are now 2–5 and channels 3–9 — so nothing may hardcode an id.

**The guide's own expected values need no arithmetic change.** 0.078 and 0.0827
were always the right numbers; only the symbol was wrong. Change `$` to SAR and
the prose stands.

## 6a. New pre-flight facts

- Staging host: `ksa-ai-stage-37686456.dev.odoo.com`, user `37686456`,
  database `ksa-ai-stage-37686456`.
- **The provider key does not survive a rebuild.** `odoo.conf` comes back with
  `dbfilter` only — no `ai_anthropic_token`, no environment variable. Expected
  consequence, not a fault. Restore it and set the file to `600`.
- **A build is not a rebuild.** A normal Odoo.sh build *updates* the database and
  will not fix currency: the companies already exist so `_get_or_create` returns
  early, and Odoo refuses a currency change once the branch has journal items.

## 7. Numbers to restate

- Test suite: **679 tests, 0 failed** (was 620).
- CI: **16 passed, 0 failed, 2 skipped**.
- Screenshot pack: **20 images**, `~/ai_operations-screenshots/`.
- Cost: roughly **87,600 tokens per full pass**, against a 200,000 daily
  ceiling — about **three full runs per day**. Manufacturing is the heaviest
  step at ~60,000.

## 8. Known defects the guide must not paper over

1. ~~Currency shows USD~~ — **FIXED in `89a7964`.** It was a bug, not a
   configuration choice: `_build_companies` searched for SAR without
   `active_test=False`, Odoo ships unused currencies archived, so the search
   found nothing and the company took the database default. Supplier offers
   needed the same fix separately. Every price is now SAR and no amount changed.
   If the guide contains a dollar sign, it is stale.
2. **The refusal string is English inside an Arabic UI, by decision.** It is a
   frozen security constant, not a missing translation.
3. **Chat widget labels render in English** despite a shipped `ar_001.po` —
   static-asset extraction limitation, documented in the file header.
4. `audit_log.token_input` / `token_output` are never written. Token accounting
   is per-run and not attributed per tool call.
5. `profile.tokens_today` is a **non-stored compute** — reading it in SQL always
   returns NULL. Do not document a SQL check against it.
6. The full demo requires **Odoo Enterprise**.

## 9. Two things the guide should teach the presenter to say

Both look like faults on screen and are neither. They came out of reading the
screenshots one at a time, and a presenter who cannot answer them loses the room.

- **The Accountant reports every ageing bucket as 0.00.** That is correct: the
  125 open receivables belong to Naqaa Distribution Co., and both the accountant
  and his agent are scoped to Naqaa Water Manufacturing Co. It is the company
  boundary working, not an empty database.
- **Stock shows 230,400 bottles and the order is still short.** Different
  warehouse. The order pulls from the Raw Material Store, which holds 8,000.
