"""A chat turn records who sent it, from where and when it started, once (TASK-ONE-TURN-RECORD).

``hermes_cli/harness_parts/persona/chat_turn_commit/turn_record.py`` takes the record when the
turn is admitted; the write-ahead journal record's ``started_at``, the active-turn hand-off the
steer watcher keeps (``active.json`` ``send_args``) and the leftover-steer queues read it.

The handler, lease, steer watcher, journal and send queue are the production ones (the same rig
as ``test_dead_turn_steer_boot_requeue.py``); the provider is stubbed. Mutations, each seen red:

* ``run.py`` hands the steer watcher ``send_origin()`` again instead of the record's origin →
  ``test_the_active_turn_keeps_the_sender_it_was_admitted_with`` reddens (the later read);
* ``turn_record._admitted_origin`` reads ``send_origin()`` before the carried origin →
  ``test_a_queued_run_is_recorded_as_its_queued_sender`` reddens;
* ``run.py::_write_ahead`` drops ``started_at=`` (or ``journal.transition_mission_chat_turn``
  stamps its own clock regardless) → ``test_the_journal_start_is_the_admission_instant`` reddens;
* a ``send_origin(`` call is added under ``chat_turn_commit/`` outside the record →
  ``test_no_turn_phase_rereads_the_serve_request`` reddens.
"""

from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent_runtime import chat_root_send_queue, paths
from agent_runtime.mission_chat_steer import roots_owing_steers, submit_mission_chat_steer
from agent_runtime.mission_chat_turns import mission_chat_turn_record
from hermes_cli.harness_parts.persona.chat_turn_commit import TurnCommit, run as commit_run
from hermes_cli.harness_parts.persona.chat_turn_commit.turn_record import admit_turn_record
from hermes_cli.harness_parts.serve import queued_turn_origin
from tests.agent_runtime.test_chat_lease_finalization_tail import ROOT, _install_chat_lane
from tests.agent_runtime.test_persona_assignments_chat_history import _mission_chat_test_args

pytestmark = pytest.mark.usefixtures("persisted_persona_samples")

ORIGIN = chat_root_send_queue.ORIGIN_ARG
PHONE = {"owner": "conn-phone", "gateway": True}
ADMITTED_AT = "2026-11-15T01:02:03.000004+00:00"


class _Agent:
    def steer(self, text) -> bool:
        return True


def _run_a_turn_that_dies_holding_a_steer(monkeypatch, args, *, during_turn=None) -> None:
    """``args`` through the real handler; it accepts one steer and dies, so ``active.json`` stays."""

    handler = _install_chat_lane(monkeypatch)

    class _Provider:
        def __init__(self, *a, **k):
            pass

        def mission_chat_reply(self, persona, message, **kwargs):
            if during_turn is not None:
                during_turn()
            kwargs["agent_ready_callback"](_Agent())
            ack = submit_mission_chat_steer(
                runtime_root=paths.store_root(), session_id=ROOT, message="one more thing",
                client_message_id="cm-steer")
            assert ack["ok"] is True, ack
            raise RuntimeError("the process was killed here")

    monkeypatch.setattr(commit_run, "GPTPersonaRuntime", _Provider)
    monkeypatch.setattr(TurnCommit, "_queue_leftover_steer", lambda self, **kwargs: None)
    assert handler._cmd_mission_chat_message(args) != 0


def _kept_origin() -> dict:
    (owed,) = roots_owing_steers(runtime_root=paths.store_root())
    return owed["send_args"][ORIGIN]


def test_the_active_turn_keeps_the_sender_it_was_admitted_with(monkeypatch, isolate_agent_runtime_root):
    """A direct send from a paired device: the serve request names it at admission and only then."""

    live = {"origin": dict(PHONE)}
    monkeypatch.setattr(queued_turn_origin, "send_origin", lambda: dict(live["origin"]))

    def _the_request_context_moves_on():
        live["origin"] = {"owner": "conn-someone-else", "gateway": False}

    _run_a_turn_that_dies_holding_a_steer(
        monkeypatch, _mission_chat_test_args("cm-direct", stream=True), during_turn=_the_request_context_moves_on)

    assert _kept_origin() == PHONE


def test_a_queued_run_is_recorded_as_its_queued_sender(monkeypatch, isolate_agent_runtime_root):
    """The runner runs a queued send with no serve request of its own: the entry's origin is the sender."""

    monkeypatch.setattr(queued_turn_origin, "send_origin", lambda: {"owner": None, "gateway": False})
    args = _mission_chat_test_args("cm-queued", stream=True)
    setattr(args, ORIGIN, dict(PHONE))

    record = admit_turn_record(args)
    assert dict(record.origin) == PHONE
    assert record.requested_by == "test"

    _run_a_turn_that_dies_holding_a_steer(monkeypatch, args)
    assert _kept_origin() == PHONE


def test_the_journal_start_is_the_admission_instant(monkeypatch, isolate_agent_runtime_root):
    import agent_runtime.clock as clock

    real_now = clock.now_iso_micro
    stamps = iter([ADMITTED_AT])
    # Only the record's own read gets the admission stamp; every later clock read is the real one.
    monkeypatch.setattr(clock, "now_iso_micro", lambda: next(stamps, None) or real_now())

    _run_a_turn_that_dies_holding_a_steer(monkeypatch, _mission_chat_test_args("cm-start", stream=True))

    record = mission_chat_turn_record(session_id=ROOT, client_message_id="cm-start")
    assert isinstance(record, dict), record
    assert record["started_at"] == ADMITTED_AT


def test_the_record_is_frozen():
    record = admit_turn_record(SimpleNamespace(requested_by=None, **{ORIGIN: dict(PHONE)}), now=ADMITTED_AT)
    with pytest.raises(Exception):
        record.origin["owner"] = "someone"  # type: ignore[index]
    with pytest.raises(Exception):
        record.started_at = "later"  # type: ignore[misc]
    assert record.requested_by is None and record.started_at == ADMITTED_AT


#: SHRINK-ONLY, started at today's count (2026-11-15): turn phases that read the serve request's
#: sender again instead of the admission record. Lower it when one goes; never raise it.
SEND_ORIGIN_REREADS_CEILING = 0


def test_no_turn_phase_rereads_the_serve_request():
    package = Path(commit_run.__file__).parent
    rereads = [
        f"{path.name}:{number}"
        for path in sorted(package.glob("*.py")) if path.name != "turn_record.py"
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if re.search(r"\bsend_origin\s*\(", line)
    ]
    assert len(rereads) <= SEND_ORIGIN_REREADS_CEILING, (
        "a turn phase re-reads its sender off the serve request; take it from self.turn_record: "
        + ", ".join(rereads))
