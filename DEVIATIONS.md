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
