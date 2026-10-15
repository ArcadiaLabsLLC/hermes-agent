"""The manifest's ``params`` block names exactly the keys each h-twins verb reads (owner ruling L4.22).

``runtime.health``, the five chat-family twins and the ten ``runtime.realm.*``
twins ignore unknown keys by contract, so a client can only tell "honoured"
from "ignored" by the published list. Each verb runs here against a mapping
that records every key it asks for, with its one implementation patched out,
and the published list must equal what it asked.
"""

from __future__ import annotations

from typing import Any

import pytest

from agent_runtime import serve_rpc
from agent_runtime.serve_rpc.realm import REALM_METHODS
from agent_runtime.serve_rpc.twin_params import (
    CHAT_VERB_METHOD_PARAMS,
    HEALTH_METHOD_PARAMS,
    REALM_METHOD_PARAMS,
)


class _RecordingParams(dict):
    """A params mapping that remembers every key a handler asked for."""

    def __init__(self, values: dict):
        super().__init__(values)
        self.asked: set[str] = set()

    def get(self, key, default=None):  # type: ignore[override]
        self.asked.add(key)
        return super().get(key, default)


_EVERY_VALUE: dict[str, Any] = {
    "action": "dismiss", "add_instance": False, "agents": None, "all": False, "before": None,
    "client_message_id": "c1", "credential": None, "display_name": "D", "dry_run": False,
    "items": None, "key": "k", "kill_active": False, "limit": 5, "none": False,
    "persona_id": "neko", "persona_instance_id": "pi_1", "placement_id": None, "realm_id": "r1",
    "reason": None, "requested_by": None, "server_id": None, "session_id": "s1", "skill": "sk",
    "skills": None, "sort": None, "take": "local", "title": "T", "to": None, "turn_id": "t1",
    "workspace": False, "workspace_id": None, "yes": True,
}


def _row(*_args: Any, **_kwargs: Any) -> dict:
    return {"ok": True}


def test_all_sixteen_are_published_sorted():
    published = serve_rpc.manifest()["params"]
    rows = {**HEALTH_METHOD_PARAMS, **CHAT_VERB_METHOD_PARAMS, **REALM_METHOD_PARAMS}
    assert len(rows) == 16
    assert set(REALM_METHOD_PARAMS) == set(REALM_METHODS)
    for name, keys in rows.items():
        assert name in serve_rpc.registry._METHODS
        assert published[name] == list(keys) == sorted(keys)


@pytest.mark.parametrize("name", sorted(CHAT_VERB_METHOD_PARAMS))
def test_a_chat_twin_publishes_exactly_the_keys_it_reads(name, monkeypatch):
    from agent_runtime.chat_verbs import door, history, queue_skill, turn_resolve

    monkeypatch.setattr(door, "run_cli_chat_verb", _row)
    monkeypatch.setattr(history, "persona_chat_history_page", _row)
    monkeypatch.setattr(turn_resolve, "resolve_chat_turn", _row)
    monkeypatch.setattr(queue_skill, "queue_skills_next_turn", _row)
    recorder = _RecordingParams({key: _EVERY_VALUE[key] for key in CHAT_VERB_METHOD_PARAMS[name]})
    reply = serve_rpc.registry._METHODS[name]("r", recorder)
    assert reply.get("result") == {"ok": True}, reply
    assert sorted(recorder.asked) == list(CHAT_VERB_METHOD_PARAMS[name])


@pytest.mark.parametrize("name", sorted(REALM_METHOD_PARAMS))
def test_a_realm_twin_publishes_exactly_the_keys_it_reads(name, monkeypatch):
    import agent_runtime.realm_verbs as verbs

    for attr in ("realm_sync_status", "realm_sync_pull", "realm_sync_publish", "realm_sync_revert",
                 "realm_sync_resolve", "realm_skills_show", "realm_skills_set", "realm_agents_show",
                 "realm_agents_set", "realm_adopt"):
        monkeypatch.setattr(verbs, attr, _row)
    recorder = _RecordingParams({key: _EVERY_VALUE[key] for key in REALM_METHOD_PARAMS[name]})
    assert REALM_METHODS[name](recorder) == {"ok": True}
    assert sorted(recorder.asked) == list(REALM_METHOD_PARAMS[name])


def test_health_publishes_none_and_refuses_any():
    assert serve_rpc.manifest()["params"]["runtime.health"] == []
    reply = serve_rpc.registry._METHODS["runtime.health"]("r", {"filter": "x"})
    assert reply["error"]["data"]["reason"] == "unexpected_params"
