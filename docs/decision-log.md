# Decision log

Document C §3 requires exceptions to the architecture's own rules to carry *"a written entry in the
decision log"*. This is that log. One entry per decision, each with the rule it touches, the
reasoning, and the cost accepted.

Entries are append-only. A decision that is later reversed gets a new entry that says so; the
original stays.

| # | Date | Decision | Status |
|---|---|---|---|
| DL-001 | 2026-09-06 | Credential storage stays out of the ORM — Option B is unimplementable as approved | ⚠ Open question returned to the approver |
| DL-002 | 2026-09-06 | Move the project off the Odoo.sh trial before 4 October 2026 | Recorded, no code |
| DL-003 | 2026-09-06 | `ir.cron` per profile, shipped inactive with the pack | Implemented |
| DL-004 | 2026-09-06 | `discuss.channel` chat surface, C §9.3 scope only | Implemented |
| DL-005 | 2026-09-06 | B-i to B-iv — the four questions §9.3 leaves open | Implemented |
| DL-006 | 2026-09-06 | The B3 write-path rule and the STOP-gate rule, stated once | Standing rules |
| DL-007 | 2026-09-06 | `ai_operations_bridge` stays unbuilt in Phase 1 | Declined deliberately |

---

## DL-001 — The credential stays out of the ORM, and Option B cannot be built as approved

**Approved as:** *"D1 use recommended Option B for credential handling. Never store or expose the
Anthropic API key in ORM/database, Git, source code, logs, documentation, tests, or memory."*

**The problem: those two halves contradict each other.** Option B, as written in
`docs/reviews/decision-request-phase1-completion.md` §7 and in the original credential memo §5, *is*
"read the key from `ir.config_parameter` once at registry load". Its documented and explicitly
accepted cost was the second ❌ on that option: **the key then lives in the database and enters every
dump.** The instruction "never store the key in ORM/database" forbids exactly the thing Option B
does. Only one of the two can be honoured.

**Two further authorities agree with the constraint, not with Option B:**

- **CI check 11** (Document D §15, frozen, "a build failure, not a warning"):
  `grep -rn "ir.config_parameter" ai_operations*/` outside a test → fails. *The API key never touches
  the ORM.*
- **Document C §5.10**, which chose environment-or-`odoo.conf` precisely to avoid `sudo()` and to
  keep the key out of dumps.

**Resolved as:** the constraint wins over the mechanism. `_credential()` is unchanged — environment
variable `ODOO_AI_ANTHROPIC_TOKEN`, then `odoo.conf` key `ai_anthropic_token`, and nothing else. No
`ir.config_parameter`. No `sudo()`. No code change was required to comply, because the shipped
adapter already complied.

**What was added instead:** the rule is now executable rather than assumed.
`test_no_module_in_the_repository_reads_a_credential_from_the_orm` scans every non-test Python file
in every `ai_operations*` module for an ORM credential read. CI check 11 stated this rule and nothing
ever ran it, so a future adapter could have reintroduced what §5.10 forbids with a fully green suite.
The guard was verified by introducing a violation and watching it fail.

It matches usage, not the word — `env['ir.config_parameter'` and `.get_param(` — because the rule is
explained in prose in several places, and a check that fails on its own rationale is the defect this
project has already found three times in the frozen greps (checks 1, 11 and 16).

**⚠ What this does NOT solve, and what is still open.** Odoo.sh offers neither an environment
variable UI nor a durable `odoo.conf`, so **no agent can reach the vendor from an HTTP or cron worker
on Odoo.sh.** Honouring the constraint means the deployment problem the memo raised is unsolved, not
solved. The remaining routes, none of which can be chosen here:

1. Move off Odoo.sh to a platform with real environment variables or secrets.
2. Accept database storage after all — i.e. Option B with its documented dump exposure, which
   requires withdrawing the "never in ORM/database" constraint.
3. A secrets service the adapter reads over the network, which is new architecture and out of the
   approved scope.

For testing, a key exported inside an SSH shell on the staging container is visible to a manual
`odoo-bin` process and to nothing else. That is a testing workaround, not a deployment.

---

## DL-002 — Off the trial before 4 October 2026

Recorded per the approval. No code action. The Odoo.sh project auto-deletes on **4 October 2026**,
taking branches, builds and database, and trial builds are capped at 1 GB.

---

## DL-003 — `ir.cron` per profile, shipped inactive

**Rule touched:** none. This is Session 11's own deliverable, specified by Document C §9's diagram
(`ir.cron → trigger = CRON`) and never built.

One `ir.cron` per agent profile, in the same policy pack as the profile, under the pack's existing
`noupdate="1"` so a client's schedule survives an upgrade. The record is a `code` server action
calling `model.run('<profile code>', 'CRON')` on `ai.operations.execution` — the single runtime,
never a pack-local loop.

**Shipped `active=False`**, for the same reason the profile is: a policy pack cannot know the
client's company, routing users or service user. Activating the cron before the profile produces a
daily traceback rather than a daily review — fail-closed and visible, but not a pleasant discovery at
07:00, so the ordering is documented in the XML itself.

**No `nextcall`**: a fixed datetime in XML is stale the day after it is written. Odoo defaults it to
installation time and the administrator sets the hour when activating.

**The cron carries no identity of its own.** C §9 puts the autonomous identity on
`profile.service_user_id` and the runtime resolves it there. The cron does not set `user_id`, so
nothing about the scheduler's own identity can widen a run.

---

## DL-004 — The `discuss.channel` chat surface

**Rule touched:** none. Session 12's own deliverable, specified by C §9.3, and never built.

Scope is §9.3 and nothing more: a channel between the employee and the profile's partner, a message
in that channel calls `run(..., trigger='CHAT', session_id=<channel id>)` as `env.user`, and the
answer is posted back as the profile's partner. `discuss.channel` is in `mail`, which the kernel
already depends on, so **the platform stays Community-installable** — the commercial position §9.3
names.

**No new security surface.** The dispatcher decides nothing: it resolves the profile from the channel
and hands the turn to the same runtime a cron uses. Autonomy, model permissions, action permissions,
company scope, budgets, blocklist and audit are unchanged and still enforced by the one guard. A
chat user can reach exactly what the guard already allows them, which for an ordinary employee is
INTERACTIVE mode as themselves.

**Failures stay neutral in the channel.** A provider outage or a budget stop is rendered as a fixed
sentence carrying no provider name, endpoint or reason code — the same rule `NEUTRAL_DENIAL` applies
to tool results, because a leak in a friendly font is still a leak.

---

## DL-005 — B-i to B-iv, the four questions §9.3 leaves open

Recorded in `decision-request-phase1-completion.md` §6 and committed at `76ba807` before any
implementation began; formalised here.

**B-i — how a channel is bound to a profile.** A `Many2one` on `discuss.channel`, and the channel is
created on demand by a button on the agent profile. Rejected: a new model to represent the pairing
(nothing to store that the channel cannot hold), and provisioning a channel per employee in advance
(unbounded, and stale the moment staff change). A channel without the field is an ordinary
conversation and never reaches the runtime.

**B-ii — every message, or only a mention.** **Every message in a bound channel is a turn.** A
mention requires parsing and introduces a failure mode where the agent silently ignores a user who is
plainly talking to it. The channel is dedicated to the agent; there is nobody else in it to address.

**B-iii — a second message while a run is in flight.** **Refused, with a posted notice.** Not
queued: two runs on one channel would share a `session_id`, which is what budgets and the audit log
are reconciled on. Not dropped silently, which is worse than refusing. The flag is released in a
`finally`, so a provider outage cannot wedge a channel permanently — pinned by a test.

*Known ceiling:* the flag is transactional, so it serialises the realistic case (one user, one
browser) and not two simultaneous HTTP workers. Row-level locking is the upgrade path if that ever
matters; it is not needed for Phase 1's interaction model.

**B-iv — who may open a channel.** **`group_ai_user`.** It is already the group the guard reads its
own policy as, so a user without it cannot execute a tool — letting them open a channel would only
produce a conversation that refuses every turn. Enforced with an `AccessError` in
`action_open_chat`, and the button is hidden unless the profile is active, interactive and has a
partner.

---

## DL-006 — Two standing rules, stated once

Both patterns were rediscovered per session. They are stated here so they stop being rediscovered.

### The B3 write-path rule

> **Before specifying a write, name the identity that performs it.** The guard executes as the
> calling identity and `sudo()` is banned, so any record the runtime writes must be writable by an
> ordinary employee in CHAT mode — or the design is wrong, not the ACL.

It appeared five times: the audit log, the policy tables, the token counter, the credential, and
service users needing `group_ai_user`. Four were solved the same way — move the data to a record
whose ACL can safely open. **The credential is the one that cannot be**, because no ACL makes a
secret safe, which is why DL-001 is a deployment question and not an ACL question.

### The STOP-gate rule

> **A gate must fail when the deliverable is absent.** If the gate's test can pass with the
> deliverable unbuilt, it is testing the layer underneath.

It has now happened three times:

| Gate | Deliverable | What the gate actually tested |
|---|---|---|
| Session 11 | Crons | The activity service, called directly |
| Session 12 | Chat surface | `execute_tool()` with two trigger strings |
| T-80 (review finding B4) | The guard refusing an over-scoped tool | Passed without reaching the guard |

Applied here: every test added for DL-003 and DL-004 starts from the artefact a user or the scheduler
touches — a posted message, or the shipped cron's own server action — and two of them
(`test_the_runtime_really_runs_from_a_posted_message`, `test_the_cron_really_runs_the_runtime`) patch
nothing at all, proving the real runtime was entered by asserting on the audit rows it writes.

---

## DL-007 — `ai_operations_bridge` stays unbuilt

Declined deliberately, and confirmed by the approver. Document D §5 makes it optional — *"uninstalling
it changes discoverability and nothing else"* — and it would add an Enterprise dependency to a product
C §9.3 positions as Community-installable, in exchange for a second way to find a menu.
