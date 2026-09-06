# `ai_operations_demo_data` — NON-PRODUCTION

**Staging and manual-testing configuration for AI Operations. Never install this on a production
database.**

It creates no business master data. Every company, product, vendor, warehouse and BoM it uses is
Naqaa's, from `alshayeb_demo_water`. What it adds is the AI Operations *configuration* a deployment
would otherwise type in by hand, plus two small source records, so that final manual testing is four
scenarios instead of an afternoon of data entry.

## Isolation

- Nothing in production depends on this module. The dependency runs one way only.
- Removing it leaves the platform working exactly as before; it changes no production code.
- It holds **no credential, no secret and no password**. A test asserts that.
- It never uses `sudo()`, never writes a business model outside a registered tool, never creates a
  handoff or an audit row by hand, and never raises autonomy above Level 2 (Prepare).

**Depends on:** `ai_operations`, `ai_operations_anthropic`, `ai_operations_procurement`,
`ai_operations_manufacturing`, `alshayeb_demo_water`.

## ⚠ A production defect this module compensates for — do not lose this

`ai_operations_manufacturing` ships the `manufacturing.raise_handoff` tool **and** the
`MATERIAL_SHORTAGE` handoff type, but its policy pack grants **no model permission on
`ai.operations.handoff`**. The guard therefore refuses the pack's own handoff tool:

```
MODEL_NOT_PERMITTED: ai.operations.handoff is not in the allowlist
```

**The handoff feature is unreachable in production as shipped.** This module adds the missing
permission (`_compensate_pack_defects`) so the handoff scenario can be tested at all. It is
deliberately here and not in the pack: changing a production policy pack is the approver's decision.

**The fix, once approved:** two fields on one record in
`ai_operations_manufacturing/data/policy_pack.xml` — `perm_read` and `perm_create` on
`ai.operations.handoff` — after which `_compensate_pack_defects` becomes a no-op and should be
deleted.

**A second, smaller finding:** `core.describe_scope` (the kernel's own diagnostic tool) declares
`res.company`, and **no policy pack grants a permission on it**, so that tool is denied for every
shipped profile. This module does not assign it, rather than widening a profile to make a diagnostic
work. Both findings are the same shape: a tool declares a model its pack never permits.

## What it creates

Everything is resolved by **business key** — a login, a company name, a profile code, a tool code —
never by database id, because Naqaa's records are built in Python and carry no XML ids, and ids
differ between databases.

### Agent profiles (2, activated — not created)

The profiles are the packs' own. This module activates and configures them; it invents no new agent.

| | Procurement Intelligence | Manufacturing Intelligence |
|---|---|---|
| Company | Naqaa Water Manufacturing Co. | same |
| Provider / model | `anthropic` / `claude-sonnet-5` | same |
| Routine reviewer | `ahmed.q` | `khalid.m` |
| Escalation | `salem.i` | `salem.i` |
| Service user | `ai.procurement` | `ai.manufacturing` |
| Interactive / autonomous | yes / **no** | yes / **no** |
| Max autonomy | 2 (Prepare) | 2 (Prepare) |
| Budgets | 8 tool calls, 2 writes, 200k tokens/day | same |
| Audit level | FULL | FULL |

`allow_autonomous` stays **off**: the cron is the only autonomous trigger and arming it on staging
would schedule a daily vendor call. Inventory and Quality are left inactive — no prepared scenario
needs them, and activating them would be privilege nobody is testing.

### Tool assignments (least privilege)

Procurement: `get_shortage_context`, `get_open_pos`, `compare_suppliers`, `prepare_draft_rfq`.
Manufacturing: `check_readiness`, `raise_handoff`. Each capped with `max_calls_per_run`.

**How the grant is actually bounded — this matters.** Each pack wires an assignment for *every* tool
it registers, in `_register_hook` (see `ai_operations_procurement/models/policy.py`), and that hook
runs at loading STEP 9, **after** every data file. So `assignment.enabled` is not a gate this module
can hold: anything it disables is recreated a moment later.

`tool.enabled` is the gate. `build_tool_definitions()` offers a tool to the model only when the tool
record **and** the assignment are enabled, so this module enables its six and **disables every other
tool** — for all profiles, not just these two. That is what bounds what any agent is ever shown, and
it is what the test asserts: the *offered* set, computed the way the runtime computes it.

### Chat channels (3)

| Channel | Employee | Agent |
|---|---|---|
| `AI Demo — Procurement (Noura)` | `noura.p` | Procurement Intelligence |
| `AI Demo — Procurement (Fahad, read-only)` | `fahad.p` | Procurement Intelligence |
| `AI Demo — Manufacturing (Khalid)` | `khalid.m` | Manufacturing Intelligence |

Real `discuss.channel` records bound through `ai_profile_id`, the same field the **Chat with Agent**
button sets — so the button keeps working and finds these.

### Handoff type

None created. `MATERIAL_SHORTAGE` (Manufacturing → Procurement) already ships with the manufacturing
pack and is used as it stands.

### Identities

No new users. Naqaa's own people are used, and three of them are granted `ai_operations.group_ai_user`
so they can reach the platform: `noura.p`, `fahad.p`, `khalid.m`. Three `res.partner` records are
created — one per agent — because a channel needs an identity for the agent to speak as.

**`fahad.p` is on the procurement channel deliberately.** Document A §12 seeds him READ ONLY on
purchase, so the request Noura may make is refused for him. That is the denial scenario, and it comes
from Naqaa's own least privilege rather than from a weakened profile.

### Source records (2, and only if absent)

`alshayeb_demo_water` seeds **master data only**; the 18 months of transactions are Session 7's
separate history generator, which is not run on install. A freshly installed Naqaa therefore has zero
purchase orders and zero manufacturing orders, and two scenarios would have nothing to read. So:

- one **draft RFQ** — 250,000 × PK-BTL-330 from Jeddah Plastic Industries
- one **manufacturing order** — 120,000 × FG-330

Both carry `origin = 'AI-DEMO'`, which is what makes them recognisable and idempotent. Both are
drafts: nothing here posts stock or accounting.

### Cron

No cron is created. The four `ir.cron` records already ship with the packs, **inactive**.

**Which cron to activate once a credential exists:** `ai_operations_procurement.cron_ai_procurement`
("AI Operations: Procurement daily review"). Activating it also requires setting `allow_autonomous`
on the Procurement profile, which this module deliberately leaves off — two deliberate acts, not one
checkbox.

## Idempotency

Safe to install, upgrade and re-run. The builder runs from a `<function>` in an updatable data file
rather than a `post_init_hook`, because a hook fires on install only and an upgraded database would
keep whatever configuration it happened to have. Nothing is created that can be found first, and
every field write is the same write on a second run, so a re-run is a no-op that also repairs drift.
A test asserts that a second `build_all()` changes no record counts.

## Uninstall

Uninstalling removes this module's own records and **leaves the configuration behind**: profiles stay
active, assignments stay, channels stay, and the two seeded drafts stay. That is deliberate — they
are records on models this module does not own. To return a database to a pre-demo state, archive the
two profiles and delete the records with `origin = 'AI-DEMO'`.

## Manual testing

Four scenarios; see the handover notes for the exact messages. All four need a working Anthropic
credential — the automated suite proves them with a scripted vendor, but a human typing into a
channel needs the real one.

1. **Successful read** — Noura asks Procurement for open purchase orders.
2. **Prepared draft** — Noura asks for a draft RFQ; a `draft` purchase order appears, never confirmed.
3. **Handoff** — Khalid reports a shortage; a `MATERIAL_SHORTAGE` handoff reaches Procurement.
4. **Denial** — Fahad asks for the same draft and is refused, with a DENIED audit row and nothing
   leaked into the conversation.
