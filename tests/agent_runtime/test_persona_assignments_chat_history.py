"""Persona chat history projection, chat delete and the mission-chat transcript seams.

Split from one 5,169-line file so the per-file runner parallelises it
(FH-PREPUSH-TOUCHED-OVER-BUDGET-PERSONA-ASSIGNMENTS); shared helpers live in
``tests/agent_runtime/persona_assignments_helpers.py``.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from agent_runtime import paths
from agent_runtime.events import EventLog
from agent_runtime.mission_chat_turns import mission_chat_turn_record
from agent_runtime.persona_assignments import (
    PersonaInstanceStore,
    persona_instance_id_for,
    persona_instance_summary,
)
from agent_runtime.persona_chat_history import persona_chat_history_summary
from agent_runtime.snapshot import build_snapshot
from agent_runtime.store import RunStore
from hermes_cli.harness_parts.persona import (
    chat_delete,
    chat_history_writes,
    chat_open,
    chat_turn_message,
    lifecycle_commands,
)
from hermes_cli.harness_parts.persona.chat_turn_commit import run as commit_run
from tests.agent_runtime.persona_assignments_helpers import (
    _assignment_config,
    _FailingTranscriptDB,
    _TranscriptDB,
)

pytestmark = pytest.mark.usefixtures("persisted_persona_samples")


class _FakeSessionDB:
    def __init__(self, sessions, messages=None):
        self.sessions = sessions
        self.messages = messages or {}

    def close(self):
        return None

    def list_sessions_rich(self, **kwargs):
        return list(self.sessions)

    def get_session(self, session_id):
        for session in self.sessions:
            if session.get("id") == session_id:
                return dict(session)
        return None

    def get_messages(self, session_id):
        return list(self.messages.get(session_id, []))


def test_persona_chat_history_summary_projects_bound_sessions_redaction_safe(isolate_agent_runtime_root):
    store = PersonaInstanceStore()
    instance = store.open_chat(persona_id="dev", session_id="chat_old_123")

    rows = persona_chat_history_summary(
        persona_instances=[instance],
        session_db=_FakeSessionDB(
            [
                {
                    "id": "chat_old_123",
                    "title": "API_KEY=super-secret",
                    "preview": "Please inspect the proof packet.",
                    "message_count": 7,
                    "input_tokens": 1234,
                    "output_tokens": 56,
                    "cache_read_tokens": 9000,
                    "cache_write_tokens": 300,
                    "started_at": 10,
                    "last_active": 20,
                    "archived": 0,
                },
                {"id": "unbound", "title": "Should not leak"},
            ]
        ),
    )

    assert rows == [
        {
            "session_id": "chat_old_123",
            "persona_id": "dev",
            "persona_instance_id": "personainst_dev",
            "title": "Untitled persona chat",
            "last_message_preview": "Please inspect the proof packet.",
            "message_count": 7,
            "visible_message_count": 0,
            "created_at": "1970-01-01T00:00:10.000000Z",
            "updated_at": "1970-01-01T00:00:20.000000Z",
            "state": "open",
            "redaction_status": "redacted",
            "input_tokens": 1234,
            "output_tokens": 56,
            "total_tokens": 1290,
            "cache_read_tokens": 9000,
            "cache_write_tokens": 300,
            "cache_mode": "none",
            "cache_ttl_seconds": None,
            "cache_ttl_basis": None,
            "messages": [],
            "root_chat_session_id": "chat_old_123",
            "active_session_id": "chat_old_123",
            "runtime_state": "unknown",
            "last_runtime_transition": None,
            "runtime_observer_id": "external_cli",
            "runtime_observed_at": None,
            "continuation_depth": 0,
            "last_resumed_at": None,
        }
    ]


def test_persona_chat_history_parity_separates_the_bound_limit_from_lost_sessions(
    isolate_agent_runtime_root,
):
    """The directory's ``limit`` is a bound; ``session_not_in_db`` is a defect.

    Live 2026-07-25 the same envelope carried both (103 + 10) and the Launcher,
    reading only ``dropped``, showed a permanent amber "projection drops 113".
    The classification now travels WITH the envelope.
    """

    from agent_runtime.projection_accountant import ProjectionAccountant

    store = PersonaInstanceStore()
    newer = store.open_chat(persona_id="dev", session_id="chat_new")
    older = store.open_chat(persona_id="backend_dev", session_id="chat_old")
    ghost = store.open_chat(persona_id="qa", session_id="chat_ghost")
    accountant = ProjectionAccountant("persona_chat_history")

    rows = persona_chat_history_summary(
        persona_instances=[newer, older, ghost],
        session_db=_FakeSessionDB(
            [
                {"id": "chat_new", "title": "new", "started_at": 20},
                {"id": "chat_old", "title": "old", "started_at": 10},
            ]
        ),
        limit=1,
        accountant=accountant,
    )

    assert len(rows) == 1
    summary = accountant.summary()
    assert summary["reasons"]["limit"] == 1
    assert summary["reasons"]["session_not_in_db"] == 1
    # Only the deliberate bound is declared by-design; the orphaned binding is
    # a real anomaly an operator can act on (harness persona-instance reconcile).
    assert summary["by_design"] == ["limit"]


def test_persona_chat_history_emits_cache_policy_for_known_provider(isolate_agent_runtime_root):
    # A session whose effective model is an automatic-prefix provider must carry
    # the estimated warm-window policy so the Launcher can render an honest
    # (non-contractual) freshness indicator.
    store = PersonaInstanceStore()
    instance = store.open_chat(persona_id="dev", session_id="chat_codex_1")

    rows = persona_chat_history_summary(
        persona_instances=[instance],
        session_db=_FakeSessionDB(
            [
                {
                    "id": "chat_codex_1",
                    "title": "codex chat",
                    "message_count": 2,
                    "provider": "openai-codex",
                    "model": "gpt-5.6-luna",
                    "api_mode": "codex",
                    "started_at": 10,
                    "last_active": 20,
                }
            ]
        ),
    )

    assert rows[0]["cache_mode"] == "automatic_prefix"
    assert rows[0]["cache_ttl_basis"] == "estimated"
    assert rows[0]["cache_ttl_seconds"] == 300


def test_persona_chat_history_accounting_ignores_unrelated_session_sources(isolate_agent_runtime_root):
    from agent_runtime.projection_accountant import ProjectionAccountant

    store = PersonaInstanceStore()
    instance = store.open_chat(persona_id="dev", session_id="chat_bound_1")

    accountant = ProjectionAccountant("persona_chat_history")
    rows = persona_chat_history_summary(
        persona_instances=[instance],
        session_db=_FakeSessionDB(
            [
                {"id": "chat_bound_1", "title": "bound", "message_count": 1},
                # Unrelated SessionDB sources (cron/telegram/cli) can never
                # render as persona chat rows: out of scope, NOT drops.
                {"id": "cron_20260618", "source": "cron", "title": "cron run"},
                {"id": "tg_20260620", "source": "telegram", "title": "tg chat"},
                # A genuine persona-chat orphan stays a visible drop.
                {
                    "id": "chat_orphan_1",
                    "source": "agent_runtime_persona_chat",
                    "title": "orphan",
                },
            ]
        ),
        accountant=accountant,
    )

    assert [row["session_id"] for row in rows] == ["chat_bound_1"]
    summary = accountant.summary()
    assert summary["considered"] == 2
    assert summary["included"] == 1
    assert summary["dropped"] == 1
    assert summary["reasons"] == {"no_instance_match": 1}


def test_persona_chat_history_separates_a_retired_instance_from_a_lost_binding(
    isolate_agent_runtime_root,
):
    # HC-H2: the "projection drops" chip must count LOST data, not the residue of
    # the operator's own first-class retires. A retire archives the row and leaves
    # the chat session behind by design (history is never destroyed), so an
    # undifferentiated orphan count grew by one on every retire, forever — and
    # buried the drops that actually mean something. Three sessions, three
    # outcomes, one archive listing telling them apart.
    from agent_runtime.projection_accountant import ProjectionAccountant

    store = PersonaInstanceStore()
    # (a) bound to a live instance.
    live = store.open_chat(persona_id="dev", session_id="chat_live_1")
    # (b) bound to an instance the operator retired through the first-class verb:
    # the row exists ONLY in the archive now, and its chat session is the residue.
    retiring = store.add_instance(
        persona_id="qa",
        placement_id="scene_child_9_agent_2",
        display_name="QA (9)",
    )
    retired_session_id = retiring.session_id
    assert retired_session_id
    store.retire(retiring.id, reason="placement deleted")
    # (c) bound to an id that exists NOWHERE — live roster or archive. This is the
    # genuinely anomalous orphan, and it must stay counted.
    lost_instance_id = "personainst_never_placed_c30e16a4"

    accountant = ProjectionAccountant("persona_chat_history")
    rows = persona_chat_history_summary(
        persona_instances=[live],
        session_db=_FakeSessionDB(
            [
                {"id": "chat_live_1", "title": "live", "message_count": 1},
                {
                    "id": retired_session_id,
                    "source": "agent_runtime_persona_chat",
                    "title": "retired placement chat",
                    "model_config": {"persona_instance_id": retiring.id},
                },
                {
                    "id": "chat_lost_1",
                    "source": "agent_runtime_persona_chat",
                    "title": "lost binding",
                    "model_config": {"persona_instance_id": lost_instance_id},
                },
            ]
        ),
        accountant=accountant,
    )

    assert [row["session_id"] for row in rows] == ["chat_live_1"]
    summary = accountant.summary()
    assert summary["considered"] == 3
    assert summary["included"] == 1
    assert summary["dropped"] == 2
    # The whole stage in two lines: the retire is by-design lifecycle, the lost
    # binding is still an anomaly, and neither one absorbed the other.
    assert summary["reasons"] == {"instance_retired": 1, "no_instance_match": 1}
    assert summary["by_design"] == ["instance_retired"]
    # …and the codes are not merely present in the right counts, they are on the
    # right sessions: a mutant that swapped them keeps both tallies at 1.
    samples = {sample["entity_id"]: sample for sample in accountant.drop_samples()}
    assert samples[retired_session_id]["code"] == "instance_retired"
    assert samples[retired_session_id]["by_design"] is True
    assert samples[retired_session_id]["detail"] == retiring.id
    assert samples["chat_lost_1"]["code"] == "no_instance_match"
    assert samples["chat_lost_1"]["by_design"] is False


def test_retired_persona_instance_ids_lists_only_retirement_tombstones(
    isolate_agent_runtime_root,
):
    # The bulk listing HC-H2's projection reads must answer the same question the
    # per-id tombstone probe answers, not a wider one: only ``*_retire`` batches
    # are tombstones. A reconcile/prune archive row means something else entirely,
    # and reading it as "retired" would classify a live-lineage id's orphaned
    # session as by-design lifecycle.
    from agent_runtime import paths
    from agent_runtime.persona_assignments import retired_persona_instance_ids

    store = PersonaInstanceStore()
    retiring = store.add_instance(
        persona_id="dev",
        placement_id="scene_child_11_agent_2",
        display_name="Dev (11)",
    )
    store.retire(retiring.id, reason="placement deleted")
    reconcile_dir = paths.persona_instances_archive_dir() / "20260809T183345Z_reconcile"
    reconcile_dir.mkdir(parents=True, exist_ok=True)
    (reconcile_dir / "personainst_reconciled_only.json").write_text("{}", encoding="utf-8")

    ids = retired_persona_instance_ids()

    assert retiring.id in ids
    assert "personainst_reconciled_only" not in ids
    # The store is the discoverable door to the same listing.
    assert PersonaInstanceStore().retired_instance_ids() == ids


def test_persona_chat_history_summary_empty_bound_chat_is_safe_placeholder(isolate_agent_runtime_root):
    store = PersonaInstanceStore()
    instance = store.open_chat(persona_id="dev", session_id="chat_empty_123")

    rows = persona_chat_history_summary(
        persona_instances=[instance],
        session_db=_FakeSessionDB(
            [
                {
                    "id": "chat_empty_123",
                    "source": "agent_runtime_persona_chat",
                    "system_prompt": "Mission Control persona chat for dev",
                    "title": None,
                    "preview": None,
                    "message_count": 0,
                    "started_at": 100,
                    "last_active": 100,
                    "archived": 0,
                }
            ]
        ),
    )

    assert rows[0]["session_id"] == "chat_empty_123"
    assert rows[0]["last_message_preview"] == "No messages yet."
    assert rows[0]["message_count"] == 0
    assert rows[0]["redaction_status"] == "safe"


def test_persona_chat_history_hides_bound_session_deleted_from_session_db(isolate_agent_runtime_root):
    store = PersonaInstanceStore()
    instance = store.open_chat(persona_id="dev", session_id="deleted_chat_123")

    rows = persona_chat_history_summary(
        persona_instances=[instance],
        session_db=_FakeSessionDB([]),
    )

    assert rows == []


def test_persona_instance_update_profile_persists_runtime_overrides_only(isolate_agent_runtime_root):
    store = PersonaInstanceStore()
    instance = store.create_operator_chat(
        persona_id="profile_alice",
        display_name="Alice Agent",
        session_id="chat_alice",
    )

    updated = store.update_profile(
        instance.id,
        display_name="Alice Mission Lead",
        current_chat_goal="Keep the operator channel warm.",
        goal_id="task_123",
        skills=["agent-runtime-harness", "technical-writing", "technical-writing"],
    )

    assert updated.id == instance.id
    assert updated.persona_id == "profile_alice"
    assert updated.profile_id == "alice"
    assert updated.display_name == "Alice Mission Lead"
    assert updated.current_chat_goal == "Keep the operator channel warm."
    assert updated.goal_id == "task_123"
    assert updated.current_task_id is None  # RT-TASK-BOUND-UPDATE-GOAL-STAMP: the goal is not a task
    assert updated.skill_overrides == ["agent-runtime-harness", "technical-writing"]

    summary = persona_instance_summary(updated)
    assert summary["display_name"] == "Alice Mission Lead"
    assert summary["backing_profile"] == "alice"
    assert summary["current_chat_goal"] == "Keep the operator channel warm."
    assert summary["skills"] == ["agent-runtime-harness", "technical-writing"]
    assert summary["skill_overrides"] == ["agent-runtime-harness", "technical-writing"]


def test_persona_chat_history_summary_ignores_task_bound_worker_sessions(isolate_agent_runtime_root):
    from agent_runtime.models import PersonaInstance
    from agent_runtime.states import WorkerSessionState

    task_bound = PersonaInstance(
        id="personainst_dev",
        persona_id="dev",
        role="dev",
        display_name="Launcher Dev Agent",
        profile_id=None,
        runtime_root="runtime",
        state=WorkerSessionState.IDLE,
        mode="task_bound",
        session_id="worker_session_123",
    )

    rows = persona_chat_history_summary(
        persona_instances=[task_bound],
        session_db=_FakeSessionDB(
            [
                {
                    "id": "worker_session_123",
                    "title": None,
                    "preview": "# Agent Runtime Tick Context ## Task",
                    "message_count": 2,
                    "started_at": 10,
                    "last_active": 20,
                }
            ]
        ),
    )

    assert rows == []


def test_persona_chat_history_summary_projects_builtin_chat_source_when_worker_overwrites_binding(
    isolate_agent_runtime_root,
):
    from agent_runtime.models import PersonaInstance
    from agent_runtime.states import WorkerSessionState

    task_bound = PersonaInstance(
        id="personainst_qa",
        persona_id="qa",
        role="qa",
        display_name="QA Agent",
        profile_id=None,
        runtime_root="runtime",
        state=WorkerSessionState.IDLE,
        mode="task_bound",
        session_id="worker_session_qa",
    )

    rows = persona_chat_history_summary(
        persona_instances=[task_bound],
        session_db=_FakeSessionDB(
            [
                {
                    "id": "chat_qa_123",
                    "source": "agent_runtime_persona_chat",
                    "system_prompt": "Mission Control persona chat for qa",
                    "title": None,
                    "preview": "hi, what's your take on shipping fast?",
                    "message_count": 2,
                    "started_at": 100,
                    "last_active": 200,
                    "archived": 0,
                }
            ],
            messages={
                "chat_qa_123": [
                    {
                        "id": "msg_1",
                        "role": "user",
                        "content": "hi, what's your take on shipping fast?",
                    }
                ]
            },
        ),
    )

    assert rows[0]["session_id"] == "chat_qa_123"
    assert rows[0]["persona_id"] == "qa"
    assert rows[0]["persona_instance_id"] == "personainst_qa"
    assert rows[0]["title"] == "hi, what's your take on shipping fast?"
    assert rows[0]["messages"][0]["text"] == "hi, what's your take on shipping fast?"


def test_snapshot_preserves_open_chat_and_emits_history(monkeypatch, isolate_agent_runtime_root):
    import agent_runtime.persona_chat_history as history
    import agent_runtime.snapshot as snapshot_module
    from agent_runtime import chat_session_scope

    cfg = _assignment_config()
    monkeypatch.setattr("agent_runtime.snapshot.envelope.load_agent_runtime_config", lambda: cfg)
    monkeypatch.setattr("agent_runtime.snapshot.sections.load_agent_runtime_config", lambda: cfg)
    db = _FakeSessionDB(
        [
            {
                "id": "chat_old_123",
                "title": "Launcher Dev operator channel",
                "preview": "Continue the old chat safely.",
                "message_count": 3,
                "started_at": 100,
                "last_active": 200,
            }
        ],
        messages={
            "chat_old_123": [
                {
                    "id": "msg_1",
                    "role": "user",
                    "content": "Can you keep working from the old chat?",
                    "created_at": "2026-06-19T10:00:00Z",
                },
                {
                    "id": "msg_2",
                    "role": "assistant",
                    "content": "Yes. I will continue from this persona session.",
                    "created_at": "2026-06-19T10:01:00Z",
                },
            ]
        },
    )
    monkeypatch.setattr(chat_session_scope, "open_chat_session_db", lambda scope=None, **_access: db)
    monkeypatch.setattr(snapshot_module.details, "_default_persona_session_db", lambda: db)
    PersonaInstanceStore().open_chat(persona_id="dev", session_id="chat_old_123")

    snapshot = build_snapshot()
    by_instance = {item["persona_instance_id"]: item for item in list(snapshot["persona_instances"].values())}

    assert by_instance["personainst_dev"]["mode"] == "chat"
    assert by_instance["personainst_dev"]["session_id"] == "chat_old_123"
    # S2/S7-B: the frame emits the open chat's history as a recency POINTER — the
    # anchors (session/persona/instance ids, title, preview, count, timestamps,
    # state) survive; the heavy message tail is evicted and fetched on demand via
    # `harness persona chat history --session-id <id> --json` (the fetch path is
    # covered by test_snapshot_history_eviction). The open chat is still emitted —
    # as a pointer, never a silent absence.
    history = snapshot["persona_chat_history"]
    assert len(history) == 1
    pointer = history[0]
    assert pointer["session_id"] == "chat_old_123"
    assert pointer["persona_id"] == "dev"
    assert pointer["persona_instance_id"] == "personainst_dev"
    assert "kind" not in pointer and "live_mission" not in pointer  # RT-TASK-BOUND-WIRE-PRUNE
    assert pointer["title"] == "Launcher Dev operator channel"
    assert pointer["last_message_preview"] == "Continue the old chat safely."
    assert pointer["message_count"] == 3
    assert pointer["created_at"] == "1970-01-01T00:01:40.000000Z"
    assert pointer["updated_at"] == "1970-01-01T00:03:20.000000Z"
    assert pointer["state"] == "open"
    assert pointer["redaction_status"] == "safe"
    # The tail is gone from the frame; the eviction is flagged, never silent.
    assert pointer["messages"] == []
    assert pointer["messages_evicted"] is True
    assert not list(paths.persona_assignments_dir().glob("*.json"))
    assert RunStore().list_all() == []


def _mission_chat_test_args(client_message_id: str, *, stream: bool = False):
    return SimpleNamespace(
        persona_id="dev",
        persona_instance_id="personainst_dev",
        session_id="persona_chat_personainst_dev",
        task_id=None,
        goal_id=None,
        message="please answer",
        surface_prompt="",
        intent_hint="chat",
        requested_by="test",
        client_message_id=client_message_id,
        stream=stream,
        max_seconds=5.0,
        json=True,
    )


def test_mission_chat_never_forwards_retired_goal_opt_in(
    monkeypatch,
    capsys,
    isolate_agent_runtime_root,
):

    db = _TranscriptDB()
    seen = []

    class _ProviderSpy:
        def __init__(self, *args, **kwargs):
            pass

        def mission_chat_reply(self, persona, message, **kwargs):
            seen.append("allow_mission_goal" in kwargs)
            return SimpleNamespace(
                final_response="provider reply",
                input_tokens=1,
                output_tokens=2,
                total_tokens=3,
                raw={},
            )

    monkeypatch.setattr(chat_turn_message, "load_agent_runtime_config", _assignment_config)
    monkeypatch.setattr(chat_turn_message, "_default_persona_session_db", lambda: db)
    monkeypatch.setattr(commit_run, "GPTPersonaRuntime", _ProviderSpy)

    normal = _mission_chat_test_args("client_chat_only")
    assert chat_turn_message._cmd_mission_chat_message(normal) == 0
    capsys.readouterr()

    assert seen == [False]


@pytest.mark.parametrize("operation", ["session_create"])
def test_mission_chat_required_pre_model_transcript_failure_skips_provider(
    operation,
    monkeypatch,
    capsys,
    isolate_agent_runtime_root,
):

    provider_calls = []

    class _ProviderSpy:
        def __init__(self, *args, **kwargs):
            provider_calls.append("constructed")

        def mission_chat_reply(self, *args, **kwargs):
            provider_calls.append("called")
            raise AssertionError("provider must not run after transcript persistence failure")

    monkeypatch.setattr(chat_turn_message, "load_agent_runtime_config", _assignment_config)
    monkeypatch.setattr(
        chat_turn_message,
        "_default_persona_session_db",
        lambda: _FailingTranscriptDB(operation),
    )
    monkeypatch.setattr(commit_run, "GPTPersonaRuntime", _ProviderSpy)

    code = chat_turn_message._cmd_mission_chat_message(
        _mission_chat_test_args(f"client_pre_model_{operation}")
    )

    assert code == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert payload["execution_state"] == "failed"
    assert payload["persistence_operation"] == operation
    assert provider_calls == []


def test_mission_chat_session_db_acquisition_failure_is_typed_and_skips_provider(
    monkeypatch,
    capsys,
    isolate_agent_runtime_root,
):
    import hermes_state

    provider_calls = []

    def _fail_session_db(*args, **kwargs):
        raise OSError("simulated canonical DB open failure")

    class _ProviderSpy:
        def __init__(self, *args, **kwargs):
            provider_calls.append("constructed")

    monkeypatch.setattr(chat_turn_message, "load_agent_runtime_config", _assignment_config)
    monkeypatch.setattr(hermes_state, "SessionDB", _fail_session_db)
    monkeypatch.setattr(commit_run, "GPTPersonaRuntime", _ProviderSpy)

    code = chat_turn_message._cmd_mission_chat_message(
        _mission_chat_test_args("client_db_acquire_failure", stream=True)
    )

    assert code == 2
    frames = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert len(frames) == 1
    assert frames[0]["type"] == "chat.final"
    assert frames[0]["ok"] is False
    assert frames[0]["persistence_operation"] == "session_db_acquire"
    assert provider_calls == []


def test_mission_chat_fake_runtime_does_not_use_legacy_assistant_append(
    monkeypatch,
    capsys,
    isolate_agent_runtime_root,
):

    db = _FailingTranscriptDB("assistant_append")
    provider_calls = []

    class _ProviderSpy:
        def __init__(self, *args, **kwargs):
            provider_calls.append("constructed")

        def mission_chat_reply(self, persona, message, **kwargs):
            provider_calls.append("called")
            kwargs["stream_callback"]("provider reply")
            return SimpleNamespace(
                final_response="provider reply",
                input_tokens=1,
                output_tokens=2,
                total_tokens=3,
                raw={},
            )

    monkeypatch.setattr(chat_turn_message, "load_agent_runtime_config", _assignment_config)
    monkeypatch.setattr(chat_turn_message, "_default_persona_session_db", lambda: db)
    monkeypatch.setattr(commit_run, "GPTPersonaRuntime", _ProviderSpy)

    code = chat_turn_message._cmd_mission_chat_message(
        _mission_chat_test_args("client_assistant_db_failure", stream=True)
    )

    assert code == 0
    frames = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert provider_calls == ["constructed", "called"]
    assert frames[-1]["type"] == "chat.final"
    assert frames[-1]["ok"] is True
    terminal_frames = [frame for frame in frames if frame.get("type") == "turn.end"]
    assert terminal_frames
    assert {frame.get("state") for frame in terminal_frames} == {"completed"}
    record = mission_chat_turn_record(
        session_id="persona_chat_personainst_dev",
        client_message_id="client_assistant_db_failure",
    )
    assert record["state"] == "projected"


def test_persona_instance_create_persists_empty_operator_chat_history(
    monkeypatch, capsys, isolate_agent_runtime_root
):

    cfg = _assignment_config()
    db = _TranscriptDB()
    monkeypatch.setattr(lifecycle_commands, "load_agent_runtime_config", lambda: cfg)
    monkeypatch.setattr(lifecycle_commands, "_default_persona_session_db", lambda: db)

    def _args(display_name: str):
        return SimpleNamespace(
            persona_id="profile_reviewer",
            display_name=display_name,
            title=f"{display_name} chat",
            message="New operator chat opened. Wait for operator input.",
            requested_by="test",
            json=True,
            client_message_id=None,
            session_id=None,
            add_instance=False,
            placement_id=None,
        )

    assert lifecycle_commands._cmd_persona_instance_create(_args("Reviewer One")) == 0
    first_session_id = PersonaInstanceStore().get(
        persona_instance_id_for("profile_reviewer")
    ).session_id
    assert lifecycle_commands._cmd_persona_instance_create(_args("Reviewer Two")) == 0
    second_session_id = PersonaInstanceStore().get(
        persona_instance_id_for("profile_reviewer")
    ).session_id
    capsys.readouterr()

    assert first_session_id != second_session_id
    assert sorted(db.sessions) == sorted([first_session_id, second_session_id])

    rows = persona_chat_history_summary(
        persona_instances=PersonaInstanceStore().list_all(),
        session_db=db,
    )
    by_session = {row["session_id"]: row for row in rows}

    assert set(by_session) == {first_session_id, second_session_id}
    assert by_session[first_session_id]["persona_id"] == "profile_reviewer"
    assert by_session[first_session_id]["persona_instance_id"] == persona_instance_id_for(
        "profile_reviewer"
    )
    assert by_session[first_session_id]["last_message_preview"] == "No messages yet."
    assert by_session[first_session_id]["redaction_status"] == "safe"
    assert by_session[second_session_id]["last_message_preview"] == "No messages yet."
    assert by_session[second_session_id]["redaction_status"] == "safe"


def test_persona_chat_delete_removes_session_and_clears_binding(
    monkeypatch, capsys, isolate_agent_runtime_root
):

    cfg = _assignment_config()
    db = _TranscriptDB()
    monkeypatch.setattr(chat_open, "load_agent_runtime_config", lambda: cfg)
    monkeypatch.setattr(lifecycle_commands, "load_agent_runtime_config", lambda: cfg)
    monkeypatch.setattr(chat_delete, "_default_persona_session_db", lambda: db)
    monkeypatch.setattr(chat_open, "_default_persona_session_db", lambda: db)
    monkeypatch.setattr(lifecycle_commands, "_default_persona_session_db", lambda: db)

    store = PersonaInstanceStore()
    instance = store.create_operator_chat(
        persona_id="profile_reviewer",
        display_name="Reviewer",
    )
    db.create_session(instance.session_id, "agent_runtime_persona_chat")
    db.append_message(instance.session_id, "user", "delete this")

    code = chat_delete._cmd_persona_chat_delete(
        SimpleNamespace(
            session_id=instance.session_id,
            persona_id=instance.persona_id,
            persona_instance_id=instance.id,
            requested_by="test",
            json=True,
        )
    )

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["deleted_session"] is True
    assert payload["cleared_bindings"] == [instance.id]
    assert instance.session_id not in db.sessions
    updated = PersonaInstanceStore().get(instance.id)
    assert updated.session_id is None
    assert updated.mode == "configured"
    assert persona_chat_history_summary(persona_instances=[updated], session_db=db) == []


def test_persona_chat_delete_clears_stale_binding_when_session_already_missing(
    monkeypatch, capsys, isolate_agent_runtime_root
):

    cfg = _assignment_config()
    db = _TranscriptDB()
    monkeypatch.setattr(chat_open, "load_agent_runtime_config", lambda: cfg)
    monkeypatch.setattr(lifecycle_commands, "load_agent_runtime_config", lambda: cfg)
    monkeypatch.setattr(chat_delete, "_default_persona_session_db", lambda: db)
    monkeypatch.setattr(chat_open, "_default_persona_session_db", lambda: db)
    monkeypatch.setattr(lifecycle_commands, "_default_persona_session_db", lambda: db)

    store = PersonaInstanceStore()
    instance = store.open_chat(persona_id="dev", session_id="deleted_chat_123")

    code = chat_delete._cmd_persona_chat_delete(
        SimpleNamespace(
            session_id="deleted_chat_123",
            persona_id="dev",
            persona_instance_id=instance.id,
            requested_by="test",
            json=True,
        )
    )

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["deleted_session"] is False
    assert payload["cleared_bindings"] == [instance.id]
    assert PersonaInstanceStore().get(instance.id).session_id is None


def test_persona_chat_delete_unbinds_every_row_pointing_at_the_deleted_session(
    monkeypatch, capsys, isolate_agent_runtime_root
):
    """Delete is the moment the pointer becomes dangling — clear ALL of them.

    A drifted/sibling row holding the same session id used to survive the
    owner-filtered loop, and the projection could then only hide it and account
    a permanent ``session_not_in_db`` parity drop (live 2026-07-25: 10 of them).
    """

    cfg = _assignment_config()
    db = _TranscriptDB()
    monkeypatch.setattr(chat_open, "load_agent_runtime_config", lambda: cfg)
    monkeypatch.setattr(lifecycle_commands, "load_agent_runtime_config", lambda: cfg)
    monkeypatch.setattr(chat_delete, "_default_persona_session_db", lambda: db)
    monkeypatch.setattr(chat_open, "_default_persona_session_db", lambda: db)
    monkeypatch.setattr(lifecycle_commands, "_default_persona_session_db", lambda: db)

    store = PersonaInstanceStore()
    owner = store.create_operator_chat(persona_id="profile_reviewer", display_name="Reviewer")
    db.create_session(owner.session_id, "agent_runtime_persona_chat")

    sibling = store.open_chat(persona_id="qa", session_id="persona_chat_sibling_seed")
    sibling.default_chat_session_id = owner.session_id
    sibling.session_id = owner.session_id
    store.update(sibling)

    code = chat_delete._cmd_persona_chat_delete(
        SimpleNamespace(
            session_id=owner.session_id,
            persona_id=owner.persona_id,
            persona_instance_id=owner.id,
            requested_by="test",
            json=True,
        )
    )

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert sorted(payload["cleared_bindings"]) == sorted([owner.id, sibling.id])
    healed = PersonaInstanceStore()
    assert healed.get(owner.id).default_chat_session_id is None
    assert healed.get(sibling.id).default_chat_session_id is None
    assert healed.get(sibling.id).session_id is None
    # Store mutations always emit an event.
    cleared = [
        event
        for event in EventLog().tail(200)
        if getattr(event, "type", None) == "persona_instance.chat_binding_cleared"
    ]
    assert {event.payload["persona_instance_id"] for event in cleared} == {owner.id, sibling.id}
    assert {event.payload["reason"] for event in cleared} == {"chat_deleted"}


def test_persona_chat_delete_leaves_a_pointer_to_another_session_alone(
    monkeypatch, capsys, isolate_agent_runtime_root
):
    """Only the pointers naming THIS session are nulled.

    The old delete blanked ``session_id`` unconditionally, so deleting one chat
    could silently drop an unrelated live pointer.
    """

    cfg = _assignment_config()
    db = _TranscriptDB()
    monkeypatch.setattr(chat_open, "load_agent_runtime_config", lambda: cfg)
    monkeypatch.setattr(lifecycle_commands, "load_agent_runtime_config", lambda: cfg)
    monkeypatch.setattr(chat_delete, "_default_persona_session_db", lambda: db)
    monkeypatch.setattr(chat_open, "_default_persona_session_db", lambda: db)
    monkeypatch.setattr(lifecycle_commands, "_default_persona_session_db", lambda: db)

    store = PersonaInstanceStore()
    instance = store.create_operator_chat(persona_id="profile_reviewer", display_name="Reviewer")
    deleted_session = instance.default_chat_session_id
    db.create_session(deleted_session, "agent_runtime_persona_chat")
    instance.session_id = "persona_chat_other_live"
    store.update(instance)

    code = chat_delete._cmd_persona_chat_delete(
        SimpleNamespace(
            session_id=deleted_session,
            persona_id=instance.persona_id,
            persona_instance_id=instance.id,
            requested_by="test",
            json=True,
        )
    )

    assert code == 0
    json.loads(capsys.readouterr().out)
    updated = PersonaInstanceStore().get(instance.id)
    # The deleted session is gone from BOTH pointers, and the unrelated live
    # session survives (the v1 back-fill in PersonaInstance.__post_init__ then
    # re-derives the default pointer from it — the instance keeps its real chat).
    assert deleted_session not in {updated.default_chat_session_id, updated.session_id}
    assert updated.session_id == "persona_chat_other_live"  # untouched
    assert updated.default_chat_session_id == "persona_chat_other_live"
    assert updated.mode == "chat"  # still holds a chat pointer


def test_persona_chat_delete_reports_missing_without_silent_success(
    monkeypatch, capsys, isolate_agent_runtime_root
):

    cfg = _assignment_config()
    monkeypatch.setattr(chat_open, "load_agent_runtime_config", lambda: cfg)
    monkeypatch.setattr(lifecycle_commands, "load_agent_runtime_config", lambda: cfg)
    monkeypatch.setattr(chat_delete, "_default_persona_session_db", lambda: _TranscriptDB())
    monkeypatch.setattr(chat_open, "_default_persona_session_db", lambda: _TranscriptDB())
    monkeypatch.setattr(lifecycle_commands, "_default_persona_session_db", lambda: _TranscriptDB())

    code = chat_delete._cmd_persona_chat_delete(
        SimpleNamespace(
            session_id="missing_chat_123",
            persona_id="dev",
            persona_instance_id="personainst_dev",
            requested_by="test",
            json=True,
        )
    )

    assert code == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert payload["status"] == "not_found"
    assert payload["error"] == "persona chat session not found: missing_chat_123"


def test_persona_chat_delete_rejects_foreign_instance_before_mutation(
    monkeypatch, capsys, isolate_agent_runtime_root
):

    cfg = _assignment_config()
    db = _TranscriptDB()
    monkeypatch.setattr(chat_open, "load_agent_runtime_config", lambda: cfg)
    monkeypatch.setattr(lifecycle_commands, "load_agent_runtime_config", lambda: cfg)
    monkeypatch.setattr(chat_delete, "_default_persona_session_db", lambda: db)
    monkeypatch.setattr(chat_open, "_default_persona_session_db", lambda: db)
    monkeypatch.setattr(lifecycle_commands, "_default_persona_session_db", lambda: db)

    store = PersonaInstanceStore()
    owner = store.create_operator_chat(persona_id="dev", display_name="Owner")
    foreign = store.add_instance(
        persona_id="qa", placement_id="foreign-delete_agent_2", display_name="Foreign"
    )
    db.create_session(owner.session_id, "agent_runtime_persona_chat")
    db.append_message(owner.session_id, "user", "must survive")

    code = chat_delete._cmd_persona_chat_delete(
        SimpleNamespace(
            session_id=owner.session_id,
            persona_id=foreign.persona_id,
            persona_instance_id=foreign.id,
            requested_by="test",
            json=True,
        )
    )

    assert code == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["error_kind"] == "foreign_chat_session"
    assert db.get_session(owner.session_id) is not None
    assert PersonaInstanceStore().get(owner.id).session_id == owner.session_id


def test_persona_chat_transcript_records_operator_and_assistant_turn(isolate_agent_runtime_root):

    db = _TranscriptDB()
    session_id = "persona_chat_personainst_dev"
    db.create_session(session_id, "agent_runtime_persona_chat")
    chat_history_writes._append_persona_operator_turn(
        session_db=db,
        session_id=session_id,
        message="hi",
    )
    chat_history_writes._append_persona_assistant_text(
        session_db=db,
        session_id=session_id,
        text="Hey — what are we working on?\n\n- Scope\n- Proof",
    )

    assert [item["role"] for item in db.messages[session_id]] == [
        "user",
        "assistant",
    ]
    assert db.messages[session_id][0]["content"] == "hi"
    assert (
        db.messages[session_id][1]["content"]
        == "Hey — what are we working on?\n\n- Scope\n- Proof"
    )
