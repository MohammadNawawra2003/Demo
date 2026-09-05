# Decision request — credential storage, and the `sudo()` ban

**To:** George · **From:** Mohammad · **Date:** 2026-09-05
**Status:** 🔴 **Blocks a production Session 5.** Sessions 1–5 are built, tested and deployed to
staging; nothing here blocks the code. Session 6 is on hold pending your answer.
**Decide:** one question, in §4. Everything else is context.

---

## ملخّص بالعربية

**المشكلة:** المستند C الفقرة 5.10 يفرض أن مفتاح الـ API يُقرأ من **متغيّر بيئة أو من ملف
`odoo.conf` فقط**، وذلك تحديدًا لتجنّب الحاجة إلى الدالة `sudo`. لكن منصّة Odoo.sh **لا توفّر أي
مكان دائم** لضبط أيٍّ منهما: صفحة الإعدادات لا تحتوي على قسم للمتغيّرات أو الأسرار إطلاقًا (تم
التحقّق بصريًا من الصفحة كاملة)، ومجلّد الشيفرة على الخادم يُعاد بناؤه مع كل commit. أي أن الآلية
المختارة في المواصفة **غير متاحة على منصّة النشر المعلنة نفسها**.

**القرار المطلوب منك سؤال واحد:** هل منع استخدام `sudo` **مطلق**، أم أنه «ممنوع في مسار الحارس
والأدوات، مع استثناء واحد موثَّق للبنية التحتية»؟ المستند C الفقرة 3 يذكر أصلًا أن «الاستثناءات
تتطلّب قيدًا مكتوبًا في سجلّ القرارات» — أي أن المنع لم يكن مطلقًا منذ البداية، وهذه أول حالة تحتاجه.

**التوصية:** الخيار الثاني — قراءة المفتاح **مرّة واحدة عند تحميل السجلّ** في سياق يمنحه أودو نفسه
صلاحية النظام، دون أن نستدعي `sudo` نحن إطلاقًا. يبقى عيب واحد صريح: المفتاح يصبح داخل نسخ قاعدة
البيانات، ويُعالَج بمفاتيح منفصلة لكل بيئة وبتدوير المفتاح عند تصدير أي نسخة.

⚠ **حاجز ثانٍ منفصل:** بناءات النسخة التجريبية محدودة بـ **1 غيغابايت**، والجلستان 6 و7 تولّدان نحو
ربع مليون سجل. هذا قد يتجاوز الحد قبل أن يكتمل التوليد.

---

## 1. The finding

Document C §5.10 requires the provider credential to come from **the environment or `odoo.conf`,
and from nowhere else**. The stated reason is precise and correct:

> `ir.config_parameter` has exactly one ACL row in Odoo 19 — `base.group_system` — and `get_param()`
> calls `check_access('read')` before returning. Service users are constitutionally barred from
> `base.group_system` (§5.1), so a service user reading the key would require `sudo()`.

Both halves verified against shipped source:

| Claim | Verified at |
|---|---|
| One ACL row, `group_system`, full CRUD | `base/security/ir.model.access.csv:118` |
| `get_param()` calls `check_access('read')` | `base/models/ir_config_parameter.py:68` |

**The problem is that neither of the two permitted locations is settable on Odoo.sh.**

| Location | Status on Odoo.sh |
|---|---|
| Environment variable | **No UI exists.** The full Project Settings page has no Environment Variables, Variables or Secrets section — checked visually, top to bottom. The build's environment carries only platform-set values (`ODOO_STAGE`, `ODOO_VERSION`, `PGPASSWORD`, …) |
| `odoo.conf` | `~/.config/odoo/odoo.conf` exists on the build, but `~/src/user` is a git checkout and **the container is rebuilt on every commit**. Anything written by hand is gone at the next push |

So C §5.10's mechanism is unavailable on the project's own stated deployment target. This is not a
disagreement with the reasoning — the reasoning is sound. It is that the platform does not offer the
thing the reasoning selected.

## 2. What this blocks, and what it does not

**Not blocked.** The adapter is written, and its full test suite passes offline — the credential
path, the endpoint, the request shape, the response parsing, and the guarantee that no failure ever
renders the key. Local development works today with an exported variable. 224 tests are green on
staging.

**Blocked.** Any deployment where an agent actually calls the vendor. Session 6 onward will need it,
and every scenario test from Session 8 does.

## 3. Why this is the same conversation as B3

Finding B3 has now appeared **four times**, and the credential is the fourth:

| # | Where | Resolution |
|---|---|---|
| 1 | The audit log is opened before the guard and updated five times, so the executing identity needs write on the security log recording its own denials | **Append-only**, one row per event, create-only ACL |
| 2 | The guard reads its own policy as the executing identity, so ordinary users need read on the permission tables | Granted `group_ai_user` read; harmless, and necessary |
| 3 | The runtime increments a token counter that C §5.1 puts on the agent profile — the record carrying `max_autonomy_level` | Moved to `ai.operations.budget`: a profile, a date, an integer, nothing worth protecting |
| 4 | **The adapter must read a secret as the executing identity** | **No resolution of that shape exists** |

The first three were all solved the same way: move the data to a record whose ACL can safely be
opened. **That cannot work for a credential** — it is a secret, so there is no ACL that makes
exposing it safe. This is the first instance where the pattern genuinely runs out.

Which is why the decision below is architectural rather than an implementation detail.

## 4. The decision we need

> **Is the `sudo()` ban absolute, or is it "no `sudo()` in the guard or tool path, with a documented
> allowlist for infrastructure"?**

Document C §3 already anticipates this: *"Exceptions require a written entry in the decision log."*
The ban was never absolute — it has an escape hatch that nobody has needed until now. We are asking
you to either use it once, deliberately, or to rule it out and pick a different option.

## 5. The options, with honest costs

### Option A — `ir.config_parameter`, with one documented `sudo()` in the adapter only

The key lives in System Parameters. The adapter reads it with a single `sudo()`, recorded in the
decision log, and CI check 1 gains exactly one allowlisted file.

- ✅ Works on Odoo.sh today, with no platform feature required.
- ✅ Confined to the adapter. The kernel, the guard and every tool stay `sudo()`-free.
- ❌ **Uses the escape hatch**, and the first exception is the one that makes the second easier.
- ❌ The key enters every database dump — precisely what C §5.10 wanted to avoid: *"it keeps the key
  out of every database dump, which matters the first time a client database is restored onto a
  laptop."*

### Option B — read once at registry load, in the superuser context Odoo already provides ⭐

`_register_hook()` is called by `odoo/modules/loading.py:594`, under an environment built at line 404
as `api.Environment(cr, api.SUPERUSER_ID, {})`. **That context is already superuser — we would not
be escalating to it.** The adapter reads the parameter once per worker at load, caches it in module
memory, and the runtime never touches the ORM for it again.

- ✅ Works on Odoo.sh today.
- ✅ **No `sudo()` call anywhere**, so CI check 1 stays clean with no allowlist and the ban stays
  absolute in letter and in spirit. The read happens in Odoo's own bootstrap, not in a user request.
- ✅ No ORM access at all on the hot path — strictly less exposure than Option A at run time.
- ❌ Same dump exposure as Option A. This is the unavoidable cost of any database-backed secret.
- ❌ Changing the key requires a worker restart. On Odoo.sh that is a redeploy, which is arguably
  correct for a credential rotation anyway.

### Option C — move the runtime out of Odoo

The agent loop runs as a separate service that holds the key; Odoo exposes tools over authenticated
RPC.

- ✅ The only option where the key never touches the database.
- ❌ Contradicts Document B §16 decision 3 and Document C §9, the one-runtime architecture that
  deletes four defects and makes the platform Community-installable. It would reopen all of them.
- ❌ A Phase 2 conversation at best.

### Not options

- **Leaving the key in git, source, logs or documentation** — never.
- **Writing `odoo.conf` on the build by hand** — erased on the next commit.
- **Encrypting it in a custom model** — the encryption key needs storing, which is the same problem
  one layer down.

## 6. Recommendation

**Option B.** It is the only one that keeps the `sudo()` ban intact as written while working on the
platform we are actually deploying to, and it puts strictly less ORM surface on the hot path than
Option A. It is also reversible: if you later get a real secrets mechanism, the adapter's
`_credential()` is one method and the rest of the platform never learns where the key came from —
which is exactly what the provider abstraction was for.

The dump exposure is real and should be accepted explicitly, with two mitigations written into the
decision:

1. **A different key per environment**, so a restored staging dump never carries the production key.
2. **Rotate on export** — any dump leaving the platform invalidates the key it contains.

`ir.config_parameter` is already on the global field blocklist with no carve-out, so the value can
never be serialised into an LLM's context regardless of which option you pick.

## 7. A second, separate blocker — trial limits versus Sessions 6 and 7

Two things on the same Settings page, both affecting the demo database:

- **"Trial project builds are limited to 1 GB in storage."** Sessions 6 and 7 generate roughly
  250,000 records through the ORM with automated real-time AVCO valuation. With indexes and
  valuation layers that is plausibly several hundred megabytes and may not fit. The production
  database is currently 57 MB, so there is no headroom measured yet.
- **"This project is activated as a trial… After 30 days it will be deleted automatically."**
  That is **4 October 2026**. Fourteen sessions do not fit inside it, and the deletion takes the
  branches, the builds and the database with it.

Neither needs a decision from you today, but both need one before Session 6 starts, and the
activation code is the cheaper of the two to fix.

## 8. What we need back

1. **Option A, B or C** — or a fourth we have not seen.
2. If B: confirmation that reading in Odoo's own superuser bootstrap satisfies the ban, so it goes
   in the decision log as an interpretation rather than an exception.
3. A ruling on the **B3 pattern** generally: the specification assumes several writes the executing
   identity cannot make, and it would be cheaper to state the rule once than to rediscover it each
   session.
4. Whether the project moves off trial before Session 6.

Everything else continues. Sessions 1–5 are on `development` and `stage` at `d8da86b`, 224 tests
green, and the architecture is untouched pending your answer.
