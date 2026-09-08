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

## 6. Every record reference changed

The screenshot pack and runbook were rebuilt. Old references are gone:

| | Current |
|---|---|
| Sales order | `S02067` |
| Manufacturing order | `RM/MO/00004` |
| Draft purchase order | `P01066` — 4,000 @ 0.078, Jeddah Plastic Industries |
| Shortage | `PK-BTL-600`, 12,000 required / 8,000 reserved / **4,000 short** |

Any figure, screenshot, or reference from an earlier pack should be replaced
wholesale rather than checked one by one.

## 7. Numbers to restate

- Test suite: **679 tests, 0 failed** (was 620).
- CI: **16 passed, 0 failed, 2 skipped**.
- Screenshot pack: **20 images**, `~/ai_operations-screenshots/`.
- Cost: roughly **87,600 tokens per full pass**, against a 200,000 daily
  ceiling — about **three full runs per day**. Manufacturing is the heaviest
  step at ~60,000.

## 8. Known defects the guide must not paper over

1. **Currency shows USD, not SAR.** The chat says "ريال", the purchase order
   prints dollars. Every Naqaa company is USD because SAR is archived. Customer-
   visible and unfixed.
2. **The refusal string is English inside an Arabic UI, by decision.** It is a
   frozen security constant, not a missing translation.
3. **Chat widget labels render in English** despite a shipped `ar_001.po` —
   static-asset extraction limitation, documented in the file header.
4. `audit_log.token_input` / `token_output` are never written. Token accounting
   is per-run and not attributed per tool call.
5. `profile.tokens_today` is a **non-stored compute** — reading it in SQL always
   returns NULL. Do not document a SQL check against it.
6. The full demo requires **Odoo Enterprise**.
