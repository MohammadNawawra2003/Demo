"""One opt-in live call against the real vendor.

**Excluded from every normal run.** The tag is ``-standard``, so this never
executes as part of the suite, on Odoo.sh, or in CI. Run it deliberately::

    odoo-bin -d <db> --test-enable --test-tags=ai_live --stop-after-init

It sends a handful of tokens once, which is the cheapest thing that proves the
credential, the endpoint, the request shape and the response parsing all work
together. Everything else about this adapter is covered offline in
``test_adapter.py``, which makes no network call at all.
"""

from odoo.tests import TransactionCase, tagged

MAX_TOKENS = 16


@tagged('-standard', 'ai_live')
class TestAnthropicLive(TransactionCase):

    def test_one_minimal_live_completion(self):
        provider = self.env['ai.operations.provider.anthropic']
        usable, reason = provider.health_check()
        if not usable:
            self.skipTest(reason)

        result = provider.complete(
            [{'role': 'user', 'content': 'Reply with the single word: ok'}],
            max_tokens=MAX_TOKENS, timeout=60)

        self.assertIn('ok', (result['content'] or '').lower())
        self.assertGreater(result['usage']['input_tokens'], 0)
        self.assertGreater(result['usage']['output_tokens'], 0)
        self.assertEqual(result['tool_calls'], [])

    def test_live_tool_definition_round_trip(self):
        """The vendor accepts our generated tool schema and asks to use it.

        This is the one thing a scripted double cannot prove: that
        ``input_schema.to_json_schema()`` produces something the vendor will
        actually accept.
        """
        provider = self.env['ai.operations.provider.anthropic']
        usable, reason = provider.health_check()
        if not usable:
            self.skipTest(reason)

        from odoo.addons.ai_operations.services.registry import get_tool
        spec = get_tool('core.describe_scope')
        result = provider.complete(
            [{'role': 'user', 'content': 'What scope am I running under? Use the tool.'}],
            tools=[{'name': spec.code, 'description': spec.description,
                    'input_schema': spec.input_schema.to_json_schema()}],
            max_tokens=MAX_TOKENS * 4, timeout=60)

        self.assertTrue(
            result['tool_calls'] or result['content'],
            "the vendor returned neither text nor a tool call")
        if result['tool_calls']:
            self.assertEqual(result['tool_calls'][0]['name'], 'core.describe_scope')
