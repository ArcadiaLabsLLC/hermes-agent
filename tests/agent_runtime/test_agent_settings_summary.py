"""A device driving this engine reads an agent's short list of safe settings, never its config file.

Row ``RT-FU-ANOTHER-DEVICE-SEES-A-SHORT-LIST-OF-SAFE-AGENT-SETTINGS-NEVER-THE-CONFIG-FILE``. The
agent's bound profile writes a real ``config.yaml`` carrying the secrets the file can hold (a custom
endpoint's key and base URL, an MCP server's command, env and headers); the detail verb
``runtime.persona.instance.detail`` is called through the real dispatcher, as the owner and a paired
device. Every test runs in the ``tests/agent_runtime`` conftest's isolated
store root.

Killing mutations (each red seen 2026-11-22):

* ``agent_settings_summary.SAFE_SETTINGS_FIELDS``: add ``"base_url"`` (with its value read off the
  profile's ``model:`` block), and the exact-field-set and no-secret tests red;
* ``agent_settings_summary.agent_settings_summary``: answer the profile's whole ``model:`` block for
  ``model``, and the no-secret test finds the key in the reply;
* ``snapshot.details.persona_instance_detail_for_id``: drop the ``settings`` key on the agent path,
  and the paired-device test finds no block.
"""

from __future__ import annotations

import json
import textwrap

import pytest

from agent_runtime import call_authorization as ca
from agent_runtime import serve_rpc
from agent_runtime.agent_settings_summary import SAFE_SETTINGS_FIELDS
from agent_runtime.models import AgentPersona
from agent_runtime.parse_cache import clear_parse_cache
from agent_runtime.store import AgentStore

DETAIL = "runtime.persona.instance.detail"

#: Every secret the profile's config.yaml carries; none may reach any reply.
_SECRETS = ("sk-secret-never-served", "https://private.example.invalid/v1", "mcp-env-secret",
            "Bearer header-secret", "/opt/secret-mcp-server")

_CONFIG = """\
model:
  default: profile-model
  provider: custom
  base_url: https://private.example.invalid/v1
  api_key: sk-secret-never-served
toolsets:
  - web
  - file
mcp_servers:
  private:
    command: /opt/secret-mcp-server
    env:
      TOKEN: mcp-env-secret
    headers:
      Authorization: Bearer header-secret
"""


@pytest.fixture
def agent(bundled_persona_profiles):
    """A persona bound to a profile whose config.yaml holds every secret the file can hold."""

    from hermes_cli.profiles import get_profile_dir

    (get_profile_dir("gpt-launcher") / "config.yaml").write_text(textwrap.dedent(_CONFIG), encoding="utf-8")
    clear_parse_cache()
    AgentStore().save(AgentPersona(id="dev", display_name="Dev", role="dev", model="claude-sonnet-x",
                                   provider="anthropic", api_mode=None, hermes_profile="gpt-launcher"))
    return "dev"


def _ask(caller, agent_id: str) -> dict:
    return serve_rpc.handle_request({"jsonrpc": "2.0", "id": "s", "method": DETAIL,
                                     "params": {"instance_id": agent_id}},
                                    serve_rpc.RpcContext(caller=caller, transport=ca.TRANSPORT_GATEWAY))


def _paired_device() -> ca.RpcCaller:
    return ca.RpcCaller(kind=ca.CALLER_DEVICE, connection_key="c1", transport=ca.TRANSPORT_GATEWAY,
                        device_id="dev_phone", device_tier=ca.TIER_CONSOLE)


def test_the_settings_block_is_exactly_model_provider_and_toolsets(agent):
    settings = _ask(ca.STDIO_OWNER, agent)["result"]["settings"]

    assert SAFE_SETTINGS_FIELDS == ("model", "provider", "toolsets")
    assert list(settings) == list(SAFE_SETTINGS_FIELDS)
    assert settings == {"model": "claude-sonnet-x", "provider": "anthropic", "toolsets": ["web", "file"]}


def test_no_secret_from_the_config_file_reaches_any_reply(agent):
    for caller in (ca.STDIO_OWNER, _paired_device()):
        wire = json.dumps(_ask(caller, agent))
        for secret in _SECRETS:
            assert secret not in wire, (caller.kind, secret)
        # The file's contents reach no caller.
        assert "config" not in json.dumps(_ask(caller, agent)["result"]["settings"])


def test_a_paired_device_reads_the_block(agent):
    expected = _ask(ca.STDIO_OWNER, agent)["result"]["settings"]
    reply = _ask(_paired_device(), agent)
    assert "result" in reply, reply
    assert reply["result"]["settings"] == expected
