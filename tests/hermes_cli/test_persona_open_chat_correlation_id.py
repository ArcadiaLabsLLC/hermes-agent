"""``harness persona instance open-chat --correlation-id`` (correlation-id plan
P2, row RT-CORRELATION-ID-CI3-ACCEPTANCE).

The token rides ``persona_instance.chat_opened`` and its paired ``state.patched``
row on the ``--session-id`` rebind, and an absent flag leaves both byte-identical.
(The ``--add-instance`` mint branch this file also pinned is retired:
RT-THE-OLD-CREATE-NO-LONGER-PLACES-OR-COPIES-AN-AGENT.)

Everything drives the REAL argparse tree (a flag no parser declares is a flag
no launcher can send).
"""

from __future__ import annotations

import argparse
import json

import pytest

from agent_runtime import paths
from agent_runtime.events import EventLog
from agent_runtime.state_patches import STATE_PATCHED_EVENT_TYPE
from hermes_cli.harness_parts.persona import chat_open, lifecycle_commands

TOKEN = "g-office-open-1"


@pytest.fixture(autouse=True)
def hermetic_runtime_root(tmp_path, monkeypatch):
    """Pin the runtime root inside this test's tmp dir, and prove it landed —
    these tests mint durable roster rows."""

    root = tmp_path / "agent-runtime"
    monkeypatch.setenv("HERMES_AGENT_RUNTIME_ROOT", str(root))
    resolved = paths.store_root().resolve()
    assert resolved == root.resolve() or root.resolve() in resolved.parents, (
        f"store_root() resolved to {resolved}, OUTSIDE {root}."
    )
    return root


class _SessionDB:
    def __init__(self):
        self.titles: dict[str, str] = {}

    def create_session(self, session_id, source, **kwargs):
        return session_id

    def get_session(self, session_id):
        return None

    def get_session_title(self, session_id):
        return self.titles.get(session_id)

    def set_session_title(self, session_id, title):
        self.titles[session_id] = title

    def append_message(self, session_id, role, content=None, **kwargs):
        pass

    def get_messages(self, session_id, include_inactive=False):
        return []


@pytest.fixture(autouse=True)
def session_db(monkeypatch):
    db = _SessionDB()
    monkeypatch.setattr(chat_open, "_default_persona_session_db", lambda: db)
    monkeypatch.setattr(lifecycle_commands, "_default_persona_session_db", lambda: db)
    return db


@pytest.fixture(autouse=True)
def qa_persona():
    from agent_runtime.models import AgentPersona
    from agent_runtime.store import AgentStore

    persona = AgentPersona(
        id="qa",
        display_name="QA Agent",
        role="qa",
        model=None,
        provider=None,
        api_mode=None,
        system_prompt_path="",
    )
    AgentStore().save(persona)
    return persona


def _dispatch(argv: list[str]) -> int:
    from hermes_cli import harness

    root = argparse.ArgumentParser(prog="hermes")
    harness.build_parser(root.add_subparsers(dest="command"))
    args = root.parse_args(argv)
    return args.func(args)


def _log_end() -> int:
    return max((o for o, _ in EventLog().iter_from_offset(0)), default=-1)


def _since(offset: int) -> list:
    return [e for o, e in EventLog().iter_from_offset(0) if o > offset]


def _placed():
    from agent_runtime.persona_assignments import PersonaInstanceStore

    return PersonaInstanceStore().add_instance(
        persona_id="qa", placement_id="qa_corr_agent_3", display_name="QA Agent (2)")


def _rebind(capsys, instance, *extra: str) -> tuple[int, dict]:
    """A placed instance's chat re-bound to a second root: the open-chat branch that binds and
    emits. (The ``--add-instance`` mint branch is retired: RT-THE-OLD-CREATE-NO-LONGER-PLACES-OR-
    COPIES-AN-AGENT; a placement's own token rides ``runtime.agent.place``.)"""

    bound = instance.default_chat_session_id
    # A second root for the same instance, so the rebind MOVES the pointer (an
    # idempotent re-open is an observation and emits nothing).
    code = _dispatch(
        [
            "harness", "persona", "instance", "open-chat",
            "--persona", "qa",
            "--persona-instance-id", instance.id,
            "--session-id", f"{bound}_rebind",
            "--json",
            *extra,
        ]
    )
    return code, json.loads(capsys.readouterr().out)


def _opened_pair(events) -> tuple[dict, dict]:
    (opened,) = [e.payload for e in events if e.type == "persona_instance.chat_opened"]
    (patch,) = [
        e.payload
        for e in events
        if e.type == STATE_PATCHED_EVENT_TYPE and e.payload.get("entity") == "persona_instance"
    ]
    return opened, patch


def test_the_session_rebind_carries_the_token(capsys):
    instance = _placed()
    before = _log_end()
    code, data = _rebind(capsys, instance, "--correlation-id", TOKEN)
    assert code == 0, data
    opened, patch = _opened_pair(_since(before))
    assert opened["correlation_id"] == TOKEN
    assert patch["correlation_id"] == TOKEN


def test_no_flag_leaves_the_event_and_row_without_the_key(capsys):
    instance = _placed()
    before = _log_end()
    code, data = _rebind(capsys, instance)
    assert code == 0, data
    opened, patch = _opened_pair(_since(before))
    assert "correlation_id" not in opened
    assert "correlation_id" not in patch


def test_an_illegal_token_degrades_to_no_token_never_rides_the_wire(capsys):
    instance = _placed()
    before = _log_end()
    code, data = _rebind(capsys, instance, "--correlation-id", "x" * 300)
    assert code == 0, data
    opened, patch = _opened_pair(_since(before))
    assert "correlation_id" not in opened
    assert "correlation_id" not in patch
