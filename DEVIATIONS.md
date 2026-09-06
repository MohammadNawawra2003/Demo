# Deviations from Documents C and D — Session 1

The specification is **freeze-ready, not frozen**. Nothing below is a deviation from a frozen
document; each is a proposed correction, raised now because Session 1's own definition of done
depends on it. Every one traces to a finding in
`docs/reviews/ai_operations_review_2026-09-05.md`.

---

## Applied

### 1. Four security groups, not five — the Approver group is gone (finding M4)

**Document D §16** makes "five security groups created with the Document C §11 separation" a
Session 1 acceptance item. **Document C §11** gives the Approver group one power: *"Approve flagged
actions."*

**Document C §1** deletes the approval state machine outright — no approval permission fields, no
guard step, no approval workflow. `approval_required` is a plain boolean stamped on a draft record,
and approval is a human pressing the native Confirm button. So the Approver group has nothing to
approve and no model to approve it on.

Shipped: **User · Auditor · Security Administrator · Technical Administrator.**
`test_the_deleted_approver_group_does_not_exist` asserts the absence, so this cannot be
reintroduced by accident.

Rule 1 of the engineering principles: remove the obsolete path rather than ship a group with no
meaning.

### 2. `partner_id` added to the agent profile (finding H4)

**Document C §9.3** requires the chat surface to be *"a `discuss.channel` between the employee and
the profile's partner."* **Document C §5.1**'s field list has no partner. Session 12 — the session
that proves the one-runtime property via T-99 — would block on a field nobody added.

`res.partner` is in `base`, so this holds the `base + mail` rule and CI check 15 (verified).

---

## Discovered while building — two of the frozen CI checks fail on correct code

Both are in **Document D §15**, which declares each check "a build failure, not a warning". As
written, each fails this session's code, which is itself correct.

### 3. CI check 1 — `grep -rn "sudo()" ai_operations*/`

Matches the string `sudo()` **inside comments and docstrings**. This module contains no `.sudo()`
call, but it explains the ban in four places — including the constraint message *"It must never
fall back to the administrator or to sudo()."* — and the check fails on all four.

A check that punishes documenting the rule will be worked around by deleting the documentation.

**Proposed:** `grep -rn "\.sudo(" ai_operations*/` — matches an actual call, not a mention.
Verified: PASS on this codebase, and it still catches `self.env['x'].sudo()`.

### 4. CI check 16 — `grep -rniE "anthropic|claude|openai|gemini|api\.anthropic|_TOKEN"`

The `-i` flag makes `_TOKEN` case-insensitive, so it matches **every token-budget field Document C
§5.1 mandates**: `max_daily_tokens`, `tokens_today`, `tokens_date`, and later `token_input` /
`token_output` on the audit row. The check designed to keep vendor names out of the kernel fails on
the kernel's own spend ceiling.

**Proposed:** split it — case-insensitive for the vendor names, case-sensitive for the credential
suffix:

```bash
grep -rniE "anthropic|claude|openai|gemini|api\.anthropic" ai_operations/   # vendors
grep -rn  "_TOKEN" ai_operations/                                           # credential names
```

Verified: both PASS on this codebase.

---

## Empirical support for finding B3 (the audit-log write path)

Not a deviation — a fact this session surfaced and the guard will hit in Session 3.

`ai.operations.model.permission` and `.action.permission` had to be granted **read to
`group_ai_user`**, the ordinary agent user. That is not a convenience: the guard runs as the
executing identity and `sudo()` is banned, so a plain employee must be able to read the policy
being enforced against them. `test_plain_ai_user_can_read_policy` documents it.

Reading policy is harmless. **Writing the audit log is not**, and it is the same mechanism: the
audit row is opened before the guard runs and then updated five times (Document D §11), so the
executing identity needs `create` *and* `write` on `ai.operations.audit.log`. In CHAT mode that
identity is an ordinary employee, who could then edit their own denial rows.

Session 3 cannot be built until this is decided. The two options in the review are append-only rows
(`create=1, write=0, unlink=0`, reconstructing a run by `correlation_id`) or a single documented
`sudo()` carve-out confined to the audit service.

---

## Session 2 — two calls the specification leaves open

### 5. When the tool registry freezes

Document C §6.2 says the registry is "frozen after load". There is no Odoo hook that fires once
every addon has been imported — `post_load` and `post_init_hook` are both per-module, and the tool
packs load *after* the kernel. So:

- Freezing at kernel load would lock the packs out entirely.
- Freezing lazily on first read would also lock them out, because `ai.operations.tool` reads the
  registry to compute its own fields during install.

`freeze_registry()` is therefore an **explicit call**, which the execution runtime makes once before
its first provider call — long after every module has been imported. That preserves the property
that actually matters (no registration at *runtime*) and is asserted by T-05. Session 5 wires the
call; until then the registry is open, which is correct, because nothing executes yet.

### 6. The tool description comes from the docstring, not the database

Document C §5.5 lists `description` as a plain editable `Text`, while Document D §8's `ToolSpec`
carries `description: str  # from the docstring`. They cannot both be the source.

Shipped as a **computed readonly mirror of the Python docstring**, following D. An admin-editable
description is text that goes straight into the model's context as part of the tool definition — a
prompt-injection surface reachable by configuration rather than by code. Making it readonly costs
nothing and closes it, and it means the description cannot drift from the code it describes. Same
reasoning C §5.5 already applies to `code`, `models_used`, `actions_used` and `idempotent`.

---

## Session 2 UI regression — the app tile never appeared (fixed in 19.0.1.2.0)

Found by manual UI testing on Odoo.sh staging: `ai_operations` installed cleanly, the Apps page
showed the icon and all seven menus, and **no AI Operations tile appeared on the home screen**.

### How Odoo decides

`ir.ui.menu._visible_menu_ids()` (`base/models/ir_ui_menu.py`) makes a menu visible only when it has
an action whose model the user may read, then walks that visibility **upward** to its ancestors.
Menus whose `group_ids` the user lacks are filtered out before any of that. So a tile appears only
if the root survives the group filter *and* some descendant action survives the ACL check.

### Root cause, confirmed against the staging database

**Primary: nobody held any AI Operations group.** Querying the stage database for users holding any
group owned by this module returned **zero rows** — `admin` included. That is Document C §11 working
exactly as written (`base.group_system` deliberately implies no AI group), but nothing ever granted
the groups to anyone, so the root menu's `groups="group_ai_user"` matched no user in the database.

**Secondary, latent: the root menu restricted itself.** It carried `groups="group_ai_user"` while
its only child, Configuration, required `group_ai_auditor`. A user holding only `group_ai_user`
would therefore pass the root's own filter and still see nothing, because no descendant was visible
and visibility only propagates upward. Not the cause of the reported symptom — once a user holds
Security Administrator the implication chain satisfies `group_ai_user` anyway — but a real defect.

### The fix

1. **Bootstrap the administrator.** `base.user_admin` is linked into `group_ai_security_admin` and
   `group_ai_technical_admin` via `user_ids` on the group records — the pattern every Odoo app uses.
   This grants two groups to **one named user**, visibly and revocably. It does **not** add an
   implication from `base.group_system`, which would hand the AI security model to every
   administrator in every database. `test_group_system_still_implies_no_ai_group` and
   `test_a_fresh_system_administrator_does_not_inherit_the_app` hold that line.
2. **Removed `groups=` from the root menu.** It can never add visibility — Odoo already hides a
   parent whose descendants are all hidden — so it can only subtract, hiding the app from someone
   who legitimately has a child menu.

**No ACL was widened and no group gained a member beyond the one administrator.** `Configuration`
still requires `group_ai_auditor`; every Session 1 and 2 separation test still passes.

### Regression cover

`tests/test_menus.py`, ten tests asserting against `_visible_menu_ids()` itself rather than against
a proxy such as the icon attachment, which was perfectly correct the whole time the tile was
invisible. Verified by negative control: restoring `groups="ai_operations.group_ai_user"` on the
root fails `test_root_menu_carries_no_group_of_its_own` and nothing else.

### The lesson worth keeping

A security model that grants nothing by default is correct and unusable at the same time. Every
future group this kernel adds needs an explicit answer to "who holds this on day one", or the
feature ships invisible.

---

## Session 5 — the provider layer, the runtime, service users and budgets

T-60 to T-71 and T-86 pass, plus T-09, T-72, T-73, T-74a and **T-100**. The kernel still installs
alone on a bare Community database and still names no vendor: CI check 16 passes on
`ai_operations/`, and every vendor string lives in `ai_operations_anthropic/`.

### B3-b closed — by ordering, not by infrastructure

Session 4 found that an audit row written *inside* the savepoint a failure rolls back disappears
with the failure it records. The fix needed no separate connection: **the runtime audits after the
rollback**, in the outer transaction. `execute_tool` runs the tool and serialiser inside
`cr.savepoint()` and writes the DENIED row in the `except` block outside it. The serialiser no
longer audits at all, which also gives it one job.

`test_a_failure_inside_the_savepoint_is_still_audited` proves a blocklist hit survives.
Worth noting for anyone writing the next such test: **`assertRaises` cannot be used for it** —
Odoo wraps that in a savepoint which rolls back on the exception, which is the exact behaviour
under test. Catch the exception directly.

### The daily token counter lives off the policy record (B3 again, third instance)

Document C §5.1 puts `tokens_today` / `tokens_date` on the agent profile. The runtime must increment
them **as the executing identity**, `sudo()` is banned, and the profile is the record carrying
`max_autonomy_level` and every permission line. Granting an ordinary user write on the profile so
they can count tokens would hand them write on the policy governing them.

The counter is therefore `ai.operations.budget`: a profile reference, a date and an integer, with
nothing sensitive to protect, so agent users may increment it while the policy record stays
read-only to them. `profile.tokens_today` becomes a computed read of it, and `tokens_date` is gone.

That is now **three** places where C's design assumed a write the executing identity cannot make:
the audit log, the token counter, and the policy read that needed `group_ai_user`. The pattern is
worth stating once in the specification rather than rediscovering per session.

### 🔴 CONFIRMED BLOCKER: C §5.10's secret mechanism does not exist on Odoo.sh

**Confirmed 2026-09-05** by inspecting the full Odoo.sh Project Settings page: there is **no
Environment Variables, Variables or Secrets section**. The page offers Project Name, Collaborators,
Session lifetime, Public Access, GitHub commit statuses, GitHub Key & Webhook, Submodules,
Production Database Size, Database Workers, Workers Settings, Staging Branches, Development
Branches, Firewall and Activation — and nothing else.

**Decision memo prepared for George:** `docs/reviews/decision-request-credential-storage.md`. It
states the one question (is the `sudo()` ban absolute, or "no `sudo()` in the guard or tool path
with a documented allowlist"?), three options with honest costs, and a recommendation.

**Nothing is being changed until he rules.** Session 6 is on hold. The architecture is untouched.

Two facts that shape the options, both verified against source:

- `ir.config_parameter`: one ACL row, `group_system`, and `get_param()` calls `check_access('read')`
  (`ir.model.access.csv:118`, `ir_config_parameter.py:68`). So a DB-stored key needs `sudo()` **at
  request time**.
- `_register_hook()` is called from `odoo/modules/loading.py:594` under an environment built at
  line 404 as `api.Environment(cr, api.SUPERUSER_ID, {})`. **That context is already superuser**, so
  a read there is not an escalation we perform — which is the basis of the recommended option.

### The B3 pattern, now four instances

The credential is the fourth time the specification has assumed a write or read the executing
identity cannot make: the audit log, the policy tables, the token counter, and now the secret. The
first three were each solved by moving the data to a record whose ACL could safely be opened.
**That cannot work for a credential**, because no ACL makes exposing a secret safe. George should
state the rule once in the specification rather than have it rediscovered per session.

### (Original note, superseded by the confirmation above)

Document C §5.10 requires the API key to come from **the environment or `odoo.conf`, and nowhere
else**, specifically so no `sudo()` is needed to read it. On the staging build:

- `~/.config/odoo/odoo.conf` exists, but `~/src/user` is a git checkout and the container is
  rebuilt on every commit, so anything written there by hand is lost at the next build.
- The environment carries only platform-set variables (`ODOO_STAGE`, `ODOO_VERSION`, `PGPASSWORD`);
  there is no developer-settable entry among them.

**Odoo.sh appears to offer no durable, developer-settable environment variable or `odoo.conf`
entry.** If that is confirmed, C §5.10's mechanism is unavailable on the project's stated deployment
target, and the options are: a platform feature we have not found yet, a documented `sudo()`
carve-out confined to the adapter reading `ir.config_parameter`, or a different deployment target.
**This blocks a production Session 5, not the code** — the adapter is written and tested, and the
local development path (an exported variable) works today.

### Live API usage

The suite makes **no network calls**. The provider parity test (T-100) and the "no network at
configuration time" test (T-74a) both use a scripted null adapter, and every adapter test patches
the transport. One opt-in live test exists, tagged `-standard` so it never runs in the suite, on
Odoo.sh, or in CI:

```bash
odoo-bin -d <db> --test-enable --test-tags=ai_live --stop-after-init
```

It sends a few tokens and asserts the credential, endpoint, request shape and response parsing work
together — plus one call proving the vendor accepts a schema generated by
`input_schema.to_json_schema()`, which is the one thing a double cannot prove.

---

## Session 4 — the serialiser, and a hole in the audit guarantee

Session 4 shipped the output sanitiser (`services/serializer.py`) and the global blocklist
(`services/blocklist.py`). T-41 to T-45 pass. Two things came out of building it.

### Finding B3-b — a denial CAN escape unlogged, under rollback

Document C §5.9 states that the audit row is opened before the guard so *"a denial can never escape
unlogged"*, and calls that the property T-80 depends on. Document C §7 step 20 executes the tool
**inside a savepoint**, and step 24 **rolls back on any failure**.

Those two cannot both hold while the audit row shares that transaction. **Rolling back the failure
rolls back its own evidence.** Found because a test asserted the audit row after
`assertRaises` — which Odoo wraps in a rolling-back savepoint — and the row was gone, having been
demonstrably written first (verified by instrumenting the writer).

This is the same family as B3: the audit log is the one record the product's credibility rests on,
and the transaction semantics quietly undermine it. Odoo solves it for its own database logger by
writing on an **independent connection** (`odoo/netsvc.py::PostgreSQLHandler`), so log rows survive
whatever the main transaction does.

**Not fixed in Session 4, deliberately.** `Registry.cursor()` in Odoo 19 opens a genuinely new
connection with no test-mode redirection, so a naive durable writer would commit rows outside the
test transaction and pollute every test database. Doing it properly is a Session 3 architectural
change and belongs with Session 5's runtime, where the savepoint actually lives. Two tests document
the current behaviour honestly rather than hiding it, one of which is written to **fail once the gap
is closed**, so it cannot be forgotten:
`test_an_audit_row_written_inside_a_rollback_does_not_survive`.

**For George:** this makes three findings against the audit design (B3, B3-b) and it strengthens the
case for the append-only decision, since durability and immutability are the same conversation.

### CI check 11 fails on the code that implements the rule

`grep -rn "ir.config_parameter" ai_operations*/` matches **the blocklist entry that blocks
`ir.config_parameter`** — the single line enforcing the rule the check exists to protect. That is
now the **third** frozen CI check that fails correct code, after check 1 (`sudo()` in comments) and
check 16 (`_TOKEN` matching the spec's own token counters).

**Proposed:** match usage, not the string.

```bash
grep -rnE "env\[['\"]ir\.config_parameter|\.get_param\(|\.set_param\(" ai_operations/
```

Verified PASS against this codebase. The pattern is worth taking seriously as a class: every one of
these checks was written as a text search for a *word*, and each one fails on the code that
documents or implements the very rule it guards.

---

## `ir.model` is administrator-only metadata, and the AI roles are not administrators (19.0.1.5.0)

Manual staging test as a genuine **AI Technical Admin** — Technical Administrator group, no Odoo
Settings or Access Rights — reported:

> Failed to write field `ai.operations.tool.models_used`
> You are not allowed to access 'Models' (`ir.model`) records.

### What was reproducible, and what was not

**On 19.0.1.4.0 the reported error could not be reproduced**: ORM read, `get_views`,
`web_search_read`, `web_read`, `default_get` and `new()` all passed as a non-system Technical
Administrator. The guards that make them pass — a `try/except AccessError` in the compute and
`groups="base.group_erp_manager"` on the form field — both landed in 19.0.1.3.0, so the report almost
certainly came from 1.1.0–1.2.1, where the form carried a bare `models_used` and the compute had no
guard. Clicking **New** on the then-empty Tools list raises exactly that message.

Guarded is not fixed. Both guards are the kind that hold until somebody edits the view.

**A second defect was reproducible, and worse:** `ir.model.name_search` raises `AccessError` for a
Security Administrator, so **the model picker is dead and a Security Administrator cannot configure a
model permission at all** — the entire job of the role. Nobody had noticed, because every role test
so far called `search()` and `write()` directly and never opened a screen.

### Root cause

`ir.model` grants `base.group_user` **`0,0,0,0`** in Odoo 19 — no read whatsoever. It is
administrator-only metadata. The AI administrators are deliberately **not** Odoo administrators
(Document C §11), so any relation or picker pointing at `ir.model` is unusable by exactly the roles
meant to use it.

### The fix

1. **`models_used` (Many2many → `ir.model`) is deleted.** The declared names were the whole point,
   and `models_used_names`, a computed `Char` from the registry, carries them with no privilege at
   all. The guard never used the relation — it reads `spec.models` from the registry and the stored
   `model_name` on permission records. Removing the field removes the failure mode instead of
   defending it. `test_no_view_exposes_an_ir_model_relation_on_the_tool` sweeps every field on the
   model so it cannot come back.
2. **The permission *lists* now show the stored `model_name`** rather than the `model_id` relation,
   so they render for any authorised role without touching metadata. `model_id` stays on the forms,
   where a Security Administrator genuinely needs the picker.
3. **One ACL row: `ir.model` read-only for `group_ai_security_admin`.** Not
   `base.group_erp_manager` (which is `1,1,1,1` on `ir.model` plus all of Settings), not Access
   Rights administration. You cannot define *which models an agent may touch* without seeing the
   list of models; this is the minimum that makes the role's own job possible.
   `test_security_admins_ir_model_grant_is_read_only` asserts write, create and unlink still refuse.

**Nobody else gains metadata.** The Technical Administrator does not get `ir.model` — enabling a tool
never needed it — nor does the Auditor, nor a plain user. Verified by negative control: deleting that
single ACL row fails exactly the two tests that need the picker.

### Why the automated tests missed it

Every role test called `search()` and `write()` on the ORM. The browser calls `get_views`,
`web_search_read`, `web_read` and `default_get`, and it was one of those that raised. Fixed by
`tests/test_role_ui_access.py`: 20 tests that drive the **web read path** as genuine internal users,
starting with an assertion that none of those users is an Odoo administrator — because if they were,
nothing below it would prove anything.

---

## Session 2 runtime gap — registered tools were never materialised (fixed in 19.0.1.4.0)

Found by manual UI testing on staging: **Configuration → Tools showed "No tools registered yet"**
while the registry on the running worker held `core.describe_scope`.

### What it was not

Checked on the staging worker before changing anything, because each of these was a plausible cause:

| Hypothesis | Evidence |
|---|---|
| Not registered on the HTTP worker | Registry reported `['core.describe_scope']` |
| The registry freeze closed too early | `is_frozen()` was **False**; the freeze is never called yet |
| Record rules hiding it | **Zero** `ir.rule` rows on `ai.operations.tool` |
| ACL hiding it from the Administrator | Row count as `base.user_admin` was 0, same as superuser |
| Present in Postgres but invisible | `select count(*) from ai_operations_tool` → **0** |

### What it was

**Nothing ever created the row.** Session 2 assumed policy packs would ship `ai.operations.tool`
records, the way they ship profiles and permissions. That was wrong, and Document C §5.5 says why:
every field describing what a tool *does* is computed from the decorator and readonly, under the
rule *"Admins may configure. They may never author."* An administrator who must hand-create the
record is authoring it — and an XML record per tool duplicates the registry in a second place,
which is exactly the drift this design refuses when it rejects the native app's editable
`ai_tool_schema`. T-04 ("a record with no registry entry cannot be enabled") only makes sense as a
guard against **stale** records, which presumes records are generated rather than written.

### The fix

`ai.operations.tool._register_hook()` calls `_sync_from_registry()`, which creates a record for every
registered code it does not already have. `loading.py` STEP 9 calls `_register_hook` **exactly once
per registry load, after every module has imported**, under `SUPERUSER_ID` — so it covers install,
upgrade, and tool packs that register after the kernel, with no per-session migration to maintain.

**Records are created disabled, with no assignment.** Registration makes a tool *configurable*, never
*available*: enabling stays a Technical Administrator's act and a call still needs an assignment.
`test_a_materialised_tool_is_still_refused_until_enabled` asserts the guard keeps refusing.
Existing configuration is never touched, so an upgrade cannot reset what an administrator chose.

A tool removed from the code keeps its record, flagged `registered = False` and unable to be
enabled. Deleting it would silently drop its assignments; leaving it makes the orphan visible.

### Regression cover

`tests/test_tool_materialisation.py`, fifteen tests asserting the **database** state the install
produced — the registry was correct the entire time the UI was empty, so testing the registry would
have proved nothing. Includes a sweep over the whole registry, so a future tool pack cannot ship
half-wired.

---

## Session 3 — the audit log is append-only (this is the answer to finding B3)

**Proposed deviation, pending George's ruling.** Document D §11 opens the audit row before the guard
and then updates it five times. The executing identity is an ordinary employee in CHAT mode and
`sudo()` is banned, so "update" means **granting every user of the platform write access to the log
recording their own denials**. That is the one record the product's credibility rests on.

Shipped instead: **one row per event**, keyed by `correlation_id` and ordered by `sequence`, with an
`event_type` of OPEN / DECISION / RESULT / WRITE / VARIANCE / ERROR. `open_entry` still runs *before*
the guard, so no denial escapes unlogged — the property T-80 depends on. ACL is `create` only, and
`write()` / `unlink()` raise outright, so the rule holds even if an ACL is later loosened by mistake.

If George prefers the `sudo()` carve-out, reverting is small: collapse the six event types back to
one row and swap the appends for writes. The tests are written against `call_events(correlation_id)`
rather than against a single row id, so they survive either choice.

### What building it proved

**`ir.model` grants `base.group_user` `0,0,0,0` in Odoo 19** — no read at all
(`base/security/ir.model.access.csv`). Every guard query originally filtered on `model_id.model`,
which traverses into `ir.model`, so the guard raised `AccessError` for any ordinary user. It only
appeared to work in early tests because that user happened to hold `group_erp_manager`.

Two fixes, both of which make the guard more honest:
1. All guard queries now filter on the stored `model_name` field, so the guard needs no privilege
   beyond reading its own policy tables.
2. `_permission_for` converts a leaked `AccessError` into a neutral `AIAccessDenied`. This is not
   cosmetic: the runner hands a tool's exception text back to the model, so an escaping `AccessError`
   would publish part of the permission model into the LLM's context. Covered by
   `test_a_user_without_the_ai_group_gets_a_neutral_denial`.

### Where the guard's steps live

`authorize()` runs steps 1-9, 11-12 and 19 — everything knowable before a tool has resolved a
record. Steps 10, 13 and 14 are record-level and run through `check_records()`, which a tool reaches
via `ctx.check_records()` once it has ids, because only the tool knows them. Steps 15-18 are reached
through `check_action()` and `ctx.check_variance()`. Each check is independently testable against
its own matrix id, which Document D §9 requires.

### A contradiction in the specification, for George

**Document C §16.2 and §16.3 name `purchase.order`, `account.move`, `hr.employee` and a
warehouse-scoped user, and place those tests in Session 3 — which builds a kernel that must install
and pass on a bare database (CI check 3).** Those models do not exist there. The two requirements
cannot both be met as written.

Resolved by asserting the *semantics* against base models of the same shape — `res.partner` as a
permitted model, `res.currency` as an unpermitted one, and `res.company` for the intersection,
because core grants `base.group_user` read-only on it and `group_erp_manager` full access, which is
exactly the `noura.p` / `fahad.p` shape. **T-24 (warehouse scoping) is deferred to the Inventory tool
pack**, since it needs `stock` and `stock_security_warehouse`. The named-model assertions belong in
Sessions 8-11 and the matrix should say so.

---

## Deferred to their own sessions — not deviations

| Item | Session | Why not now |
|---|---|---|
| `tool_assignment_ids` on the profile | 2 | `ai.operations.tool.assignment` does not exist; a One2many to it breaks the registry |
| `provider_code`, `model_code` | 5 | Both are Selections sourced from the provider registry, which does not exist. The Session 1 prompt puts "any provider adapter" on the do-not-build list |
| `data/ir_sequence.xml` | 9 | It exists for the handoff sequence `AIH/%(year)s/#####` |
| Tool / handoff / audit views in the manifest | 2, 3, 9 | Document D §3.1 lists the **final** data set; referencing a view for a model that does not exist breaks the bare-database install that is this session's STOP gate |
| Service-user credential constraints (T-69) | 5 | Document C §10 lifecycle rules; the Session 1 prompt's constraint list stops at `base.group_system` |
| "Security Admin cannot enable a tool" | 2 | There is no tool model yet. Its counterpart, "Technical Admin cannot alter a permission", **is** tested now |

---

## 2026-09-06 — Sessions 11 and 12 completed, and the H4 field finally used

Neither of these is a deviation: both are **frozen deliverables that were never built**, found during
final manual testing and documented in `docs/reviews/decision-request-phase1-completion.md`. The
approved answers and their reasoning are in `docs/decision-log.md`; only the parts that touch this
file are repeated here.

- **`profile.partner_id` (deviation 2, finding H4) now has a consumer.** It was added in Session 1
  because C §9.3's chat surface needs a partner and C §5.1's field list has none. It sat referenced
  by no code until the surface itself was built. The field is unchanged.
- **`discuss.channel` gains two fields in `ai_operations/models/`** — `ai_profile_id` and
  `ai_run_active`. `ai_profile_id` is a `Many2one` to a kernel model, which is the shape CI check 15
  already permits everywhere else in the kernel (`model_permission.profile_id`,
  `audit_log.profile_id`, `audit_log.tool_id`); the check's intent is "no dependency on a module
  outside `base`/`mail`", and `discuss.channel` is in `mail`.
- **CI check 11 now has a test.** It was a grep nobody ran. See DL-001 — including the reason the
  credential decision is *not* resolved by that test.

---

## 2026-09-06 — manual Test 1 failed with HTTP 400: dot-namespaced tool names

Found by the first real end-to-end message on Odoo.sh staging, not by any suite. The agent replied
*"I am unavailable right now"*, and the audit log held an `ERROR` row with **no** profile, tool,
provider or model and **0 tokens in and out** — the request was rejected before anything ran.

### Root cause

Anthropic requires a tool name to match `^[a-zA-Z0-9_-]{1,128}$`. Our tool codes are dot-namespaced
(`procurement.get_open_pos`) and `build_tool_definitions()` sent `spec.code` verbatim as the vendor
tool name. **A dot is not in that set, and the vendor rejects the whole request rather than the one
tool.**

Isolated on staging with three probes at minimum tokens:

| Probe | Result |
|---|---|
| A — no tools | **HTTP 200** |
| B — name `procurement.get_open_pos` | **HTTP 400** `tools.0.custom.name: String should match pattern '^[a-zA-Z0-9_-]{1,128}$'` |
| C — name `procurement_get_open_pos` | **HTTP 200** |

So the endpoint, the `anthropic-version` header, the model id `claude-sonnet-5`, the request JSON
shape, `system`/`messages`, `max_tokens`, and reading the credential from `odoo.conf` were **all
already correct**. One defect, one line.

### Fix

In `ai_operations_anthropic` only. This is one vendor's naming grammar and the kernel must not know a
vendor exists (CI check 16), so nothing in `ai_operations/` changed.

`_vendor_tools()` rewrites illegal characters and returns `{vendor name: our code}`; `_normalise()`
maps the name back, because the runtime looks a tool up by the name that comes back and a one-way
rename would miss the registry on every call. Collisions are resolved rather than assumed away. A
name we never sent is passed through untouched, so it reaches the guard and is denied and logged
there instead of being silently dropped.

### Tests — all three watched failing first

- `test_tool_names_sent_to_the_vendor_match_the_vendor_pattern`
- `test_a_tool_call_is_returned_under_our_own_tool_code`
- `test_an_unknown_tool_name_is_passed_through_untouched`

**420 tests across 9 modules, 0 failed.**

### Staging verification

`ai_operations_anthropic` **19.0.1.1.0** on `stage` `973cc08`. One live call with the exact payload
that had failed — the four real procurement tool definitions — returned **HTTP 200**, 148 input / 4
output tokens, `stop_reason=end_turn`. Only `complete()` was called, so no tool executed and no
business record was created; the transaction was rolled back.

### The credential, resolved (see DL-001)

The key lives in `[options]` of `/home/odoo/.config/odoo/odoo.conf`, whose own header states it *"is
loaded by Odoo.sh workers"*. Odoo keeps unknown keys (`config.py:906-918`) and `config.options` is a
`ChainMap` including them (`config.py:164-170`), so `config.get('ai_anthropic_token')` resolves in
the web worker. **No ORM, no database, no git, no logged value** — CI check 11 stays green and this
is C §5.10's own second permitted location. ⚠ The file is baked into the container image, so a **new
build resets it** and the key must be re-entered.

---

## 2026-09-06 — manual Test 1, second failure: the assistant turn was never replayed

After the tool-name fix the first vendor call succeeded, the vendor chose
`procurement.get_open_pos`, the guard **ALLOWED** it and the tool returned a result. The **second**
call then failed with HTTP 400 — again an `ERROR` row with no profile, tool or model and 0 tokens.

### Root cause — in the kernel this time

`run()` appended the tool result but **never the assistant turn that requested it**, so the second
request was `[user, tool_result]`: an answer with no question in front of it.

Reproduced against the live API at minimum tokens:

| Probe | Result |
|---|---|
| turn 1 | **200**, vendor picks `procurement_get_open_pos` |
| **A** — no assistant turn (what `run()` sent) | **HTTP 400** — `messages.0.content.1: unexpected `tool_use_id` found in `tool_result` blocks … Each `tool_result` block must have a corresponding `tool_use` block in the previous message.` |
| **B** — assistant turn, vendor-safe name | **200** |
| **C** — assistant turn, dotted internal name | **200** |

**Probe C settles a standing hypothesis:** the dotted internal name replayed in history is *not* the
problem. The vendor does not re-validate tool names inside historical `tool_use` blocks. The adapter
still translates them — for consistency with the declarations, not to avoid an error.

### Fix — on both sides of the boundary, each in its own layer

- **Kernel** appends the assistant turn using its own tool codes, and stays vendor-agnostic.
- **Adapter** renders it as `tool_use` blocks with vendor-safe names, and **groups consecutive tool
  results into one user message**. Two results as two user messages would leave the second with a
  user message before it and no matching `tool_use` in it — the same defect waiting for the first
  parallel tool call. That part is preventive, proven by test rather than by a live 400.

### Tests — five, all watched failing first

`test_the_second_call_carries_the_assistant_turn_that_asked_for_the_tool`,
`test_the_assistant_turn_names_the_tool_it_called`, `test_the_tool_result_still_matches_its_call`,
`test_an_assistant_turn_becomes_tool_use_blocks_with_vendor_names`,
`test_results_for_one_assistant_turn_are_grouped_into_one_message`.

**425 tests across 9 modules, 0 failed.**

### Staging verification — the whole loop, live

`stage` `1212666`, kernel **19.0.1.12.0**, adapter **19.0.1.2.0**. A real `run()` as `noura.p`:
`status=COMPLETED`, one tool call, reply naming **P00001 / Jeddah Plastic Industries / Draft**, audit
`OPEN → DECISION(ALLOWED) → RESULT(ALLOWED)` and **no ERROR row**. Purchase-order count unchanged
(1 → 1) and the transaction rolled back, so no business record was created.

---

## 2026-09-06 — manual Test 2: two defects behind one misleading denial

Noura's request was refused with `USER_ACL_DENIED` on `get_shortage_context` and
`compare_suppliers`. It was neither a rights problem nor a single defect.

### Diagnosis came from the audit row, not from guessing

`denial_detail` said *"execution user cannot read product.product"* and `input_args` said the model
had passed **`product_id: 330`** — invented from the code `PK-BTL-330`. **Product 330 does not
exist; PK-BTL-330 is product 8.** Reading a record that does not exist raises `AccessError`, which
the guard correctly maps to `USER_ACL_DENIED` — so a *missing* record reads exactly like a
*forbidden* one.

That conflation is Odoo's own convention (it refuses to leak whether a record exists), so it stays.
But it is worth knowing when reading an audit log: **`USER_ACL_DENIED` on a read is as likely to mean
"no such record" as "not your record".**

Verified as Noura before changing anything: `product_id 330` denied, `product_id 8` **succeeds**,
with no permission change. She already holds `purchase.group_purchase_user` and
`stock.group_stock_user`, both of which grant read on `product.product`. So not missing groups, not
an over-reaching tool, not an incomplete policy, not bad seed references.

### Defect 1 — the agent could not resolve a product (`ai_operations_procurement`)

Every tool in every pack takes a numeric `product_id`, and **no tool anywhere resolved a code to
one**. The model had nothing to do but guess, and any guess is refused.

Adds `procurement.find_product`: READ, QUERY autonomy, declares `product.product` only — already
permitted by the profile, so no permission was widened. Its parameter is **`product_ref`, not
`query`**: the kernel refuses that name outright (`registry.py PROHIBITED_PARAM_NAMES`) because a
parameter the LLM fills must never be mistakable for a domain, a model or an expression. The
registration guard rejected the first attempt — the check works.

### Defect 2 — Naqaa's vendors were invisible (`alshayeb_demo_water`)

`product.supplierinfo.company_id` defaults to the **installing user's** company, so all 33 supplier
prices landed on *My Company* rather than Naqaa, and the multi-company record rule hid every one of
them from every Naqaa user. `compare_suppliers` returned an empty offer list for every product, with
no error anywhere — the worst kind of failure.

The company is now explicit, existing rows are corrected on the way past, and `build_all` runs from
an updatable data file instead of a `post_init_hook`: a hook fires on install alone, so a database
built before the fix could never repair itself. Staging repaired itself on upgrade — all 33 rows
moved to company 212.

### Tests — five, reproducing Noura's exact path, all watched failing first

Resolve the code · shortage context · vendor comparison · a draft that is never confirmed · the same
request twice producing one order. **430 tests across 9 modules, 0 failed.**

### Staging verification — no vendor call at all

`stage` `7b0b1fa`. As Noura, through `execute_tool` end to end: `find_product` → id 8;
`shortage_context` → PK-BTL-330; `compare_suppliers` → Jeddah 0.055 **and** Riyadh 0.0583;
`prepare_draft_rfq` → **P00002, state=draft**; the same key twice → **one** order. Transaction rolled
back, so nothing persisted. Zero Anthropic calls were spent on this diagnosis.
