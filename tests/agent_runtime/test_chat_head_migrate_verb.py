"""RT-CHAT-HEAD-CH3-MOVE-VERB — ``persona chat-head migrate`` moves an agent's chats into its profile.

Plan: ``docs/agent-runtime-harness/planned/chat-head-per-profile-2026-10-26.md`` §2.3, §7.2 decision 8 (b).
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from agent_runtime.chat_head_migration import migrate_chat_heads
from agent_runtime.chat_session_scope import resolve_chat_session_scope
from agent_runtime.models import CHAT_HEAD_KIND_PER_PROFILE
from agent_runtime.persona_assignments import PersonaInstanceStore

INSTANCE_ID = "personainst_qa_agent_c0ffee00"
ROOT = "persona_chat_personainst_qa_agent_c0ffee00"
CHILD = "compressed_child_of_root"
OTHER = "persona_chat_of_someone_else"


@pytest.fixture
def heads(tmp_path, monkeypatch):
    """``HERMES_HEAD_HOME=profiles/base`` holds qa's legacy chats; qa runs in profile ``alice``."""

    from agent_runtime.config import roster
    from agent_runtime import profile_context
    from hermes_state import SessionDB

    root = tmp_path / ".hermes"
    store_root, base, alice = root / "agent-runtime", root / "profiles" / "base", root / "profiles" / "alice"
    for path in (store_root, base, alice):
        path.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("HERMES_AGENT_RUNTIME_ROOT", str(store_root))
    monkeypatch.setenv("HERMES_HOME", str(base))
    monkeypatch.setenv("HERMES_HEAD_HOME", str(base))
    from agent_runtime.models import AgentPersona
    persona = AgentPersona(id="qa", display_name="QA", role="qa", model=None, provider=None, api_mode=None, hermes_profile=None)
    monkeypatch.setattr(roster, "ensure_persisted_personas", lambda *a, **k: [persona])
    monkeypatch.setattr(profile_context, "profile_exists", lambda name: name == "alice")
    monkeypatch.setattr(profile_context, "get_profile_dir", lambda name: {"alice": alice}[name])

    db = SessionDB(db_path=base / "state.db")
    try:
        db.create_session(ROOT, "mission_control", model_config={"persona_instance_id": INSTANCE_ID})
        db.create_session(CHILD, "mission_control", parent_session_id=ROOT)
        db.create_session(OTHER, "mission_control", model_config={"persona_instance_id": "personainst_other"})
        for sid, count in ((ROOT, 3), (CHILD, 2), (OTHER, 1)):
            for n in range(count):
                db.append_message(sid, "user", f"{sid} message {n}")
    finally:
        db.close()
    # Bound while the persona inherited base (a legacy process record), then rebound to alice.
    PersonaInstanceStore().open_chat(persona_id="qa", session_id=ROOT, persona_instance_id=INSTANCE_ID)
    persona.hermes_profile = "alice"
    return SimpleNamespace(base=base, alice=alice, persona=persona)


def _counts(home) -> dict[str, int]:
    from hermes_state import SessionDB

    if not (home / "state.db").is_file():
        return {}
    db = SessionDB(db_path=home / "state.db", read_only=True)
    try:
        return {row["id"]: db.count_messages_all(row["id"]) for row in db._read_all("SELECT id FROM sessions", [])}
    finally:
        db.close()


def _row(report) -> dict:
    (row,) = [r for r in report["instances"] if r["instance_id"] == INSTANCE_ID]
    return row


def test_a_dry_run_reports_the_lineage_and_changes_nothing(heads):
    before = _counts(heads.base)

    report = migrate_chat_heads(instance_id=INSTANCE_ID)

    assert report["applied"] is False
    assert _row(report) == {"instance_id": INSTANCE_ID, "status": "planned", "target_home": str(heads.alice),
                                 "session_ids": [ROOT, CHILD], "messages": 5}
    assert _counts(heads.base) == before
    assert _counts(heads.alice) == {}
    assert PersonaInstanceStore().get(INSTANCE_ID).chat_head_kind != CHAT_HEAD_KIND_PER_PROFILE


def test_apply_moves_the_lineage_flips_the_record_and_deletes_from_base(heads):
    report = migrate_chat_heads(instance_id=INSTANCE_ID, apply=True)

    assert _row(report)["status"] == "moved"
    assert _counts(heads.alice) == {ROOT: 3, CHILD: 2}
    assert _counts(heads.base) == {OTHER: 1}
    instance = PersonaInstanceStore().get(INSTANCE_ID)
    assert (instance.chat_head_kind, instance.chat_head_home) == (CHAT_HEAD_KIND_PER_PROFILE, str(heads.alice))
    assert resolve_chat_session_scope(session_id=ROOT).head_home == heads.alice


def test_a_second_apply_reports_present_and_changes_nothing(heads):
    migrate_chat_heads(instance_id=INSTANCE_ID, apply=True)
    moved = (_counts(heads.base), _counts(heads.alice))

    report = migrate_chat_heads(instance_id=INSTANCE_ID, apply=True)

    assert _row(report)["status"] == "present"
    assert (_counts(heads.base), _counts(heads.alice)) == moved


def test_a_busy_chat_is_refused_and_nothing_moves(heads):
    from agent_runtime.persona_chat_continuity.lease import persona_chat_root_lease

    with persona_chat_root_lease(ROOT, observer_kind="test_turn"):
        report = migrate_chat_heads(instance_id=INSTANCE_ID, apply=True)

    assert (_row(report)["status"], _row(report)["reason"]) == ("refused", "chat_busy")
    assert report["ok"] is False
    assert _counts(heads.base)[ROOT] == 3
    assert _counts(heads.alice) == {}
    assert PersonaInstanceStore().get(INSTANCE_ID).chat_head_kind != CHAT_HEAD_KIND_PER_PROFILE


def test_an_unverified_copy_never_flips_and_never_deletes(heads, monkeypatch):
    from hermes_state import SessionDB

    monkeypatch.setattr(SessionDB, "import_moved_session", lambda self, payload, *, profile_name: "present")

    report = migrate_chat_heads(instance_id=INSTANCE_ID, apply=True)

    assert (_row(report)["status"], _row(report)["reason"]) == ("refused", "copy_unverified")
    assert _counts(heads.base)[ROOT] == 3
    assert PersonaInstanceStore().get(INSTANCE_ID).chat_head_kind != CHAT_HEAD_KIND_PER_PROFILE


def test_positive_control_a_persona_running_in_the_process_head_is_skipped(heads):
    heads.persona.hermes_profile = None

    report = migrate_chat_heads(instance_id=INSTANCE_ID, apply=True)

    assert (_row(report)["status"], _row(report)["reason"]) == ("skipped", "runs_in_process_head")
    assert _counts(heads.base)[ROOT] == 3


def test_the_cli_verb_is_dry_run_by_default(heads, capsys):
    from hermes_cli.harness_parts.persona.chat_head_commands import _cmd_persona_chat_head_migrate

    code = _cmd_persona_chat_head_migrate(SimpleNamespace(instance=INSTANCE_ID, apply=False, json=True))

    assert code == 0
    assert json.loads(capsys.readouterr().out)["applied"] is False
    assert _counts(heads.alice) == {}
