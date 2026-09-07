"""CI checks 7 and 8, as tests rather than as prose. Document D §15.

Both were "a build failure, not a warning" and neither was executable. Check 7
in particular is the one that makes a coverage claim mechanical instead of
rhetorical: without it, "the matrix is covered" is something a person asserts by
reading, and 25 ids had drifted out of the naming convention that lets a machine
check it.
"""

import pathlib
import re

from odoo.tests import TransactionCase, tagged

from ..services.enums import DenialReason

#: Document C §16. Every id the matrix defines.
MATRIX_IDS = [
    't01', 't02', 't03', 't04', 't05', 't06', 't07', 't08', 't09',
    't10', 't11', 't12', 't13', 't14', 't15', 't16', 't17', 't18', 't19',
    't20', 't21', 't22', 't23', 't24', 't25',
    't30', 't31', 't32', 't33', 't34', 't35', 't36', 't37', 't38', 't39',
    't40', 't41', 't42', 't43', 't44', 't45',
    't50', 't51', 't52', 't53', 't54', 't55', 't56', 't57',
    't60', 't61', 't62', 't63', 't64', 't65', 't66', 't67', 't68', 't69',
    't70', 't71', 't72', 't73', 't74a', 't74b', 't74c', 't74d', 't74e',
    't75', 't76', 't77', 't78', 't79',
    't80', 't81', 't82', 't83', 't84', 't85', 't86', 't87',
    't90', 't91', 't92', 't93', 't94', 't95', 't96', 't97', 't98', 't99',
    't100',
]

#: Reasons no denial test can produce, with the reason recorded here rather than
#: silently omitted from the list.
UNASSERTABLE_REASONS = {
    # Raised only when a tool declares a model the ORM cannot resolve; every
    # shipped tool declares real models, and registering a fake one is what
    # T-80's tool double already does under MODEL_NOT_PERMITTED.
}


def _repo_root():
    return pathlib.Path(__file__).resolve().parents[2]


def _all_test_source():
    chunks = []
    for path in _repo_root().glob('*/tests/test_*.py'):
        chunks.append(path.read_text(encoding='utf-8'))
    return '\n'.join(chunks)


@tagged('post_install', '-at_install', 'ai_security')
class TestMatrixCoverage(TransactionCase):

    def test_check7_every_matrix_id_has_a_named_test(self):
        """Document D §2: "Every test method carries its matrix id."

        Not decoration. It is what lets a reviewer answer "is T-40 covered?"
        with a grep instead of an argument.
        """
        source = _all_test_source()
        missing = [
            matrix_id for matrix_id in MATRIX_IDS
            if not re.search(r'def test_%s[_(]' % matrix_id, source)
        ]
        self.assertFalse(
            missing,
            "Document C §16 ids with no test method named for them: %s"
            % ', '.join(missing))

    def test_check8_every_denial_reason_is_asserted_somewhere(self):
        """A reason the guard can raise and no test ever expects is a branch
        nobody has read since it was written."""
        source = _all_test_source()
        unasserted = []
        for reason in DenialReason:
            if reason.value in UNASSERTABLE_REASONS:
                continue
            if re.search(r'DenialReason\.%s\b' % reason.name, source):
                continue
            unasserted.append(reason.value)
        self.assertFalse(
            unasserted,
            "DenialReason members no test asserts: %s" % ', '.join(unasserted))

    def test_the_matrix_list_itself_matches_document_c(self):
        """Guards the guard: if somebody trims MATRIX_IDS to make check 7 pass,
        this notices the list got shorter."""
        self.assertGreaterEqual(len(MATRIX_IDS), 90)
        self.assertIn('t80', MATRIX_IDS, "the go/no-go left the matrix")
        self.assertIn('t99', MATRIX_IDS, "the one-runtime test left the matrix")
