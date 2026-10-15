"""Native handler-entry anchor: one source, public frames/status, exact identities."""
from contextlib import closing
import json
import os
from pathlib import Path

import pytest

from agent_runtime import mission_chat_phases
from agent_runtime.chat_turn_reservations import read_chat_turn_receipt
from agent_runtime.mission_chat_phases import TurnPhaseMarks, safe_handler_anchor, safe_turn_phases, turn_timing_block
from agent_runtime.mission_chat_turns import persist_mission_chat_turn
from agent_runtime.persona_chat_durability import default_persona_session_db, ensure_persona_chat_session
from tests.agent_runtime.operator_lane_fixture import OperatorLane
from tests.agent_runtime.test_operator_conversation_attachment import call, fixture

ANCHOR = "2026-10-07T12:00:00.123456Z"
OTHER = "2026-10-07T12:03:00.654321+00:00"


@pytest.mark.parametrize("invalid", [None, True, 4, {}, [], "", "s", "2026-10-07", "2026-10-07T12:00:00", "2026-99-07T12:00:00Z", "x" * 81])
def test_one_sanitizer_drops_invalid_anchor_on_all_projections(invalid):
    assert safe_handler_anchor(invalid) is None
    assert "anchored_at" not in (safe_turn_phases({"anchored_at": invalid}) or {})
    assert "anchored_at" not in (turn_timing_block(phases={"anchored_at": invalid}, profile_timing={}) or {})


@pytest.mark.parametrize("valid", [ANCHOR, OTHER])
def test_valid_handler_stamp_is_copied_without_clock_conversion(valid):
    assert safe_handler_anchor(valid) == valid
    assert turn_timing_block(phases={"anchored_at": valid}, profile_timing={}) == {"anchored_at": valid}


def test_start_uses_supplied_handler_anchor_not_emitter_clock(monkeypatch):
    from hermes_cli.harness_parts.persona import chat_events
    frames = []
    monkeypatch.setattr(chat_events, "_emit_chat_frame", lambda payload: frames.append(payload))
    marks = TurnPhaseMarks(monotonic=lambda: 10.0, wall_now=lambda: ANCHOR)
    emitter = chat_events._ChatProtocolV2Emitter(turn_id="delayed", client_message_id="delayed", clock=lambda: 999.0, turn_phases=marks)
    try:
        start = frames[0]
        assert start["type"] == "turn.start"
        assert start["anchored_at"] == marks.anchored_at == ANCHOR
        assert start["turn_id"] == start["client_message_id"] == "delayed"
    finally:
        emitter.finish(state="complete")


@pytest.mark.parametrize("anchor", ["not a stamp", "2026-10-07T12:00:00", None])
def test_start_omits_invalid_or_absent_handler_stamp(monkeypatch, anchor):
    from types import SimpleNamespace
    from hermes_cli.harness_parts.persona import chat_events
    frames = []
    monkeypatch.setattr(chat_events, "_emit_chat_frame", frames.append)
    emitter = chat_events._ChatProtocolV2Emitter(turn_id="invalid", client_message_id="invalid", turn_phases=SimpleNamespace(anchored_at=anchor))
    try:
        assert "anchored_at" not in frames[0]
    finally:
        emitter.finish(state="complete")


def test_legacy_emitter_does_not_invent_anchor(monkeypatch):
    from hermes_cli.harness_parts.persona import chat_events
    frames = []
    monkeypatch.setattr(chat_events, "_emit_chat_frame", lambda payload: frames.append(payload))
    emitter = chat_events._ChatProtocolV2Emitter(turn_id="old", client_message_id=None, clock=lambda: 999.0)
    try:
        assert "anchored_at" not in frames[0]
    finally:
        emitter.finish(state="complete")


@pytest.mark.parametrize("corruption", ["turn", "root", "old", "invalid", "missing-admission"])
def test_status_does_not_borrow_another_identity_or_invent_anchor(tmp_path, monkeypatch, corruption):
    target = fixture(tmp_path / "home", monkeypatch, "Anchor")
    params = {**target, "turn_request_id": "named", "message": "Work"}
    lane = OperatorLane(tmp_path / "home", lambda _: 0)
    if corruption != "missing-admission":
        assert lane.rpc("runtime.chat.message", params)["result"]["accepted"]
    metadata = {"root_chat_session_id": target["session_id"], "phases": {"anchored_at": ANCHOR}}
    if corruption == "root": metadata["root_chat_session_id"] = "other-root"
    if corruption == "old": metadata.pop("phases")
    if corruption == "invalid": metadata["phases"]["anchored_at"] = "bad stamp"
    persist_mission_chat_turn(session_id=target["session_id"], client_message_id="named", turn_id="other-turn" if corruption == "turn" else "named", elements=[], state="running", metadata=metadata)
    response = call("status", params)["result"]
    assert "anchored_at" not in response.get("timing", {})
    assert "anchored_at" not in call("status", {**params, "turn_request_id": "absent"})["result"].get("timing", {})


def test_two_named_turns_and_roots_keep_original_anchor_on_replay(tmp_path, monkeypatch):
    target = fixture(tmp_path / "home", monkeypatch, "Anchor")
    lane = OperatorLane(tmp_path / "home", lambda _: 0)
    for key, anchor in [("first", ANCHOR), ("second", OTHER)]:
        params = {**target, "turn_request_id": key, "message": "Work"}
        assert lane.rpc("runtime.chat.message", params)["result"]["accepted"]
        persist_mission_chat_turn(session_id=target["session_id"], client_message_id=key, turn_id=key, elements=[], state="completed", metadata={"root_chat_session_id": target["session_id"], "phases": {"anchored_at": anchor}})
        before = read_chat_turn_receipt(key)
        assert call("status", params)["result"]["timing"]["anchored_at"] == anchor
        assert lane.rpc("runtime.chat.message", params)["result"]["idempotent_replay"]
        assert read_chat_turn_receipt(key) == before
    assert call("status", {**target, "turn_request_id": "first"})["result"]["timing"]["anchored_at"] == ANCHOR
    # Another installation/root cannot adopt this identity's wall stamp.
    other = fixture(tmp_path / "other", monkeypatch, "Other")
    assert "anchored_at" not in call("status", {**other, "turn_request_id": "first"})["result"].get("timing", {})
    assert "error" in call("status", {**target, "turn_request_id": "first"})


def test_real_handler_start_terminal_and_native_status_share_anchor(tmp_path, monkeypatch, capsys, isolate_agent_runtime_root):
    from agent_runtime import paths
    from agent_runtime.gateway_identity import ensure_install_identity
    from agent_runtime.persona_assignments import PersonaInstanceStore
    from agent_runtime.workspace_scope import effective_workspace_id
    from hermes_cli.harness_parts.persona import chat_turn_message
    from tests.hermes_cli.test_mission_chat_budget_payload import _seed
    from tests.hermes_cli.test_mission_chat_turn_phases import _args, _streaming_provider
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setenv("HERMES_HEAD_HOME", str(home))
    monkeypatch.setenv("HERMES_AGENT_RUNTIME_ROOT", str(home / "runtime"))
    install = ensure_install_identity(paths.store_root()).install_id
    statuses = []
    target = {}
    base_provider = _streaming_provider()
    class Provider(base_provider):
        def mission_chat_reply(self, *args, **kwargs):
            statuses.append(call("status", target)["result"])
            return super().mission_chat_reply(*args, **kwargs)
    _seed(monkeypatch, Provider)
    monkeypatch.setattr(chat_turn_message, "_default_persona_session_db", default_persona_session_db)
    args = _args("handler-anchor", stream=True)
    args.session_id += "_123456abcdef"
    with closing(default_persona_session_db()) as db:
        ensure_persona_chat_session(session_db=db, session_id=args.session_id, persona_id="dev", required=True)
    real_marks = TurnPhaseMarks
    created = []
    def marks_factory():
        marks = real_marks(monotonic=lambda: 10.0, wall_now=lambda: ANCHOR)
        created.append(marks)
        return marks
    monkeypatch.setattr(mission_chat_phases, "TurnPhaseMarks", marks_factory)
    def dispatch(argv):
        # The real handler resolves its instance before the provider callback.
        return chat_turn_message._cmd_mission_chat_message(args)
    lane = OperatorLane(home, dispatch)
    params = {"persona_id": "dev", "session_id": args.session_id, "turn_request_id": "handler-anchor", "message": args.message, "stream": True}
    ack = lane.rpc("runtime.chat.message", params)["result"]
    assert ack["accepted"] and "anchored_at" not in ack
    # Persisted persona projection supplies the immutable attachment identity.
    from agent_runtime.config import ensure_persisted_personas, AgentRuntimeConfig
    store = PersonaInstanceStore()
    store.ensure_for_personas(ensure_persisted_personas(AgentRuntimeConfig()))
    instance = store.get("personainst_dev")
    target.update(install_id=install, workspace_id=effective_workspace_id(instance, active_workspace_id=None), persona_id="dev", persona_instance_id=instance.id, session_id=args.session_id, turn_request_id="handler-anchor")
    lane.advance()
    captured = capsys.readouterr()
    frames = [json.loads(line) for line in captured.out.splitlines() if line.strip().startswith("{")]
    assert any(frame.get("type") == "turn.start" for frame in frames), captured.out
    start = next(frame for frame in frames if frame.get("type") == "turn.start")
    terminal = next(frame for frame in frames if frame.get("type") == "chat.final")
    status = call("status", target)["result"]
    assert len(created) == 1
    assert start["anchored_at"] == terminal["timing"]["anchored_at"] == statuses[0]["timing"]["anchored_at"] == status["timing"]["anchored_at"] == created[0].anchored_at == ANCHOR
    assert start["turn_id"] == terminal["turn_id"] == status["turn_request_id"] == "handler-anchor"
    assert statuses[0]["outcome"] == "unsettled" and status["outcome"] == "finished"
    assert lane.rpc("runtime.chat.message", params)["result"]["idempotent_replay"]
    assert lane.jobs == []
    assert call("status", target)["result"]["timing"]["anchored_at"] == ANCHOR
    proof_path = os.environ.get("HERMES_ANCHOR_PROOF_OUTPUT")
    if proof_path:
        Path(proof_path).write_text(json.dumps({"ack": ack, "start": start, "terminal": terminal, "running_status": statuses[0], "terminal_status": status}, indent=2)+"\n", encoding="utf-8")
