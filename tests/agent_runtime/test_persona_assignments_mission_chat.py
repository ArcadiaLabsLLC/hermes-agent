"""Mission chat turns (model override, skills, persistence, replay) and profile-persona prompt observability.

Split from one 5,169-line file so the per-file runner parallelises it
(FH-PREPUSH-TOUCHED-OVER-BUDGET-PERSONA-ASSIGNMENTS); shared helpers live in
``tests/agent_runtime/persona_assignments_helpers.py``.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from agent_runtime import persona_chat_session as chat_session
from agent_runtime.events import EventLog
from agent_runtime.mission_chat_turns import (
    mission_chat_turn_record,
    persist_mission_chat_turn,
    transition_mission_chat_turn,
)
from agent_runtime.models import AgentPersona, PersonaInstance
from agent_runtime.persona_assignments import (
    PersonaInstanceStore,
    persona_instance_summary,
    persona_instance_tool_detail,
)
from agent_runtime.persona_chat_history import persona_chat_history_summary
from agent_runtime.states import WorkerSessionState
from agent_runtime.store import AgentStore
from agent_runtime.tool_permissions import default_permission_mode
from hermes_cli.harness_parts.persona import (
    chat_coordinator,
    chat_events,
    chat_open,
    chat_target,
    chat_tickets_commands,
    chat_turn_message,
    lifecycle_commands,
)
from hermes_cli.harness_parts.persona.chat_turn_commit import run as commit_run
from hermes_cli.harness_parts.persona.chat_turn_commit import settle as commit_settle
from tests.agent_runtime.persona_assignments_helpers import (
    REPO_ROOT,
    _assignment_config,
    _persona,
    _TranscriptDB,
)

pytestmark = pytest.mark.usefixtures("persisted_persona_samples")


def test_mission_chat_model_override_is_chat_scoped_and_does_not_mutate_persona(
    monkeypatch, capsys, isolate_agent_runtime_root
):

    cfg = _assignment_config()
    cfg.personas["dev"] = {
        "model": "gpt-default",
        "provider": "openai-codex",
        "api_mode": "codex_responses",
        "hermes_profile": "profile-dev",
    }
    monkeypatch.setattr(chat_turn_message, "load_agent_runtime_config", lambda: cfg)
    monkeypatch.setattr(commit_settle, "_maybe_auto_title_persona_chat", lambda **_kwargs: None)
    db = _TranscriptDB()
    monkeypatch.setattr(chat_turn_message, "_default_persona_session_db", lambda: db)
    # Base-profile foundation: only `base` is seeded into the store now, but this test
    # asserts the chat override does not mutate the *persisted* typed persona, so persist
    # `dev` explicitly (it stays resolvable via the dormant catalog either way).
    from agent_runtime.config import (
        persona_records_from_config as _persona_records_from_config,
    )
    from agent_runtime.store import AgentStore as _AgentStore
    _AgentStore().save(next(p for p in _persona_records_from_config(cfg) if p.id == "dev"))
    captured: dict = {}

    class _FakeRuntime:
        def __init__(self, *args, **kwargs):
            captured["runtime_kwargs"] = kwargs

        def mission_chat_reply(self, persona_arg, message, **kwargs):
            captured["persona_model"] = persona_arg.model
            captured["persona_provider"] = persona_arg.provider
            captured["reply_kwargs"] = kwargs
            return SimpleNamespace(
                final_response="override accepted",
                input_tokens=3,
                output_tokens=4,
                total_tokens=7,
                raw={
                    "model_input_observability": {
                        "kind": "redaction_safe_final_model_input",
                        "message_count": 1,
                        "messages": [],
                    }
                },
            )

    monkeypatch.setattr(commit_run, "GPTPersonaRuntime", _FakeRuntime)

    code = chat_turn_message._cmd_mission_chat_message(
        SimpleNamespace(
            persona_id="dev",
            persona_instance_id="personainst_dev",
            session_id="persona_chat_personainst_dev",
            task_id=None,
            goal_id=None,
            title="Operator message",
            message="use the override",
            provider="openrouter",
            model="anthropic/claude-sonnet-4",
            use_agent_default=False,
            surface_prompt="",
            intent_hint="chat",
            requested_by="test",
            client_message_id="client_override_1",
            stream=False,
            max_seconds=5.0,
            json=True,
        )
    )

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["model_selection"]["default_provider"] == "openai-codex"
    assert payload["model_selection"]["default_model"] == "gpt-default"
    assert payload["model_selection"]["effective_provider"] == "openrouter"
    assert payload["model_selection"]["effective_model"] == "anthropic/claude-sonnet-4"
    assert payload["model_selection"]["model_is_default"] is False
    assert captured["reply_kwargs"]["provider_override"] == "openrouter"
    assert captured["reply_kwargs"]["model_override"] == "anthropic/claude-sonnet-4"
    assert captured["persona_provider"] == "openai-codex"
    assert captured["persona_model"] == "gpt-default"
    stored_persona = AgentStore().get("dev")
    assert stored_persona.provider == "openai-codex"
    assert stored_persona.model == "gpt-default"

    stored_config = json.loads(db.sessions["persona_chat_personainst_dev"]["model_config"])
    override = stored_config["mission_control_chat_model_override"]
    assert override["provider"] == "openrouter"
    assert override["model"] == "anthropic/claude-sonnet-4"
    assert override["scope"] == "mission_control_chat_session"

    instance = PersonaInstanceStore().get("personainst_dev")
    rows = persona_chat_history_summary(persona_instances=[instance], session_db=db)
    assert rows[0]["chat_provider"] == "openrouter"
    assert rows[0]["chat_model"] == "anthropic/claude-sonnet-4"
    assert rows[0]["effective_provider"] == "openrouter"
    assert rows[0]["effective_model"] == "anthropic/claude-sonnet-4"
    assert rows[0]["chat_model_is_default"] is False

    code = chat_turn_message._cmd_mission_chat_message(
        SimpleNamespace(
            persona_id="dev",
            persona_instance_id="personainst_dev",
            session_id="persona_chat_personainst_dev",
            task_id=None,
            goal_id=None,
            title="Operator message",
            message="back to default",
            provider=None,
            model=None,
            use_agent_default=True,
            surface_prompt="",
            intent_hint="chat",
            requested_by="test",
            client_message_id="client_default_1",
            stream=False,
            max_seconds=5.0,
            json=True,
        )
    )

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["model_selection"]["effective_provider"] == "openai-codex"
    assert payload["model_selection"]["effective_model"] == "gpt-default"
    assert payload["model_selection"]["model_is_default"] is True
    stored_config = json.loads(db.sessions["persona_chat_personainst_dev"]["model_config"])
    assert "mission_control_chat_model_override" not in stored_config


def test_a_draft_chats_first_send_pins_its_model_to_the_new_session_only(
    monkeypatch, capsys, isolate_agent_runtime_root
):
    """Owner ruling 2026-10-15: a model picked in a DRAFT chat is held by the Launcher and
    rides the first send; hermes pins it to the session that draft minted. The next send
    (no model) keeps it, and the agent's other chat and its default are untouched."""

    from argparse import Namespace

    cfg = _assignment_config()
    cfg.personas["dev"] = {
        "model": "gpt-default",
        "provider": "openai-codex",
        "api_mode": "codex_responses",
        "hermes_profile": "profile-dev",
    }
    db = _TranscriptDB()
    for module in (chat_turn_message, chat_open, lifecycle_commands):
        monkeypatch.setattr(module, "load_agent_runtime_config", lambda: cfg)
        monkeypatch.setattr(module, "_default_persona_session_db", lambda: db)
    monkeypatch.setattr(commit_settle, "_maybe_auto_title_persona_chat", lambda **_kwargs: None)
    seen: list[str | None] = []

    class _FakeRuntime:
        def __init__(self, *args, **kwargs):
            pass

        def mission_chat_reply(self, persona_arg, message, **kwargs):
            seen.append(kwargs.get("model_override"))
            return SimpleNamespace(final_response="ok", input_tokens=1, output_tokens=1,
                                   total_tokens=2, raw={})

    monkeypatch.setattr(commit_run, "GPTPersonaRuntime", _FakeRuntime)
    instance = PersonaInstanceStore().create_operator_chat(persona_id="dev", display_name="Dev")
    first_thread = instance.session_id
    assert chat_open._cmd_persona_instance_open_chat(Namespace(
        persona_id="dev", persona_instance_id=instance.id, session_id=None, new_session=True,
        idempotency_key="draft-chat-1", add_instance=False, json=True,
    )) == 0
    draft_session = json.loads(capsys.readouterr().out)["session_id"]
    assert draft_session and draft_session != first_thread

    def send(client_message_id, model):
        return chat_turn_message._cmd_mission_chat_message(SimpleNamespace(
            persona_id="dev", persona_instance_id=instance.id, session_id=draft_session,
            task_id=None, goal_id=None, title=None, message="hello", provider=None,
            model=model, use_agent_default=False, surface_prompt="", intent_hint="chat",
            requested_by="test", client_message_id=client_message_id, stream=False,
            max_seconds=5.0, json=True,
        ))

    assert send("draft_first", "anthropic/claude-sonnet-4") == 0
    first = json.loads(capsys.readouterr().out)
    assert first["session_id"] == draft_session
    assert first["model_selection"]["effective_model"] == "anthropic/claude-sonnet-4"
    assert send("draft_second", None) == 0
    second = json.loads(capsys.readouterr().out)
    assert second["model_selection"]["effective_model"] == "anthropic/claude-sonnet-4"
    assert seen == ["anthropic/claude-sonnet-4", "anthropic/claude-sonnet-4"]
    pinned = json.loads(db.sessions[draft_session]["model_config"])
    assert pinned["mission_control_chat_model_override"]["model"] == "anthropic/claude-sonnet-4"
    other = db.sessions.get(first_thread) or {}
    assert "mission_control_chat_model_override" not in json.loads(other.get("model_config") or "{}")
    assert AgentStore().get("dev").model != "anthropic/claude-sonnet-4"


def test_mission_chat_model_override_rejects_bad_values_before_turn_is_written(
    monkeypatch, capsys, isolate_agent_runtime_root
):

    cfg = _assignment_config()
    monkeypatch.setattr(chat_turn_message, "load_agent_runtime_config", lambda: cfg)
    db = _TranscriptDB()
    monkeypatch.setattr(chat_turn_message, "_default_persona_session_db", lambda: db)

    code = chat_turn_message._cmd_mission_chat_message(
        SimpleNamespace(
            persona_id="dev",
            persona_instance_id="personainst_dev",
            session_id="persona_chat_personainst_dev",
            task_id=None,
            goal_id=None,
            title="Operator message",
            message="bad model please",
            provider="openrouter",
            model="bad model with spaces",
            use_agent_default=False,
            surface_prompt="",
            intent_hint="chat",
            requested_by="test",
            client_message_id="client_bad_model",
            stream=False,
            max_seconds=5.0,
            json=True,
        )
    )

    assert code == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert payload["error_kind"] == "invalid_chat_model_override"
    assert "Hermes profile defaults were not changed" in payload["next_expected"]
    assert db.messages["persona_chat_personainst_dev"] == []


def test_mission_chat_queues_skill_for_next_turn_once(
    monkeypatch, capsys, isolate_agent_runtime_root
):
    from agent_runtime.queued_skills import pending_skills_for_next_turn

    cfg = _assignment_config()
    monkeypatch.setattr(chat_turn_message, "load_agent_runtime_config", lambda: cfg)
    monkeypatch.setattr(commit_settle, "_maybe_auto_title_persona_chat", lambda **_kwargs: None)
    db = _TranscriptDB()
    monkeypatch.setattr(chat_turn_message, "_default_persona_session_db", lambda: db)

    from agent import skill_utils

    skill_root = isolate_agent_runtime_root / "skills"
    manifest = skill_root / "deep-audit" / "SKILL.md"
    manifest.parent.mkdir(parents=True)
    manifest.write_text("---\nname: deep-audit\n---\nbody\n", encoding="utf-8")
    monkeypatch.setattr(skill_utils, "get_all_skills_dirs", lambda: [skill_root])

    code = chat_coordinator._cmd_mission_chat_queue_skill(
        SimpleNamespace(
            persona_id="dev",
            persona_instance_id="personainst_dev",
            session_id="persona_chat_personainst_dev",
            skill="deep-audit",
            json=True,
        )
    )

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["queued_skills"] == ["deep-audit"]
    assert pending_skills_for_next_turn(
        persona_id="dev",
        session_id="persona_chat_personainst_dev",
    ) == ["deep-audit"]

    from agent import skill_commands

    monkeypatch.setattr(
        skill_commands,
        "build_preloaded_skills_prompt",
        lambda skills, task_id=None: ("PRELOADED SKILL PROMPT", list(skills), []),
    )
    captured_prompts: list[str | None] = []

    class _FakeRuntime:
        def __init__(self, *args, **kwargs):
            pass

        def mission_chat_reply(self, persona_arg, message, **kwargs):
            captured_prompts.append(kwargs.get("preloaded_skill_prompt"))
            return SimpleNamespace(
                final_response="skill queued",
                input_tokens=1,
                output_tokens=2,
                total_tokens=3,
                raw={
                    "model_input_observability": {
                        "kind": "redaction_safe_final_model_input",
                        "message_count": 1,
                        "messages": [],
                    }
                },
            )

    monkeypatch.setattr(commit_run, "GPTPersonaRuntime", _FakeRuntime)

    def _message_args(client_id: str):
        return SimpleNamespace(
            persona_id="dev",
            persona_instance_id="personainst_dev",
            session_id="persona_chat_personainst_dev",
            task_id=None,
            goal_id=None,
            title="Operator message",
            message=f"turn {client_id}",
            provider=None,
            model=None,
            use_agent_default=False,
            surface_prompt="",
            intent_hint="chat",
            requested_by="test",
            client_message_id=client_id,
            stream=False,
            max_seconds=5.0,
            json=True,
        )

    assert chat_turn_message._cmd_mission_chat_message(_message_args("client_skill_1")) == 0
    payload = json.loads(capsys.readouterr().out)
    # The preload reaches the runtime inside its structural envelope so the
    # transcript projection can strip it from the displayed operator text.
    from agent_runtime.runtime_hud import render_skill_preload_envelope

    expected_preload = render_skill_preload_envelope(
        skill_names=["deep-audit"],
        skill_preload_content="PRELOADED SKILL PROMPT",
    )
    assert captured_prompts == [expected_preload]
    assert "PRELOADED SKILL PROMPT" in expected_preload
    assert payload["queued_skills_loaded"] == ["deep-audit"]
    used = payload["prompt_observability"]["used_skills"]
    assert used[0]["name"] == "deep-audit"
    assert used[0]["source"] == "queued_next_turn_skill"
    assert used[0]["resolution_status"] == "resolved"
    assert used[0]["hash_tracked"] is True
    assert used[0]["content_hash"]
    assert pending_skills_for_next_turn(
        persona_id="dev",
        session_id="persona_chat_personainst_dev",
    ) == []

    assert chat_turn_message._cmd_mission_chat_message(_message_args("client_skill_2")) == 0
    json.loads(capsys.readouterr().out)
    # No skill queued on the second turn -> no envelope at all.
    assert captured_prompts == [expected_preload, ""]


def test_queue_skill_rejects_missing_skill_without_pending_state(
    monkeypatch, capsys, isolate_agent_runtime_root
):
    from agent_runtime.queued_skills import pending_skills_for_next_turn
    from tools import skills_tool

    monkeypatch.setattr(skills_tool, "find_all_skills", list)

    code = chat_coordinator._cmd_mission_chat_queue_skill(
        SimpleNamespace(
            persona_id="dev",
            persona_instance_id="personainst_dev",
            session_id="persona_chat_personainst_dev",
            skill="missing-skill",
            json=True,
        )
    )

    assert code == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert pending_skills_for_next_turn(
        persona_id="dev",
        session_id="persona_chat_personainst_dev",
    ) == []


def test_prompt_observability_reports_redaction_safe_available_skill_catalog(
    monkeypatch, isolate_agent_runtime_root
):
    from agent_runtime import prompt_observability
    from tools import skills_tool

    monkeypatch.setattr(
        skills_tool,
        "find_all_skills",
        lambda: [
            {
                "name": "deep-audit",
                "description": "Inspect the runtime deeply.",
                "category": "harness",
                "identifier": "harness/deep-audit",
            }
        ],
    )
    context = prompt_observability.mission_chat_prompt_observability(
        persona=_persona("dev"),
        session_id="persona_chat_personainst_dev",
    )

    skill = context["available_skills"][0]
    assert skill["name"] == "deep-audit"
    assert skill["status"] == "available"
    assert skill["load_state"] == "catalog_only"
    assert skill["resolution_status"] == "missing"
    assert skill["loadable"] is False
    assert skill["hash_tracked"] is False
    assert skill["content_hash"] is None
    assert skill["category"] == "harness"
    assert skill["description"] == "Inspect the runtime deeply."
    assert "content" not in skill
    # C1 record-once (2026-07-17): the `skills_catalog` alias key is retired —
    # the row carries ONE canonical copy (`available_skills`), no compat
    # emission (ruling 0).
    assert "skills_catalog" not in context


def test_chat_protocol_v2_emitter_can_suppress_frames_while_accumulating(capsys):

    updates = []
    emitter = chat_events._ChatProtocolV2Emitter(
        turn_id="turn_1",
        client_message_id="client_1",
        emit_frames=False,
        on_update=lambda item: updates.append(list(item.elements)),
    )

    emitter.delta("He")
    emitter.delta("llo")
    emitter.progress(
        {
            "type": "run.tool.started",
            "tool_name": "terminal",
            "summary": "run tests",
        }
    )
    emitter.progress(
        {
            "type": "run.tool.finished",
            "tool_name": "terminal",
            "status": "ok",
            "output": "passed",
        }
    )
    emitter.finish(state="completed")

    assert capsys.readouterr().out == ""
    assert updates
    assert emitter.elements[0]["kind"] == "segment"
    assert emitter.elements[0]["text"] == "Hello"
    assert emitter.elements[1]["kind"] == "tool"
    assert emitter.elements[1]["state"] == "finished"


def test_mission_chat_non_stream_persists_completed_turn_and_prints_one_json(
    monkeypatch,
    capsys,
    isolate_agent_runtime_root,
):

    cfg = _assignment_config()
    db = _TranscriptDB()
    monkeypatch.setattr(chat_turn_message, "load_agent_runtime_config", lambda: cfg)
    monkeypatch.setattr(chat_turn_message, "_default_persona_session_db", lambda: db)
    monkeypatch.setattr(commit_settle, "_maybe_auto_title_persona_chat", lambda **_kwargs: None)

    class _FakeRuntime:
        def __init__(self, *args, **kwargs):
            pass

        def mission_chat_reply(self, persona, message, **kwargs):
            kwargs["trace_callback"](
                {
                    "type": "run.tool.started",
                    "tool_name": "terminal",
                    "summary": "run focused tests",
                }
            )
            kwargs["trace_callback"](
                {
                    "type": "run.tool.finished",
                    "tool_name": "terminal",
                    "status": "ok",
                    "output": "passed",
                }
            )
            return SimpleNamespace(
                final_response="Done.",
                input_tokens=1,
                output_tokens=2,
                total_tokens=3,
                api_calls=1,
                model="gpt-test",
                raw={},
            )

    monkeypatch.setattr(commit_run, "GPTPersonaRuntime", _FakeRuntime)

    code = chat_turn_message._cmd_mission_chat_message(
        SimpleNamespace(
            persona_id="dev",
            persona_instance_id="personainst_dev",
            session_id="persona_chat_personainst_dev",
            task_id=None,
            goal_id=None,
            message="please run it",
            surface_prompt="",
            intent_hint="chat",
            requested_by="test",
            client_message_id="client_durable_1",
            stream=False,
            max_seconds=5.0,
            json=True,
        )
    )

    assert code == 0
    stdout = capsys.readouterr().out
    # Protocol-v2 frames serialize compactly (separators=(",", ":")); the final
    # payload is indented, so the compact form only ever matches a leaked frame.
    assert '"type":"turn.start"' not in stdout
    assert '"type":"tool.started"' not in stdout
    payload = json.loads(stdout)
    assert payload["ok"] is True
    assert payload["protocol_version"] is None
    record = mission_chat_turn_record(
        session_id="persona_chat_personainst_dev",
        client_message_id="client_durable_1",
    )
    assert record["state"] == "projected"
    assert [item["kind"] for item in record["elements"]] == ["tool"]
    assert record["elements"][0]["state"] == "finished"


def test_mission_chat_post_boundary_failure_marks_outcome_unknown(monkeypatch, capsys, isolate_agent_runtime_root):

    cfg = _assignment_config()
    db = _TranscriptDB()
    monkeypatch.setattr(chat_turn_message, "load_agent_runtime_config", lambda: cfg)
    monkeypatch.setattr(chat_turn_message, "_default_persona_session_db", lambda: db)

    class _FakeRuntime:
        def __init__(self, *args, **kwargs):
            pass

        def mission_chat_reply(self, persona, message, **kwargs):
            # The request LEFT the process (the runner's agent-ready handoff),
            # then its answer was lost: that is what makes the outcome unknown.
            # A raise before this callback is `provider_unavailable` (D2.02).
            kwargs["agent_ready_callback"](object())
            raise RuntimeError("provider unavailable")

    monkeypatch.setattr(commit_run, "GPTPersonaRuntime", _FakeRuntime)

    code = chat_turn_message._cmd_mission_chat_message(
        SimpleNamespace(
            persona_id="dev",
            persona_instance_id="personainst_dev",
            session_id="persona_chat_personainst_dev",
            task_id=None,
            goal_id=None,
            message="please run it",
            surface_prompt="",
            intent_hint="chat",
            requested_by="test",
            client_message_id="client_failed_1",
            stream=False,
            max_seconds=5.0,
            json=True,
        )
    )

    assert code == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert payload["error_kind"] == "chat_turn_outcome_unknown"
    assert payload["root_chat_session_id"] == "persona_chat_personainst_dev"
    assert payload["client_message_id"] == "client_failed_1"
    assert payload["turn_id"] == "client_failed_1"
    record = mission_chat_turn_record(
        session_id="persona_chat_personainst_dev",
        client_message_id="client_failed_1",
    )
    assert record["state"] == "outcome_unknown"


def test_mission_chat_retry_recovers_native_reply_before_outcome_unknown(
    monkeypatch, capsys, isolate_agent_runtime_root
):

    cfg = _assignment_config()
    db = _TranscriptDB()
    monkeypatch.setattr(chat_turn_message, "load_agent_runtime_config", lambda: cfg)
    monkeypatch.setattr(chat_turn_message, "_default_persona_session_db", lambda: db)
    instance = PersonaInstanceStore().open_chat(
        persona_id="dev", session_id="persona_chat_personainst_dev"
    )
    db.create_session(instance.session_id, "agent_runtime_persona_chat")
    db.append_message(
        instance.session_id,
        "user",
        "recover me",
        platform_message_id="client_recover_native",
    )
    db.append_message(
        instance.session_id,
        "assistant",
        "Native reply already committed.",
        platform_message_id="client_recover_native",
    )
    transition_mission_chat_turn(
        session_id=instance.session_id,
        client_message_id="client_recover_native",
        turn_id="client_recover_native",
        state="pending",
    )
    transition_mission_chat_turn(
        session_id=instance.session_id,
        client_message_id="client_recover_native",
        turn_id="client_recover_native",
        state="executing",
        metadata={"provider_submitted": True},
    )

    class _MustNotRun:
        def __init__(self, *args, **kwargs):
            raise AssertionError("provider must not be called during native recovery")

    monkeypatch.setattr(commit_run, "GPTPersonaRuntime", _MustNotRun)
    code = chat_turn_message._cmd_mission_chat_message(
        SimpleNamespace(
            persona_id="dev",
            persona_instance_id=instance.id,
            session_id=instance.session_id,
            task_id=None,
            goal_id=None,
            message="recover me",
            surface_prompt="",
            intent_hint="chat",
            requested_by="test",
            client_message_id="client_recover_native",
            stream=False,
            max_seconds=5.0,
            json=True,
        )
    )

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["reply"] == "Native reply already committed."
    assert payload["idempotent_replay"] is True
    assert mission_chat_turn_record(
        session_id=instance.session_id,
        client_message_id="client_recover_native",
    )["state"] == "projected"
    projected = [
        event
        for _, event in EventLog().iter_from_offset(0)
        if event.type == "persona_chat.projected"
        and event.payload.get("client_message_id") == "client_recover_native"
    ]
    assert len(projected) == 1
    assert projected[0].payload["persona_instance_id"] == instance.id


def test_mission_chat_turn_resolve_requires_exact_owner_and_records_abandon(
    monkeypatch, capsys, isolate_agent_runtime_root
):

    db = _TranscriptDB()
    from agent_runtime.chat_verbs import turn_resolve as turn_resolve_verb

    monkeypatch.setattr(turn_resolve_verb, "_default_persona_session_db", lambda: db)
    owner = PersonaInstanceStore().open_chat(
        persona_id="dev", session_id="persona_chat_personainst_dev"
    )
    foreign = PersonaInstanceStore().add_instance(
        persona_id="qa", placement_id="foreign-placement_agent_2"
    )
    db.create_session(
        owner.session_id,
        "agent_runtime_persona_chat",
        model_config=json.dumps(
            {
                "source": "agent_runtime_persona_chat",
                "persona_instance_id": owner.id,
            }
        ),
    )
    for state in ("pending", "executing", "outcome_unknown"):
        transition_mission_chat_turn(
            session_id=owner.session_id,
            client_message_id="client_ambiguous",
            turn_id="client_ambiguous",
            state=state,
        )

    bad_code = chat_tickets_commands._cmd_mission_chat_turn_resolve(
        SimpleNamespace(
            session_id=owner.session_id,
            client_message_id="client_ambiguous",
            turn_id="client_ambiguous",
            action="abandon",
            persona_instance_id=foreign.id,
            reason="wrong owner",
            json=True,
        )
    )
    bad = json.loads(capsys.readouterr().out)
    assert bad_code == 2
    assert bad["error_kind"] == "foreign_chat_session"
    assert mission_chat_turn_record(
        session_id=owner.session_id, client_message_id="client_ambiguous"
    )["state"] == "outcome_unknown"

    code = chat_tickets_commands._cmd_mission_chat_turn_resolve(
        SimpleNamespace(
            session_id=owner.session_id,
            client_message_id="client_ambiguous",
            turn_id="client_ambiguous",
            action="abandon",
            persona_instance_id=owner.id,
            reason="operator confirmed unknown outcome",
            json=True,
        )
    )
    payload = json.loads(capsys.readouterr().out)
    record = mission_chat_turn_record(
        session_id=owner.session_id, client_message_id="client_ambiguous"
    )
    assert code == 0
    assert payload["journal_state"] == "abandoned"
    assert record["state"] == "abandoned"
    assert record["resolution_actor"] == owner.id
    assert record["resolution_reason"] == "operator confirmed unknown outcome"


def test_mission_chat_new_turn_interrupts_prior_running_turn(
    monkeypatch,
    capsys,
    isolate_agent_runtime_root,
):

    cfg = _assignment_config()
    db = _TranscriptDB()
    monkeypatch.setattr(chat_turn_message, "load_agent_runtime_config", lambda: cfg)
    monkeypatch.setattr(chat_turn_message, "_default_persona_session_db", lambda: db)
    monkeypatch.setattr(commit_settle, "_maybe_auto_title_persona_chat", lambda **_kwargs: None)
    persist_mission_chat_turn(
        session_id="persona_chat_personainst_dev",
        client_message_id="client_stale",
        turn_id="turn_stale",
        elements=[],
        state="running",
    )

    class _FakeRuntime:
        def __init__(self, *args, **kwargs):
            pass

        def mission_chat_reply(self, persona, message, **kwargs):
            return SimpleNamespace(
                final_response="Fresh turn.",
                input_tokens=1,
                output_tokens=2,
                total_tokens=3,
                api_calls=1,
                model="gpt-test",
                raw={},
            )

    monkeypatch.setattr(commit_run, "GPTPersonaRuntime", _FakeRuntime)

    code = chat_turn_message._cmd_mission_chat_message(
        SimpleNamespace(
            persona_id="dev",
            persona_instance_id="personainst_dev",
            session_id="persona_chat_personainst_dev",
            task_id=None,
            goal_id=None,
            message="new one",
            surface_prompt="",
            intent_hint="chat",
            requested_by="test",
            client_message_id="client_fresh",
            stream=False,
            max_seconds=5.0,
            json=True,
        )
    )

    assert code == 0
    json.loads(capsys.readouterr().out)
    assert mission_chat_turn_record(
        session_id="persona_chat_personainst_dev",
        client_message_id="client_stale",
    )["state"] == "interrupted"
    assert mission_chat_turn_record(
        session_id="persona_chat_personainst_dev",
        client_message_id="client_fresh",
    )["state"] == "projected"


def test_mission_chat_post_native_projection_crash_stays_repairable(
    monkeypatch,
    capsys,
    isolate_agent_runtime_root,
):
    """W4: a crash AFTER the provider replied (transcript/bookkeeping steps)
    must persist a terminal `failed` state — never strand `running` — and the
    stdout contract (exactly one JSON object) must hold."""

    cfg = _assignment_config()
    db = _TranscriptDB()
    monkeypatch.setattr(chat_turn_message, "load_agent_runtime_config", lambda: cfg)
    monkeypatch.setattr(chat_turn_message, "_default_persona_session_db", lambda: db)

    # The native lane no longer calls _update_persona_chat_token_counts (the
    # per-call runtime writes are its sole usage authority - see the
    # single-writer guard in test_mission_chat_usage_single_writer.py), so the
    # post-native crash is injected at the lane's own fault seam instead.
    monkeypatch.setenv("HERMES_PERSONA_CHAT_FAULT_INJECTION", "after_native_commit")

    class _FakeRuntime:
        def __init__(self, *args, **kwargs):
            pass

        def mission_chat_reply(self, persona, message, **kwargs):
            return SimpleNamespace(
                final_response="The reply that must not vanish.",
                input_tokens=1,
                output_tokens=2,
                total_tokens=3,
                api_calls=1,
                model="gpt-test",
                raw={},
            )

    monkeypatch.setattr(commit_run, "GPTPersonaRuntime", _FakeRuntime)

    code = chat_turn_message._cmd_mission_chat_message(
        SimpleNamespace(
            persona_id="dev",
            persona_instance_id="personainst_dev",
            session_id="persona_chat_personainst_dev",
            task_id=None,
            goal_id=None,
            message="please answer",
            surface_prompt="",
            intent_hint="chat",
            requested_by="test",
            client_message_id="client_post_crash",
            stream=False,
            max_seconds=5.0,
            json=True,
        )
    )

    assert code == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert payload["error_kind"] == "chat_projection_incomplete"
    assert payload["reply"] == "The reply that must not vanish."
    assert "injected persona chat fault at after_native_commit" in payload["blocker"]
    record = mission_chat_turn_record(
        session_id="persona_chat_personainst_dev",
        client_message_id="client_post_crash",
    )
    assert record["state"] == "native_committed"


def test_mission_chat_success_persist_sequence_has_single_terminal_write(
    monkeypatch,
    capsys,
    isolate_agent_runtime_root,
):
    """W5: one write-ahead, one on_update per tool event, ONE terminal write.
    finish() must not sneak an extra `running` persist around the terminal."""

    cfg = _assignment_config()
    db = _TranscriptDB()
    monkeypatch.setattr(chat_turn_message, "load_agent_runtime_config", lambda: cfg)
    monkeypatch.setattr(chat_turn_message, "_default_persona_session_db", lambda: db)
    monkeypatch.setattr(commit_settle, "_maybe_auto_title_persona_chat", lambda **_kwargs: None)

    recorded: list[tuple[str | None, bool]] = []
    real_persist = commit_run.persist_mission_chat_turn

    def _recording_persist(**kwargs):
        recorded.append((kwargs.get("state"), bool(kwargs.get("write_ahead"))))
        return real_persist(**kwargs)

    monkeypatch.setattr(commit_run, "persist_mission_chat_turn", _recording_persist)

    class _FakeRuntime:
        def __init__(self, *args, **kwargs):
            pass

        def mission_chat_reply(self, persona, message, **kwargs):
            kwargs["trace_callback"](
                {"type": "run.tool.started", "tool_name": "terminal", "summary": "run"}
            )
            kwargs["trace_callback"](
                {"type": "run.tool.finished", "tool_name": "terminal", "status": "ok"}
            )
            return SimpleNamespace(
                final_response="Done.",
                input_tokens=1,
                output_tokens=2,
                total_tokens=3,
                api_calls=1,
                model="gpt-test",
                raw={},
            )

    monkeypatch.setattr(commit_run, "GPTPersonaRuntime", _FakeRuntime)

    code = chat_turn_message._cmd_mission_chat_message(
        SimpleNamespace(
            persona_id="dev",
            persona_instance_id="personainst_dev",
            session_id="persona_chat_personainst_dev",
            task_id=None,
            goal_id=None,
            message="run it",
            surface_prompt="",
            intent_hint="chat",
            requested_by="test",
            client_message_id="client_sequence",
            stream=False,
            max_seconds=5.0,
            json=True,
        )
    )

    assert code == 0
    json.loads(capsys.readouterr().out)
    assert recorded == [(None, False), (None, False)]
    assert mission_chat_turn_record(
        session_id="persona_chat_personainst_dev",
        client_message_id="client_sequence",
    )["state"] == "projected"


def test_mission_chat_message_replays_duplicate_client_message_id(
    monkeypatch,
    capsys,
    isolate_agent_runtime_root,
):

    cfg = _assignment_config()
    db = _TranscriptDB()
    calls = {"count": 0}
    monkeypatch.setattr(chat_turn_message, "load_agent_runtime_config", lambda: cfg)
    monkeypatch.setattr(chat_turn_message, "_default_persona_session_db", lambda: db)

    def _title(**kwargs):
        kwargs["session_db"].set_session_title(
            kwargs["session_id"], "Mission Chat"
        )

    monkeypatch.setattr(commit_settle, "_maybe_auto_title_persona_chat", _title)

    class _FakeRuntime:
        def __init__(self, *args, **kwargs):
            pass

        def mission_chat_reply(self, persona, message, **kwargs):
            calls["count"] += 1
            return SimpleNamespace(
                final_response="Recovered canonical reply.",
                input_tokens=1,
                output_tokens=2,
                total_tokens=3,
                api_calls=1,
                model="gpt-test",
                raw={},
            )

    monkeypatch.setattr(commit_run, "GPTPersonaRuntime", _FakeRuntime)

    def _args():
        return SimpleNamespace(
            persona_id="dev",
            persona_instance_id="personainst_dev",
            session_id="persona_chat_personainst_dev",
            task_id=None,
            goal_id=None,
            message="hi",
            surface_prompt="",
            intent_hint="chat",
            requested_by="test",
            client_message_id="client_dup_1",
            stream=False,
            max_seconds=5.0,
            json=True,
        )

    assert chat_turn_message._cmd_mission_chat_message(_args()) == 0
    first = json.loads(capsys.readouterr().out)
    assert first.get("idempotent_replay") is not True

    assert chat_turn_message._cmd_mission_chat_message(_args()) == 0
    replay = json.loads(capsys.readouterr().out)

    assert calls["count"] == 1
    assert db.messages["persona_chat_personainst_dev"] == []
    assert replay["idempotent_replay"] is True
    assert replay["client_message_id"] == "client_dup_1"
    assert replay["reply"] == "Recovered canonical reply."
    record = mission_chat_turn_record(
        session_id="persona_chat_personainst_dev",
        client_message_id="client_dup_1",
    )
    assert record["projection_event_emitted"] is True
    projected = [
        event
        for _, event in EventLog().iter_from_offset(0)
        if event.type == "persona_chat.projected"
        and event.payload.get("client_message_id") == "client_dup_1"
    ]
    assert len(projected) == 1
    assert projected[0].payload["change_kind"] == "projection_committed"
    metadata_events = [
        event
        for _, event in EventLog().iter_from_offset(0)
        if event.type == "persona_chat.metadata_updated"
        and event.payload.get("root_chat_session_id")
        == "persona_chat_personainst_dev"
    ]
    assert len(metadata_events) == 1
    assert metadata_events[0].payload["change_kind"] == "auto_title_updated"


def test_mission_chat_message_generates_client_message_id_when_missing(
    monkeypatch,
    capsys,
    isolate_agent_runtime_root,
):

    cfg = _assignment_config()
    db = _TranscriptDB()
    captured = {}
    monkeypatch.setattr(chat_turn_message, "load_agent_runtime_config", lambda: cfg)
    monkeypatch.setattr(chat_turn_message, "_default_persona_session_db", lambda: db)
    monkeypatch.setattr(
        "agent.title_generator.generate_title",
        lambda user_message, assistant_response, **kwargs: "Mission Chat",
    )

    class _FakeRuntime:
        def __init__(self, *args, **kwargs):
            pass

        def mission_chat_reply(self, persona, message, **kwargs):
            captured["turn_id"] = kwargs.get("turn_id")
            return SimpleNamespace(
                final_response="Generated id reply.",
                input_tokens=1,
                output_tokens=2,
                total_tokens=3,
                api_calls=1,
                model="gpt-test",
                raw={},
            )

    monkeypatch.setattr(commit_run, "GPTPersonaRuntime", _FakeRuntime)

    code = chat_turn_message._cmd_mission_chat_message(
        SimpleNamespace(
            persona_id="dev",
            persona_instance_id="personainst_dev",
            session_id="persona_chat_personainst_dev",
            task_id=None,
            goal_id=None,
            message="hi",
            surface_prompt="",
            intent_hint="chat",
            requested_by="test",
            client_message_id=None,
            stream=False,
            max_seconds=5.0,
            json=True,
        )
    )

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    client_message_id = payload["client_message_id"]
    assert client_message_id.startswith("agent-chat-send-")
    assert payload["turn_id"] == client_message_id
    assert captured["turn_id"] == client_message_id
    assert mission_chat_turn_record(
        session_id="persona_chat_personainst_dev",
        client_message_id=client_message_id,
    )["state"] == "projected"
    # C3: the terminal frame's `prompt_observability` is the slim subset — the
    # turn id lives at the top level (asserted above); the slim block links to
    # the persisted record-at-injection row only by `context_id`.
    assert payload["prompt_observability"]["context_id"] == payload["prompt_context_id"]
    assert "turn_id" not in payload["prompt_observability"]


def test_mission_chat_message_stream_terminal_frame_is_slim(
    monkeypatch,
    capsys,
    isolate_agent_runtime_root,
):
    """C3 emission-shape sabotage anchor (main handler, streaming lane).

    The terminal ``chat.final`` frame carries the slim typed observability subset
    and NO ``turn_elements``. Re-adding ``turn_elements`` to the emit path, or
    restoring the full row, turns this red."""
    from agent_runtime.prompt_observability.turn_results import (
        CHAT_FINAL_OBSERVABILITY_FIELDS,
    )

    cfg = _assignment_config()
    db = _TranscriptDB()
    monkeypatch.setattr(chat_turn_message, "load_agent_runtime_config", lambda: cfg)
    monkeypatch.setattr(chat_turn_message, "_default_persona_session_db", lambda: db)
    monkeypatch.setattr(commit_settle, "_maybe_auto_title_persona_chat", lambda **_kwargs: None)

    class _FakeRuntime:
        def __init__(self, *args, **kwargs):
            pass

        def mission_chat_reply(self, persona, message, **kwargs):
            callback = kwargs.get("stream_callback")
            if callback is not None:
                callback("He")
                callback("llo")
            return SimpleNamespace(
                final_response="Hello",
                input_tokens=1,
                output_tokens=2,
                total_tokens=3,
                api_calls=1,
                model="gpt-test",
                raw={
                    "model_input_observability": {
                        "kind": "redaction_safe_final_model_input",
                        "message_count": 1,
                        "messages": [],
                    }
                },
            )

    monkeypatch.setattr(commit_run, "GPTPersonaRuntime", _FakeRuntime)

    code = chat_turn_message._cmd_mission_chat_message(
        SimpleNamespace(
            persona_id="dev",
            persona_instance_id="personainst_dev",
            session_id="persona_chat_personainst_dev",
            task_id=None,
            goal_id=None,
            message="hi",
            surface_prompt="",
            intent_hint="chat",
            requested_by="test",
            client_message_id="client_slim_1",
            stream=True,
            max_seconds=5.0,
            json=True,
        )
    )

    assert code == 0
    lines = [
        json.loads(line)
        for line in capsys.readouterr().out.splitlines()
        if line.strip()
    ]
    final = lines[-1]
    assert final["type"] == "chat.final"
    assert final["ok"] is True
    # The double carriage is gone: no full turn-element echo on the wire.
    assert "turn_elements" not in final
    obs = final["prompt_observability"]
    # ONE shape: exactly the slim field set — no more, no less.
    assert set(obs) == set(CHAT_FINAL_OBSERVABILITY_FIELDS)
    # The heavy record-at-injection payloads never ride the terminal frame.
    for dropped in (
        "final_model_input",
        "prompt_layers",
        "context_files",
        "chat_history_context",
        "accessible_skills",
        "available_skills",
        "accessible_skills_ref",
        "available_skills_ref",
    ):
        assert dropped not in obs, dropped
    # The kept fields carry real content for the launcher's peek fallback +
    # usage overlay.
    assert obs["context_id"] == final["prompt_context_id"]
    assert isinstance(obs["situational_hud"], dict)
    assert isinstance(obs["used_skills"], list)
    assert isinstance(obs["model_selection"], dict)


def test_mission_chat_pre_trace_ack_is_presentation_only(
    monkeypatch,
    capsys,
    isolate_agent_runtime_root,
):
    """C8: the pre-trace ack NEVER enters the durable record.

    It rides the stream as a presentation-only protocol-v2 ``turn.ack`` frame:
    no SessionDB assistant row, no turn-store element — replay after the fact
    shows no ack. (Pre-C8 the ack was injected into SessionDB and then
    marker-suppressed launcher-side; that inject-then-hide seam is retired.)
    """

    from agent_runtime.mission_chat_turns import mission_chat_turn_elements

    cfg = _assignment_config()
    db = _TranscriptDB()
    monkeypatch.setattr(chat_turn_message, "load_agent_runtime_config", lambda: cfg)
    monkeypatch.setattr(chat_turn_message, "_default_persona_session_db", lambda: db)
    monkeypatch.setattr(commit_settle, "_maybe_auto_title_persona_chat", lambda **_kwargs: None)

    class _FakeRuntime:
        def __init__(self, *args, **kwargs):
            pass

        def mission_chat_reply(self, persona, message, **kwargs):
            kwargs["pre_trace_callback"](
                {
                    "type": "run.tool.started",
                    "phase": "tool",
                    "step": "tool_started",
                    "status": "started",
                    "tool_name": "skill_view",
                }
            )
            kwargs["stream_callback"]("The guidance is loaded.")
            return SimpleNamespace(
                final_response="The guidance is loaded; this is the right place.",
                input_tokens=1,
                output_tokens=2,
                total_tokens=3,
                api_calls=1,
                model="gpt-test",
                raw={},
            )

    monkeypatch.setattr(commit_run, "GPTPersonaRuntime", _FakeRuntime)

    code = chat_turn_message._cmd_mission_chat_message(
        SimpleNamespace(
            persona_id="dev",
            persona_instance_id="personainst_dev",
            session_id="persona_chat_personainst_dev",
            task_id=None,
            goal_id=None,
            message="is that a good place to do it",
            surface_prompt="",
            intent_hint="chat",
            requested_by="test",
            client_message_id="client_pre_trace_1",
            stream=True,
            max_seconds=5.0,
            json=True,
        )
    )

    assert code == 0
    lines = [
        json.loads(line)
        for line in capsys.readouterr().out.splitlines()
        if line.strip()
    ]
    # The ack IS on the live stream (typed, presentation-only), before content.
    ack_frames = [line for line in lines if line["type"] == "turn.ack"]
    assert len(ack_frames) == 1
    assert ack_frames[0]["protocol_version"] == 2
    assert ack_frames[0]["turn_id"] == "client_pre_trace_1"
    assert ack_frames[0]["text"] == (
        "I'll load the relevant guidance first, then report back with the useful part."
    )
    assert lines.index(ack_frames[0]) < min(
        index for index, line in enumerate(lines) if line["type"] == "segment.start"
    )
    # Native persistence is owned by the runtime actor. This fake runtime writes
    # no SessionDB rows, proving the CLI did not restore the retired append lane.
    messages = db.messages["persona_chat_personainst_dev"]
    assert messages == []
    # …and the turn store's elements hold only real content (replay shows no ack).
    persisted = mission_chat_turn_elements(
        session_id="persona_chat_personainst_dev",
        client_message_id="client_pre_trace_1",
    )
    assert persisted, "turn store must hold the streamed segment"
    assert all(item["kind"] in {"segment", "tool"} for item in persisted)
    assert all("report back" not in str(item.get("text") or "") for item in persisted)


def test_persona_chat_auto_title_waits_for_session_title_write(monkeypatch, isolate_agent_runtime_root):

    db = _TranscriptDB()
    session_id = "persona_chat_personainst_dev"
    db.create_session(session_id, "agent_runtime_persona_chat")
    called = []
    # One title attempt per session per process: start from a process that has
    # not tried this chat yet, whatever ran before this test.
    monkeypatch.setattr(chat_target, "_AUTO_TITLE_ATTEMPTED", set())

    def fake_auto_title_session(*, session_db, session_id, user_message, **kwargs):
        called.append((session_id, user_message))
        session_db.set_session_title(session_id, "Shipping Strategy Discussion")

    monkeypatch.setattr("agent.title_generator.auto_title_session", fake_auto_title_session)

    chat_target._maybe_auto_title_persona_chat(
        session_db=db,
        session_id=session_id,
        user_message="what's your take on shipping fast?",
        assistant_response="Ship the smallest coherent slice.",
    )

    assert called == [(session_id, "what's your take on shipping fast?")]
    assert db.get_session_title(session_id) == "Shipping Strategy Discussion"


def test_persona_chat_context_uses_native_structured_prior_turns(isolate_agent_runtime_root):

    db = _TranscriptDB()
    session_id = "persona_chat_personainst_dev"
    db.create_session(session_id, "agent_runtime_persona_chat")
    db.append_message(session_id, "user", "remember the blue button")
    db.append_message(session_id, "assistant", "I will remember the blue button.")

    history = commit_run.safe_native_history(
        chat_session._persona_chat_native_history(db, session_id)
    )

    assert history == [
        {"role": "user", "content": "remember the blue button"},
        {"role": "assistant", "content": "I will remember the blue button."},
    ]


def test_profile_persona_resolution_does_not_borrow_role_skills(monkeypatch, isolate_agent_runtime_root):

    cfg = _assignment_config()
    cfg.default_provider = "openai-codex"
    cfg.default_model = "gpt-default"
    cfg.personas["neko_supervisor"] = {
        "display_name": "Neko Mission Lead",
        "hermes_profile": "alice",
        "provider": "openai-codex",
        "model": "gpt-5.5",
        "api_mode": "codex_responses",
        "skills": ["harness-mission-lead", "systematic-debugging"],
    }

    persona = chat_target._persona_by_id(cfg, "profile_alice")

    assert persona is not None
    assert persona.id == "profile_alice"
    assert persona.role == "profile"
    assert persona.hermes_profile == "alice"
    assert persona.skills == []
    assert persona.model == "gpt-default"
    assert persona.provider == "openai-codex"
    assert not hasattr(persona, "toolsets")


def test_profile_persona_resolution_prefers_exact_id_over_profile_owner(
    monkeypatch, isolate_agent_runtime_root
):
    from agent_runtime.personas import (
        PROFILE_CHAT_TOOLSET_MATCHED_EXACT,
        profile_persona_resolution,
    )

    exact = _persona("profile_shared")
    exact.hermes_profile = "different"
    owner = _persona("profile_owner")
    owner.hermes_profile = "shared"
    monkeypatch.setattr(chat_target, "ensure_persisted_personas", lambda _cfg: [owner, exact])

    assert chat_target._persona_by_id(_assignment_config(), "profile_shared") is exact
    matched, reason, _ = profile_persona_resolution("shared", [owner, exact])
    assert matched is exact
    assert reason == PROFILE_CHAT_TOOLSET_MATCHED_EXACT


def test_ambiguous_profile_owners_do_not_supply_arbitrary_defaults(
    monkeypatch, isolate_agent_runtime_root
):
    from agent_runtime.personas import (
        PROFILE_CHAT_TOOLSET_AMBIGUOUS,
        profile_persona_resolution,
    )

    first = _persona("first")
    first.hermes_profile = "shared"
    second = _persona("second")
    second.hermes_profile = "shared"
    monkeypatch.setattr(chat_target, "ensure_persisted_personas", lambda _cfg: [first, second])

    resolved = chat_target._persona_by_id(_assignment_config(), "profile_shared")
    assert resolved is not None
    assert resolved.id == "profile_shared"
    matched, reason, candidates = profile_persona_resolution("shared", [first, second])
    assert matched is None
    assert reason == PROFILE_CHAT_TOOLSET_AMBIGUOUS
    assert set(candidates) == {"first", "second"}


def test_profile_prompt_observability_uses_profile_skills_and_chat_title(
    monkeypatch,
    tmp_path,
    isolate_agent_runtime_root,
):
    from agent_runtime import prompt_observability

    profile_dir = tmp_path / "alice"
    profile_dir.mkdir()
    (profile_dir / ".skills_prompt_snapshot.json").write_text(
        json.dumps(
            {
                "skills": [
                    {"skill_name": "agent-runtime-harness"},
                    {"skill_name": "creative-ideation"},
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(prompt_observability.context_budget, "get_profile_dir", lambda profile: profile_dir)
    monkeypatch.setattr(prompt_observability.context_files, "get_profile_dir", lambda profile: profile_dir)
    db = _TranscriptDB()
    db.create_session("persona_chat_alice", "agent_runtime_persona_chat")
    db.set_session_title("persona_chat_alice", "Alice Agent chat")

    context = prompt_observability.mission_chat_prompt_observability(
        persona=AgentPersona(
            id="profile_alice",
            display_name="Alice Agent",
            role="profile",
            model="gpt-test",
            provider="openai-codex",
            api_mode="codex_responses",
            system_prompt_path="",
            hermes_profile="alice",
            skills=[],
        ),
        persona_instance_id="personainst_profile_alice",
        session_id="persona_chat_alice",
        session_db=db,
    )

    assert context["chat_id"] == "persona_chat_alice"
    assert context["chat_title"] == "Alice Agent chat"
    assert context["chat_name"] == "Alice Agent chat"
    assert context["chat"]["source"] == "agent_runtime_persona_chat"
    assert context["used_skills"] == []
    assert [item["name"] for item in context["accessible_skills"]] == [
        "agent-runtime-harness",
        "creative-ideation",
    ]
    # C1 record-once (2026-07-17): the `skills` alias key is retired — one
    # canonical copy (`accessible_skills`), no compat emission (ruling 0).
    assert "skills" not in context
    assert {item["source"] for item in context["accessible_skills"]} == {
        "profile_skills_snapshot"
    }
    assert {item["status"] for item in context["accessible_skills"]} == {"missing"}
    assert {item["load_state"] for item in context["accessible_skills"]} == {
        "assigned_not_loaded"
    }
    assert all(not item["hash_tracked"] for item in context["accessible_skills"])


def test_prompt_observability_reports_used_skill_from_skill_view_trace(
    monkeypatch,
    tmp_path,
    isolate_agent_runtime_root,
):
    from agent_runtime import prompt_observability

    profile_dir = tmp_path / "alice"
    profile_dir.mkdir()
    (profile_dir / ".skills_prompt_snapshot.json").write_text(
        json.dumps({"skills": [{"skill_name": "agent-runtime-harness"}]}),
        encoding="utf-8",
    )
    monkeypatch.setattr(prompt_observability.context_budget, "get_profile_dir", lambda profile: profile_dir)
    monkeypatch.setattr(prompt_observability.context_files, "get_profile_dir", lambda profile: profile_dir)

    context = prompt_observability.mission_chat_prompt_observability(
        persona=AgentPersona(
            id="profile_alice",
            display_name="Alice Agent",
            role="profile",
            model="gpt-test",
            provider="openai-codex",
            api_mode="codex_responses",
            system_prompt_path="",
            hermes_profile="alice",
            skills=[],
        ),
        persona_instance_id="personainst_profile_alice",
        session_id="persona_chat_alice",
        trace_events=[
            {
                "tool_name": "skill_view",
                "step": "tool_finished",
                "status": "passed",
                "skill_name": "agent-runtime-harness",
            },
            {
                "tool_name": "skills_list",
                "step": "tool_finished",
                "status": "passed",
                "skill_name": "creative-ideation",
            },
        ],
    )

    assert [item["name"] for item in context["used_skills"]] == [
        "agent-runtime-harness"
    ]
    assert context["used_skills"][0]["source"] == "skill_view_trace"


def test_prompt_observability_refreshes_stale_derived_fields(
    monkeypatch,
    tmp_path,
    isolate_agent_runtime_root,
):
    from agent_runtime import prompt_observability

    profile_dir = tmp_path / "alice"
    profile_dir.mkdir()
    (profile_dir / ".skills_prompt_snapshot.json").write_text(
        json.dumps({"skills": [{"skill_name": "fresh-profile-skill"}]}),
        encoding="utf-8",
    )
    monkeypatch.setattr(prompt_observability.context_budget, "get_profile_dir", lambda profile: profile_dir)
    monkeypatch.setattr(prompt_observability.context_files, "get_profile_dir", lambda profile: profile_dir)
    db = _TranscriptDB()
    db.create_session("persona_chat_alice", "agent_runtime_persona_chat")
    db.set_session_title("persona_chat_alice", "Alice Agent chat")
    stale = {
        "context_id": "ctx_stale",
        "persona_id": "profile_alice",
        "persona_instance_id": "personainst_profile_alice",
        "profile": "alice",
        "session_id": "persona_chat_alice",
        "skills": [
            {
                "name": "harness-mission-lead",
                "kind": "skill",
                "status": "loaded",
                "hash_tracked": True,
                "source": "persona_definition",
            }
        ],
        "used_skills": None,
        "model_selection": {
            "effective_provider": "openai-codex",
            "effective_model": "gpt-5.5",
        },
        "final_model_input": {
            "messages": [
                {"role": "system", "bytes": 40},
                {"role": "user", "bytes": 60},
            ]
        },
        "context_budget": {
            "model": "gpt-5.5",
            "provider": "openai-codex",
            "window_tokens": 272000,
            "compaction_ratio": 0.85,
            "compaction_tokens": 231200,
            "used_tokens": None,
            "used_estimated": True,
        },
    }
    prompt_observability.persist_prompt_observability_context(stale)
    built = prompt_observability.mission_chat_prompt_observability(
        persona=AgentPersona(
            id="profile_alice",
            display_name="Alice Agent",
            role="profile",
            model="gpt-test",
            provider="openai-codex",
            api_mode="codex_responses",
            system_prompt_path="",
            hermes_profile="alice",
            skills=[],
        ),
        persona_instance_id="personainst_profile_alice",
        session_id="persona_chat_alice",
        session_db=db,
    )

    merged = prompt_observability.context_store._merge_latest_contexts([built])

    refreshed = merged[0]
    assert refreshed["context_id"] == "ctx_stale"
    assert refreshed["chat_title"] == "Alice Agent chat"
    assert refreshed["used_skills"] == []
    assert [item["name"] for item in refreshed["accessible_skills"]] == ["fresh-profile-skill"]
    # C1 record-once (2026-07-17): the `skills` alias key is retired — the row
    # carries ONE canonical copy (`accessible_skills`); the legacy alias on the
    # persisted input is normalized in, never re-emitted.
    assert "skills" not in refreshed
    assert refreshed["accessible_skills"][0]["source"] == "profile_skills_snapshot"
    assert refreshed["context_budget"]["used_tokens"] == 25


def test_snapshot_prompt_observability_builds_profile_instance_context(
    monkeypatch,
    tmp_path,
    isolate_agent_runtime_root,
):
    from agent_runtime import prompt_observability
    from agent_runtime.models import PersonaInstance, WorkerSessionState

    profile_dir = tmp_path / "alice"
    profile_dir.mkdir()
    (profile_dir / ".skills_prompt_snapshot.json").write_text(
        json.dumps({"skills": [{"skill_name": "alice-profile-skill"}]}),
        encoding="utf-8",
    )
    monkeypatch.setattr(prompt_observability.context_budget, "get_profile_dir", lambda profile: profile_dir)
    monkeypatch.setattr(prompt_observability.context_files, "get_profile_dir", lambda profile: profile_dir)
    db = _TranscriptDB()
    db.create_session("persona_chat_personainst_profile_alice", "agent_runtime_persona_chat")
    db.set_session_title("persona_chat_personainst_profile_alice", "Alice Agent chat")
    stale = {
        "context_id": "ctx_stale_profile_alice",
        "persona_id": "profile_alice",
        "persona_instance_id": "personainst_profile_alice",
        "profile": "alice",
        "session_id": "persona_chat_personainst_profile_alice",
        "skills": [
            {
                "name": "harness-mission-lead",
                "kind": "skill",
                "status": "loaded",
                "hash_tracked": True,
                "source": "persona_definition",
            }
        ],
    }
    prompt_observability.persist_prompt_observability_context(stale)

    snapshot = prompt_observability.snapshot_prompt_observability(
        personas=[],
        persona_instances=[
            PersonaInstance(
                id="personainst_profile_alice",
                persona_id="profile_alice",
                role="profile",
                display_name="Alice Agent",
                profile_id="alice",
                runtime_root=".",
                state=WorkerSessionState.IDLE,
                mode="chat",
                session_id="persona_chat_personainst_profile_alice",
                # Regression: a profile-backed instance is synthesized rather
                # than loaded from AgentStore. Explicit skill policy must still
                # overlay through the typed AgentPersona path; the old
                # SimpleNamespace fallback crashed dataclasses.replace and took
                # down `harness stream` before its hydrate frame.
                skill_overrides=["harness-runtime-model"],
            )
        ],
        session_db=db,
    )

    context = snapshot["chat_contexts"][0]
    assert context["context_id"] == "ctx_stale_profile_alice"
    assert context["chat_id"] == "persona_chat_personainst_profile_alice"
    assert context["chat_title"] == "Alice Agent chat"
    assert context["used_skills"] == []
    # S8: the ``skills_catalogs`` table is evicted from the frame; rows keep only
    # the content hash. The accessible set here is the profile-snapshot fallback
    # (backfilled at merge time — distinct from the persisted persona_definition
    # skills), so this pins the RESOLUTION content by proving the ref equals the
    # content hash of the expected backfilled list (`skills` aliases it → same
    # ref). The on-disk resolver covers persisted lists; this in-memory backfill
    # is pinned by hash equality instead.
    expected_context = prompt_observability.mission_chat_prompt_observability(
        persona=AgentPersona(
            id="profile_alice",
            display_name="Alice Agent",
            role="profile",
            model="gpt-test",
            provider="openai-codex",
            api_mode="codex_responses",
            system_prompt_path="",
            hermes_profile="alice",
            skills=["harness-runtime-model"],
        ),
        persona_instance_id="personainst_profile_alice",
        session_id="persona_chat_personainst_profile_alice",
        session_db=db,
        instance_skill_overrides=["harness-runtime-model"],
    )
    expected_accessible = expected_context["accessible_skills"]
    assert "skills_catalogs" not in snapshot
    assert context["accessible_skills_ref"] == prompt_observability.hoist._skills_list_content_hash(
        expected_accessible
    )


def test_profile_persona_instance_summary_includes_tool_visibility(isolate_agent_runtime_root):
    instance = PersonaInstance(
        id="personainst_profile_alice",
        persona_id="profile_alice",
        role="profile",
        display_name="Alice Agent",
        profile_id="alice",
        runtime_root=str(REPO_ROOT),
        state=WorkerSessionState.IDLE,
        mode="chat",
        session_id="persona_chat_personainst_profile_alice_e898c1dc3794",
    )

    summary = persona_instance_summary(instance)

    # Residue-slim R2: the summary keeps only the head SCALARS + a typed
    # visibility_ref pointer; the heavy payloads (and the retired agent_hud_state)
    # leave the wire row.
    assert "tool_resolution" not in summary
    assert "turn_tool_context" not in summary
    assert "permission_state" not in summary
    assert "agent_hud_state" not in summary
    assert "blocked_tools" not in summary
    # The runtime DEFAULT posture since the 2026-08-09 ruling — the drawer must
    # render what a turn actually gets, not a bounded literal.
    assert summary["permission_mode"] == default_permission_mode()
    assert summary["permission_mode"] == "unbounded"
    assert isinstance(summary["mutation_boundary"], dict)
    assert isinstance(summary["tool_count"], int)
    assert summary["blocked_tools_count"] >= 0
    assert summary["visibility_ref"]["evicted"] is True
    assert summary["visibility_ref"]["id"] == "personainst_profile_alice"
    assert "agent_hud_state" not in summary["visibility_ref"]["fields"]

    # The full payloads are rebuilt on demand by persona_instance_tool_detail (the
    # `harness persona-instance detail` body) — the same bytes the frame used to
    # carry, minus the retired agent_hud_state.
    detail = persona_instance_tool_detail(instance)
    assert detail["tool_resolution"]["persona_id"] == "profile_alice"
    assert detail["turn_tool_context"]["persona_id"] == "profile_alice"
    # T9b: this preview is the persona instance's operator CHAT lane, so it
    # reflects whatever that lane actually ships. Under the 2026-08-09 runtime
    # default (`unbounded`) the T3/T6a cost cuts do not apply, so the dev toolkit
    # is present — the preview would be LYING if it still hid it (the bounded
    # shape is pinned by the companion test below).
    final_tools = detail["tool_resolution"]["final_model_tools"]
    assert "read_file" in final_tools
    assert "terminal" in final_tools
    assert "agent_chat_send" in final_tools
    assert "clarify" in final_tools
    # The persona-safety blocks yield to the mode; registry hygiene never does.
    assert "send_message" not in detail["tool_resolution"]["blocked_tool_names"]
    assert "kanban_create" in detail["tool_resolution"]["blocked_tool_names"]
    assert detail["permission_state"]["mode"] == "unbounded"
    assert "agent_hud_state" not in detail
    assert summary["tool_count"] == len(detail["tool_resolution"]["final_model_tools"])


def test_profile_persona_instance_preview_reflects_an_operator_restriction(
    isolate_agent_runtime_root, bounded_chat_session
):
    """The same preview, for a session an operator narrowed.

    The chat-lane cost policy (T3/T6a) is alive and unchanged — it just no longer
    applies to the DEFAULT posture. This is the tier it does apply to, and the
    preview must track it rather than reporting one fixed shape.
    """

    session_id = "persona_chat_personainst_profile_alice_e898c1dc3794"
    bounded_chat_session("profile_alice", session_id)
    instance = PersonaInstance(
        id="personainst_profile_alice",
        persona_id="profile_alice",
        role="profile",
        display_name="Alice Agent",
        profile_id="alice",
        runtime_root=str(REPO_ROOT),
        state=WorkerSessionState.IDLE,
        mode="chat",
        session_id=session_id,
    )

    summary = persona_instance_summary(instance)
    detail = persona_instance_tool_detail(instance)
    final_tools = detail["tool_resolution"]["final_model_tools"]

    assert summary["permission_mode"] == "profile_default"
    assert "read_file" not in final_tools
    assert "terminal" not in final_tools
    assert "execute_code" not in final_tools
    assert "mission_goal_create" not in final_tools
    assert "agent_chat_send" in final_tools
    assert "clarify" in final_tools
    assert "send_message" in detail["tool_resolution"]["blocked_tool_names"]
    assert detail["permission_state"]["mode"] == "profile_default"


def test_profile_visibility_preserves_custom_instance_role_without_config(monkeypatch):
    from agent_runtime.persona_assignments import _profile_visibility_persona

    instance = PersonaInstance(
        id="personainst_profile_researcher",
        persona_id="profile_researcher",
        role="literature_reviewer",
        display_name="Researcher",
        profile_id="researcher",
        runtime_root=str(REPO_ROOT),
        state=WorkerSessionState.IDLE,
    )

    persona = _profile_visibility_persona(instance, list)

    assert persona.id == "profile_researcher"
    assert persona.role == "literature_reviewer"
    assert persona.hermes_profile == "researcher"


def test_profile_visibility_uses_configured_custom_role_without_rewriting_raw_id(monkeypatch):
    from agent_runtime.persona_assignments import _profile_visibility_persona

    configured = AgentPersona(
        id="configured_researcher",
        display_name="Configured Researcher",
        role="evidence_synthesist",
        model="gpt-custom",
        provider="custom-provider",
        api_mode="chat_completions",
        system_prompt_path="SOUL.md",
        hermes_profile="researcher",
    )
    instance = PersonaInstance(
        id="personainst_profile_researcher",
        persona_id="profile_researcher",
        role="profile",
        display_name="Raw Profile Chat",
        profile_id="researcher",
        runtime_root=str(REPO_ROOT),
        state=WorkerSessionState.IDLE,
    )

    persona = _profile_visibility_persona(instance, lambda: [configured])

    assert persona.id == "profile_researcher"
    assert persona.display_name == "Raw Profile Chat"
    assert persona.role == "evidence_synthesist"
    assert persona.hermes_profile == "researcher"
