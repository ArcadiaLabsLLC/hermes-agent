"""RT-CHAT-HEAD-CH2-LADDER — a ``per_profile`` instance record outranks the env head.

Plan: ``docs/agent-runtime-harness/planned/chat-head-per-profile-2026-10-26.md``
§7.2 decisions 1, 2, 4 and 8's no-downgrade guard; test plan §7.4.
"""

from __future__ import annotations

import shutil
from types import SimpleNamespace

import pytest

from agent_runtime.chat_session_scope import (
    CHAT_HEAD_MISSING,
    ChatHeadSource,
    SessionDbAccess,
    chat_head_for,
    open_chat_session_db,
    resolve_chat_session_scope,
    resolve_instance_chat_scope,
)
from agent_runtime.models import CHAT_HEAD_KIND_PER_PROFILE, CHAT_HEAD_KIND_PROCESS
from agent_runtime.persona_assignments import PersonaInstanceStore

SESSION_ID = "persona_chat_personainst_qa_agent_c0ffee00"


@pytest.fixture
def heads(tmp_path, monkeypatch):
    """The launcher's layout: ``HERMES_HEAD_HOME=profiles/base``, a profile ``alice``."""

    root = tmp_path / ".hermes"
    store_root = root / "agent-runtime"
    base = root / "profiles" / "base"
    alice = root / "profiles" / "alice"
    for path in (store_root, base, alice):
        path.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("HERMES_AGENT_RUNTIME_ROOT", str(store_root))
    monkeypatch.setenv("HERMES_HOME", str(base))
    monkeypatch.setenv("HERMES_HEAD_HOME", str(base))
    return {"base": base, "alice": alice}


def _stamped(kind: str | None, home) -> tuple[PersonaInstanceStore, object]:
    store = PersonaInstanceStore()
    instance = store.open_chat(persona_id="qa", session_id=SESSION_ID)
    instance.chat_head_home = str(home)
    instance.chat_head_kind = kind
    return store, store.update(instance)


def test_a_per_profile_record_outranks_the_env_head_without_a_mismatch(heads):
    _stamped(CHAT_HEAD_KIND_PER_PROFILE, heads["alice"])

    scope = resolve_chat_session_scope(session_id=SESSION_ID)

    assert scope.head_home == heads["alice"]
    assert scope.source is ChatHeadSource.INSTANCE_RECORDED
    assert scope.mismatch is None
    assert scope.refusal is None


@pytest.mark.parametrize("kind", [CHAT_HEAD_KIND_PROCESS, None])
def test_positive_control_a_process_record_still_loses_to_the_env_head(heads, kind):
    """Same row, one variable changed: the kind. The env head must win again."""

    _stamped(kind, heads["alice"])

    scope = resolve_chat_session_scope(session_id=SESSION_ID)

    assert scope.head_home == heads["base"]
    assert scope.source is ChatHeadSource.ENV_HEAD_HOME
    assert scope.mismatch is not None  # today's disagreement, still surfaced


def test_a_per_profile_record_whose_home_is_gone_refuses_and_never_answers_base(heads):
    _stamped(CHAT_HEAD_KIND_PER_PROFILE, heads["alice"])
    shutil.rmtree(heads["alice"])

    scope = resolve_chat_session_scope(session_id=SESSION_ID)

    assert scope.refusal == CHAT_HEAD_MISSING
    assert scope.head_home == heads["alice"]
    assert open_chat_session_db(scope, access=SessionDbAccess.WRITE) is None
    assert not heads["alice"].exists()  # the refused write created nothing


def test_the_instance_door_gives_the_ladders_answer(heads):
    _, per_profile = _stamped(CHAT_HEAD_KIND_PER_PROFILE, heads["alice"])
    assert resolve_instance_chat_scope(per_profile).head_home == heads["alice"]

    per_profile.chat_head_kind = CHAT_HEAD_KIND_PROCESS
    process = resolve_instance_chat_scope(per_profile)
    assert process.head_home == heads["base"]
    assert process.source is ChatHeadSource.ENV_HEAD_HOME

    per_profile.chat_head_kind = CHAT_HEAD_KIND_PER_PROFILE
    shutil.rmtree(heads["alice"])
    assert resolve_instance_chat_scope(per_profile).refusal == CHAT_HEAD_MISSING


def test_the_turn_stamp_never_downgrades_a_per_profile_record(heads):
    store, _ = _stamped(CHAT_HEAD_KIND_PER_PROFILE, heads["alice"])

    reopened = store.open_chat(persona_id="qa", session_id=SESSION_ID)

    assert reopened.chat_head_home == str(heads["alice"])
    assert reopened.chat_head_kind == CHAT_HEAD_KIND_PER_PROFILE
    assert resolve_chat_session_scope(session_id=SESSION_ID).head_home == heads["alice"]


def test_positive_control_the_turn_stamp_still_corrects_a_process_record(heads):
    store, _ = _stamped(CHAT_HEAD_KIND_PROCESS, heads["alice"])

    reopened = store.open_chat(persona_id="qa", session_id=SESSION_ID)

    assert reopened.chat_head_home == str(heads["base"])


def test_chat_head_for_is_the_home_the_persona_runs_in(heads, monkeypatch):
    import agent_runtime.profile_context as profile_context

    monkeypatch.setattr(profile_context, "profile_exists", lambda name: name == "alice")
    monkeypatch.setattr(profile_context, "get_profile_dir", lambda name: heads[name])

    assert chat_head_for(SimpleNamespace(id="qa", hermes_profile="alice")) == heads["alice"]
    assert chat_head_for(SimpleNamespace(id="qa", hermes_profile=None)) == heads["base"]
    assert chat_head_for(SimpleNamespace(id="qa", hermes_profile="gone")) == heads["base"]
