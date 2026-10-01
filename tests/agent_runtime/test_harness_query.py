"""HQ1: the harness query core, its in-turn tool, and the CLI verb's routing.

Evidence: launcher ``docs/mission_control/SIX_SCREENSHOT_FINDINGS_2026-10-01.md``
F1-F5 — a lookup turn spent 126 s on three 907 KB snapshots and then claimed a
QA session no receipt named. Each question below has a positive control: the
same fixture with one variable changed, where the thing MUST happen.

Killing mutations (each applied, red recorded, reverted — see the commit):
  M1 core._roster returns ``rows[:1]``                      -> roster test red
  M2 core.resolve_instance reads every token verbatim       -> persona-id test red
  M3 summary.rows ignores ``only_instance_ids``             -> sessions test red
  M4 core.LIVE_RUNTIME_STATES = {"hot"}                      -> busy QA test red
  M5 core._live_qa drops the persona filter                  -> dev-busy test red
  M6 harness_query registered into toolset "harness_query"   -> registration test red
  M7 answer_routed never dials the serve                     -> serve-routing test red
"""

from __future__ import annotations

import argparse
import json

import pytest

from agent_runtime import harness_query
from agent_runtime.harness_query import core
from agent_runtime.persona_assignments import PersonaInstanceStore
from agent_runtime.persona_chat_continuity import runtime_registry
from tools.registry import discover_builtin_tools, registry

QA_ROOT = "persona_chat_personainst_qa_root01"
DEV_ROOT = "persona_chat_personainst_dev_root01"


@pytest.fixture(autouse=True)
def _tools_loaded():
    discover_builtin_tools()


@pytest.fixture
def no_resident_registry(monkeypatch):
    """A CLI one-shot: no process-owned resident-actor registry."""
    monkeypatch.setattr(runtime_registry, "_REGISTRY", None)


@pytest.fixture
def resident_registry(monkeypatch):
    """The serve's registry, owned by this process."""
    registry_ = runtime_registry.PersonaChatRuntimeRegistry()
    monkeypatch.setattr(runtime_registry, "_REGISTRY", registry_)
    return registry_


def _session(session_id: str, text: str = "hello") -> None:
    from hermes_state import SessionDB

    db = SessionDB()
    db.create_session(
        session_id=session_id, source="agent_runtime_persona_chat", model=None, system_prompt="test persona chat"
    )
    db.append_message(session_id=session_id, role="assistant", content=text)


def _qa_and_dev():
    store = PersonaInstanceStore()
    qa = store.open_chat(persona_id="qa", session_id=QA_ROOT)
    dev = store.open_chat(persona_id="dev", session_id=DEV_ROOT)
    _session(QA_ROOT)
    _session(DEV_ROOT)
    return qa, dev


# ── the core ─────────────────────────────────────────────────────────────────


def test_roster_lists_every_stored_instance_with_its_default_chat():
    qa, dev = _qa_and_dev()

    reply = harness_query.answer("roster")

    assert reply["ok"] is True and reply["question"] == "roster"
    rows = {row["persona_instance_id"]: row for row in reply["instances"]}
    assert set(rows) == {qa.id, dev.id}
    assert reply["count"] == 2 and reply["unreadable_rows"] == 0
    assert rows[qa.id]["default_chat_session_id"] == QA_ROOT
    assert rows[dev.id]["persona_id"] == "dev"


def test_roster_of_an_empty_store_is_empty_not_an_error():
    reply = harness_query.answer("roster")
    assert reply["ok"] is True and reply["instances"] == [] and reply["count"] == 0


def test_instance_resolves_by_instance_id_and_by_persona_id_and_misses_honestly():
    qa, _dev = _qa_and_dev()

    by_id = harness_query.answer("instance", instance=qa.id)
    by_persona = harness_query.answer("instance", instance="qa")
    miss = harness_query.answer("instance", instance="personainst_nobody")

    assert by_id["instance"]["persona_instance_id"] == qa.id
    assert by_persona["instance"]["persona_instance_id"] == qa.id  # positive control for M2
    assert by_id["mcp"]["exercised"].startswith("not_answered_here")
    assert by_id["mcp"]["basis"] in {"resolved_now", "unresolved"}
    assert miss["ok"] is False and miss["error"] == "not_found"


def test_sessions_returns_only_the_named_instances_sessions(no_resident_registry):
    qa, dev = _qa_and_dev()

    qa_reply = harness_query.answer("sessions", instance=qa.id)
    dev_reply = harness_query.answer("sessions", instance=dev.id)

    assert [row["session_id"] for row in qa_reply["sessions"]] == [QA_ROOT]
    assert [row["session_id"] for row in dev_reply["sessions"]] == [DEV_ROOT]  # positive control
    assert qa_reply["sessions"][0]["is_default"] is True
    # Off the serve nothing is observed, and the answer says who observed it.
    assert qa_reply["sessions"][0]["runtime_state"] == "unknown"
    assert qa_reply["observer"]["runtime_observer_id"] == "external_cli"
    assert qa_reply["observer"]["observes_runtime_state"] is False


def test_sessions_report_the_registrys_state_when_this_process_owns_it(resident_registry):
    qa, _dev = _qa_and_dev()
    resident_registry.transition(QA_ROOT, "busy")

    reply = harness_query.answer("sessions", instance=qa.id)

    assert reply["sessions"][0]["runtime_state"] == "busy"
    assert reply["observer"]["runtime_observer_id"].startswith("serve:")


def test_live_qa_with_no_qa_instance_says_so(no_resident_registry):
    PersonaInstanceStore().open_chat(persona_id="dev", session_id=DEV_ROOT)
    _session(DEV_ROOT)

    reply = harness_query.answer("live_qa")

    assert reply["qa_instance_ids"] == [] and reply["live"] == [] and reply["resumable"] == []
    assert reply["verdict"] == "no_qa_session"


def test_live_qa_off_the_serve_names_the_session_but_will_not_call_it_live(no_resident_registry):
    qa, _dev = _qa_and_dev()

    reply = harness_query.answer("live_qa")

    assert reply["live"] == []
    assert [(row["persona_instance_id"], row["session_id"]) for row in reply["resumable"]] == [(qa.id, QA_ROOT)]
    assert reply["verdict"] == "runtime_state_unobservable_here"


def test_live_qa_on_the_serve_names_the_busy_session_by_id(resident_registry):
    """The positive control for the test above: same fixture, the registry owned."""
    qa, _dev = _qa_and_dev()
    resident_registry.transition(QA_ROOT, "busy")

    reply = harness_query.answer("live_qa")

    assert [(row["persona_instance_id"], row["session_id"]) for row in reply["live"]] == [(qa.id, QA_ROOT)]
    assert reply["verdict"] == "live_session"


def test_live_qa_on_the_serve_with_a_cold_qa_session_is_not_live(resident_registry):
    _qa_and_dev()
    resident_registry.transition(QA_ROOT, "cold")

    reply = harness_query.answer("live_qa")

    assert reply["live"] == [] and [row["session_id"] for row in reply["resumable"]] == [QA_ROOT]
    assert reply["verdict"] == "no_live_session"


def test_a_busy_dev_session_is_never_a_live_qa_session(resident_registry):
    _qa_and_dev()
    resident_registry.transition(DEV_ROOT, "busy")
    resident_registry.transition(QA_ROOT, "cold")

    reply = harness_query.answer("live_qa")

    assert reply["live"] == []
    assert DEV_ROOT not in {row["session_id"] for row in reply["resumable"]}


def test_an_unknown_question_is_a_typed_refusal_naming_the_real_ones():
    reply = harness_query.answer("snapshot")
    assert reply == {
        "ok": False,
        "error": "unknown_question",
        "question": "snapshot",
        "questions": ["roster", "instance", "sessions", "live_qa"],
    }


# ── the in-turn tool ─────────────────────────────────────────────────────────


def test_harness_query_is_an_agent_chat_tool_and_rides_every_chat_lane():
    from agent_runtime.chat_lane_bundle import _CHAT_CAPABILITY_TOOLSETS

    entry = registry.get_entry("harness_query")

    assert entry is not None and entry.toolset == "agent_chat"
    assert "agent_chat" in _CHAT_CAPABILITY_TOOLSETS
    assert entry.schema["parameters"]["properties"]["question"]["enum"] == list(core.QUESTIONS)


def test_the_tool_answers_from_the_same_core():
    qa, dev = _qa_and_dev()

    raw = registry.dispatch("harness_query", {"question": "roster"}, task_id=None, session_id=None)
    payload = json.loads(raw)

    assert {row["persona_instance_id"] for row in payload["instances"]} == {qa.id, dev.id}
    assert payload["instances"] == harness_query.answer("roster")["instances"]


# ── the CLI verb: serve first, direct read otherwise ─────────────────────────


def _run_cli(argv: list[str]) -> int:
    from hermes_cli.harness_parts.parser import build_parser

    parser = argparse.ArgumentParser()
    build_parser(parser.add_subparsers())
    args = parser.parse_args(argv)
    return args.func(args)


def test_the_verb_reads_directly_and_says_why_when_no_serve_is_live(capsys):
    _qa_and_dev()

    code = _run_cli(["harness", "query", "live_qa", "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert code == 0
    assert payload["answered_by"] == {"lane": "direct_read", "serve_fallback": "no_live_serve_socket"}
    assert [row["session_id"] for row in payload["resumable"]] == [QA_ROOT]


def test_the_serve_runs_the_direct_form_so_it_never_dials_itself():
    assert harness_query.query_argv("sessions", "personainst_qa", 5) == [
        "harness", "query", "sessions", "personainst_qa", "--limit", "5", "--direct", "--json",
    ]


def test_the_verb_is_answered_by_the_running_serve_over_its_argv_lane(no_resident_registry, monkeypatch):
    """A REAL serve on REAL loopback runs the real parser. Positive control: the
    test above, same fixture, no serve -> ``direct_read``.

    The registry is installed once the serve is up, standing in for the one a
    production serve owns (this harness's serve does not boot one); the busy
    mark is what a running turn would write into it.
    """
    from tests.agent_runtime.test_serve_socket_lane import running_serve

    qa, _dev = _qa_and_dev()

    with running_serve(dispatch=_run_cli):
        serve_registry = runtime_registry.PersonaChatRuntimeRegistry()
        monkeypatch.setattr(runtime_registry, "_REGISTRY", serve_registry)
        serve_registry.transition(QA_ROOT, "busy")
        reply = harness_query.answer_routed("live_qa")

    assert reply["answered_by"]["lane"] == "serve", reply["answered_by"]
    assert reply["observer"]["runtime_observer_id"].startswith("serve:")
    assert [(row["persona_instance_id"], row["session_id"]) for row in reply["live"]] == [(qa.id, QA_ROOT)]
    assert reply["verdict"] == "live_session"


def test_persona_show_resolves_through_the_same_core(capsys):
    qa, _dev = _qa_and_dev()

    code = _run_cli(["harness", "persona", "show", "qa", "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert code == 0 and payload["persona_instance"]["persona_instance_id"] == qa.id
