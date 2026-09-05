"""The Phase 1 provider adapter. Document D 12.

The kernel names no vendor, no endpoint and no credential variable -- CI check
16 enforces that on ``ai_operations/``. All three live here, in a module whose
installation is a deployment act, because installing an adapter adds an egress
destination for the fully assembled agent context.
"""

import json
import logging
import os
import time
import urllib.error
import urllib.request

from odoo import api, models
from odoo.tools import config

from odoo.addons.ai_operations.services.exceptions import AIProviderError
from odoo.addons.ai_operations.services.provider import ai_provider

_logger = logging.getLogger(__name__)

ENDPOINT = 'https://api.anthropic.com/v1/messages'
API_VERSION = '2023-06-01'

#: The adapter owns its credential's name. The kernel never learns it.
ENV_VAR = 'ODOO_AI_ANTHROPIC_TOKEN'
CONF_KEY = 'ai_anthropic_token'

#: DECLARED, never fetched. Configuration must not depend on the vendor being
#: reachable, and a config screen must not make an unauthenticated network call.
MODELS = (
    ('claude-opus-5', 'Claude Opus 5'),
    ('claude-sonnet-5', 'Claude Sonnet 5'),
)


@ai_provider(code='anthropic', label='Anthropic', models=MODELS)
class AnthropicProvider(models.AbstractModel):
    _name = 'ai.operations.provider.anthropic'
    _inherit = 'ai.operations.provider'
    _description = 'Anthropic Provider Adapter'

    # ------------------------------------------------------------------

    @api.model
    def _credential(self):
        """Environment or ``odoo.conf``, and nowhere else.

        Never ``ir.config_parameter``: it carries a single ``group_system`` ACL
        row and ``get_param()`` calls ``check_access('read')``, so a service user
        reading a DB-stored key would need ``sudo()`` -- which is banned and
        grepped for. Reading the environment needs no privilege, no ORM and no
        exception, and keeps the key out of every database dump.
        """
        return os.environ.get(ENV_VAR) or config.get(CONF_KEY)

    @api.model
    def get_models(self):
        return list(MODELS)

    @api.model
    def health_check(self):
        """(usable, neutral reason). Never returns or logs the credential."""
        if not self._credential():
            return False, "No credential is configured for the Anthropic adapter."
        return True, "Adapter configured."

    @api.model
    def complete(self, messages, system=None, tools=None, model=None,
                 max_tokens=4096, timeout=120):
        key = self._credential()
        if not key:
            raise AIProviderError(
                "The Anthropic adapter has no credential configured.")

        payload = {
            'model': model or MODELS[0][0],
            'max_tokens': max_tokens,
            'messages': self._to_vendor_messages(messages),
        }
        if system:
            # Cache breakpoint at the end of the stable prefix. The saving is
            # WITHIN one run's tool loop, where the same system block and tool
            # list are re-sent on every iteration. It is not a cross-run saving:
            # four agents have four different prompts and the runs are 24 hours
            # apart against a five-minute cache.
            payload['system'] = [{'type': 'text', 'text': system,
                                  'cache_control': {'type': 'ephemeral'}}]
        if tools:
            vendor_tools = [
                {'name': t['name'], 'description': t['description'],
                 'input_schema': t['input_schema']} for t in tools]
            vendor_tools[-1]['cache_control'] = {'type': 'ephemeral'}
            payload['tools'] = vendor_tools

        raw = self._post(payload, key, timeout)
        return self._normalise(raw)

    # ------------------------------------------------------------------

    def _post(self, payload, key, timeout):
        """Two attempts, exponential backoff, on 429 and 5xx only."""
        body = json.dumps(payload).encode()
        headers = {
            'content-type': 'application/json',
            'x-api-key': key,
            'anthropic-version': API_VERSION,
        }
        last = None
        for attempt in range(2):
            request = urllib.request.Request(
                ENDPOINT, data=body, headers=headers, method='POST')
            try:
                with urllib.request.urlopen(request, timeout=timeout) as response:
                    return json.loads(response.read().decode())
            except urllib.error.HTTPError as error:
                last = error
                if error.code == 429 or 500 <= error.code < 600:
                    time.sleep(2 ** attempt)
                    continue
                # Never let a vendor body reach the caller verbatim.
                raise AIProviderError(
                    "Anthropic returned HTTP %s." % error.code) from error
            except Exception as error:      # transport, DNS, timeout
                last = error
                time.sleep(2 ** attempt)
        raise AIProviderError(
            "The Anthropic endpoint could not be reached.") from last

    @staticmethod
    def _to_vendor_messages(messages):
        vendor = []
        for message in messages:
            if message.get('role') == 'tool':
                vendor.append({'role': 'user', 'content': [{
                    'type': 'tool_result',
                    'tool_use_id': message.get('tool_use_id'),
                    'content': json.dumps(message.get('content'), default=str),
                }]})
            else:
                vendor.append({'role': message.get('role', 'user'),
                               'content': message.get('content') or ''})
        return vendor

    @staticmethod
    def _normalise(raw):
        """Parse content blocks **by type, never by position**."""
        content, tool_calls = [], []
        for block in raw.get('content') or []:
            if block.get('type') == 'text':
                content.append(block.get('text', ''))
            elif block.get('type') == 'tool_use':
                tool_calls.append({'id': block.get('id'),
                                   'name': block.get('name'),
                                   'input': block.get('input') or {}})
        usage = raw.get('usage') or {}
        return {
            'content': '\n'.join(content),
            'tool_calls': tool_calls,
            'stop_reason': raw.get('stop_reason'),
            'usage': {'input_tokens': usage.get('input_tokens') or 0,
                      'output_tokens': usage.get('output_tokens') or 0},
        }
