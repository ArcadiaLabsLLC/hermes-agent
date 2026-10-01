"""RW3 — the chat stream tells running from hung, and a timeout from a blank card.

Between ``tool.started`` and ``tool.finished`` the protocol-v2 stream said
nothing; a 160 s silent build reached the operator as a card frozen on
"running". These drive the emitter the way the mission-chat handler does (the
runner's ``run.tool.*`` payloads) with frames captured, and pin: the started
frame's call id and deadline, the ``tool.progress`` beat with the foreground
command's pid / silence / tail, the emitter-timed duration the completion lane
cannot supply, call-id pairing, and the ``timed_out`` outcome on both the frame
and the persisted element.
"""

from __future__ import annotations

import threading
import time

import pytest

from agent_runtime import live_turns
from agent_runtime.mission_chat_turns.records import _safe_elements
from hermes_cli.harness_parts.persona import chat_events
from tools.environments import foreground_watch


@pytest.fixture
def frames(monkeypatch):
    captured: list[dict] = []
    monkeypatch.setattr(chat_events, "_emit_chat_frame", captured.append)
    return captured


@pytest.fixture
def emitter(frames):
    item = chat_events._ChatProtocolV2Emitter(turn_id="turn_1", client_message_id="client_1", emit_frames=True)
    yield item
    item.finish(state="completed")


def started(name, **extra):
    return {"type": "run.tool.started", "tool_name": name, "summary": f"Started tool {name}", **extra}


def finished(name, **extra):
    return {"type": "run.tool.finished", "tool_name": name, "status": "passed", **extra}


def of_type(frames, kind):
    return [frame for frame in frames if frame.get("type") == kind]


class _Output:
    def __init__(self, text: str) -> None:
        self.text = text

    @property
    def total_chars(self) -> int:
        return len(self.text)

    def render(self) -> str:
        return self.text


def test_started_frame_carries_call_id_and_deadline(emitter, frames):
    emitter.progress(started("terminal", tool_call_id="call_a", timeout_seconds=180, command_full="flutter build"))

    [frame] = of_type(frames, "tool.started")
    assert frame["tool_call_id"] == "call_a"
    assert frame["timeout_seconds"] == 180


def test_finished_without_a_duration_is_timed_by_the_emitter(emitter, frames):
    emitter.progress(started("terminal", tool_call_id="call_a", command_full="flutter build"))
    time.sleep(0.06)
    emitter.progress(finished("terminal", tool_call_id="call_a", command_full="flutter build"))

    [frame] = of_type(frames, "tool.finished")
    assert isinstance(frame["duration_ms"], int) and frame["duration_ms"] >= 50
    assert frame["outcome"] is None and frame["timed_out"] is False


def test_a_timeout_reaches_the_frame_and_the_persisted_element(emitter, frames):
    emitter.progress(started("terminal", tool_call_id="call_a", timeout_seconds=180, command_full="sleep 999"))
    emitter.progress(finished("terminal", tool_call_id="call_a", status="failed", outcome="timed_out",
                              timed_out=True, exit_code=124, command_full="sleep 999"))

    [frame] = of_type(frames, "tool.finished")
    assert frame["outcome"] == "timed_out"
    assert frame["timed_out"] is True
    [element] = [e for e in _safe_elements(emitter.elements) if e["kind"] == "tool"]
    assert element["outcome"] == "timed_out"
    assert element["timed_out"] is True
    assert element["timeout_seconds"] == 180
    assert "started_mono" not in element


def test_the_call_id_pairs_two_identical_concurrent_calls(emitter, frames):
    """Same tool, same command: only the call id can tell them apart. Finishing
    the SECOND first must land on the second, not FIFO on the first."""

    emitter.progress(started("terminal", tool_call_id="call_a", command_full="make"))
    emitter.progress(started("terminal", tool_call_id="call_b", command_full="make"))
    emitter.progress(finished("terminal", tool_call_id="call_b", command_full="make", output="B-OUTPUT"))

    by_call = {e["tool_call_id"]: e for e in emitter.elements if e["kind"] == "tool"}
    assert by_call["call_b"]["state"] == "finished"
    assert by_call["call_b"].get("output") == "B-OUTPUT"
    assert by_call["call_a"]["state"] == "started"


def test_the_heartbeat_reports_the_foreground_command(emitter, frames):
    key = 0xBEEF
    with live_turns.live_turn(turn_id="turn_1", session_id="s", persona_instance_id="i", agent=object()):
        live_turns.tool_started("turn_1", "call_hb", "terminal", command="flutter build", timeout_seconds=180)
        foreground_watch.publish(key, pid=4242, command="flutter build", timeout=170,
                                 owner_tid=threading.get_ident(), output=_Output("Resolving dependencies...\n"))
        try:
            emitter.progress(started("terminal", tool_call_id="call_hb", timeout_seconds=180, command_full="flutter build"))
            assert emitter._heartbeat.beat() == 1
        finally:
            foreground_watch.retract(key)

    [beat] = of_type(frames, "tool.progress")
    assert beat["tool_call_id"] == "call_hb"
    assert beat["pid"] == 4242
    # The command's ARMED deadline outranks the planned one on the started frame.
    assert beat["timeout_seconds"] == 170
    assert "Resolving dependencies" in beat["output_tail"]
    assert isinstance(beat["seconds_since_output"], float)
    assert beat["output_chars"] == len("Resolving dependencies...\n")
    assert isinstance(beat["elapsed_ms"], int)


def test_a_non_foreground_tool_beats_without_a_command(emitter, frames):
    """Positive control on the join: a live tool with no foreground command still
    beats (elapsed, deadline) and claims no pid or output."""

    emitter.progress(started("mcp__launcher_qa__mcp_launcher_qa_open_app_tab", tool_call_id="call_m"))
    assert emitter._heartbeat.beat() == 1

    [beat] = of_type(frames, "tool.progress")
    assert beat["pid"] is None and beat["output_tail"] is None and beat["seconds_since_output"] is None
    assert isinstance(beat["elapsed_ms"], int)


def test_no_beat_once_the_tool_finished(emitter, frames):
    emitter.progress(started("terminal", tool_call_id="call_a", command_full="echo"))
    emitter.progress(finished("terminal", tool_call_id="call_a", command_full="echo"))

    assert emitter._heartbeat.beat() == 0
    assert of_type(frames, "tool.progress") == []
