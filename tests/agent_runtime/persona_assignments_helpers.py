"""Helpers shared by the ``test_persona_assignments*.py`` files (split 2026-11-02)."""

from __future__ import annotations

import json
import uuid
from pathlib import Path

from agent_runtime import paths
from agent_runtime.config import AgentRuntimeConfig
from agent_runtime.models import AgentPersona, AgentRun
from agent_runtime.serde import to_jsonable
from agent_runtime.states import RunState
from hermes_time import now
from utils import atomic_json_write


def _seed_run(
    persona_id: str,
    task_id: str,
    stage_id: str | None = None,
    *,
    session_id: str | None = None,
) -> AgentRun:
    """Persist a run row without ``RunStore.open_run``.

    The run store is now historical/read-only. Tests that exercise projections
    seed a representative historical row directly.
    """

    ts = now()
    run = AgentRun(
        id=f"run_{uuid.uuid4().hex[:12]}",
        persona_id=persona_id,
        task_id=task_id,
        stage_id=stage_id,
        state=RunState.RUNNING,
        started_at=ts,
        last_heartbeat_at=ts,
        session_id=session_id,
    )
    atomic_json_write(paths.run_path(run.id), to_jsonable(run), indent=2, sort_keys=True)
    return run


REPO_ROOT = Path(__file__).resolve().parents[2]


def _persona(persona_id: str = "dev", *, role: str = "dev") -> AgentPersona:
    return AgentPersona(
        id=persona_id,
        display_name=f"{persona_id} worker",
        role=role,
        model="gpt-test",
        provider="openai-codex",
        api_mode="codex_responses",
        system_prompt_path="agent_runtime/prompts/dev.md",
        hermes_profile=f"profile-{persona_id}",
    )


def _assignment_config() -> AgentRuntimeConfig:
    # S56: the persona-instance runtime / assignment store are unconditional now;
    # the enterprise_worker_sessions gate block was deleted.
    return AgentRuntimeConfig()


class _TranscriptDB:
    def __init__(self):
        self.sessions = {}
        self.messages = {}
        self.titles = {}

    def close(self):
        return None

    def get_session_model_config_value(self, session_id, key, default=None):
        raw = (self.get_session(session_id) or {}).get("model_config")
        config = json.loads(raw) if isinstance(raw, str) else raw
        return (config or {}).get(key, default)

    def create_session(self, session_id, source, **kwargs):
        self.sessions.setdefault(session_id, {"source": source, **kwargs})
        self.messages.setdefault(session_id, [])
        return session_id

    def list_sessions_rich(self, **kwargs):
        source = kwargs.get("source")
        exclude_sources = set(kwargs.get("exclude_sources") or [])
        rows = []
        for session_id, session in self.sessions.items():
            row_source = session.get("source")
            if source and row_source != source:
                continue
            if row_source in exclude_sources:
                continue
            rows.append(
                {
                    "id": session_id,
                    "source": row_source,
                    "system_prompt": session.get("system_prompt"),
                    "model": session.get("model"),
                    "model_config": session.get("model_config"),
                    "title": self.titles.get(session_id),
                    "preview": None,
                    "message_count": len(self.messages.get(session_id, [])),
                    "started_at": None,
                    "last_active": None,
                    "archived": 0,
                }
            )
        return rows

    def append_message(self, session_id, role, content=None, **kwargs):
        self.messages.setdefault(session_id, []).append(
            {"role": role, "content": content, **kwargs}
        )
        return len(self.messages[session_id])

    def get_messages(self, session_id, include_inactive=False):
        return list(self.messages.get(session_id, []))

    def get_session(self, session_id):
        session = self.sessions.get(session_id)
        if session is None:
            return None
        return {
            "id": session_id,
            "source": session.get("source"),
            "system_prompt": session.get("system_prompt"),
            "model": session.get("model"),
            "model_config": session.get("model_config"),
            "title": self.titles.get(session_id),
            "preview": None,
            "message_count": len(self.messages.get(session_id, [])),
            "started_at": None,
            "last_active": None,
            "archived": 0,
        }

    def get_session_title(self, session_id):
        return self.titles.get(session_id)

    def set_session_title(self, session_id, title):
        self.titles[session_id] = title

    def update_session_meta(self, session_id, model_config_json, model=None):
        session = self.sessions.setdefault(session_id, {})
        session["model_config"] = model_config_json
        if model is not None:
            session["model"] = model

    def delete_session(self, session_id, **kwargs):
        if session_id not in self.sessions:
            return False
        del self.sessions[session_id]
        self.messages.pop(session_id, None)
        self.titles.pop(session_id, None)
        return True


class _FailingTranscriptDB(_TranscriptDB):
    def __init__(self, operation: str):
        super().__init__()
        self.operation = operation

    def create_session(self, session_id, source, **kwargs):
        if self.operation == "session_create":
            raise OSError("simulated canonical session create failure")
        return super().create_session(session_id, source, **kwargs)

    def append_message(self, session_id, role, content=None, **kwargs):
        if self.operation == "operator_append" and role == "user":
            raise OSError("simulated canonical operator append failure")
        if self.operation == "assistant_append" and role == "assistant":
            raise OSError("simulated canonical assistant append failure")
        return super().append_message(session_id, role, content, **kwargs)
