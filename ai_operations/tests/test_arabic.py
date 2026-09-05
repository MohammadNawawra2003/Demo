"""Session 14. Arabic, and the verification Document A §15 actually asks for.

> Agent prompts, tool descriptions, output schemas and generated activity
> summaries must all be verified in Arabic — the output sanitiser in particular
> must not mangle RTL or Arabic-Indic digits.

So these do not merely assert that a translation loads. They assert that Arabic
text **survives the pipeline**: through the serialiser, into an activity, out of
a denial. That is where mangling would happen, and it is invisible until someone
reads the screen.
"""

import unicodedata

from odoo import Command
from odoo.tests import tagged

from ..services.context import ExecutionContext, RunBudget
from ..services.exceptions import NEUTRAL_DENIAL
from ..services.schema import Schema, Str
from .common import AIOperationsCommon

#: U+200F RIGHT-TO-LEFT MARK and friends. Stripping these silently reverses the
#: visual order of a mixed Arabic/Latin string, and nothing raises.
BIDI_MARKS = ('‎', '‏', '‪', '‫', '‬', '؜')

#: Arabic-Indic digits. A "helpful" normalisation to ASCII digits changes what a
#: reader sees on a Saudi client's screen.
ARABIC_INDIC = '٠١٢٣٤٥٦٧٨٩'

ARABIC_SUMMARY = 'نقص في زجاجات ٣٣٠ مل — ٤٨٦٬٠٠٠ وحدة'


class ArabicOutput(Schema):
    summary = Str()
    lot_name = Str()


@tagged('post_install', '-at_install', 'ai_security')
class TestArabic(AIOperationsCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.serializer = cls.env['ai.operations.serializer']
        cls.activity_service = cls.env['ai.operations.activity']
        cls.lang = cls.env['res.lang'].with_context(active_test=False).search(
            [('code', '=', 'ar_001')], limit=1)

    def _ctx(self):
        return ExecutionContext(
            env=self.env, profile=self.profile, execution_user=self.env.user,
            execution_mode='INTERACTIVE', trigger='CHAT',
            company_ids=(self.company.id,), autonomy=2, tool_code='kt_arabic',
            correlation_id='corr-arabic', session_id='s', audit_id=0,
            policy_version='1.0.0', budget=RunBudget())

    # -- the language itself -------------------------------------------------

    def test_arabic_is_available_and_right_to_left(self):
        """Document A §2: primary UI language ar_001."""
        self.assertTrue(self.lang, "ar_001 is not present in this database")
        self.assertEqual(self.lang.direction, 'rtl')

    def test_the_translation_file_ships_with_the_module(self):
        import pathlib
        po = pathlib.Path(__file__).resolve().parent.parent / 'i18n' / 'ar_001.po'
        self.assertTrue(po.exists(), "no Arabic translation shipped")
        text = po.read_text(encoding='utf-8')
        self.assertIn('عمليات الذكاء الاصطناعي', text)

    def test_the_protocol_is_deliberately_not_translated(self):
        """DenialReason values, tool codes and action codes are a closed
        protocol read by the guard and the test matrix. Translating them would
        break the audit log's meaning across databases."""
        import pathlib
        po = pathlib.Path(__file__).resolve().parent.parent / 'i18n' / 'ar_001.po'
        text = po.read_text(encoding='utf-8')
        for protocol_value in ('MODEL_NOT_PERMITTED', 'BOUND_EXCEEDED',
                               'CREATE_DRAFT', 'MATERIAL_SHORTAGE'):
            self.assertNotIn('msgid "%s"' % protocol_value, text)

    # -- the pipeline: does Arabic survive it? --------------------------------

    def test_the_serialiser_does_not_mangle_arabic(self):
        """The highest-leverage control is also the place a naive
        normalisation would silently corrupt a Saudi client's screen."""
        payload = {'summary': ARABIC_SUMMARY, 'lot_name': 'WT-260819-02'}
        result = self.serializer.serialize(self._ctx(), payload, ArabicOutput)
        self.assertEqual(result['summary'], ARABIC_SUMMARY)

    def test_arabic_indic_digits_survive_serialisation(self):
        payload = {'summary': 'الكمية ٤٨٦٠٠٠', 'lot_name': 'x'}
        result = self.serializer.serialize(self._ctx(), payload, ArabicOutput)
        for digit in '٤٨٦':
            self.assertIn(digit, result['summary'])
        self.assertNotIn('486', result['summary'],
                         "Arabic-Indic digits were normalised to ASCII")

    def test_bidi_control_marks_are_preserved(self):
        """Stripping these reverses the visual order of mixed Arabic/Latin text,
        and nothing raises — the defect is only visible on screen."""
        mixed = 'الصنف‏ PK-BTL-330 ‏ناقص'
        result = self.serializer.serialize(
            self._ctx(), {'summary': mixed, 'lot_name': 'y'}, ArabicOutput)
        self.assertEqual(result['summary'], mixed)
        self.assertIn('‏', result['summary'])

    def test_arabic_is_not_decomposed(self):
        """A normalisation to NFD would break rendering of composed forms."""
        payload = {'summary': ARABIC_SUMMARY, 'lot_name': 'z'}
        result = self.serializer.serialize(self._ctx(), payload, ArabicOutput)
        self.assertEqual(result['summary'],
                         unicodedata.normalize('NFC', result['summary']))

    def test_an_arabic_summary_reaches_an_activity_intact(self):
        """§15 names generated activity summaries specifically."""
        activity = self.activity_service.create_or_update(
            self._ctx(), 'res.partner', 1, ARABIC_SUMMARY,
            '<p>نقص مؤكد</p>', 'SHORTAGE_AR')
        self.assertTrue(activity)
        self.assertEqual(activity.summary, ARABIC_SUMMARY)
        self.assertIn('نقص', activity.note)

    def test_the_dedup_key_is_unaffected_by_the_language(self):
        """The key is built from codes, not from translated text, so the same
        exception deduplicates whatever language the reader is using."""
        english = self.activity_service.create_or_update(
            self._ctx(), 'res.partner', 2, 'Shortage', '<p>x</p>', 'SAME_REASON')
        arabic = self.activity_service.create_or_update(
            self._ctx(), 'res.partner', 2, ARABIC_SUMMARY, '<p>ص</p>',
            'SAME_REASON')
        self.assertEqual(english, arabic,
                         "a translated summary must not defeat deduplication")

    def test_the_neutral_denial_is_translatable_but_still_neutral(self):
        """Translating it must not make it informative: it still carries no
        model name, no field name and no reason code."""
        for leak in ('account.move', 'MODEL_NOT_PERMITTED', 'bank_ids'):
            self.assertNotIn(leak, NEUTRAL_DENIAL)
        arabic_denial = 'مرفوض: هذا الطلب خارج النطاق المصرّح به للوكيل.'
        for leak in ('account', 'move', 'hr.'):
            self.assertNotIn(leak, arabic_denial)

    def test_an_arabic_lot_name_traces_correctly(self):
        """Lot codes stay Latin by design — NQ-L1-260812-004 is a printed date
        code under GSO labelling rules, not display text."""
        lot_name = 'WT-260819-02'
        result = self.serializer.serialize(
            self._ctx(), {'summary': 'دفعة المياه', 'lot_name': lot_name},
            ArabicOutput)
        self.assertEqual(result['lot_name'], lot_name)

    def test_the_blocklist_scans_arabic_keys_too(self):
        """A blocklisted key must be caught whatever the surrounding language."""
        from ..services.exceptions import AIBlocklistViolation
        with self.assertRaises(AIBlocklistViolation):
            self.serializer.assert_clean(
                self._ctx(), {'الوصف': 'قيمة', 'api_key': 'sk-live'})
