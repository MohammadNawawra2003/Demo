# What is now stale in the existing user guide

Input for the guide rewrite. This lists **only what changed**, so the rewrite does
not have to re-derive it.

---

## 0. 2026-09-09 — George's feedback round. Read this section first.

Four changes from this round, and the first one invalidates **every screenshot of
the agent selector in the guide**.

### 0a. Each employee now sees only the agents assigned to them

**Was:** the chat selector listed all six agents to every AI user. That is what
George's screenshot shows — Noura Al-Harbi, a procurement clerk, being offered
Accounting Intelligence.

**Now:** an Agent Profile carries **Allowed Users**, and an employee is offered
only the agents naming them. Noura sees **Procurement Intelligence** and nothing
else. The demo assignment is one agent per employee, with `fahad.p` also on
Procurement because the refusal scene needs him to reach the guard.

**What this makes stale:**
- any screenshot of the chat selector showing more than one agent
- any sentence saying the selector lists the agents "available in your company"
- any instruction to "pick the agent you need from the list"

**What it does not change:** nothing about security. The guard already refused
what the employee's own permissions refused; that is unchanged and is still what
`EFFECTIVE = USER ∩ AGENT ∩ TOOL ∩ ACTION ∩ COMPANY` means. Eligibility is a new
term ahead of it that can only subtract. If the guide claims the old behaviour
was a security hole, that is wrong and worse than saying nothing — it was a
usability and administration gap.

### 0b. Agent Profiles has a new field an administrator will look for

**Allowed Users** on the Agent Profile form (and in the list view). This is the
answer to "how do I know which users this agent belongs to?" — a question the
product previously could not answer at all. Worth a screenshot.

### 0c. The six `AI /` users are explained on screen now

`AI / Accounting`, `AI / General Manager`, `AI / Inventory`, `AI / Manufacturing`,
`AI / Procurement`, `AI / Quality` are **service identities, not employees**. They
exist so an autonomous run has an identity that is not an administrator and not
`sudo()`, and they cannot be logged into — two independent mechanisms enforce it.

They now carry a visible **AI Service User** marker on the user form and a filter
in the user list. If the guide lists them among staff, or omits them and leaves a
reader to find six unexplained accounts, fix that. **They must not be deleted:**
the ORM blocks it, and `ai_operations_demo_data` becomes unupgradeable without
them.

### 0d. Users can send the agent an image

**New capability, so the guide has no wrong text about it — it simply has none.**

A user can attach a picture in the chat widget (paperclip beside the composer)
or in Discuss, and the agent receives and reads it. Worth a screenshot of the
composer with an attachment queued, and one of an answer about an image.

What the guide should say, and should not overstate:

- **JPEG, PNG, GIF and WebP only.** Anything else is refused with a sentence
  naming the reason. A PDF is not an image and is not sent.
- **Up to 4 images per message**, 5 MB each. Larger files are refused, not
  silently truncated.
- **Images are downscaled before sending** (longest edge 1568 px). This is a
  cost control — an image is billed as input tokens — not a quality choice.
  Fine print in a photograph may not survive it. Say so rather than let a
  customer discover it.
- **An image is not remembered.** It travels with the message it was attached
  to and is not replayed on later turns, so a follow-up question about the same
  picture needs the picture again. This is deliberate and bounds both cost and
  exposure.
- **The agent's permissions do not change because an image is attached.**
  Sending a photograph of an invoice does not let a procurement agent read
  accounting. The picture is input, not authority.
- **Voice is not supported.** If anyone asks, it was not requested and was not
  built.

### 0e. Which new screenshot replaces which old one

The pack was rebuilt on 2026-09-09 against `89b707e` and lives in
`~/ai_operations-screenshots/` (28 images, with `SCREENSHOT_INDEX.md`). Use this
table to swap images rather than hunting through both sets.

| Old guide image | Replace with | Why |
|---|---|---|
| any **agent selector / picker** shot listing several agents | **`01-eligibility-noura-procurement-only.png`** + **`02-eligibility-khalid-manufacturing-only.png`** | the selector no longer lists other people's agents; each employee gets one |
| any **Agent Profiles list** | **`18-agent-profiles.png`** | now carries the **Allowed Users** column — this single image answers George's question |
| any **Agent Profile form** | **`26-agent-profile-allowed-users.png`** | ALLOWED USERS is now a group on the form |
| any **user list** used to explain the `AI /` accounts | **`27-ai-service-users.png`** | now shows the **AI Service User** marker column |
| — (new, no predecessor) | **`28-ai-service-user-form.png`** | proves a service identity is Role=User, Accounting=No, Sales=No |
| any **chat composer** shot | **`25-chat-composer-attach-button.png`** | the composer now has a paperclip |
| — (new, no predecessor) | **`24-discuss-image-attachment.png`** | the only image showing a picture reaching the agent |
| any **widget-in-context** shot | **`29-widget-in-context.png`** | panel over Noura's own purchase list, SAR totals, Arabic UI |
| any **draft RFQ** shot | **`14-draft-rfq-form.png`** | reference is now `P00070`; 312.00 SR unchanged |
| any **RFQ list** shot | **`13-purchase-rfq-list.png`** | same |
| any **audit log** shot | **`19-audit-log.png`** | 169 rows; still shows the ALLOWED-then-DENIED pair |
| any **handoff queue** shot | **`20-handoffs.png`** | `AIH/2026/00025` Accepted + 2 cancelled artefacts |
| any **conversation** shot | `03`, `05`, **`06`**, `07`, `09`, `10`, `11`, `12` | all reshot; `06` is new and carries the 312.00 SAR draft |

**Unchanged in meaning, safe to keep if the old one is legible:** `00-apps`,
`15-manufacturing-orders`, `16-manufacturing-order-form`, `17-inventory-overview`,
`21-gm-profile-read-only`, `22-stock-on-hand`, `23-quality-checks`. All were
recaptured anyway so the whole pack comes from one database.

⚠️ **Every record reference changed** (`P00070`, `AIH/2026/00025`, 169 audit
rows). Replace figures wholesale rather than checking them one at a time.

### 0f. Handoff notification — new capability, landing after this pack

**The guide has no wrong text about this; it simply has none** — the same shape
as 0d for image input.

Raising a handoff now notifies the receiving side instead of leaving a row for
somebody to find: the request is posted to the handoff's own chatter, a
`mail.activity` is scheduled for the receiving department's reviewer, the systray
activity clock carries it, the chat launcher shows a count badge and opens itself
once, and the receiving agent is entered automatically with a `HANDOFF` trigger.
A new denial reason `HANDOFF_CASCADE_BLOCKED` holds it to one hop.

**What the guide must say carefully:** `Allow Autonomous` becomes **True for the
profiles that RECEIVE work** (procurement and manufacturing). On its own that tick
reads as "the agent now acts by itself", which is wrong. It permits exactly one
thing — opening work another department queued, once — and the daily cron stays
inactive. Say both halves or neither.

⚠️ **This is not in the current screenshot pack** (captured at `89b707e`; the
handoff work is `baaec43`). `SCREENSHOT_INDEX.md` has the full recapture list
under "What is already stale". At the time of writing the flow was **not yet
verified green on staging**, so do not describe it as shipped until that is
confirmed.

### 0g. A new denial reason exists

`PROFILE_NOT_ELIGIBLE`, alongside the eighteen the guide may already list plus
`STATE_NOT_PERMITTED`. Any table of denial reasons is now short by one.

---

Everything below predates this round.

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

- ~~The Accountant reports every ageing bucket as 0.00.~~ **FIXED.** It was
  correct — the invoices all belonged to Naqaa Distribution while the accountant
  and his agent are scoped to Naqaa Water Manufacturing — but it meant the agent
  could *never* show a figure. The manufacturer now invoices its own
  distribution arm at §3's transfer price, so it has a ledger of its own. The
  Accountant returns **367,145.85 SAR outstanding, 247,735.07 overdue** across
  three buckets, and the GM's financial headlines report the same. **No agent's
  company scope was changed and no permission was widened** — the fix was to
  record the sale a manufacturer actually makes.
- **Payables still read 0.00.** Purchase orders exist but were never billed, so
  there is nothing outstanding to a supplier. That is a true state, not a gap,
  and the GM will say so.
- **Stock shows 230,400 bottles and the order is still short.** Different
  warehouse. The order pulls from the Raw Material Store, which holds 8,000.
