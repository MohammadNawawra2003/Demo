# `ai_operations` — pre-freeze review of Documents A–D

**Reviewer:** Mohammad · **Date:** 2026-09-05
**Reviewed:** A v1.2 · B v1.3 · C v0.4 · D v0.4 · `05_progress.md` · the Session 1 resume prompt
**Method:** every Odoo 19 claim below was checked against shipped source — `odoo/release.py` confirms
`version_info = (19, 0, 0, FINAL, 0, '')` — plus the Enterprise addons tree. File and line are cited
inline. Nothing is asserted from memory.
**Status:** the documents are freeze-*ready*, not frozen. Everything below is meant to be settled
before the C §21 / D §17 sign-off, because afterwards each one is a Change Request across fourteen
sessions.

---

## ملخّص بالعربية

### الفكرة

المنتج ليس «ذكاء اصطناعي داخل أودو». المنتج هو **نواة أمنية** يصادف أنها تشغّل ذكاءً اصطناعيًا.
الجملة التي يقوم عليها كل شيء موجودة في المستند C الفقرة 2: **«الـ prompt ليس هو الحد»**.
أي تكامل منافس هو شات بوت لديه وصول لقاعدة البيانات، والشيء الوحيد الذي يمنعه من قراءة الرواتب هو
أن التعليمات طلبت منه ذلك بلطف. هنا، الوكيل الذي يُسأل عن صافي الربح يفشل عند فحص صلاحيات على مستوى
الـ ORM، **ويفشل بنفس الطريقة تمامًا** حتى لو أُعيدت كتابة تعليماته لتطلب صافي الربح صراحةً.
هذا هو الاختبار T-80، والمستند C يسمّيه نقطة القبول أو الرفض للمشروع كلّه.

المعادلة: صلاحية المستخدم ∩ صلاحية الوكيل ∩ صلاحية الأداة ∩ صلاحية الإجراء ∩ نطاق الشركة.
واستخدام الدالة sudo ممنوع ويُفحص آليًا في الـ CI. طبقة الوكيل **تطرح فقط** — لا تضيف أبدًا.

أربعة قرارات تحمل التصميم كله:
- النموذج اللغوي **لا يسمّي أبدًا** موديل أو ميثود أو domain. الأدوات دوال بايثون مسجّلة بـ decorator،
  والسجل يُجمَّد عند تحميل الموديول.
- **لا شيء يخرج إلا إذا كان معلنًا** في مخطط إخراج. الحقل bank_ids ليس محجوبًا — هو ببساطة غير قابل
  للوصول أصلًا.
- **أودو يحسب، والذكاء الاصطناعي يفسّر.** الرقم القطعي والتوصية يُعرضان دائمًا كحقلين منفصلين.
- **السقف هو المستوى 2 «تحضير»، وليس «تنفيذ».** أي تغيير حالة يبقى إنسانًا يضغط زرًا أصليًا في أودو.

وقراران استراتيجيان أذكى مما يبدوان: إلغاء ازدواجية الـ runtime (تطبيق الـ ai في النسخة Enterprise
لا يدعم Anthropic أصلًا ويعيد نص الأخطاء إلى النموذج — وقد تحقّقت من الأمرين في الكود المصدري)، وما
نتج عنه أن **المنصّة كاملة تعمل على أودو Community**. والقرار الثاني أن طبقة المزوّد عامة تمامًا،
فإضافة مزوّد ثانٍ تصبح عملية تثبيت لا إعادة تصميم.

**التقييم العام: التصميم سليم ومتين.** ما يلي تصحيحات داخل مواصفة جيدة، وليس إنقاذًا لمواصفة سيئة.

### أربع مشكلات حاجزة (تُفشل اختبارًا معلنًا أو جلسة بناء)

1. **مفتاح الـ idempotency الخاص بالـ handoff يُبطل الغرض الذي وُجد له.** المستند C الفقرة 5.8 يجعل
   التفرّد على المستقبِل تحديدًا كي ينتج عن اكتشاف نفس النقص من وكيلين **مهمة واحدة**. لكن الفقرة 13
   تعرّف المفتاح مسبوقًا باسم الوكيل **المُرسِل**، فينتج نصّان مختلفان ولا يعمل الفهرس إطلاقًا.
   النتيجة: الاختباران T-57 و T-94 يفشلان. السبب الجذري أن صيغة واحدة تؤدي وظيفتين متعاكستين.
2. **النموذج المرجعي لحزمة السياسات في المستند D الفقرة 13 يخالف المستند C الفقرة 5.2 مرتين** —
   يستخدم قيمة مجرّدة في الحقل state_restriction بعد أن شرح المستند C بإسهاب أن ذلك مستحيل، ويستخدم
   في الـ domain اسمًا غير حرفي يرفضه المدقّق المحدَّد في المواصفة نفسها. وهذا النموذج تحديدًا يُنسخ
   حرفيًا في أربع حزم خلال الجلسات 8 إلى 11.
3. **سجل التدقيق لا يمكن كتابته دون كسر منع الدالة sudo.** الصف يُنشأ قبل الحارس ثم يُحدَّث خمس مرات،
   أي أن الهوية المنفِّذة تحتاج صلاحية إنشاء **وتعديل**. وفي وضع المحادثة هذه الهوية موظف عادي — أي أن
   كل مستخدم يستطيع تعديل صفوف الرفض الخاصة به لاحقًا. وهذا هو السجل الذي تقوم عليه مصداقية المنتج كله.
4. **الاختبار T-80، وهو نقطة القبول أو الرفض، قد ينجح دون أن يختبر شيئًا.** لا توجد أداة تعلن الموديل
   المحاسبي أصلًا، فلا شيء يصل إلى الحارس. الاختبار كما هو مكتوب يثبت «لا توجد أداة كهذه»، لا «الحارس
   يعمل». يحتاج أداة اختبار مقصودة واسعة الصلاحية.

### أبرز الملاحظات المهمة

- المثال المعطى للحقل state_restriction يعتمد على حقل **قابل للترجمة** في قاعدة بيانات لغتها
  الافتراضية العربية — تحقّقت: الخاصية translate=True موجودة فعلًا في الكود المصدري.
- **مفتاح منع تكرار الأنشطة ليس له مكان يُخزَّن فيه.** تحقّقت: الموديل mail.activity لا يملك أي حقل
  صالح لذلك ولا أي قيد تفرّد. الاختبار T-98 يعتمد عليه.
- بناء بيئة التنفيذ **يستبدل** الـ context بالكامل فيفقد اللغة — تحقّقت من ذلك في الكود — بينما أحد
  شروط القبول أن يعمل السيناريوهان بالعربية.
- اقتطاع النتائج عند 200 سجل خطر على تتبّع الاستدعاء: يُنقص تقدير حجم المنتج المتأثر بصمت.
- ادعاء العمل على النسخة Community أضيق مما يبدو: حزمتا التصنيع والجودة تعتمدان على الوحدة
  quality_mrp وهي Enterprise. فعلى Community يحصل العميل على وكيلين لا أربعة.

### التوصية الوحيدة التي ليست خطأً

المرحلة الأولى كما هي محدَّدة = ثماني وحدات، أربعة وكلاء، ٩٣ اختبارًا، ومولّد بيانات بربع مليون سجل.
هذه منتج كامل وليست مرحلة. وهدفا المرحلة الأولى المعلنان — إثبات الحارس وإثبات التسلسل — يمكن إثباتهما
بالنواة + وكيل المشتريات + وكيل التصنيع + السيناريو S-01 + مجموعة الاختبارات العدائية فقط.
ثم تأتي الجودة والمخزون وسيناريو الاستدعاء فوق منتج **يعمل بالفعل**. هذه هي القاعدة الثالثة من قواعد
المدير نفسه مطبَّقة على خطته، وهي تحمي المخاطرة الزمنية التي حدّدها هو. الحديث عن **الترتيب**، لا عن
حذف سيناريو الاستدعاء.

**ملاحظة إدارية:** الملفات موضوعة حاليًا داخل مستودع مشروع آخر وعلى فرع لا يخصّها، وتحتاج مستودعًا
مستقلًا قبل بدء الجلسة الأولى.

---

# English — full findings

Severity is "what breaks if this ships as written", not "how wrong it is".

## BLOCKERS

### B1 · The handoff idempotency key format defeats the deduplication it exists to provide

C §5.8 scopes handoff uniqueness to `(to_profile_id, idempotency_key)` **specifically** so that
Manufacturing and Inventory, both noticing the same shortage on the same morning, produce one item
of work on Procurement's queue. T-57 and T-94 assert it; B §11 row 13 demos it.

C §13 then defines the key as
`{profile_code}:{company_id}:{purpose}:{product_ref}:{location_ref}:{date}` — prefixed with the
**raising** profile. Manufacturing produces `manufacturing:1:shortage:PK-BTL-330:RM:2026-09-04`,
Inventory produces `inventory:1:shortage:…`. Two different strings. The unique index never fires.

**T-57 and T-94 fail as specified, and B §11 row 13 cannot be demonstrated.**

Root cause: one format is doing two jobs with opposite requirements.

| Key | Needs the profile prefix? | Why |
|---|---|---|
| Record key (`purchase.order.ai_idempotency_key`) | **Yes** | C §13's own argument: without it two profiles collide |
| Handoff key | **No** | Collision across raisers is the *desired* behaviour |

They need two names and two formats. A third variant exists as well: B §7 step 18 calls
`prepare_draft_rfq` with `shortage:PK-BTL-330:RM:2026-09-04` — no profile, no company —
contradicting C §13 for the identical call.

**Suggested resolution.** Name them separately in D §2's conventions table: `record_idempotency_key`
= `{profile_code}:{company_id}:{purpose}:…`, `handoff_idempotency_key` =
`{company_id}:{purpose}:{product_ref}:{location_ref}:{date}` — receiver-scoped by the unique index,
raiser-agnostic by construction. Then fix B §7 step 18 to match.

---

### B2 · The policy-pack sample in D §13 violates C §5.2 twice

```xml
<field name="state_restriction">draft</field>
<field name="domain">[('company_id','in',allowed_company_ids)]</field>
```

- C §5.2 explains at length that a **bare** `state_restriction` cannot work and must be written
  `field=value`, because `purchase.order` uses `state`, `quality.check` uses `quality_state`, and
  `quality.alert` has no state field at all. It flags the bare form as a v0.1 defect — and the v0.4
  sample still ships it.
- C §5.2 also specifies domains are parsed with `ast.literal_eval` and that **any non-literal is
  rejected on write**. `allowed_company_ids` is a bare Name node; `ast.literal_eval` raises
  `ValueError`. The shipped policy pack would be rejected by the kernel's own validator.

This is worse than a typo because D exists so that "four tool packs written in four separate
sessions are indistinguishable in style" — its samples are copied verbatim. This one is copied into
four policy packs in Sessions 8–11 and fails on first install.

**The design question underneath.** If literal-only domains are the rule, how does a policy pack
express company scoping at all? Two coherent answers, and one should be chosen before freeze rather
than improvised in Session 9:

1. Give the validator a small **allowlist of named context keys** (`allowed_company_ids`,
   `company_id`, `uid`) that are substituted at evaluation time and rejected otherwise. Still no
   `eval`, still no callables.
2. Keep domains strictly literal and leave company scoping entirely to `allowed_company_ids` on the
   execution env, which C §12 already sets explicitly. Simpler, and arguably the correct one — the
   guard already intersects company scope at steps 8 and 14, so a domain repeating it is a second
   source of truth for the same restriction.

---

### B3 · The audit log cannot be written without either breaking the `sudo()` ban or giving ordinary users write access to the security log

D §11: the audit row is created **before** the guard runs (`open_entry`), then updated by
`record_decision`, `record_result`, `record_write`, `record_variance` and `record_error`. The
executing identity therefore needs `create` **and `write`** on `ai.operations.audit.log`.

In CHAT mode that identity is `env.user` — an ordinary employee such as `noura.p`. So every user of
the platform gets write access to the security audit log and can retroactively edit their own denial
rows through the ORM or XML-RPC. `sudo()` is banned and grepped in CI (C §3, CI check 1), so the
usual Odoo escape is unavailable by design.

> **Confirmed by building it.** Session 1 shipped on 2026-09-05, and the ACLs had to grant
> `group_ai_user` — the ordinary agent user — **read** on `ai.operations.model.permission` and
> `.action.permission`. Not a convenience: the guard runs as the executing identity and `sudo()` is
> banned, so a plain employee must be able to read the policy being enforced against them. Reading
> policy is harmless. Writing the audit log is the same mechanism and is not.

Two more instances of the same shape:

- `profile.tokens_today` is accumulated after every provider call (D §11 step 8) → the executing
  identity needs **write on the agent profile**, the same record that carries `max_autonomy_level`
  and the model permissions. An employee who can write that record can widen their own agent.
- `ai.operations.handoff` creation, and the `ai_idempotency_key` write on `purchase.order`.

**Two acceptable fixes. One must be chosen before Session 3, because Session 3 builds the audit log.**

1. **Append-only audit.** One row per event; ACL `create=1, write=0, unlink=0`; reconstruct a run by
   grouping on `correlation_id` (already indexed). This deletes the problem rather than guarding it,
   and it is strictly stronger — append-only is what an auditor actually wants. Cost: the §5.9 row
   estimate roughly doubles, which is nothing at 100–150k rows/year.
2. **One documented `sudo()` carve-out**, confined to `AIAuditService` and the budget counter, with
   the decision-log entry C §3 already provides for, plus a CI rule that permits the grep hit in
   exactly those two files and fails everywhere else.

Counters need the same decision: field-level `groups=` on the profile's sensitive fields, or move
`tokens_today` / `tokens_date` onto their own small model with a narrower ACL.

---

### B4 · T-80, the declared go/no-go, can pass without testing anything

T-80 rewrites Procurement's system prompt to demand accounting profit and expects
`MODEL_NOT_PERMITTED` **at the guard**.

But by the design's own logic no tool takes a model name, and no Procurement tool declares
`account.move`. The LLM cannot express the request — it can only call registered tools. **The guard
is never reached.** The test will most likely be implemented as "assert no out-of-scope tool was
called", which proves that no such tool exists, not that the guard works. It is also
non-deterministic, since it depends on what the model chooses to do (see H5).

That is a materially weaker claim than the one the product is sold on.

**Suggested resolution.** Register a deliberately over-scoped tool double in the test suite — one
that *does* declare `account.move` in its `models` list — and assert the guard denies it at §7
step 11 with `MODEL_NOT_PERMITTED` and the reason audited. Then both halves are proven: nothing
reachable declares finance data, **and** the guard would stop it if something did.

Related: T-84 ("tool arguments tampered to reference an out-of-scope model") is closer to the real
threat than T-80 and deserves go/no-go billing alongside it.

---

## HIGH

### H1 · `state_restriction` on `quality.alert` keys on a translatable field, in an Arabic-default database

C §5.2's worked example is `stage_id.name=New`.

**Verified:** `quality.alert.stage.name` is `fields.Char('Name', required=True, translate=True)` —
`enterprise/quality/models/quality.py:170`. Document A §15 sets Arabic as the default UI language for
all operational users. A restriction matching the English stage name will not match under an
Arabic-context env — and `quality.alert` is the one model the Quality agent is permitted to write.

Key on an XML id, or on a non-translated column, never on `name`.

*Minor related correction:* `quality.alert` is defined in the `quality` addon (`quality.py:306`),
not `quality_control`. The D §3.2 dependency chain still reaches it, but the attribution is off.

### H2 · The activity deduplication key has nowhere to live

B §8 requires every activity to carry `{agent}:{model}:{res_id}:{reason_code}` so a repeated
exception updates rather than duplicates — described as "the single most common way this class of
system dies". T-98 tests it. No field is specified anywhere: not in the kernel model list (C §4),
not in the tool-pack conventions (D §13, which adds only `ai_idempotency_key` to `purchase.order`).

**Verified:** `mail.activity` (`addons/mail/models/mail_activity.py:54-107`) has no ref, key, origin
or external-id field and no unique constraint — its only two constraints are CHECKs on `res_id` and
`user_id`. The sole free-text char is `summary`, a user-facing label with no index and no
uniqueness.

A custom field is genuinely required. The kernel depends on `mail`, so it can and should own an
indexed `ai_dedup_key` on `mail.activity`. Left unspecified, a builder will match on `summary` text —
fragile, and in an Arabic-default database, language-dependent.

### H3 · The activity volume ceiling is stated but never specified

B §8: "maximum 5 activities per user per agent per day; beyond that the agent consolidates into one
summary activity and says so." No field on the profile (C §5.1), no guard step (C §7), no test in the
matrix (C §16). As written it will not get built.

### H4 · The agent profile has no `partner_id`, but the chat surface requires one

C §9.3: "A `discuss.channel` between the employee and the profile's partner." No such field exists in
C §5.1's frozen field list. Session 12 — the session that proves the one-runtime property via T-99 —
blocks on a field nobody added. `res.partner` is in `base`, so adding it breaks neither the
`base + mail` rule nor CI check 15.

### H5 · Five matrix tests depend on what the LLM decides to do

T-80, T-81, T-87, T-95 and T-96 all require the model to *choose* to call something. As CI that is
flaky, slow and costs money on every push — and a flaky go/no-go test gets disabled within a month,
which is precisely the failure mode this specification is otherwise so careful about.

The null adapter invented for T-100 is exactly the right instrument and should be promoted from one
test to the default: the standard suite runs against a scripted adapter returning deterministic
`tool_use` blocks; live-provider runs become a separate manual tier gated on the demo. Small change
now, painful one later.

### H6 · The sanctioned execution env drops `lang` and `tz`

```python
env = self.env(user=execution_user, context={'allowed_company_ids': effective_company_ids})
```

**Verified:** `Environment.__call__` (`odoo/orm/environments.py:126`) uses the passed `context`
verbatim and consults the existing one only when `context is None`. Full replacement.

That loses `lang`, which is load-bearing for a demo whose acceptance criterion (C §18) is "both
scenarios run in Arabic" — tool outputs and activity summaries would render in the server default.
It also interacts with H1.

Set `lang` and `tz` explicitly, and state which language the **audit log** is written in. It should
be English per D §2 regardless of the user's UI language, since it is a forensic record — worth
making explicit rather than leaving to whichever context happens to be active.

*Note for Session 1:* there is no `odoo/api.py` in 19.0; `odoo/api/` is a package re-exporting from
`odoo/orm/`.

### H7 · `max_records` truncation is unsafe on a recall trace

T-16 accepts silent truncation at 200 records plus an audit line. Fine for a stock query. Dangerous
for `quality.trace_forward`: A §13 S-10 has one treated-water batch feeding 4 FG lots across 11
customers and 3 branches, against ~180,000 stock moves. A trace that silently returns the first 200
move lines **under-reports recall exposure** — while the demo's headline claim is that the agent
tells you exactly who received affected product.

Traces must paginate, or deny with an explicit "scope exceeds limit", never truncate. This is a
safety property, not a performance setting, and it should be a separate flag on the tool spec rather
than the shared `max_results`.

### H8 · The Community claim is true of the platform and false of the product; the wording needs to be exact before it reaches a prospect

`ai_operations_manufacturing` and `ai_operations_quality` both depend on `quality_mrp`, which is
Enterprise. So on Community the buyer gets **Procurement and Inventory, not four agents**. The demo
database is Enterprise-only, which also means T-95 and T-96 — the two end-to-end scenario tests — can
never run under CI check 14.

None of this is wrong; all of it is currently implicit. "Runs without Odoo Enterprise AI" is a
sentence a salesperson will shorten to "runs on Community". Write the precise claim into B §14 now:

> The kernel, the execution runtime and the chat surface install and run on Odoo Community. The
> Manufacturing and Quality tool packs require Enterprise Quality (`quality_mrp`). The Naqaa demo
> database requires Enterprise.

### H9 · The daily token ceiling can be overshot by a full call

Checked before each provider call (C §7 step 5), accumulated after the response (D §11 step 8). One
call with a large context can pass the check and land well past `max_daily_tokens`.

Either reserve `max_tokens` against the budget before the call, or accept the overshoot and document
its bound — it is at most one call, so accepting may well be correct. But say so, because
"fail-closed spend ceiling" (C §5.1) currently implies otherwise.

---

## MEDIUM

| # | Finding |
|---|---|
| **M1** | **`@ai_provider` has two incompatible signatures.** C §6.3 shows `@ai_provider(code, label)` with `MODELS` as a class attribute on a plain `AIProvider` subclass. D §8.2 and §12 show `@ai_provider(code, label, models=…)` on a `models.AbstractModel` using `_inherit`. Two frozen documents, one decorator, two contracts — and Session 5 binds to it. |
| **M2** | **The guard's step count disagrees three ways.** C §7's table has 24 rows; C §9's pipeline diagram says "steps 1-19"; D §9's `authorize()` docstring says "steps 1-18". Fourteen sessions cite this. |
| **M3** | **Arabic is Session 14 in C §17 and Session 13 in D §2.** |
| **M4** | **The "AI Operations / Approver" group approves nothing.** C §1 removes the approval state machine entirely — approval is a human pressing Confirm. The group is a leftover from the deleted machinery, and D §16 makes creating all five a Session 1 acceptance item. Per rule 1 of the engineering principles, delete it; four groups is the honest number. |
| **M5** | **The `max_amount` rationale is factually wrong.** C §5.3 says the field is `Float` and not `Monetary` because "the kernel has no `res.currency` relation to hang one on". **Verified:** `res.currency` is in `base` (`odoo/addons/base/models/res_currency.py:21`), so the kernel could hold that relation without breaking `base + mail` or CI check 15. The decision may still be right — a variance bound across three companies is genuinely awkward to denominate — but the stated reason is not. |
| **M6** | **The four `mail.activity.type` records are unassigned, and the failure is silent.** B §12 names four types; no module's data list owns them. **Verified:** `activity_type_id` is **not required** (`mail_activity.py:65`) and its default (`:39-51`) picks the first matching type by sequence, returning an empty recordset if none match. So without them activities are still created — carrying whatever type sorts first, or none — and B §12's routing design degrades without raising. Assign them to a module and assert the type in the activity tests. |
| **M7** | **The `ir.cron` records are unspecified.** Four crons, four service users, but nothing states what `ir.cron.user_id` is set to — and whichever user it is needs ACL to read the agent profile, the tool assignments and the tool records. Interacts directly with B3. |
| **M8** | **The prompt-injection residual risk is rated too comfortably.** C §20's "injection can only request registered tools" is true and is the design's real strength. But a permitted tool with attacker-influenced *content* remains live: injected text in a vendor name or a PO description can steer which vendor lands on a draft PO, or plant attacker-authored text in an activity note a human trusts because it came from the system. Scope cannot be widened; the human's decision can be manipulated. Rate it Medium and name the mitigation — B §12 already requires the activity to show deterministic facts alongside the recommendation, which is exactly the defence. |
| **M10** | **CI check 1 fails on correct code.** `grep -rn "sudo()" ai_operations*/` matches the string inside **comments and docstrings**. The Session 1 kernel contains no `.sudo()` call but explains the ban in four places — including a constraint message reading *"It must never fall back to the administrator or to sudo()"* — and the check fails on all four. A check that punishes documenting the rule gets worked around by deleting the documentation. **Proposed:** `grep -rn "\.sudo("` — an actual call, not a mention. Verified PASS against the built module. |
| **M11** | **CI check 16 fails on the spec's own fields.** `grep -rniE "…\|_TOKEN"` is case-**insensitive**, so `_TOKEN` matches every token-budget field Document C §5.1 mandates: `max_daily_tokens`, `tokens_today`, `tokens_date`, and later `token_input` / `token_output` on the audit row. The check that keeps vendor names out of the kernel fails on the kernel's own spend ceiling. **Proposed:** split it — case-insensitive for vendor names, case-sensitive for `_TOKEN`. Both verified PASS. |
| **M9** | **`_check_credentials` — override the right one.** C §10 proposes overriding it on `res.users` to refuse authentication for service users. **Verified viable:** the 19.0 signature is `_check_credentials(self, credential, env)` (`res_users.py:312`), returning an `auth_info` dict. Trap worth writing into the spec: `res.users.apikeys` has a different method of the same name (`res_users.py:1574`, `_check_credentials(self, *, scope, key)`), and the old public `check_credentials` is no longer called at all (`:1311`). An override on the wrong one passes review and does nothing. |

---

## The one recommendation that is not a defect

### S1 · Phase 1 as scoped is a product, not a phase — ship the cascade slice first

Phase 1 is eight modules, four agents, roughly thirty tools, 93 tests, a generator producing ~250k
records through the ORM with AVCO valuation, and an Arabic delivery. C §20 already names demo-history
generation as the largest schedule risk, sitting on the critical path of every scenario test.

Both of Phase 1's own stated goals (B §1) — **the guard** and **the cascade** — are provable with:

> kernel + `ai_operations_anthropic` + `ai_operations_manufacturing` + `ai_operations_procurement`
> + seeded condition S-01 + the adversarial suite.

Two agents, one scenario, and a demo database needing far less generated history. Inventory, Quality,
the recall scenario, the `quality_mrp` dependency and treated-water lot tracking then land on a
product that already works end to end.

This is rule 3 of the engineering principles applied to the plan itself — *"grow the system in
layers… never trade a working product for unfinished complexity"* — and it directly protects the
schedule risk already identified in C §20.

**The recall scenario is the headline demo and must not be cut.** The argument is about **sequence**,
not scope.

---

## What held up — the specification's own claims, re-verified

The 2026-09-04 review states its corrections were checked against shipped source. The load-bearing
ones were re-checked here independently against Odoo 19.0 final. **All confirmed:**

| Claim | Verified at |
|---|---|
| `ir.config_parameter` has one ACL row (`group_system`) and `get_param()` calls `check_access('read')` — so a DB-stored key forces the first `sudo()` | `base/security/ir.model.access.csv:118`; `ir_config_parameter.py:68` |
| `stock.lot.location_id` is `False` whenever quants span more than one location — a warehouse rule on it would hide exactly the lots a recall is about | `stock/models/stock_lot.py:167-171`; the inverse at `:173` even raises `UserError` |
| `odoo.fields.Domain` is the v19 idiom; `odoo.osv.expression.AND` emits a `DeprecationWarning` | `odoo/orm/domains.py:196`; `odoo/osv/expression.py:240` |
| The Enterprise `ai` app's `PROVIDERS` is a hardcoded OpenAI + Google list with no Anthropic and no extension point | `enterprise/ai/utils/llm_providers.py:17-39`; `get_provider()` raises for anything else |
| `_exec_tool` catches broadly and returns the error text to the model as a tool result | `enterprise/ai/models/ir_actions_server.py:160-200` — the code comment explicitly names access errors |
| `quality.check` uses `quality_state`; `quality.alert` has no `state` field at all | `enterprise/quality/models/quality.py:202`, `:306-404`, plus all four `_inherit` extensions |

Decision 3 (own the runtime) and decision 5 (key out of the database) are both correctly reasoned
from real source. Worth stating plainly, because everything above is a correction inside a
specification that is fundamentally sound — not a rescue.

**One set of numbers is wrong in its own favour, and worth fixing because CI check 12 rests on the
argument.** D §13 states core v19 uses `models.Constraint(...)` "in 176 modules and the legacy
`_sql_constraints` list in exactly one". Actual: **303 occurrences across 89 modules, and zero real
`_sql_constraints` definitions.** The attribute is not legacy, it is **removed** —
`odoo/orm/model_classes.py:162` logs *"Model attribute '_sql_constraints' is no longer supported"*,
and `odoo/upgrade_code/18.1-00-sql-constraint.py` exists to rewrite it. The conclusion is right and
stronger than claimed.

---

## Housekeeping

- **K1 · The documents are untracked inside the wrong repository.** `ai_operations/` sits
  uncommitted in `~/projects/MohammadDemo` on branch `feature/rm-financials` — the Resource
  Management product's branch. It needs its own repository before Session 1, or it gets swept into
  an RM commit.
- **K2 · The Session 1 resume prompt points at files that exist only on the authoring server.**
  `/opt/odoo19/vault/Products/ai_operations/05_progress.md`,
  `/root/.claude/projects/-opt-odoo19/memory/odoo19_skills.md` §178 (marked **mandatory reading**),
  and `vault/30_Systems/Odoo-Build-System/odoo_build_standards.md` (marked FROZEN, binding). A fresh
  Odoo.sh project supplies the Odoo 19 + Enterprise source; the vault and the skills file still need
  copying, or Session 1 begins without the standards it is told are binding.
- **K3 · There is no commercial document.** A–D are engineering-complete and say nothing about
  positioning, pricing, licensing beyond `OPL-1`, who the buyer is, or the per-client deployment
  model. There is also **no demo runbook** — the scenarios are described but nobody could present
  them cold in fifteen minutes. Given A §1 calls the demo data "a reusable product asset rather than
  a throwaway", a Document E is a genuine gap.

---

## Proposed additions to the freeze checklists

**Document C §21:**
- [ ] Record and handoff idempotency keys are separately named and separately formatted; the handoff
      key is raiser-agnostic (B1)
- [ ] The audit log's write path is settled — append-only, or a single documented `sudo()` carve-out —
      and no ordinary user holds `write` on `ai.operations.audit.log` or on the agent profile (B3)
- [ ] `state_restriction` examples key on non-translatable columns (H1)
- [ ] Trace tools are exempt from silent `max_records` truncation (H7)

**Document D §17:**
- [ ] The D §13 policy-pack sample passes the C §5.2 validator as written (B2)
- [ ] `@ai_provider`'s signature is identical in C §6.3 and D §8.2/§12 (M1)
- [ ] T-80 asserts a guard denial against a deliberately over-scoped tool double, and the default
      test suite runs on the null adapter (B4, H5)
