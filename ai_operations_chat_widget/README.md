# `ai_operations_chat_widget`

A launcher fixed to the bottom-right of the Odoo backend that opens a compact chat panel, so an
agent can be reached from anywhere without opening Discuss.

## Why a separate module

`ai_operations` declares `'depends': ['base', 'mail'], # NOTHING ELSE. EVER.` and had **no frontend
code at all** — no JS, no OWL, no SCSS, no controllers. Putting a backend web asset in the kernel
would break that rule and put `web` in front of the bare-database install (CI check 3). This module
depends on `ai_operations` and `web`; nothing depends on it, and uninstalling it removes the launcher
and changes nothing else.

## It is a surface, not a second runtime

Every message goes through **the same `discuss.channel`** the Discuss conversation uses — the widget
calls `action_open_chat`, which is the same get-or-create the button uses. So it inherits, rather
than reimplements: the guard, `USER ∩ AGENT ∩ TOOL ∩ ACTION ∩ COMPANY`, the audit rows, the budgets,
the bounded and sanitised history, idempotency, handoffs and the serialiser.

"Open in Discuss" lands on that same conversation, because it *is* that conversation.

**There is no controller and no new endpoint.** The widget calls two ordinary ORM methods, so record
rules and ACLs apply exactly as everywhere else — a second door is a second thing to get wrong. The
browser never sees a provider, a key or a tool name.

| Rule | How it holds |
|---|---|
| Only authorised users see the launcher | `ai_widget_profiles` returns `[]` without `group_ai_user`, and the component renders nothing on an empty list |
| No other company's profiles | the record rule on `ai.operations.agent.profile` filters the `search`; this code never writes a company domain |
| A forged profile id | `browse` + the record rule raise before anything happens; `action_open_chat` re-checks the group |
| History isolation | one channel per (user, agent); the channel is the boundary |
| No `sudo()`, no arbitrary model/method/domain | the module contains none |

## Trigger enum — a deliberate decision

`TriggerType` is frozen at `CHAT` / `CRON` / `HANDOFF` (C §5.9). Adding `WIDGET` would change a
frozen contract for a cosmetic gain, so the widget **reuses `CHAT`**, which is what it is: an
interactive turn by a real user, identity `env.user`. Audit rows from the widget are therefore
indistinguishable from Discuss rows — which is correct, because the conversation is the same one.

## Files

- `models/agent_profile.py` — `ai_widget_profiles()` and `ai_widget_send()`
- `static/src/chat_widget.js` — the OWL component, registered in `main_components`
- `static/src/chat_widget.xml` / `.scss` — panel and launcher
- `tests/test_widget_security.py` — 10 server-side security tests
- `static/tests/chat_widget.test.js` — hoot tests for the component

## Known limitations

- **The JS tests have not been executed here.** They need the hoot browser runner; the Python tests,
  the SCSS compile and the asset bundling were verified.
- Agent routing is a *preselection* from the current app; the user can always change it.
- One conversation per agent per user. Switching agent clears the panel rather than merging threads.
- Answers render as plain text with line breaks preserved; no markdown rendering.
