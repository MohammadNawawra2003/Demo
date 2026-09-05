# Deviations from Documents C and D — Session 1

The specification is **freeze-ready, not frozen**. Nothing below is a deviation from a frozen
document; each is a proposed correction, raised now because Session 1's own definition of done
depends on it. Every one traces to a finding in
`ai_operations/reviews/ai_operations_review_2026-09-05.md` (currently in the `MohammadDemo` repo).

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

## Deferred to their own sessions — not deviations

| Item | Session | Why not now |
|---|---|---|
| `tool_assignment_ids` on the profile | 2 | `ai.operations.tool.assignment` does not exist; a One2many to it breaks the registry |
| `provider_code`, `model_code` | 5 | Both are Selections sourced from the provider registry, which does not exist. The Session 1 prompt puts "any provider adapter" on the do-not-build list |
| `data/ir_sequence.xml` | 9 | It exists for the handoff sequence `AIH/%(year)s/#####` |
| Tool / handoff / audit views in the manifest | 2, 3, 9 | Document D §3.1 lists the **final** data set; referencing a view for a model that does not exist breaks the bare-database install that is this session's STOP gate |
| Service-user credential constraints (T-69) | 5 | Document C §10 lifecycle rules; the Session 1 prompt's constraint list stops at `base.group_system` |
| "Security Admin cannot enable a tool" | 2 | There is no tool model yet. Its counterpart, "Technical Admin cannot alter a permission", **is** tested now |
