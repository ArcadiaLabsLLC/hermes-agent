"""``harness persona set-context`` and its wire twin ``runtime.persona.set_context`` (RT-PERSONA-CONTEXT-MEMORY-SETTER).

Plan ``docs/agent-runtime-harness/planned/chat-lane-context-and-memory-gaps.md`` R1. Every write is
proven by re-reading the persona's store row off DISK, never by trusting the reply; the argv cases
drive the real argparse tree through ``args.func``.
"""

from __future__ import annotations

import json

from tests.hermes_cli.test_persona_set_skills import _dispatch, _row_on_disk, _seed_persona, hermetic_runtime_root  # noqa: F401


def _set_context(persona_id: str, *flags: str) -> list[str]:
    return ["harness", "persona", "set-context", persona_id, *flags, "--json"]


def _switches_on_disk(persona_id: str = "qa") -> tuple[bool, bool]:
    row = _row_on_disk(persona_id)
    return bool(row.get("include_core_context_files")), bool(row.get("include_profile_memory"))


def test_each_switch_writes_its_own_field_and_states_its_cost(capsys):
    _seed_persona()
    assert _switches_on_disk() == (False, False)

    assert _dispatch(_set_context("qa", "--core-context-files", "on")) == 0
    data = json.loads(capsys.readouterr().out)
    assert _switches_on_disk() == (True, False)
    assert data["switches"] == {"core_context_files": True, "profile_memory": False}
    assert data["changed"] == ["core_context_files"] and data["scope"] == "persona_template"
    assert set(data["cost"]) == {"core_context_files"} and "per turn" in data["cost"]["core_context_files"]

    assert _dispatch(_set_context("qa", "--profile-memory", "on")) == 0
    data = json.loads(capsys.readouterr().out)
    assert _switches_on_disk() == (True, True)
    assert set(data["cost"]) == {"core_context_files", "profile_memory"}
    assert "MEMORY.md" in data["cost"]["profile_memory"]

    assert _dispatch(_set_context("qa", "--core-context-files", "off", "--profile-memory", "off")) == 0
    data = json.loads(capsys.readouterr().out)
    assert _switches_on_disk() == (False, False) and data["cost"] == {}


def test_a_repeat_write_changes_nothing(capsys):
    _seed_persona()
    assert _dispatch(_set_context("qa", "--profile-memory", "on")) == 0
    capsys.readouterr()
    assert _dispatch(_set_context("qa", "--profile-memory", "on")) == 0
    assert json.loads(capsys.readouterr().out)["changed"] == []
    assert _switches_on_disk() == (False, True)


def test_naming_neither_switch_is_a_refusal_not_a_write(capsys):
    _seed_persona()
    assert _dispatch(_set_context("qa")) == 2
    data = json.loads(capsys.readouterr().out)
    assert data["ok"] is False and data["error_code"] == "nothing_to_write"
    assert _switches_on_disk() == (False, False)


def test_an_unknown_persona_is_refused(capsys):
    assert _dispatch(_set_context("nobody", "--profile-memory", "on")) == 2
    assert json.loads(capsys.readouterr().out)["error_code"] == "persona_not_found"


def test_the_wire_twin_writes_the_same_row_and_refuses_a_non_bool(capsys):
    from agent_runtime.serve_rpc import console_operations as rpc
    from agent_runtime.serve_rpc.protocol import ERR_CONFLICT, ERR_INVALID_PARAMS
    from agent_runtime.serve_rpc.registry import method_tier

    _seed_persona()
    reply = rpc.persona_context("ctx", {"persona_id": "qa", "core_context_files": True})
    assert "result" in reply, reply
    assert reply["result"]["switches"]["core_context_files"] is True
    assert _switches_on_disk() == (True, False)
    assert not capsys.readouterr().out

    bad = rpc.persona_context("bad", {"persona_id": "qa", "profile_memory": "on"})
    assert bad["error"]["code"] == ERR_INVALID_PARAMS and bad["error"]["data"]["field"] == "profile_memory"
    refused = rpc.persona_context("none", {"persona_id": "qa"})
    assert refused["error"]["code"] == ERR_CONFLICT
    assert refused["error"]["data"]["error_code"] == "nothing_to_write"
    assert _switches_on_disk() == (True, False)
    assert method_tier("runtime.persona.set_context") == "console"
