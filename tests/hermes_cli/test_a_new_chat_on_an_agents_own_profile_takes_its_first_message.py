"""A new chat with an agent that runs on its own profile takes its first message and answers its model read.

RT-FU-A-NEW-CHAT-WITH-AN-AGENT-ON-ITS-OWN-PROFILE-CANNOT-TAKE-ITS-FIRST-MESSAGE (review w1118a.71). Seen live
2026-11-21 (lane namespace, account C): Mission Control -> Neko -> Create new chat minted a root, then the first
send was refused ``session_not_found`` and every model read on it failed. Neko's instance had never been bound
(a fresh namespace): the new-chat mint opened its store through ``resolve_instance_chat_scope``, which answers a
never-bound row with the process head (``profiles/base``), while the bind stamped the first-bind head (Neko's own
profile) and the send and the model read resolve through that record. The mint now acquires through the one
conversation resolver (``chat_heads.resolve_conversation_chat_scope``), so mint, bind, send and read agree.

Two profiles, the launcher's layout: ``HERMES_HEAD_HOME=profiles/base`` (the serve's), persona ``neko`` running in
profile ``neko``. The mint is the real verb (``_cmd_persona_instance_open_new_chat``); the send is the real send
lane (``_cmd_mission_chat_message``) up to the provider, stubbed to raise when admission reaches it; the model read
is ``inspect_operator_settings``, the first read of ``runtime.operator.conversation.models``.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent_runtime.models import CHAT_HEAD_KIND_PER_PROFILE
from hermes_cli.harness_parts.persona import chat_open, chat_turn_message
from hermes_cli.harness_parts.persona.chat_turn_commit import run as commit_run


class _ProviderReached(RuntimeError):
    pass


@pytest.fixture
def heads(tmp_path, monkeypatch):
    from agent_runtime import profile_context
    from agent_runtime.config import AgentRuntimeConfig
    from agent_runtime.models import AgentPersona
    from agent_runtime.store import AgentStore

    root = tmp_path / ".hermes"
    base, neko = root / "profiles" / "base", root / "profiles" / "neko"
    for path in (root / "agent-runtime", base, neko):
        path.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("HERMES_AGENT_RUNTIME_ROOT", str(root / "agent-runtime"))
    monkeypatch.setenv("HERMES_HOME", str(base))
    monkeypatch.setenv("HERMES_HEAD_HOME", str(base))
    monkeypatch.setattr(profile_context, "profile_exists", lambda name: name == "neko")
    monkeypatch.setattr(profile_context, "get_profile_dir", lambda name: {"neko": neko}[name])
    AgentStore().save(AgentPersona(
        id="neko", display_name="Neko", role="lead", model="gpt-test", provider="openai-codex",
        api_mode="codex_responses", system_prompt_path="", hermes_profile="neko",
    ))

    class _Provider:
        def __init__(self, *args, **kwargs):
            pass

        def mission_chat_reply(self, *args, **kwargs):
            raise _ProviderReached("admission reached the provider")

    monkeypatch.setattr(chat_turn_message, "load_agent_runtime_config", lambda: AgentRuntimeConfig())
    monkeypatch.setattr(commit_run, "GPTPersonaRuntime", _Provider)
    # The prewarm builds a resident actor; this test reads where the root lives, not how warm it is.
    monkeypatch.setattr(chat_open, "_prewarm_chat_actor_for_open", lambda session_id: None)
    return SimpleNamespace(base=base, neko=neko)


def _sessions(home: Path, root: str) -> int:
    db = home / "state.db"
    if not db.is_file():
        return 0
    with sqlite3.connect(db) as conn:
        return conn.execute("SELECT COUNT(*) FROM sessions WHERE id = ?", (root,)).fetchone()[0]


def _neko():
    from agent_runtime.config.roster import ensure_persisted_personas

    return next(p for p in ensure_persisted_personas() if p.id == "neko")


def _open_new_chat(capsys, instance_id: str) -> dict:
    code = chat_open._cmd_persona_instance_open_new_chat(SimpleNamespace(
        persona_instance_id=instance_id, session_id=None, add_instance=False,
        idempotency_key="sw71-new-chat-1", title=None, select_session=True, client_scope=None, json=True,
    ), persona_id="neko", coordinator_scope=None)
    payload = json.loads(capsys.readouterr().out)
    assert code == 0, payload
    return payload


def _send(capsys, instance_id: str, root: str) -> dict:
    chat_turn_message._cmd_mission_chat_message(SimpleNamespace(
        persona_id="neko", persona_instance_id=instance_id, session_id=root, new_session=False,
        message="hello, can you hear me?", surface_prompt="", intent_hint="chat",
        requested_by="operator", client_message_id="sw71-first-send", stream=False,
        max_seconds=5.0, json=True,
    ))
    return json.loads(capsys.readouterr().out)


def _model_read(instance, root: str) -> dict:
    from agent_runtime import paths
    from agent_runtime.gateway_identity import ensure_install_identity
    from agent_runtime.operator_session_inspection import inspect_operator_settings

    return inspect_operator_settings({
        "install_id": ensure_install_identity(paths.store_root()).install_id,
        "persona_id": instance.persona_id, "persona_instance_id": instance.id,
        "workspace_id": None, "session_id": root,
    })


def test_a_new_chat_of_a_never_bound_agent_on_its_own_profile_takes_its_first_message(heads, capsys):
    """KILLING MUTATION (run 2026-11-21): ``lifecycle_commands._instance_session_db`` acquiring through
    ``resolve_instance_chat_scope(instance)`` again (the mint before this fix) -> the root lands in
    ``profiles/base`` while the bind records ``profiles/neko``: ``assert (0, 1) == (1, 0)``, red (the store
    the live send then answered ``session_not_found`` from)."""

    from agent_runtime.persona_assignments import PersonaInstanceStore

    store = PersonaInstanceStore()
    instance = store.ensure_for_persona(_neko())
    assert not instance.default_chat_session_id and not instance.chat_head_home  # a fresh namespace's Neko

    root = _open_new_chat(capsys, instance.id)["session_id"]

    bound = store.get(instance.id)
    assert (bound.chat_head_kind, bound.chat_head_home) == (CHAT_HEAD_KIND_PER_PROFILE, str(heads.neko))
    assert (_sessions(heads.neko, root), _sessions(heads.base, root)) == (1, 0)

    payload = _send(capsys, instance.id, root)
    assert payload.get("error_kind") != "session_not_found", payload
    assert "admission reached the provider" in str(payload.get("blocker") or ""), payload

    model = _model_read(bound, root)["model"]
    assert model["effective_model"] == "gpt-test"


def test_positive_control_a_new_chat_of_a_bound_agent_stays_on_its_recorded_head(heads, capsys):
    """Same mint, one variable changed: the agent was bound before (its first chat already stamped the
    head), so the new chat lands on the recorded head exactly as ``resolve_instance_chat_scope`` says."""

    from agent_runtime.chat_session_scope import resolve_instance_chat_scope
    from agent_runtime.persona_assignments import PersonaInstanceStore

    store = PersonaInstanceStore()
    first = _open_new_chat(capsys, store.ensure_for_persona(_neko()).id)
    bound = store.get(first["persona_instance_id"])
    second = chat_open._cmd_persona_instance_open_new_chat(SimpleNamespace(
        persona_instance_id=bound.id, session_id=None, add_instance=False,
        idempotency_key="sw71-new-chat-2", title=None, select_session=True, client_scope=None, json=True,
    ), persona_id="neko", coordinator_scope=None)
    root = json.loads(capsys.readouterr().out)["session_id"]

    assert second == 0
    assert resolve_instance_chat_scope(store.get(bound.id)).head_home == heads.neko
    assert (_sessions(heads.neko, root), _sessions(heads.base, root)) == (1, 0)
