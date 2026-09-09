"""Sending the agent a picture, and everything that must not happen when you do.

An image is the first thing this product carries out of Odoo that a user
supplied as raw bytes, so most of this file is about refusing them: bytes that
are not an image, bytes that are too many, bytes belonging to somebody else, and
bytes reaching the vendor by a route nobody audited.

The last of those was already happening before any of this was built. Pasting an
image into Discuss produced a ``data:`` URI which ``html2plaintext`` appended to
the message text verbatim, so the whole base64 blob travelled to the model AS
TEXT -- unvalidated, unbounded, uncounted and replayed on every later turn.
``test_a_pasted_data_uri_never_reaches_the_prompt`` is the regression for it.
"""

import base64
import io

from odoo import Command
from odoo.tests import tagged

from ..services import images as images_service
from .common import AIOperationsCommon


def _png(width=40, height=40):
    """A real PNG, because a signature check is not a decode check."""
    from PIL import Image
    buffer = io.BytesIO()
    Image.new('RGB', (width, height), (200, 30, 30)).save(buffer, format='PNG')
    return buffer.getvalue()


@tagged('post_install', '-at_install', 'ai_security')
class TestImageIntake(AIOperationsCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.employee = cls._make_user('ai.test.img', 'Image Employee')
        cls.employee.write({'group_ids': [Command.link(
            cls.env.ref('ai_operations.group_ai_user').id)]})
        cls.other = cls._make_user('ai.test.img.other', 'Someone Else')

    def _attachment(self, raw, name='shot.png', mimetype='image/png',
                    user=None):
        return self.env['ir.attachment'].with_user(user or self.employee).create({
            'name': name,
            'mimetype': mimetype,
            'datas': base64.b64encode(raw),
        })

    # -- the happy path ----------------------------------------------------

    def test_a_png_is_accepted(self):
        blocks, rejected = images_service.collect(
            self._attachment(_png()), self.employee)
        self.assertEqual(rejected, [])
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0]['media_type'], 'image/png')
        self.assertTrue(blocks[0]['data'])

    def test_a_large_image_is_downscaled(self):
        """Cost control, not cosmetics.

        Visual tokens are ceil(w/28) * ceil(h/28), so an unbounded image is an
        unbounded bill -- and neither history cap can see it, because both count
        characters or turns and an image has neither.
        """
        blocks, _rejected = images_service.collect(
            self._attachment(_png(3000, 3000)), self.employee)
        from PIL import Image
        decoded = Image.open(io.BytesIO(base64.b64decode(blocks[0]['data'])))
        self.assertLessEqual(max(decoded.size), images_service.MAX_LONG_EDGE)

    # -- refusals ----------------------------------------------------------

    def test_a_file_that_is_not_an_image_is_refused(self):
        """The declared mimetype is user input; the bytes are not."""
        blocks, rejected = images_service.collect(
            self._attachment(b'MZ\x90\x00 this is an executable',
                             name='invoice.png'), self.employee)
        self.assertEqual(blocks, [])
        self.assertTrue(rejected)

    def test_an_oversized_file_is_refused(self):
        oversized = b'\x89PNG\r\n\x1a\n' + b'0' * images_service.MAX_IMAGE_BYTES
        blocks, rejected = images_service.collect(
            self._attachment(oversized), self.employee)
        self.assertEqual(blocks, [])
        self.assertIn('larger than', rejected[0])

    def test_an_attachment_the_user_may_not_read_is_refused(self):
        """Odoo does not check this for us.

        mail.thread._process_attachments_for_post links attachment ids in sudo
        and performs no ownership check at all for an internal user -- its own
        docstring says the caller must. So a user can post somebody else's
        attachment id, and this is where that stops being interesting.
        """
        theirs = self._attachment(_png(), user=self.other)
        blocks, rejected = images_service.collect(theirs, self.employee)
        self.assertEqual(blocks, [])
        self.assertTrue(rejected)

    def test_the_refusal_does_not_say_whether_the_file_exists(self):
        """A different message for "not yours" than for "no such file" is an
        enumeration oracle. Both say the same thing."""
        theirs = self._attachment(_png(), user=self.other)
        _blocks, rejected = images_service.collect(theirs, self.employee)
        self.assertEqual(rejected, ["An attached file could not be read."])

    def test_only_a_few_images_travel_per_turn(self):
        attachments = self.env['ir.attachment']
        for index in range(images_service.MAX_IMAGES_PER_TURN + 2):
            attachments |= self._attachment(_png(), name='shot%d.png' % index)
        blocks, rejected = images_service.collect(attachments, self.employee)
        self.assertEqual(len(blocks), images_service.MAX_IMAGES_PER_TURN)
        self.assertTrue(rejected)

    def test_one_bad_file_does_not_lose_the_others(self):
        good = self._attachment(_png())
        bad = self._attachment(b'not an image at all', name='x.png')
        blocks, rejected = images_service.collect(good | bad, self.employee)
        self.assertEqual(len(blocks), 1)
        self.assertEqual(len(rejected), 1)

    # -- a provider that cannot see ----------------------------------------

    def test_a_provider_without_vision_is_told_nothing(self):
        class Blind:
            def supports_images(self, model=None):
                return False

        blocks, rejected = images_service.collect(
            self._attachment(_png()), self.employee, provider=Blind())
        self.assertEqual(blocks, [])
        self.assertIn('cannot read images', rejected[0])

    # -- what may be written down ------------------------------------------

    def test_the_audit_summary_never_carries_the_image(self):
        blocks, _rejected = images_service.collect(
            self._attachment(_png()), self.employee)
        summary = images_service.audit_summary(blocks)
        self.assertEqual(
            set(summary[0]), {'name', 'media_type', 'bytes'},
            "the audit summary grew a field that could hold image data")
        self.assertNotIn('data', str(summary))

    def test_the_provider_blocks_carry_only_what_the_vendor_needs(self):
        blocks, _rejected = images_service.collect(
            self._attachment(_png()), self.employee)
        sent = images_service.to_provider_blocks(blocks)
        self.assertEqual(set(sent[0]), {'type', 'media_type', 'data'})


@tagged('post_install', '-at_install', 'ai_security')
class TestImagesInTheConversation(AIOperationsCommon):
    """The runtime half: where an image sits, and where it must never sit."""

    def test_an_image_turn_is_blocks_and_a_text_turn_is_a_string(self):
        runtime = self.env['ai.operations.execution']
        self.assertEqual(runtime._entry_content('hello', None), 'hello')

        content = runtime._entry_content('what is this?', [
            {'type': 'image', 'media_type': 'image/png', 'data': 'AAA',
             'name': 'x.png', 'bytes': 3}])
        self.assertEqual(content[0]['type'], 'image',
                         "the image must precede the text")
        self.assertEqual(content[-1], {'type': 'text', 'text': 'what is this?'})

    def test_history_never_replays_an_image(self):
        """The cost ceiling, asserted rather than trusted.

        _sanitise_history drops any content that is not a string, which is what
        keeps an image on the turn it arrived with. If that guard is ever
        relaxed, every later question in the conversation starts re-uploading
        every earlier photograph.
        """
        runtime = self.env['ai.operations.execution']
        history = [
            {'role': 'user', 'content': [
                {'type': 'image', 'media_type': 'image/png', 'data': 'AAA'},
                {'type': 'text', 'text': 'look'}]},
            {'role': 'user', 'content': 'a plain question'},
        ]
        self.assertEqual(
            runtime._sanitise_history(history),
            [{'role': 'user', 'content': 'a plain question'}])
