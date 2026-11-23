"""A computer at Look or Run chats reads the health check and the agent list without where Hermes lives.

Row ``RT-FU-A-LOOK-COMPUTER-IS-SENT-WHERE-A-PHONE-KEEPS-HERMES-BY-ITS-HEALTH-CHECK-AND-AGENT-LIST`` (review w1122d.13).
``runtime.health`` and ``runtime.agent.directory`` are called through the real dispatcher. Below console reach the
health block's ``interpreter``, ``runtime_root`` and ``hermes_home`` are null, an ``issues`` sentence names no path,
and each agent's ``profile_home`` is null; ``ok``, the packages, the profile's name and every agent's ids stay. The
owner's console, a console device and an account-level computer keep every path. Every test runs in the
``tests/agent_runtime`` conftest's isolated store root.

Killing mutations (each red seen 2026-11-23, in a scratch tree):

* ``health._runtime_health``: return ``runtime_health()`` unprojected, and the Look health test finds the
  interpreter's path (the console health test stays green);
* ``agent._runtime_agent_directory``: return the catalog unprojected, and the Look agent-list test finds
  ``profile_home`` (the console agent-list test stays green);
* ``console_operations._LOCAL_PATH_FIELDS``: drop ``"interpreter"``, and the Look health test finds it rewritten
  into a sentence, not null (dropping ``"hermes_home"`` reddens it the same way, dropping ``"profile_home"``
  reddens the Look agent-list test);
* ``console_operations._text_without_paths``: return the sentence unchanged, and the issue-sentence test finds the
  interpreter's path in the missing package's summary.
"""

from __future__ import annotations

import json
import sys

import pytest

from agent_runtime import call_authorization as ca
from agent_runtime import serve_rpc
from tests.agent_runtime.test_serve_rpc_open_chat import placed_agent, qa_persona  # noqa: F401  (fixtures)

HEALTH = "runtime.health"
DIRECTORY = "runtime.agent.directory"
_HEALTH_PATHS = ("interpreter", "runtime_root", "hermes_home")


def _ask(caller, method: str) -> dict:
    return serve_rpc.handle_request({"jsonrpc": "2.0", "id": "h", "method": method, "params": {}},
                                    serve_rpc.RpcContext(caller=caller, transport=ca.TRANSPORT_GATEWAY))


def _computer(grant: str) -> ca.RpcCaller:
    return ca.RpcCaller(kind=ca.CALLER_COMPUTER, transport=ca.TRANSPORT_GATEWAY, connection_key="lane-h",
                        computer_id="cmp-h", computer_grant=grant)


def _device(tier: str) -> ca.RpcCaller:
    return ca.RpcCaller(kind=ca.CALLER_DEVICE, connection_key="d-h", transport=ca.TRANSPORT_GATEWAY,
                        device_id="dev_h", device_tier=tier)


_BELOW_CONSOLE = (lambda: _computer(ca.COMPUTER_GRANT_LOOK), lambda: _computer(ca.COMPUTER_GRANT_CHAT))
_AT_CONSOLE = (lambda: ca.STDIO_OWNER, lambda: _device(ca.TIER_CONSOLE), lambda: _computer(ca.COMPUTER_GRANT_ACCOUNT))


@pytest.fixture
def missing_package(monkeypatch):
    """The health block reports one missing package, its real sentence naming this interpreter's path."""

    from agent_runtime import provider_health
    from hermes_cli.runtime_environment import _runtime_environment_status

    monkeypatch.setattr(provider_health, "runtime_environment_status",
                        lambda packages: _runtime_environment_status(["no-such-package-hmhealth"]))


def test_a_look_computer_reads_no_path_in_the_health_check(qa_persona):
    owner = _ask(ca.STDIO_OWNER, HEALTH)["result"]
    assert owner["interpreter"] == sys.executable  # the positive control
    for make in _BELOW_CONSOLE + (lambda: _device(ca.TIER_READ),):
        caller = make()
        reply = _ask(caller, HEALTH)
        assert "result" in reply, (caller, reply)
        seen = reply["result"]
        assert {key: seen[key] for key in _HEALTH_PATHS} == dict.fromkeys(_HEALTH_PATHS), caller
        assert sys.executable not in json.dumps(seen), caller
        kept = ("ok", "hermes_profile", "required_packages", "package_available")
        assert {key: seen[key] for key in kept} == {key: owner[key] for key in kept}, caller


def test_the_console_keeps_the_health_check_paths(qa_persona):
    for make in _AT_CONSOLE:
        caller = make()
        reply = _ask(caller, HEALTH)
        assert "result" in reply, (caller, reply)
        assert reply["result"]["interpreter"] == sys.executable, caller
        assert all(reply["result"][key] for key in _HEALTH_PATHS), caller


def test_an_issue_sentence_names_no_interpreter_path(qa_persona, missing_package):
    owner_issue = _ask(ca.STDIO_OWNER, HEALTH)["result"]["issues"][0]
    assert sys.executable in owner_issue["summary"]  # the positive control
    seen = _ask(_computer(ca.COMPUTER_GRANT_LOOK), HEALTH)["result"]
    assert seen["ok"] is False
    issue = seen["issues"][0]
    assert sys.executable not in issue["summary"]
    assert "a file on the agent's computer" in issue["summary"]
    assert {key: issue[key] for key in ("kind", "package")} == {key: owner_issue[key] for key in ("kind", "package")}


@pytest.fixture
def listed_agent(placed_agent):
    """The placed agent's instance id, bound to a profile that exists (so it has a settings folder), on an install
    with an identity (the agent list refuses one without)."""

    from agent_runtime import paths
    from agent_runtime.gateway_identity import ensure_install_identity
    from agent_runtime.store import AgentStore
    from hermes_cli.profiles import get_profile_dir

    profile = get_profile_dir("listed")
    profile.mkdir(parents=True, exist_ok=True)
    (profile / "config.yaml").write_text("toolsets:\n  - web\n", encoding="utf-8")  # a profile's identity
    personas = AgentStore()
    persona = personas.get(placed_agent["persona_id"])
    persona.hermes_profile = "listed"
    personas.save(persona)
    ensure_install_identity(paths.store_root())
    return placed_agent["persona_instance_id"]


def _agent_row(reply: dict, instance_id: str) -> dict:
    rows = [row for row in reply["result"]["agents"] if row["instance_id"] == instance_id]
    assert rows, reply
    return rows[0]


def test_a_look_computer_reads_no_settings_folder_in_the_agent_list(listed_agent):
    instance_id = listed_agent
    owner_row = _agent_row(_ask(ca.STDIO_OWNER, DIRECTORY), instance_id)
    assert owner_row["profile_home"]  # the positive control
    for make in _BELOW_CONSOLE:
        caller = make()
        reply = _ask(caller, DIRECTORY)
        assert "result" in reply, (caller, reply)
        assert owner_row["profile_home"] not in json.dumps(reply), caller
        row = _agent_row(reply, instance_id)
        assert row == {**owner_row, "profile_home": None}, caller


def test_the_console_keeps_each_agents_settings_folder(listed_agent):
    instance_id = listed_agent
    for make in _AT_CONSOLE:
        caller = make()
        reply = _ask(caller, DIRECTORY)
        assert "result" in reply, (caller, reply)
        assert _agent_row(reply, instance_id)["profile_home"], caller
