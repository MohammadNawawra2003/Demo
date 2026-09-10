"""George's path over HTTP: a normal eligible user attaches an image in the widget.

He saw "That image could not be attached." The widget's half of that -- the
CSRF token and the reply shape -- is asserted in static/tests/chat_widget.test.js.
This file holds the server half of the same contract: the route the widget posts
to, the shape it answers with, and one full image turn, driven through the real
HTTP stack as the user -- never as an admin, never through sudo.
"""

import base64
import io

from odoo import Command, http
from odoo.tests import HttpCase, tagged
from odoo.tests.common import JsonRpcException
from odoo.tools import mute_logger

from odoo.addons.ai_operations.services import provider as provider_module
from odoo.addons.ai_operations.services.provider import ai_provider


def _png(width, height):
    from PIL import Image
    buffer = io.BytesIO()
    Image.new('RGB', (width, height), (200, 30, 30)).save(buffer, format='PNG')
    return buffer.getvalue()


class _SeeingVendor:
    """A scripted vendor that can see, and keeps every message list it is handed."""

    def __init__(self):
        self.seen = []

    def supports_images(self, model=None):
        return True

    def complete(self, messages, system=None, tools=None, model=None,
                 max_tokens=4096, timeout=120):
        self.seen.append([dict(m) for m in messages])
        return {'content': 'I can see a red rectangle.', 'tool_calls': [],
                'stop_reason': 'end_turn',
                'usage': {'input_tokens': 1, 'output_tokens': 1}}


def _image_blocks(messages):
    return [block for message in messages
            if isinstance(message.get('content'), list)
            for block in message['content'] if block.get('type') == 'image']


@tagged('post_install', '-at_install', 'ai_security')
class TestWidgetImageUpload(HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        company = cls.env['res.company'].create({'name': 'Upload Co'})
        ai_user = cls.env.ref('ai_operations.group_ai_user')

        def user(login, *groups):
            return cls.env['res.users'].create({
                'name': login, 'login': login, 'password': login,
                'company_id': company.id, 'company_ids': [Command.set([company.id])],
                'group_ids': [Command.link(group.id) for group in groups]})

        cls.employee = user('widget.upload', ai_user)
        cls.colleague = user('widget.upload.colleague', ai_user)
        reviewer = user('widget.upload.reviewer', cls.env.ref('base.group_user'))

        # Registration is module-level; a second run in the same process reuses it.
        if not provider_module.has_provider('kt_widget'):
            provider_module.allow_provider_registration_for_tests()

            @ai_provider(code='kt_widget', label='Widget', models=(('w-1', 'W One'),))
            class _Registered:
                def complete(self, *args, **kwargs):
                    raise AssertionError('the test vendor is injected at _provider_for')

                def get_models(self):
                    return [('w-1', 'W One')]

                def health_check(self):
                    return True, 'ok'

        cls.profile = cls.env['ai.operations.agent.profile'].create({
            'name': 'Upload Agent', 'code': 'wg_upload',
            'company_ids': [Command.set([company.id])],
            'partner_id': cls.env['res.partner'].create({'name': 'Upload Agent'}).id,
            'max_autonomy_level': '2',
            'default_review_user_id': reviewer.id,
            'default_escalation_user_id': reviewer.id,
            'provider_code': 'kt_widget', 'model_code': 'w-1',
            # The colleague is an AI user in the same company, never assigned.
            'user_ids': [Command.set([cls.employee.id])],
        })

    def setUp(self):
        super().setUp()
        self.vendor = _SeeingVendor()
        vendor = self.vendor
        self.patch(type(self.env['ai.operations.execution']), '_provider_for',
                   lambda self, profile: vendor)
        self.authenticate('widget.upload', 'widget.upload')

    def _call(self, method, *args):
        return self.make_jsonrpc_request(
            '/web/dataset/call_kw/ai.operations.agent.profile/%s' % method,
            {'model': 'ai.operations.agent.profile', 'method': method,
             'args': [[self.profile.id], *args], 'kwargs': {}})

    def _upload(self, channel_id, raw, csrf=True):
        """The request chat_widget.js makes, field for field."""
        data = {'thread_id': channel_id, 'thread_model': 'discuss.channel'}
        if csrf:
            data['csrf_token'] = http.Request.csrf_token(self)
        with mute_logger('odoo.http'):
            return self.url_open('/mail/attachment/upload', data=data,
                                 files={'ufile': ('shapes.png', raw, 'image/png')})

    def test_the_route_refuses_an_upload_without_the_csrf_token(self):
        """What George hit, for every user and every agent: Odoo 19's http.post
        stopped adding the token, and the widget did not add its own."""
        channel_id = self._call('ai_widget_open')['channel_id']
        response = self._upload(channel_id, _png(40, 40), csrf=False)
        self.assertEqual(response.status_code, 400)

    def test_a_normal_user_attaches_and_sends_an_image(self):
        channel_id = self._call('ai_widget_open')['channel_id']
        response = self._upload(channel_id, _png(2400, 1200))
        self.assertEqual(response.status_code, 200)
        # The key the widget reads. data["ir.attachment"] -- the old parse --
        # is not in this reply at all.
        attachment_id = response.json()['data']['attachment_id']
        attachment = self.env['ir.attachment'].browse(attachment_id)
        self.assertEqual(
            (attachment.res_model, attachment.res_id, attachment.create_uid),
            ('discuss.channel', channel_id, self.employee),
            "the upload is not the user's own file on their own conversation")

        Log = self.env['ai.operations.audit.log']
        before = Log.search([]).ids
        result = self._call('ai_widget_send', 'ماذا ترى في هذه الصورة؟', [attachment_id])
        self.assertEqual(result['reply'], 'I can see a red rectangle.')

        images = _image_blocks(self.vendor.seen[0])
        self.assertEqual(len(images), 1, "the provider did not receive the image")
        self.assertEqual(set(images[0]), {'type', 'media_type', 'data'})
        self.assertEqual(images[0]['media_type'], 'image/png')
        from PIL import Image
        size = Image.open(io.BytesIO(base64.b64decode(images[0]['data']))).size
        self.assertEqual(max(size), 1568, "a 2400 px image was not downscaled")

        fragment = images[0]['data'][:64]
        for row in Log.search([('id', 'not in', before)]):
            self.assertNotIn(fragment, str(row.read()[0]),
                             "image bytes reached the audit log")

        # The next turn is text, and the photograph does not travel again.
        self._call('ai_widget_send', 'and the colour?', [])
        self.assertEqual(_image_blocks(self.vendor.seen[-1]), [],
                         "an earlier image was replayed as history")

    def test_somebody_elses_attachment_id_is_not_sent(self):
        """The id is whatever the caller passes, so it is checked as the user.

        Odoo 19 does it first: ``mail.message.create`` checks ``read`` on every
        attachment that sits on another record, so the post itself is refused
        and no turn runs. The dispatcher's own check (test_images) is the
        second line, for attachments already on the channel.
        """
        self._call('ai_widget_open')
        theirs = self.env['ir.attachment'].with_user(self.colleague).create({
            'name': 'theirs.png', 'datas': base64.b64encode(_png(40, 40))})
        with self.assertRaises(JsonRpcException), mute_logger('odoo.http'):
            self._call('ai_widget_send', 'what is this?', [theirs.id])
        self.assertEqual(self.vendor.seen, [], "the turn reached the provider")

    def test_nobody_else_can_upload_into_the_conversation(self):
        channel_id = self._call('ai_widget_open')['channel_id']
        self.authenticate('widget.upload.colleague', 'widget.upload.colleague')
        response = self._upload(channel_id, _png(40, 40))
        self.assertEqual(response.status_code, 404)
        self.assertFalse(self.env['ir.attachment'].search(
            [('res_model', '=', 'discuss.channel'), ('res_id', '=', channel_id)]))
