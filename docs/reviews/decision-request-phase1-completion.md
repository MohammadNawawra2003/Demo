# Decision request — Phase 1 completion: the missing end-user entry point

**To:** George · **From:** Mohammad · **Date:** 2026-09-06
**Addendum to:** `decision-request-credential-storage.md` (2026-09-05), which is carried forward
here unchanged — this is one decision package, not two.
**Status:** 🔴 **Blocks sign-off of end-to-end testing.** All 14 sessions are built, 371 tests green
locally, 265 on staging. The kernel is not in question. What is missing is the surface a human
touches.
**Decide:** six items, listed in §8. Everything above it is evidence.

---

## ملخّص بالعربية

**الوضع:** الجلسات الأربع عشرة كلها مبنية، و371 اختبارًا تنجح. لكن عند البدء بالاختبار اليدوي
النهائي تبيّن أن **المنتج لا يحتوي على أي مدخل يستطيع المستخدم النهائي استعماله**: لا نافذة محادثة،
ولا قناة Discuss، ولا زر على أي مستند، ولا مهمة مجدولة. الدالة التي تشغّل الوكيل
(`ai.operations.execution.run()`) **لا يستدعيها سوى الاختبارات**، ولا شيء في شيفرة المنتج.

**ما كانت المواصفة تطلبه:** المستند C الفقرة 9.3 يحدّد سطح المحادثة بأنه `discuss.channel` بين
الموظّف وشريك الوكيل، والجلسة 12 في جدول الجلسات مُعنونة صراحةً «سطح المحادثة». الذي تحقّق فعليًا في
الجلسة 12 هو الاختبار T-99 الذي يثبت أن مسار المحادثة ومسار الجدولة **نفس المسار** — وهي خاصيّة
صحيحة ومهمّة، لكنها تثبت الطبقة التي تحت السطح المفقود، لا السطح نفسه. والأمر ذاته تكرّر في الجلسة
11: تسليمها يشمل «المهام المجدولة»، ولا يوجد أي سجل `ir.cron` في المستودع.

**الأثر:** لا يمكن إجراء اختبار شامل حقيقي، ولا عرض المنتج على العميل، لأن لا أحد يستطيع تشغيل وكيل
من الواجهة إطلاقًا.

**المطلوب منك:** الموافقة على بناء ما تنصّ عليه المواصفة أصلًا (المهام المجدولة + سطح المحادثة)،
والإجابة على أربعة أسئلة تفصيلية لم تحسمها الفقرة 9.3، **بالإضافة إلى** قرار تخزين المفتاح المعلّق
من المذكّرة السابقة. ⚠ ولا يزال حذف المشروع التجريبي مبرمجًا في **4 أكتوبر 2026 — بعد 28 يومًا**.

⛔ **لم يُكتب أي سطر شيفرة لهذا الغرض، ولن يُكتب قبل موافقتك.**

---

## 1. The finding, in one line

**Nothing in the shipped product can start an agent.** `ai.operations.execution.run()` — the loop, at
`ai_operations/services/execution.py:102` — has **no caller anywhere in the repository except the
test suite**.

Verified at `3cbfcde`, on `development` and `stage`:

| Claim | How it was checked | Result |
|---|---|---|
| No chat surface | `grep -rn "discuss.channel"` across all 8 modules | **1 hit, and it is a comment** — `models/agent_profile.py:35` |
| No scheduled trigger | `grep -rn "ir.cron\|ir_cron"` across all `.py` and `.xml` | **0 hits** |
| No web entry point | `find` for `controllers/`, `wizard/`, `*.js` | **none exist in any module** |
| No record-level trigger | `grep` for `<button` / `type="object"` in all views | **none** |
| The runtime has no production caller | `grep -rn "ai.operations.execution"` excluding `tests/` | **1 hit — the `_name` declaration itself** |
| The full menu tree | `views/menus.xml`, `audit_log_views.xml`, `handoff_views.xml` | Audit Log · Handoffs · Configuration{Agent Profiles, Model Permissions, Action Permissions, Tools, Tool Assignments, Handoff Types} — **exactly what staging shows.** Nothing is broken in the install; that is the whole UI |

The only way to run an agent today is a Python call typed into `odoo-bin shell`.

## 2. What Document C §9.3 and Session 12 required — verbatim

**C §9.3, in full:**

> **9.3 Chat surface**
> A `discuss.channel` between the employee and the profile's partner. `discuss.channel` lives in
> `mail`, so the chat surface adds no dependency to the kernel and **the platform's conversational
> half runs on Odoo Community**.
> `ai_operations_bridge` is optional and adds one thing: an `ai.agent` record pointing at the
> profile, so the agent also appears in the Enterprise AI app's entry points. It dispatches nothing.

**C §9, the runner diagram** — the CHAT branch is specified with the same weight as the CRON branch:

> ```
>                     ┌─ ir.cron ──────────────► trigger = CRON
>                     │      identity = profile.service_user_id
>                     │
>                     └─ discuss.channel ──────► trigger = CHAT
>                            identity = env.user (the employee)
>                            session_id = the channel id
> ```

**C §9, budgets:** *"`session_id` is ours in both: the `discuss.channel` id for chat, the run id for
cron."*

**C §21 session table, row 12:**

> | **12** | Chat surface (`discuss.channel`), optional bridge module | **T-99 passes — chat and cron are provably the same path** |

**Document D §11, the trigger table:**

> | `session_id` | `discuss.channel` id | run id |
> | Transcript surfaced in | the channel | the audit log + record chatter |

Two further lines of the C §9 diagram are also unimplemented: **`→ post mail.message to the record
worked on`** and **`→ close the audit run row`**. The audit log is append-only by design (finding
B3), so "close the run row" is arguably satisfied by the `RESULT` event — but the `mail.message` on
the worked record is not written by `run()`, and it is the second half of D §11's "transcript
surfaced in… the record chatter."

## 3. What Session 12 actually delivered

The commit is `cc8645e`, *"Sessions 12-13: make T-80 test the guard, not the absence of a tool."*

T-99 was satisfied at `ai_operations/tests/test_adversarial.py:219` by calling `execute_tool()` twice
with `trigger='CHAT'` and `trigger='CRON'` and asserting identical output, identical denial reasons,
and two audit rows differing only in identity and trigger. **That property is real, correct and
valuable** — it is the invariant a chat surface would have ridden on.

But it proves the layer *beneath* the deliverable. The STOP gate was written as *"T-99 passes"* and
T-99 can pass without a channel existing, so the gate went green over an unbuilt deliverable.

One artefact of the intended surface did land: `agent_profile.partner_id` (`models/agent_profile.py:39`),
added under review finding H4 precisely because §9.3 needs a partner for the agent to post as, and
C §5.1's field list had none. **It is currently referenced by no code at all.**

## 4. The same shape in Session 11 — the crons

Session 11's deliverable is *"**Crons**, activity dedup, severity"*; its STOP gate is *"T-97, T-98
pass."*

T-97 (`tests/test_activity.py:129`) constructs an `ExecutionContext` by hand and calls the activity
service directly. It never calls `run()` and never touches `ir.cron`. **No `ir.cron` record ships in
any module.**

So this is not one omission but the same omission twice: **neither of the two triggers in the C §9
diagram exists in the product.** Both gates passed because both were written against the layer below
the trigger.

I am flagging this as a pattern rather than two bugs, because it is the third time this project has
hit *"the gate tested something true, but not the deliverable"* — the first being the review finding
B4, where T-80 could pass without ever reaching the guard.

## 5. Impact on real end-to-end use

**What is genuinely proven and not in doubt:** the guard's 19 steps, identity resolution, company
intersection, the serialiser, the global blocklist, the append-only audit trail, activity dedup and
fail-closed routing, handoffs and their idempotency, the four tool packs, the demo company, the
adversarial suite, Arabic. 371 tests.

**What has never executed outside a test:**

1. **No user can start an agent, and no schedule can.** There is no end-to-end path, so there is no
   end-to-end test to sign off. This is why I do not consider manual testing completable today.
2. **The interactive identity path has never run as a real user.** `resolve_identity()` returns
   `self.env.user` for INTERACTIVE mode (`security_service.py:188`). Every test that exercises it
   does so as the test user inside a `TransactionCase`. It has never resolved a genuine logged-in
   employee in a live HTTP session with their real `company_ids`.
3. **`session_id` has never been a real channel id.** Budget counters and the audit log are indexed
   on it and reconciled through it (C §9). In every test it is a hand-written string like
   `'sess-CHAT'`. Two concurrent conversations sharing a budget has never been observed.
4. **The human never sees the agent's reasoning.** Today the output surfaces are a draft record, a
   `mail.activity`, a handoff and the Audit Log. The transcript — D §11's *"surfaced in the channel"*
   — has nowhere to go. For a demo whose entire pitch is *"agents draft, humans confirm"*, the
   drafting is invisible.
5. **Nothing exercises the loop against the live vendor.** Blocked twice over: by this, and by the
   credential decision in §7.

**Honest characterisation of the risk:** the security kernel is in good shape and I would defend it.
What we cannot yet say is that the *product* works, because the product's first inch does not exist.
A green suite proved the floor under a missing step.

## 6. Recommended implementation path — NOT built, pending your approval

Written to what C §9.3 and the session table already specify. **No new architecture is proposed, and
I have deliberately not written any of it.** Three scopes; I recommend A + B and explicitly recommend
deferring C.

### Scope A — the crons (Session 11's own deliverable)

An `ir.cron` per agent profile calling `run(profile_code, trigger='CRON')`, shipped in each tool
pack's policy pack, `noupdate="1"` and **`active=False`** to match the profiles they belong to.

- Introduces **zero new design decisions.** `run()` already refuses to raise into a cron
  (`execution.py:104`) and already forces AUTONOMOUS mode and service-user identity on the CRON
  trigger.
- Makes the autonomous half of the product real and demonstrable on its own.
- Smallest possible change: data records, no new model, no new Python.

### Scope B — the chat surface (Session 12's deliverable, per C §9.3)

Exactly what §9.3 describes, and nothing beyond it:

- A `discuss.channel` between the employee and `profile.partner_id` — the field already exists and is
  waiting for this.
- A hook on incoming channel messages that calls
  `run(profile_code, trigger='CHAT', session_id=channel.id, entry_prompt=<the message>)`
  **as `env.user`**, which is what §9 already mandates for the CHAT branch.
- The response posted back to the channel as the profile's partner.
- `mail` only. No new dependency; the platform stays Community-installable, which §9.3 calls a
  commercial position.

**Four questions §9.3 does not answer, and I will not answer them by inventing:**

| # | Question | My recommendation, if you want the cheapest correct answer |
|---|---|---|
| B-i | How is a channel bound to a profile? A new channel per employee-per-profile, created on demand from a menu — or a field on `discuss.channel`? | A field on the channel pointing at the profile, created on demand. One field, no new model |
| B-ii | Does **every** message in the channel trigger a run, or only a mention of the agent partner? | Every message in a bound channel. Mentions add parsing and a failure mode where the agent silently ignores the user |
| B-iii | What happens to a second message while a run is in flight? | Refuse the second with a posted notice. Queueing is a Phase 2 conversation |
| B-iv | Who may open a channel with an agent — `group_ai_user`, or anyone? | `group_ai_user`. It is the group the guard already reads policy as |

Each is a *product* decision, not a technical one, which is why they are yours.

### Scope C — `ai_operations_bridge` (the optional module)

D §5 states it plainly: *"The bridge is optional and nothing depends on it… Uninstalling it changes
discoverability and nothing else."* It also requires Enterprise, while §9.3's whole point is that the
conversational half runs on Community.

**Recommendation: do not build it in Phase 1.** It adds an Enterprise dependency to a product
positioned as Community-installable, in exchange for a second way to find a menu.

### Estimate and sequencing

A + B is one session's work. **A should land first** — it is data-only, it makes the autonomous path
demonstrable by itself, and it does not wait on B-i to B-iv.

**Neither can complete a live run in a web worker until the credential decision below is made**, so
if you answer only one thing, answer §7.

## 7. Carried forward — the credential blocker (unchanged, still open)

Full analysis: `decision-request-credential-storage.md`. Unchanged since 2026-09-05, restated here so
this is a single package.

C §5.10 requires the API key to come from the environment or `odoo.conf` and nowhere else, to avoid
`sudo()`. **Odoo.sh provides neither**: Project Settings has no Environment Variables or Secrets
section (checked visually, top to bottom), and `~/src/user` is a git checkout rebuilt on every
commit. The mechanism the specification chose is unavailable on the deployment target the
specification names.

**The one question:** is the `sudo()` ban absolute, or is it *"no `sudo()` in the guard or tool path,
with a documented allowlist"*? C §3 already says exceptions require a decision-log entry, so the ban
was never absolute — this is the first case that needs the hatch.

**Recommendation: Option B** — read the key once at registry load, inside the superuser environment
Odoo itself builds at `odoo/modules/loading.py:404`. We would not be escalating to that context; it
is already superuser. CI check 1 stays clean, no allowlist is needed, and the ban survives in letter
and spirit. Accepted cost, to be written into the decision: the key enters database dumps, mitigated
by a different key per environment and rotation on any export.

**Interim, for testing only:** the adapter reads `ODOO_AI_ANTHROPIC_TOKEN` from its own process
environment (`ai_operations_anthropic/models/anthropic_provider.py:47`), so a key exported inside an
SSH shell on the staging container lets us run the two-call live test
(`--test-tags=ai_live`, ~16 and ~64 tokens) and a manual `run()` from `odoo-bin shell`. **That is a
testing workaround and not a resolution** — HTTP and cron workers have no such environment, so
nothing a real user or a real cron triggers can reach the vendor until this is decided.

⚠ **And the deadline has not moved:** the trial project auto-deletes **4 October 2026 — 28 days from
today** — taking the branches, the builds and the database with it. Trial builds remain capped at
1 GB.

## 8. Decisions required, in priority order

| # | Decision | Why it blocks | Recommended |
|---|---|---|---|
| **D1** | **Credential storage** — Option A (`ir.config_parameter` + one allowlisted `sudo()`), **B** (read once in Odoo's own superuser bootstrap), or C (runtime outside Odoo) | No agent can reach the vendor from a web or cron worker. Blocks every live end-to-end run | **B**, with per-environment keys and rotation-on-export written into the decision log |
| **D2** | **Move the project off trial** | Deletion on **4 Oct 2026** takes branches, builds and database. 28 days | Do it this week; it is the cheapest item on this list |
| **D3** | **Approve building Scope A — the `ir.cron` records** (Session 11's unbuilt deliverable) | Without it the autonomous path has no trigger and cannot be demonstrated | **Approve.** Data-only, no new architecture, no open questions |
| **D4** | **Approve building Scope B — the `discuss.channel` chat surface** per C §9.3 (Session 12's unbuilt deliverable) | Without it no end user can interact with the product at all, and end-to-end testing cannot be completed or signed off | **Approve**, minimal scope, §9.3 only |
| **D5** | **Answer B-i to B-iv** — channel↔profile binding, trigger-on-every-message vs mention, concurrent-message behaviour, who may open a channel | §9.3 does not specify them, and I will not invent architecture beyond the frozen spec | As tabled in §6: channel field, every message, refuse-while-running, `group_ai_user` |
| **D6** | **Rule on the B3 pattern generally** — the spec repeatedly assumes writes the executing identity cannot make (5 occurrences), and the STOP gates repeatedly passed at the layer below the deliverable (3 occurrences) | Cheaper to state the rule once than to rediscover it per session | State both rules once, in the decision log |

**Not asked, deliberately:** `ai_operations_bridge` (Scope C). D §5 makes it optional and it would add
an Enterprise dependency to a Community-installable product. I recommend it stays unbuilt in Phase 1;
say so if you disagree.

---

**Nothing is being built while this is open.** `development` and `stage` are at `3cbfcde`, 371 tests
green, `main` unpromoted at `2ac3aa3`, and the architecture is untouched pending your answers.
