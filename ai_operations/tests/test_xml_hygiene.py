"""A guard against a mistake this codebase has now made three times."""

import pathlib
import re
import xml.etree.ElementTree as ElementTree

from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install', 'ai_security')
class TestXmlHygiene(TransactionCase):
    """Every XML file in every module of this repository must parse.

    A double hyphen inside an XML comment is illegal, and the failure mode is
    unkind: the module simply refuses to install, with a parser error that names
    a line number and not the reason. It has bitten three times here, always
    while writing a comment explaining a security decision.
    """

    def _repository_root(self):
        return pathlib.Path(__file__).resolve().parents[2]

    def _xml_files(self):
        root = self._repository_root()
        return [path for path in root.rglob('*.xml')
                if '/docs/' not in str(path) and '.git' not in str(path)]

    def test_the_audit_list_can_show_who_actually_executed(self):
        """``service_user_id`` must stay reachable in the audit list.

        It is the only column separating "an employee ran this" from "the
        service identity ran this", and ``column_invisible`` put it beyond the
        optional-columns menu as well as off the screen. A list filtered to an
        autonomous run then showed the person who RAISED the work under
        Interactive User, with no way to see who executed it -- an answer to a
        question it was not answering, in a screenshot bound for the guide.
        """
        arch = self.env.ref('ai_operations.view_ai_audit_log_list').arch
        tree = ElementTree.fromstring(arch)
        field = tree.find(".//field[@name='service_user_id']")
        self.assertIsNotNone(field, "the audit list dropped service_user_id")
        self.assertNotIn('column_invisible', field.attrib,
                         "service_user_id is unreachable from the list again")
        self.assertEqual(field.attrib.get('optional'), 'hide')

    def test_every_xml_file_parses(self):
        broken = []
        for path in self._xml_files():
            try:
                ElementTree.parse(path)
            except ElementTree.ParseError as error:
                broken.append('%s: %s' % (path.name, error))
        self.assertFalse(broken, "unparseable XML: %s" % broken)

    def test_no_comment_contains_a_double_hyphen(self):
        offenders = []
        for path in self._xml_files():
            for match in re.finditer(r'<!--(.*?)-->', path.read_text(), re.S):
                if '--' in match.group(1):
                    offenders.append(path.name)
        self.assertFalse(
            offenders,
            "a double hyphen inside an XML comment is illegal: %s" % set(offenders))
