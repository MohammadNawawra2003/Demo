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
