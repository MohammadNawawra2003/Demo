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

## Where the toggle lives, and why it is not a floating button

The first version put a round launcher at the bottom-right. That corner is **not free**: mail's own
`ChatHub` anchors its bubbles there and lifts them with `--mail-ChatHub-bubbles-bottomLift`, and the
Discuss and chatter composers put their controls in the same band. A permanently visible button
there covers native controls on exactly the screens people use most, and every fix for that is a
per-screen offset that breaks at the next layout change.

The toggle is therefore a **systray item** — where Odoo puts always-available global tools. It is on
every backend screen, it collides with nothing, and it needs no per-page rule. The panel still opens
bottom-right, but only while it is being used.

## Theming

Styled the way Odoo styles its own chat window: theme-aware Bootstrap utilities in the markup
(`bg-100`, `bg-inherit`, `border-secondary`, `text-muted`) with only geometry in SCSS. The first
version hardcoded colours and a `var()` fallback that resolved to white, which is why it appeared as
a white panel on the dark theme. Agent bubbles use a translucent grey, correct on either theme
without naming a colour that exists in only one.

## Tests

- **Python: 10**, run locally.
- **JS: 9, executed in Chrome on Odoo.sh staging** —
  `--test-tags='/web:WebSuite.test_unit_desktop[@ai_operations_chat_widget]'` →
  `[HOOT] Test suite succeeded`. Running them found three real problems: missing `defineModels`,
  stale selectors from the UI rework, and a test that queried the DOM without opening the panel.

## Known limitations
- There is no local browser here, so JS tests must be run on staging.
- Agent routing is a *preselection* from the current app; the user can always change it.
- One conversation per agent per user. Switching agent clears the panel rather than merging threads.
- Answers render as plain text with line breaks preserved; no markdown rendering.
