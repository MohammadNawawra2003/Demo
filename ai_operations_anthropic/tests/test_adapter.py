"""Offline adapter tests. These make no network call and cost nothing."""

from unittest.mock import patch

from odoo.tests import TransactionCase, tagged

from odoo.addons.ai_operations.services import provider as provider_module
from odoo.addons.ai_operations.services.exceptions import AIProviderError

from ..models import anthropic_provider as adapter


@tagged('post_install', '-at_install', 'ai_security')
class TestAnthropicAdapter(TransactionCase):

    def setUp(self):
        super().setUp()
        self.provider = self.env['ai.operations.provider.anthropic']

    # -- registration ------------------------------------------------------

    def test_the_adapter_is_registered(self):
        self.assertTrue(provider_module.has_provider('anthropic'))
        spec = provider_module.get_provider('anthropic')
        self.assertEqual(spec.label, 'Anthropic')

    def test_declared_models_are_a_constant(self):
        """T-74a: configuration must not depend on the vendor being reachable,
        and a config screen must not make an unauthenticated network call."""
        with patch('urllib.request.urlopen',
                   side_effect=AssertionError('get_models made a network call')):
            self.assertEqual(self.provider.get_models(), list(adapter.MODELS))

    def test_the_profile_can_select_this_adapter(self):
        self.assertIn(('anthropic', 'Anthropic'), provider_module.provider_selection())
        self.assertIn(('claude-opus-5', 'Claude Opus 5'),
                      provider_module.model_selection('anthropic'))

    # -- the credential ----------------------------------------------------

    def test_the_credential_never_touches_the_orm(self):
        """C §5.10: ir.config_parameter carries one group_system ACL row and
        get_param() calls check_access, so a DB-stored key would force the first
        sudo() into the codebase."""
        import re
        source = (adapter.__file__ or '').replace('.pyc', '.py')
        with open(source) as handle:
            text = handle.read()
        # Match USAGE, not the word. The adapter's docstring names
        # ir.config_parameter to explain why it is not used, and a check that
        # fails on its own rationale is the defect this project keeps finding
        # in the frozen CI greps (checks 1, 11 and 16).
        self.assertIsNone(
            re.search(r"env\[['\"]ir\.config_parameter|\.get_param\(", text),
            "the credential must never be read through the ORM")
        self.assertIsNone(re.search(r"\.sudo\(", text))
        self.assertIn('os.environ.get', text)

    def test_no_module_in_the_repository_reads_a_credential_from_the_orm(self):
        """Decision D1, applied to the whole repository rather than to this one
        file. CI check 11 states the rule and nothing executed it, so the next
        adapter could have reintroduced exactly what §5.10 forbids and every
        suite would still have been green.

        Usage, not the word: the rule is explained in prose in several places,
        and a check that fails on its own rationale is the defect this project
        already found in frozen checks 1, 11 and 16.
        """
        import pathlib
        import re
        root = pathlib.Path(__file__).resolve().parents[2]
        offenders = []
        for path in sorted(root.glob('ai_operations*/**/*.py')):
            if '/tests/' in str(path):
                continue
            text = path.read_text()
            if re.search(r"env\[['\"]ir\.config_parameter|\.get_param\(", text):
                offenders.append(str(path.relative_to(root)))
        self.assertEqual(
            offenders, [],
            "a credential read through the ORM would need sudo() and would "
            "enter every database dump")

    def _without_credential(self):
        return patch.object(type(self.provider), '_credential', return_value=None)

    def test_health_check_without_a_credential_is_unusable_and_neutral(self):
        with self._without_credential():
            usable, reason = self.provider.health_check()
        self.assertFalse(usable)
        self.assertNotIn('sk-', reason)
        self.assertNotIn('key=', reason.lower())

    def test_complete_without_a_credential_raises_a_provider_error(self):
        with self._without_credential():
            with self.assertRaises(AIProviderError) as caught:
                self.provider.complete([{'role': 'user', 'content': 'hi'}])
        self.assertNotIn('sk-', str(caught.exception))

    def test_health_check_never_renders_the_credential(self):
        with patch.object(type(self.provider), '_credential',
                          return_value='sk-ant-secret-value'):
            usable, reason = self.provider.health_check()
        self.assertTrue(usable)
        self.assertNotIn('sk-ant-secret-value', reason)

    # -- normalisation -----------------------------------------------------

    def test_content_blocks_are_parsed_by_type_not_position(self):
        raw = {
            'content': [
                {'type': 'tool_use', 'id': 'tu_1', 'name': 'core.describe_scope',
                 'input': {'a': 1}},
                {'type': 'text', 'text': 'thinking out loud'},
            ],
            'stop_reason': 'tool_use',
            'usage': {'input_tokens': 11, 'output_tokens': 3},
        }
        result = self.provider._normalise(raw)
        self.assertEqual(result['content'], 'thinking out loud')
        self.assertEqual(result['tool_calls'][0]['name'], 'core.describe_scope')
        self.assertEqual(result['usage'], {'input_tokens': 11, 'output_tokens': 3})

    def test_a_response_with_no_tool_calls_normalises_cleanly(self):
        result = self.provider._normalise(
            {'content': [{'type': 'text', 'text': 'done'}], 'usage': {}})
        self.assertEqual(result['tool_calls'], [])
        self.assertEqual(result['usage'],
                         {'input_tokens': 0, 'output_tokens': 0})

    def test_tool_results_are_sent_back_in_vendor_shape(self):
        vendor = self.provider._to_vendor_messages([
            {'role': 'user', 'content': 'go'},
            {'role': 'tool', 'tool_use_id': 'tu_1', 'content': {'ok': True}},
        ])
        self.assertEqual(vendor[1]['role'], 'user')
        self.assertEqual(vendor[1]['content'][0]['type'], 'tool_result')
        self.assertEqual(vendor[1]['content'][0]['tool_use_id'], 'tu_1')

    # -- failure never leaks -----------------------------------------------

    def test_a_vendor_http_error_becomes_a_neutral_provider_error(self):
        import urllib.error
        error = urllib.error.HTTPError(
            adapter.ENDPOINT, 400, 'Bad Request', {}, None)
        with patch.object(type(self.provider), '_credential', return_value='k'), \
             patch('urllib.request.urlopen', side_effect=error):
            with self.assertRaises(AIProviderError) as caught:
                self.provider.complete([{'role': 'user', 'content': 'hi'}])
        self.assertIn('400', str(caught.exception))
        self.assertNotIn('k', str(caught.exception).replace('could not', ''))

    def test_a_scripted_response_flows_through_complete(self):
        """The whole path, with the vendor replaced by a fixture."""
        import io
        import json
        body = json.dumps({
            'content': [{'type': 'text', 'text': 'ok'}],
            'stop_reason': 'end_turn',
            'usage': {'input_tokens': 5, 'output_tokens': 1},
        }).encode()

        class _Response(io.BytesIO):
            def __enter__(self): return self
            def __exit__(self, *a): return False

        with patch.object(type(self.provider), '_credential', return_value='k'), \
             patch('urllib.request.urlopen', return_value=_Response(body)):
            result = self.provider.complete([{'role': 'user', 'content': 'hi'}])
        self.assertEqual(result['content'], 'ok')
        self.assertEqual(result['usage']['input_tokens'], 5)

    # -- vendor tool-name rules (regression: manual Test 1, HTTP 400) --------

    def _captured_payload(self, **kwargs):
        """Run complete() with the transport replaced, and return what we sent."""
        sent = {}

        def fake_post(self, payload, key, timeout):
            sent.update(payload)
            return {'content': [{'type': 'text', 'text': 'ok'}],
                    'stop_reason': 'end_turn',
                    'usage': {'input_tokens': 1, 'output_tokens': 1}}

        with patch.object(type(self.provider), '_credential', return_value='k'), \
             patch.object(type(self.provider), '_post', fake_post):
            self.provider.complete([{'role': 'user', 'content': 'hi'}], **kwargs)
        return sent

    def test_tool_names_sent_to_the_vendor_match_the_vendor_pattern(self):
        """Anthropic rejects the whole request when a tool name is not
        ``^[a-zA-Z0-9_-]{1,128}$``. Our tool codes are dot-namespaced, so sending
        ``spec.code`` verbatim returned:

            tools.0.custom.name: String should match pattern '^[a-zA-Z0-9_-]{1,128}$'

        which is HTTP 400 before a single token is billed and before any tool
        runs -- exactly what manual Test 1 hit on staging.
        """
        import re
        payload = self._captured_payload(tools=[
            {'name': 'procurement.get_open_pos', 'description': 'd',
             'input_schema': {'type': 'object', 'properties': {}}},
            {'name': 'core.describe_scope', 'description': 'd',
             'input_schema': {'type': 'object', 'properties': {}}},
        ])
        pattern = re.compile(r'^[a-zA-Z0-9_-]{1,128}$')
        for tool in payload['tools']:
            self.assertRegex(tool['name'], pattern,
                             "%r would be rejected by the vendor" % tool['name'])

    def test_a_tool_call_is_returned_under_our_own_tool_code(self):
        """The runtime looks the tool up by ``call['name']``, so whatever
        renaming the adapter does for the vendor must be undone on the way
        back -- otherwise every call would miss the registry."""
        import io
        import json
        body = json.dumps({
            'content': [{'type': 'tool_use', 'id': 'tu_1',
                         'name': 'procurement_get_open_pos', 'input': {}}],
            'stop_reason': 'tool_use',
            'usage': {'input_tokens': 1, 'output_tokens': 1},
        }).encode()

        class _Response(io.BytesIO):
            def __enter__(self): return self
            def __exit__(self, *a): return False

        with patch.object(type(self.provider), '_credential', return_value='k'), \
             patch('urllib.request.urlopen', return_value=_Response(body)):
            result = self.provider.complete(
                [{'role': 'user', 'content': 'hi'}],
                tools=[{'name': 'procurement.get_open_pos', 'description': 'd',
                        'input_schema': {'type': 'object', 'properties': {}}}])

        self.assertEqual(result['tool_calls'][0]['name'],
                         'procurement.get_open_pos')

    def test_an_unknown_tool_name_is_passed_through_untouched(self):
        """A name we never sent must reach the guard and be denied there, not
        be silently dropped or mangled into something that resolves."""
        result = self.provider._normalise(
            {'content': [{'type': 'tool_use', 'id': 't', 'name': 'made_up',
                          'input': {}}]},
            {'procurement_get_open_pos': 'procurement.get_open_pos'})
        self.assertEqual(result['tool_calls'][0]['name'], 'made_up')

    def test_an_assistant_turn_becomes_tool_use_blocks_with_vendor_names(self):
        """The second request must replay the request the results answer, and
        it must name the tool the way the vendor named it."""
        vendor = self.provider._to_vendor_messages(
            [{'role': 'user', 'content': 'go'},
             {'role': 'assistant', 'content': '',
              'tool_calls': [{'id': 'tu_1', 'name': 'procurement.get_open_pos',
                              'input': {}}]},
             {'role': 'tool', 'tool_use_id': 'tu_1', 'content': {'orders': []}}],
            {'procurement.get_open_pos': 'procurement_get_open_pos'})

        self.assertEqual([m['role'] for m in vendor], ['user', 'assistant', 'user'])
        block = vendor[1]['content'][0]
        self.assertEqual(block['type'], 'tool_use')
        self.assertEqual(block['id'], 'tu_1')
        self.assertEqual(block['name'], 'procurement_get_open_pos')
        self.assertEqual(vendor[2]['content'][0]['tool_use_id'], 'tu_1')

    def test_results_for_one_assistant_turn_are_grouped_into_one_message(self):
        """Two results as two user messages would leave the second one with a
        user message before it, and no matching tool_use in it."""
        vendor = self.provider._to_vendor_messages([
            {'role': 'user', 'content': 'go'},
            {'role': 'assistant', 'content': '', 'tool_calls': [
                {'id': 'a', 'name': 'x.one', 'input': {}},
                {'id': 'b', 'name': 'x.two', 'input': {}}]},
            {'role': 'tool', 'tool_use_id': 'a', 'content': {'n': 1}},
            {'role': 'tool', 'tool_use_id': 'b', 'content': {'n': 2}},
        ])
        self.assertEqual([m['role'] for m in vendor], ['user', 'assistant', 'user'])
        self.assertEqual([b['tool_use_id'] for b in vendor[2]['content']], ['a', 'b'])
