"""``runtime.health`` — the ``harness health`` block, one implementation, two doors."""

from __future__ import annotations

import json
from types import SimpleNamespace

from agent_runtime import provider_health, serve_rpc
from agent_runtime.call_authorization import TIER_READ
from agent_runtime.serve_rpc.protocol import ERR_INVALID_PARAMS
from hermes_cli.harness_parts import runtime_commands


def _rpc(params=None):
    return serve_rpc.handle_request(
        {"jsonrpc": "2.0", "id": "h", "method": "runtime.health", "params": params or {}})


def _argv_json(capsys) -> dict:
    assert runtime_commands._cmd_health(SimpleNamespace(json=True)) == 0
    return json.loads(capsys.readouterr().out)


def test_the_method_and_the_argv_verb_reach_one_implementation(monkeypatch, capsys):
    seen: list[list] = []
    block = {"ok": False, "interpreter": "py", "issues": [{"kind": "runtime_dependency_missing", "package": "x"}]}

    def health(personas):
        seen.append(list(personas))
        return dict(block)

    monkeypatch.setattr(provider_health, "provider_health_for_personas", health)
    assert _rpc()["result"] == block
    assert _argv_json(capsys) == block
    assert len(seen) == 2 and seen[0] == seen[1]


def test_the_result_is_the_block_harness_status_carries_by_shape():
    result = _rpc()["result"]
    assert set(result) >= {
        "ok", "interpreter", "runtime_root", "hermes_home", "hermes_profile",
        "required_packages", "package_available", "issues",
    }
    assert result["ok"] is (not result["issues"])


def test_parameters_are_a_typed_refusal():
    reply = _rpc({"persona_id": "dev"})
    assert reply["error"]["code"] == ERR_INVALID_PARAMS
    assert reply["error"]["data"]["reason"] == "unexpected_params"


def test_it_is_advertised_at_the_read_tier():
    manifest = serve_rpc.manifest()
    assert "runtime.health" in manifest["methods"]
    assert manifest["tiers"]["runtime.health"] == TIER_READ
