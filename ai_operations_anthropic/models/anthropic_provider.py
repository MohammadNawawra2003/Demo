"""The Phase 1 provider adapter. Document D 12.

The kernel names no vendor, no endpoint and no credential variable -- CI check
16 enforces that on ``ai_operations/``. All three live here, in a module whose
installation is a deployment act, because installing an adapter adds an egress
destination for the fully assembled agent context.
"""

import json
import logging
import os
import re
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

#: The vendor's tool-name rule: ``^[a-zA-Z0-9_-]{1,128}$``.
#:
#: Our tool codes are dot-namespaced -- ``procurement.get_open_pos`` -- and a
#: dot is not in that set. The vendor rejects the WHOLE request, not the one
#: tool, with HTTP 400 and
#: ``tools.0.custom.name: String should match pattern ...`` -- before a token is
#: billed and before any tool can run. This is a naming rule of one vendor, so
#: it is translated here and never in the kernel, which must not know that a
#: vendor exists (CI check 16).
_ILLEGAL_IN_TOOL_NAME = re.compile(r'[^a-zA-Z0-9_-]')
_MAX_TOOL_NAME = 128

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

        vendor_tools, name_map = self._vendor_tools(tools) if tools else ([], {})
        code_to_vendor = {code: name for name, code in name_map.items()}

        payload = {
            'model': model or MODELS[0][0],
            'max_tokens': max_tokens,
            'messages': self._to_vendor_messages(messages, code_to_vendor),
        }
        if system:
            # Cache breakpoint at the end of the stable prefix. The saving is
            # WITHIN one run's tool loop, where the same system block and tool
            # list are re-sent on every iteration. It is not a cross-run saving:
            # four agents have four different prompts and the runs are 24 hours
            # apart against a five-minute cache.
            payload['system'] = [{'type': 'text', 'text': system,
                                  'cache_control': {'type': 'ephemeral'}}]
        if vendor_tools:
            vendor_tools[-1]['cache_control'] = {'type': 'ephemeral'}
            payload['tools'] = vendor_tools

        raw = self._post(payload, key, timeout)
        return self._normalise(raw, name_map)

    @staticmethod
    def _vendor_tools(tools):
        """Rename our tool codes to what the vendor's grammar accepts.

        Returns the vendor payload and ``{vendor name: our code}``, because the
        runtime looks a tool up by the name that comes back and would miss the
        registry entirely if the rename were one-way.

        Collisions are resolved rather than assumed away: two codes differing
        only in an illegal character would otherwise map to one name and the
        second would silently shadow the first.
        """
        vendor, mapping = [], {}
        for tool in tools:
            code = tool['name']
            name = _ILLEGAL_IN_TOOL_NAME.sub('_', code)[:_MAX_TOOL_NAME]
            if mapping.get(name, code) != code:
                suffix = 2
                stem = name[:_MAX_TOOL_NAME - 4]
                while mapping.get('%s_%d' % (stem, suffix), code) != code:
                    suffix += 1
                name = '%s_%d' % (stem, suffix)
            mapping[name] = code
            vendor.append({'name': name, 'description': tool['description'],
                           'input_schema': tool['input_schema']})
        return vendor, mapping

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
    def _to_vendor_messages(messages, code_to_vendor=None):
        """Our neutral message list, in this vendor's shape.

        Two rules the vendor enforces and the kernel should not have to know:

        * a ``tool_result`` is only valid when the **previous message** is an
          assistant turn holding the matching ``tool_use``;
        * results for one assistant turn belong in **one** user message, so
          consecutive results are grouped rather than sent one message each.

        Tool names are translated back to the vendor-safe form for consistency
        with the declarations. The vendor does not currently re-validate names
        inside historical ``tool_use`` blocks -- verified against the live API --
        but sending a name it never issued would be gratuitous.
        """
        code_to_vendor = code_to_vendor or {}
        vendor = []
        pending = []

        def flush():
            if pending:
                vendor.append({'role': 'user', 'content': list(pending)})
                pending.clear()

        for message in messages:
            role = message.get('role')
            if role == 'tool':
                pending.append({
                    'type': 'tool_result',
                    'tool_use_id': message.get('tool_use_id'),
                    'content': json.dumps(message.get('content'), default=str),
                })
                continue
            flush()
            if role == 'assistant' and message.get('tool_calls'):
                blocks = []
                if message.get('content'):
                    blocks.append({'type': 'text', 'text': message['content']})
                for call in message['tool_calls']:
                    name = call.get('name')
                    blocks.append({'type': 'tool_use',
                                   'id': call.get('id'),
                                   'name': code_to_vendor.get(name, name),
                                   'input': call.get('input') or {}})
                vendor.append({'role': 'assistant', 'content': blocks})
            else:
                vendor.append({'role': role or 'user',
                               'content': message.get('content') or ''})
        flush()
        return vendor

    @staticmethod
    def _normalise(raw, name_map=None):
        """Parse content blocks **by type, never by position**.

        ``name_map`` undoes the vendor rename. A name we never sent is passed
        through untouched so it reaches the guard and is denied there -- silently
        dropping it would hide a prompt-injection attempt instead of logging one.
        """
        name_map = name_map or {}
        content, tool_calls = [], []
        for block in raw.get('content') or []:
            if block.get('type') == 'text':
                content.append(block.get('text', ''))
            elif block.get('type') == 'tool_use':
                vendor_name = block.get('name')
                tool_calls.append({'id': block.get('id'),
                                   'name': name_map.get(vendor_name, vendor_name),
                                   'input': block.get('input') or {}})
        usage = raw.get('usage') or {}
        return {
            'content': '\n'.join(content),
            'tool_calls': tool_calls,
            'stop_reason': raw.get('stop_reason'),
            'usage': {'input_tokens': usage.get('input_tokens') or 0,
                      'output_tokens': usage.get('output_tokens') or 0},
        }
