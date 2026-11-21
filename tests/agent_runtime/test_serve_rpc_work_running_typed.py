"""What is running now has typed calls on the running Hermes: ``runtime.work.running.list`` / ``.peek``.

Row ``RT-EVERY-ACTION-ETERNIA-SENDS-HAS-A-TYPED-CALL-ON-THE-RUNNING-HERMES``, family "work": the twins of
``harness work list`` / ``harness work peek``, over ONE builder (``running_work_listing``) and
``peek_work``. Also pins ``persona.elevate_tools_once``'s typed call: it is ``runtime.persona.permission.set``
with ``mode: unbounded`` and one turn — the argv verb Eternia rendered, no wider. Killing mutations per test.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from agent_runtime import serve_rpc
from agent_runtime.running_work import surface
from tests.agent_runtime.test_serve_rpc_agent_create import qa_persona  # noqa: F401  (fixture)


def _rpc(method, **params):
    return serve_rpc.handle_request({"jsonrpc": "2.0", "id": "w", "method": method, "params": params})


ROWS = [
    {"work_id": "terminal:a", "kind": "terminal", "label": "b-build"},
    {"work_id": "terminal:b", "kind": "terminal", "label": "a-serve"},
    {"work_id": "chat_turn:c", "kind": "chat_turn", "label": "c-turn"},
]


@pytest.fixture
def projection(monkeypatch):
    def build(accountant):
        return {"rows": [dict(row) for row in ROWS], "sources": {"terminal": "ok"}, "counts": {"rows": 3},
                "ambient": {"home": "here"}}

    monkeypatch.setattr(surface, "build_running_work", build)


def test_the_list_is_the_argv_envelope(projection, monkeypatch):
    """Mutation: have the argv verb build its own envelope without ``sources`` -> the two differ, red."""
    from hermes_cli.harness_parts import work_commands

    reply = _rpc("runtime.work.running.list")["result"]
    assert reply["kind"] == "list" and reply["item_kind"] == "running_work"
    assert [row["work_id"] for row in reply["items"]] == ["terminal:a", "terminal:b", "chat_turn:c"]
    assert reply["sources"] == {"terminal": "ok"} and reply["counts"] == {"rows": 3}
    assert reply["ambient"] == {"home": "here"} and "completeness" in reply

    printed = []
    monkeypatch.setattr(work_commands, "_print_stage42", lambda envelope, **_: printed.append(envelope))
    assert work_commands._cmd_work_list(SimpleNamespace(kind=None, limit=None, sort=None, json=True)) == 0
    assert printed == [reply]


def test_the_list_filters_sorts_and_cuts_at_its_limit(projection):
    """Mutation: drop ``limit=limit`` in the method -> three rows and ``truncated`` false, red."""
    reply = _rpc("runtime.work.running.list", kind="terminal", sort="label", limit=1)["result"]
    assert [row["work_id"] for row in reply["items"]] == ["terminal:b"]
    assert reply["truncated"] is True


@pytest.mark.parametrize("params", [{"kind": "nonsense"}, {"limit": 0}, {"limit": True}, {"limit": "2"},
                                    {"kind": 3}, {"other": 1}])
def test_a_malformed_list_is_refused(projection, params):
    reply = _rpc("runtime.work.running.list", **params)
    assert reply["error"]["code"] == serve_rpc.ERR_INVALID_PARAMS
    assert reply["error"]["data"]["reason"] == "invalid_request"


def test_an_unknown_kind_names_the_supported_ones(projection):
    data = _rpc("runtime.work.running.list", kind="nonsense")["error"]["data"]
    assert "terminal" in data["supported"]


def test_the_peek_answers_the_payload_and_its_refusals(monkeypatch):
    """Mutation: answer a not-found peek ``ok`` -> the second assert, red; drop the malformed arm -> the third."""
    monkeypatch.setattr(surface, "find_work_row", lambda work_id: {"work_id": work_id, "kind": "chat_turn"}
                        if work_id == "chat_turn:c" else None)
    found = _rpc("runtime.work.running.peek", work_id="chat_turn:c")["result"]
    assert found["found"] is True and found["work_kind"] == "chat_turn" and found["consumed"] is False
    assert found["tail_reason"] == "no_output_stream"

    missing = _rpc("runtime.work.running.peek", work_id="terminal:gone")["error"]
    assert missing["code"] == serve_rpc.ERR_NOT_FOUND and missing["data"]["reason"] == "not_found"
    malformed = _rpc("runtime.work.running.peek", work_id="no-colon")["error"]
    assert malformed["code"] == serve_rpc.ERR_INVALID_PARAMS and malformed["data"]["reason"] == "invalid_request"
    assert _rpc("runtime.work.running.peek")["error"]["data"]["reason"] == "invalid_request"


def test_the_two_methods_are_on_the_manifest_and_the_board_list_is_untouched():
    from agent_runtime.serve_rpc.registry import manifest

    names = set(manifest()["methods"])
    assert {"runtime.work.running.list", "runtime.work.running.peek", "runtime.work.list"} <= names


def test_elevate_tools_once_is_the_typed_permission_set(qa_persona):  # noqa: F811
    """``persona.elevate_tools_once``'s argv (``harness persona permission set --mode unbounded --turns 1
    --ttl-seconds N``) has its typed call already: the same handler, so the same approval posture.
    Mutation: drop ``unbounded`` from ``SUPPORTED_PERMISSION_MODES`` -> the call is refused, red."""
    reply = _rpc("runtime.persona.permission.set", persona_id="qa", session_id="sess-elevate", mode="unbounded",
                 reason="one bounded unlock", turns=1, ttl_seconds=240)
    assert "result" in reply, reply
    permission = reply["result"]["permission"]
    assert permission["mode"] == "unbounded" and permission["turns_remaining"] == 1
    assert permission["expires_at"] and permission["session_id"] == "sess-elevate"
