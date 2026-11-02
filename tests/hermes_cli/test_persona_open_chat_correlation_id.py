"""``harness persona instance open-chat --correlation-id`` (correlation-id plan
P2, row RT-CORRELATION-ID-CI3-ACCEPTANCE).

The launcher's add-instance placement still takes this argv door (the method
lane pins the minting keys closed), and before P2 it was the one placement door
that dropped the gesture token: ``PersonaInstanceStore.add_instance`` took none.
The token now rides ``persona_instance.chat_opened`` and its paired
``state.patched`` row on both branches that bind — the ``--add-instance`` mint
and the ``--session-id`` rebind — and an absent flag leaves both byte-identical.

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


def _open_add_instance(capsys, placement: str, *extra: str) -> tuple[int, dict]:
    code = _dispatch(
        [
            "harness", "persona", "instance", "open-chat",
            "--persona", "qa",
            "--add-instance",
            "--placement-id", placement,
            "--display-name", "QA Agent (2)",
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


def test_the_add_instance_mint_carries_the_token_on_its_event_and_its_row(capsys):
    before = _log_end()
    code, data = _open_add_instance(capsys, "qa_corr_agent_2", "--correlation-id", TOKEN)
    assert code == 0, data
    opened, patch = _opened_pair(_since(before))
    assert opened["correlation_id"] == TOKEN
    assert patch["correlation_id"] == TOKEN
    assert patch.get("created") is True


def test_the_session_rebind_carries_the_token_too(capsys):
    code, data = _open_add_instance(capsys, "qa_corr_agent_3")
    assert code == 0, data
    instance_id = "personainst_qa_corr_agent_3"
    from agent_runtime.persona_assignments import PersonaInstanceStore

    bound = PersonaInstanceStore().get(instance_id).default_chat_session_id
    # A second root for the same instance, so the rebind MOVES the pointer (an
    # idempotent re-open is an observation and emits nothing).
    other = f"{bound}_rebind"
    before = _log_end()
    PersonaInstanceStore().open_chat(
        persona_id="qa", persona_instance_id=instance_id, session_id=bound
    )
    code = _dispatch(
        [
            "harness", "persona", "instance", "open-chat",
            "--persona", "qa",
            "--persona-instance-id", instance_id,
            "--session-id", other,
            "--correlation-id", TOKEN,
            "--json",
        ]
    )
    out = capsys.readouterr().out
    assert code == 0, out
    opened, patch = _opened_pair(_since(before))
    assert opened["correlation_id"] == TOKEN
    assert patch["correlation_id"] == TOKEN


def test_no_flag_leaves_the_event_and_row_without_the_key(capsys):
    before = _log_end()
    code, data = _open_add_instance(capsys, "qa_corr_agent_4")
    assert code == 0, data
    opened, patch = _opened_pair(_since(before))
    assert "correlation_id" not in opened
    assert "correlation_id" not in patch


def test_an_illegal_token_degrades_to_no_token_never_rides_the_wire(capsys):
    before = _log_end()
    code, data = _open_add_instance(capsys, "qa_corr_agent_5", "--correlation-id", "x" * 300)
    assert code == 0, data
    opened, patch = _opened_pair(_since(before))
    assert "correlation_id" not in opened
    assert "correlation_id" not in patch
