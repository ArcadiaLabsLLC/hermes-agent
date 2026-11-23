"""A device driving this engine reads an agent's short list of safe settings, never its config file.

Row ``RT-FU-ANOTHER-DEVICE-SEES-A-SHORT-LIST-OF-SAFE-AGENT-SETTINGS-NEVER-THE-CONFIG-FILE``. The
agent's bound profile writes a real ``config.yaml`` carrying the secrets the file can hold (a custom
endpoint's key and base URL, an MCP server's command, env and headers); the detail verb
``runtime.persona.instance.detail`` is called through the real dispatcher, as the owner, a view-only
device and a computer at Look. Every test runs in the ``tests/agent_runtime`` conftest's isolated
store root.

Killing mutations (each red seen 2026-11-22):

* ``agent_settings_summary.SAFE_SETTINGS_FIELDS``: add ``"base_url"`` (with its value read off the
  profile's ``model:`` block), and the exact-field-set and no-secret tests red;
* ``agent_settings_summary.agent_settings_summary``: answer the profile's whole ``model:`` block for
  ``model``, and the no-secret test finds the key in the reply;
* ``snapshot.details.persona_instance_detail_for_id``: drop the ``settings`` key on the agent path,
  and the Look test finds no block;
* ``serve_rpc.console_operations.instance_detail``: state no ``computer=`` reach, and the Look test is
  refused.

The paths (row ``RT-FU-A-LOOK-DEVICE-IS-SENT-THE-PATH-OF-AN-AGENTS-SETTINGS-FILE``): below console reach the
reply names no absolute local path; the console, a console device and an account-level computer keep them.
Killing mutations (each red seen 2026-11-22):

* ``console_operations._detail_for_caller``: return ``result`` for every caller, and the no-path test finds
  the config file's path in the Look reply (the console test stays green);
* ``console_operations._text_without_paths``: return the string unchanged, and the issue-sentence test finds
  the path in the unknown toolset's fix hint;
* ``console_operations._sees_local_paths``: answer ``True`` for a device whatever its tier, and the no-path
  test finds the path in the view-only device's reply;
* ``console_operations._sees_local_paths``: answer ``False`` for every caller, and the console test finds no
  ``config_path``;
* ``console_operations._LOCAL_PATH_FIELDS``: drop ``"workdir"``, and the field test finds the working
  directory.
"""

from __future__ import annotations

import json
import re
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


def _view_only_device() -> ca.RpcCaller:
    return ca.RpcCaller(kind=ca.CALLER_DEVICE, connection_key="c1", transport=ca.TRANSPORT_GATEWAY,
                        device_id="dev_phone", device_tier=ca.TIER_READ)


def _look_computer() -> ca.RpcCaller:
    return ca.RpcCaller(kind=ca.CALLER_COMPUTER, transport=ca.TRANSPORT_GATEWAY, connection_key="lane-1",
                        computer_id="cmp-1", computer_grant=ca.COMPUTER_GRANT_LOOK)


def test_the_settings_block_is_exactly_model_provider_and_toolsets(agent):
    settings = _ask(ca.STDIO_OWNER, agent)["result"]["settings"]

    assert SAFE_SETTINGS_FIELDS == ("model", "provider", "toolsets")
    assert list(settings) == list(SAFE_SETTINGS_FIELDS)
    assert settings == {"model": "claude-sonnet-x", "provider": "anthropic", "toolsets": ["web", "file"]}


def test_no_secret_from_the_config_file_reaches_any_reply(agent):
    for caller in (ca.STDIO_OWNER, _view_only_device(), _look_computer()):
        wire = json.dumps(_ask(caller, agent))
        for secret in _SECRETS:
            assert secret not in wire, (caller.kind, secret)
        # The file's PATH reaches the console alone (RT-FU-A-LOOK-DEVICE-IS-SENT-THE-PATH-OF-AN-AGENTS-
        # SETTINGS-FILE, the tests below); its contents reach no caller.
        assert "config" not in json.dumps(_ask(caller, agent)["result"]["settings"])


def test_a_view_only_device_and_a_look_computer_read_the_block(agent):
    expected = _ask(ca.STDIO_OWNER, agent)["result"]["settings"]
    for caller in (_view_only_device(), _look_computer()):
        reply = _ask(caller, agent)
        assert "result" in reply, reply
        assert reply["result"]["settings"] == expected


# ── no absolute local path below console reach (RT-FU-A-LOOK-DEVICE-IS-SENT-THE-PATH-OF-AN-AGENTS-SETTINGS-FILE)

#: An absolute path as a whole value: POSIX, home-relative, a Windows drive or a UNC share.
_ABSOLUTE = re.compile(r"^(?:/|~[/\\]|[A-Za-z]:[/\\]|\\\\)")


def _strings(node):
    if isinstance(node, dict):
        for value in node.values():
            yield from _strings(value)
    elif isinstance(node, list):
        for value in node:
            yield from _strings(value)
    elif isinstance(node, str):
        yield node


def _console_device() -> ca.RpcCaller:
    return ca.RpcCaller(kind=ca.CALLER_DEVICE, connection_key="c2", transport=ca.TRANSPORT_GATEWAY,
                        device_id="dev_desk", device_tier=ca.TIER_CONSOLE)


def _computer(grant: str) -> ca.RpcCaller:
    return ca.RpcCaller(kind=ca.CALLER_COMPUTER, transport=ca.TRANSPORT_GATEWAY, connection_key="lane-2",
                        computer_id="cmp-2", computer_grant=grant)


@pytest.fixture
def pathed_agent(bundled_persona_profiles):
    """A persona whose reply carries every local path it can: its config file, a declaration issue's
    sentence naming that file (an unknown toolset), and a repository bound by absolute path."""

    from hermes_cli.profiles import get_profile_dir

    profile = get_profile_dir("gpt-launcher")
    (profile / "config.yaml").write_text("toolsets:\n  - web\n  - no-such-toolset\n", encoding="utf-8")
    clear_parse_cache()
    repo = str(profile.parent / "repos" / "secret-repo")
    AgentStore().save(AgentPersona(id="pathy", display_name="Pathy", role="dev", model="claude-sonnet-x",
                                   provider="anthropic", api_mode=None, hermes_profile="gpt-launcher",
                                   repo_scope_label=repo))
    return "pathy", str(profile / "config.yaml"), repo


def test_no_absolute_local_path_reaches_look_or_view_only(pathed_agent):
    agent_id, config_path, repo = pathed_agent
    owner = _ask(ca.STDIO_OWNER, agent_id)["result"]
    assert owner["tool_resolution"]["toolset_declaration"]["config_path"] == config_path  # the positive control
    for caller in (_view_only_device(), _look_computer(), _computer(ca.COMPUTER_GRANT_CHAT)):
        reply = _ask(caller, agent_id)
        assert "result" in reply, (caller.kind, reply)
        wire = json.dumps(reply)
        assert config_path not in wire and repo not in wire, caller
        for text in _strings(reply):
            assert not _ABSOLUTE.match(text), (caller, text)
        declaration = reply["result"]["tool_resolution"]["toolset_declaration"]
        assert declaration["profile"] == "gpt-launcher" and declaration["source"]  # labels survive
        assert reply["result"]["settings"] == owner["settings"]  # the safe block survives


def test_an_issue_sentence_names_no_local_path(pathed_agent):
    agent_id, config_path, _ = pathed_agent
    owner_issues = _ask(ca.STDIO_OWNER, agent_id)["result"]["tool_resolution"]["toolset_declaration"]["issues"]
    assert any(config_path in issue["fix_hint"] for issue in owner_issues)  # the positive control
    look_issues = _ask(_look_computer(), agent_id)["result"]["tool_resolution"]["toolset_declaration"]["issues"]
    assert [issue["code"] for issue in look_issues] == [issue["code"] for issue in owner_issues]
    for issue in look_issues:
        assert issue["config_path"] is None
        assert config_path not in issue["fix_hint"] and "agent's computer" in issue["fix_hint"], issue


def test_the_console_keeps_the_paths(pathed_agent):
    agent_id, config_path, repo = pathed_agent
    for caller in (ca.STDIO_OWNER, _console_device(), _computer(ca.COMPUTER_GRANT_ACCOUNT)):
        reply = _ask(caller, agent_id)
        assert "result" in reply, (caller.kind, reply)
        resolution = reply["result"]["tool_resolution"]
        assert resolution["toolset_declaration"]["config_path"] == config_path, caller
        assert resolution["repo_scope"] == repo, caller


def test_every_named_path_field_is_dropped_and_a_label_kept():
    from agent_runtime.serve_rpc.console_operations import _detail_for_caller

    paths = {"config_path": "/home/someone/.hermes/profiles/p/config.yaml", "workdir": "C:\\Users\\someone\\chat",
             "runtime_root": "~/runtime", "root_config_path": "\\\\box\\share\\config.yaml",
             "repo_scope": "D:/Unreal Engine/repo"}
    block = {"tool_resolution": {**paths, "hermes_profile": "p", "toolset_declaration": {"source": "profile_config"}},
             "turn_tool_context": {"preview": {"repo_scope": "eternia-launcher", "workdir": paths["workdir"]}}}
    seen = _detail_for_caller(json.loads(json.dumps(block)), _look_computer())
    assert all(seen["tool_resolution"][key] is None for key in paths), seen
    assert seen["tool_resolution"]["hermes_profile"] == "p"
    assert seen["turn_tool_context"]["preview"] == {"repo_scope": "eternia-launcher", "workdir": None}
    assert _detail_for_caller(json.loads(json.dumps(block)), ca.STDIO_OWNER) == block
