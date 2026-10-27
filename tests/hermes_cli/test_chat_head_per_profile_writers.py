"""RT-CHAT-HEAD-CH2B-WRITERS — every per-conversation chat writer acquires the instance's head.

Plan: ``docs/agent-runtime-harness/planned/chat-head-per-profile-2026-10-26.md``
§7.2 decisions 5 and 7; test plan §7.4 (CH2B).
"""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent_runtime.models import CHAT_HEAD_KIND_PER_PROFILE, CHAT_HEAD_KIND_PROCESS
from hermes_cli.harness_parts.persona import chat_turn_message
from hermes_cli.harness_parts.persona.chat_turn_commit import run as commit_run

REPO = Path(__file__).resolve().parents[2]
BOUND_ROOT = "persona_chat_personainst_qa_0123456789ab"


class _ProviderReached(RuntimeError):
    pass


@pytest.fixture
def heads(tmp_path, monkeypatch):
    """The launcher's layout: ``HERMES_HEAD_HOME=profiles/base``, a profile ``alice``."""

    from agent_runtime.config import AgentRuntimeConfig
    from agent_runtime.models import AgentPersona
    from agent_runtime.store import AgentStore

    root = tmp_path / ".hermes"
    base, alice = root / "profiles" / "base", root / "profiles" / "alice"
    for path in (root / "agent-runtime", base, alice):
        path.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("HERMES_AGENT_RUNTIME_ROOT", str(root / "agent-runtime"))
    monkeypatch.setenv("HERMES_HOME", str(base))
    monkeypatch.setenv("HERMES_HEAD_HOME", str(base))
    AgentStore().save(AgentPersona(
        id="qa", display_name="QA Agent", role="qa", model="gpt-test",
        provider="openai-codex", api_mode="codex_responses", system_prompt_path="",
    ))

    class _Provider:
        def __init__(self, *args, **kwargs):
            pass

        def mission_chat_reply(self, *args, **kwargs):
            raise _ProviderReached("admission reached the provider")

    monkeypatch.setattr(chat_turn_message, "load_agent_runtime_config", lambda: AgentRuntimeConfig())
    monkeypatch.setattr(commit_run, "GPTPersonaRuntime", _Provider)
    return {"base": base, "alice": alice}


def _stamp(kind: str, home: Path):
    from agent_runtime.persona_assignments import PersonaInstanceStore

    store = PersonaInstanceStore()
    instance = store.open_chat(persona_id="qa", session_id=BOUND_ROOT)
    instance.chat_head_home = str(home)
    instance.chat_head_kind = kind
    return store.update(instance)


def _send(capsys, instance_id: str) -> dict:
    chat_turn_message._cmd_mission_chat_message(SimpleNamespace(
        persona_id="qa", persona_instance_id=instance_id, session_id=None, new_session=True,
        message="hello, which store am I in?", surface_prompt="", intent_hint="chat",
        requested_by="operator", client_message_id="ch2b-send", stream=False,
        max_seconds=5.0, json=True,
    ))
    return json.loads(capsys.readouterr().out)


def _rows(home: Path, root: str) -> tuple[int, int]:
    """``(sessions, messages)`` *home*'s ``state.db`` holds for *root*."""

    db = home / "state.db"
    if not db.is_file():
        return 0, 0
    with sqlite3.connect(db) as conn:
        sessions = conn.execute("SELECT COUNT(*) FROM sessions WHERE id = ?", (root,)).fetchone()[0]
        messages = conn.execute("SELECT COUNT(*) FROM messages WHERE session_id = ?", (root,)).fetchone()[0]
    return sessions, messages


def test_a_send_to_a_per_profile_instance_writes_its_own_profile_and_never_base(heads, capsys):
    instance = _stamp(CHAT_HEAD_KIND_PER_PROFILE, heads["alice"])

    payload = _send(capsys, instance.id)
    root = payload.get("root_chat_session_id") or payload.get("session_id")

    assert "admission reached the provider" in str(payload.get("blocker") or ""), payload
    assert _rows(heads["alice"], root)[0] == 1
    assert _rows(heads["base"], root) == (0, 0)


def test_positive_control_a_send_to_a_process_instance_writes_base(heads, capsys):
    """Same send, one variable changed: the record's kind. The process head must hold it."""

    instance = _stamp(CHAT_HEAD_KIND_PROCESS, heads["alice"])

    payload = _send(capsys, instance.id)
    root = payload.get("root_chat_session_id") or payload.get("session_id")

    assert "admission reached the provider" in str(payload.get("blocker") or ""), payload
    assert _rows(heads["base"], root)[0] == 1
    assert _rows(heads["alice"], root) == (0, 0)


def test_a_writer_for_a_per_profile_home_that_is_gone_refuses_and_writes_nothing(heads, capsys):
    import shutil

    from agent_runtime.mission_chat_outcome import ChatErrorKind

    instance = _stamp(CHAT_HEAD_KIND_PER_PROFILE, heads["alice"])
    shutil.rmtree(heads["alice"])

    payload = _send(capsys, instance.id)

    assert payload["error_kind"] == ChatErrorKind.CHAT_SESSION_DB_UNAVAILABLE
    assert payload["persistence_operation"] == "chat_head_missing"
    assert not heads["alice"].exists()
    assert not (heads["base"] / "state.db").exists()


#: The process acquisition, called with no scope. Per-conversation writers pass
#: it as ``process=`` to ``persona_session_db_for``; calling it bare is the
#: pre-CH2B shape (a negative walk: over-approximation is the safe direction).
_BARE_PROCESS_ACQUIRE = re.compile(r"(?<![\w.`])_?default_persona_session_db\(\)")
#: Modules where the process acquisition is the answer by design (plan §7.2
#: decision 5's "stay PROCESS" set holds none that call it; the definition does).
_PROCESS_BY_DESIGN = {
    "agent_runtime/persona_chat_durability.py",
    # The projection's PROCESS read, not a writer; the summary it feeds fans
    # out over the per_profile heads (chat_heads.per_profile_read_heads).
    "agent_runtime/snapshot/details.py",
}


def test_no_writer_calls_the_process_acquisition_bare():
    offenders = sorted(
        str(path.relative_to(REPO))
        for tree in ("agent_runtime", "hermes_cli", "gateway", "tools")
        for path in (REPO / tree).rglob("*.py")
        if _BARE_PROCESS_ACQUIRE.search(path.read_text(encoding="utf-8"))
        and str(path.relative_to(REPO)) not in _PROCESS_BY_DESIGN
    )
    assert offenders == []


def test_the_resident_actor_signature_names_the_head_so_a_flip_rebuilds_it(heads):
    """Flipping the record moves the reuse key — through the DEFAULT head resolver."""

    from agent_runtime.mission_chat_turn_context import mission_chat_runtime_signature_from_components

    instance = _stamp(CHAT_HEAD_KIND_PROCESS, heads["alice"])
    process = _components(instance)
    instance.chat_head_kind = CHAT_HEAD_KIND_PER_PROFILE
    per_profile = _components(instance)

    assert process["chat_head"] == str(heads["base"] / "state.db")
    assert per_profile["chat_head"] == str(heads["alice"] / "state.db")
    assert mission_chat_runtime_signature_from_components(process) != (
        mission_chat_runtime_signature_from_components(per_profile)
    )


def _components(instance) -> dict:
    """The signature's components with every seam but the head held constant."""

    import dataclasses

    from agent_runtime.mission_chat_turn_context import (
        DEFAULT_RESOLVERS,
        mission_chat_runtime_signature_components,
    )

    resolvers = dataclasses.replace(
        DEFAULT_RESOLVERS, tool_contract=lambda *a, **k: {},
        permission_state=lambda *a, **k: {}, store_root=lambda: "root",
    )
    persona = SimpleNamespace(id="qa", hermes_profile=None, api_mode=None)
    return mission_chat_runtime_signature_components(
        persona=persona, instance=instance, config={}, session_id=BOUND_ROOT,
        session_model_config={}, model_selection={}, workspace_agents_receipt=None,
        surface_prompt="", resolvers=resolvers,
    )
