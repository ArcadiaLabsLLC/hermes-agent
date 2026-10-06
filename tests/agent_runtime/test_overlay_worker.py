"""Lane h-overlay-worker: the ``persona_chat_turn`` overlay read leaves the serve's GIL.

* C1 through the worker: the resident snapshot worker's sections for a root equal
  the in-process read's, the serve's chat-runtime observations included (the
  worker owns no resident chat, so its own registry would answer nothing true);
* a lost worker reads in process; a read the worker raised on demotes;
* the watchdog's tail(1) guard and its append are one step: two lanes racing
  one fingerprint append it once;
* a new chat's open rides the overlay for a room that declared
  ``persona_chat_open``, carrying the root the 50-row history bound now omits.
"""

from __future__ import annotations

import os
import threading
import time

import pytest

from agent_runtime.events import EventLog
from agent_runtime.patch_coverage import (
    HISTORICAL_FOLD_ENTITIES,
    PERSONA_CHAT_OPEN_CAPABILITY,
    PERSONA_CHAT_TURN_CAPABILITY,
)
from agent_runtime.persona_chat_continuity.runtime_registry import (
    initialize_persona_chat_runtime_registry,
)
from agent_runtime.snapshot_worker import executor as executor_mod
from agent_runtime.snapshot_worker.peer import WorkerLoss, WorkerLost
from agent_runtime.stream import batch_turn_roots, persona_chat_turn_frames
from agent_runtime.stream.frames import _append_state_reconciled
from agent_runtime.turn_section_read import read_turn_sections
from tests.agent_runtime.test_stream_turn_section import (  # noqa: F401  (``home`` is a fixture)
    INSTANCE,
    PERSONA,
    ROOT,
    DECLARING,
    _BuildCounter,
    _Turn,
    _event,
    _batch_since,
    _gate,
    _log_end,
    _seed_chat,
    home,
)

OPENING = sorted(set(DECLARING) | {PERSONA_CHAT_OPEN_CAPABILITY})


@pytest.fixture(autouse=True)
def _unbound():
    executor_mod.unbind()
    yield
    executor_mod.unbind()
    initialize_persona_chat_runtime_registry(enabled=False)


def _home():
    from pathlib import Path

    from hermes_constants import get_hermes_home

    return Path(get_hermes_home())


def _unclocked(value):
    """``value`` minus the observation clock (``runtime_observed_at`` is read time),
    wherever a history row is carried (the row itself, the channel's copy)."""

    if isinstance(value, dict):
        return {k: _unclocked(v) for k, v in value.items() if k != "runtime_observed_at"}
    if isinstance(value, list):
        return [_unclocked(item) for item in value]
    return value


def _differing(left, right, path=""):
    if isinstance(left, dict) and isinstance(right, dict):
        return [p for key in sorted(set(left) | set(right))
                for p in _differing(left.get(key), right.get(key), f"{path}.{key}")]
    if isinstance(left, list) and isinstance(right, list) and len(left) == len(right):
        return [p for i, (a, b) in enumerate(zip(left, right)) for p in _differing(a, b, f"{path}[{i}]")]
    return [] if left == right else [f"{path}: {str(left)[:120]} != {str(right)[:120]}"]


# ── C1 through the worker ─────────────────────────────────────────────────────


@pytest.mark.timeout(240)
def test_the_workers_sections_are_the_in_process_sections(isolate_agent_runtime_root, home):
    """*Killing mutation:* drop ``recorded_runtime_registry`` from the child's
    ``handle_turn_section`` → the worker's row reads ``unknown`` / ``external_cli``
    where the serve's registry says ``hot`` / ``serve:<pid>`` → red."""

    _seed_chat()
    registry = initialize_persona_chat_runtime_registry()
    registry.transition(ROOT, "hot")
    in_process, _timings = read_turn_sections(ROOT, named=(INSTANCE,), evict=1)
    binding = executor_mod.WorkerBinding(_home())
    try:
        execution = binding.turn_section(ROOT, named=(INSTANCE,), evict=1)
    finally:
        binding.close()
    assert execution is not None and execution.executor == "worker"
    assert execution.worker_pid and execution.worker_pid != os.getpid()
    assert {"history_ms", "trace_ms"} <= set(execution.timings)
    row = execution.sections["persona_chat_history"]
    assert row["runtime_state"] == "hot" and row["runtime_observer_id"] == f"serve:{os.getpid()}"
    assert _unclocked(execution.sections) == _unclocked(in_process), _differing(
        _unclocked(execution.sections), _unclocked(in_process))


@pytest.mark.timeout(240)
def test_a_bound_worker_reads_the_frame_and_says_so(isolate_agent_runtime_root, home, caplog):
    _seed_chat()
    start = _log_end()
    _Turn("turn-worker").start()
    batch = _batch_since(start)
    roots = batch_turn_roots(batch)
    in_process = persona_chat_turn_frames(batch, roots, base_offset=start, caller="hub")
    from agent_runtime import turn_section_reuse

    turn_section_reuse.clear()
    assert executor_mod.bind(_home())
    caplog.set_level("INFO")
    in_worker = persona_chat_turn_frames(batch, roots, base_offset=start, caller="hub")
    strip = lambda frame: {k: v for k, v in _unclocked(frame).items() if k not in {"generated_at", "watermark", "running_work"}}  # noqa: E731
    assert [strip(f) for f in in_worker] == [strip(f) for f in in_process]
    receipts = [r.getMessage() for r in caplog.records if r.getMessage().startswith("turn_section ")]
    assert receipts and " executor=worker " in receipts[-1] and " pid=" in receipts[-1]
    assert list(in_worker[0]).index("running_work") < list(in_worker[0]).index("omitted")


class _FakePeer:
    def __init__(self, loss: WorkerLoss) -> None:
        self.loss = loss
        self.alive = True
        self.pid = 4242
        self.process = self

    def turn_section(self, params, *, timeout):
        raise WorkerLost(self.loss)

    def kill(self):
        self.alive = False

    def close(self):
        self.alive = False


def test_a_lost_worker_reads_in_process_and_a_raised_read_demotes(isolate_agent_runtime_root, home):
    _seed_chat()
    start = _log_end()
    _Turn("turn-lost").start()
    batch = _batch_since(start)
    roots = batch_turn_roots(batch)

    executor_mod.bind(_home(), start=lambda _home: _FakePeer(WorkerLoss.EXITED))
    frames = persona_chat_turn_frames(batch, roots, base_offset=start)
    assert frames is not None and frames[0]["persona_instance_id"] == INSTANCE

    from agent_runtime import turn_section_reuse

    turn_section_reuse.clear()
    executor_mod.unbind()
    executor_mod.bind(_home(), start=lambda _home: _FakePeer(WorkerLoss.BUILD_ERROR))
    assert persona_chat_turn_frames(batch, roots, base_offset=start) is None


# ── the watchdog's duplicate guard ────────────────────────────────────────────


class _SlowLog:
    """A log whose tail read is slow enough for a second lane to read the same tail."""

    def __init__(self) -> None:
        self.events = []

    def tail(self, n):
        seen = self.events[-n:]
        time.sleep(0.05)
        return seen

    def append(self, event):
        self.events.append(event)


def test_two_lanes_reconcile_one_fingerprint_once():
    """*Killing mutation:* take the append out of ``_RECONCILE_APPEND_LOCK`` (or
    drop the lock) → both lanes read the same tail before either appends → two
    ``state.reconciled`` → red."""

    log = _SlowLog()
    attribution = {"families": ["chat_db"], "chat_roots": [ROOT]}
    lanes = [
        threading.Thread(target=_append_state_reconciled, args=(log, "fp-1", attribution))
        for _ in range(2)
    ]
    for lane in lanes:
        lane.start()
    for lane in lanes:
        lane.join(5)
    assert [event.payload["fingerprint"] for event in log.events] == ["fp-1"]


# ── a new chat's open rides the overlay ───────────────────────────────────────


def _session_root(index: int) -> str:
    return f"persona_chat_{INSTANCE}_{index:012x}"


def _seed_full_history():
    """The bound chat plus 49 idle chats: exactly the 50 rows the bound keeps."""

    from agent_runtime.persona_chat_durability import (
        default_persona_session_db,
        ensure_persona_chat_session,
    )

    _seed_chat()
    db = default_persona_session_db()
    for index in range(1, 50):
        assert ensure_persona_chat_session(
            session_db=db, session_id=_session_root(index), persona_id=PERSONA,
            title=f"idle {index}", required=True,
        )
    return db


@pytest.mark.timeout(120)
def test_a_new_chats_open_rides_the_overlay_and_names_the_evicted_root(
    isolate_agent_runtime_root, home, monkeypatch
):
    """*Killing mutation:* drop the ``opens`` arm of ``batch_turn_roots`` → the
    open's ``chat_opened`` refuses the batch → a ``delta`` with a led core → red."""

    from agent_runtime.persona_assignments import PersonaInstanceStore
    from agent_runtime.persona_chat_durability import ensure_persona_chat_session
    from agent_runtime.snapshot import build_snapshot
    from agent_runtime.serde import to_jsonable

    db = _seed_full_history()
    new_root = _session_root(0xABC)
    start = _log_end()
    PersonaInstanceStore().open_chat(persona_id=PERSONA, session_id=new_root)
    assert ensure_persona_chat_session(
        session_db=db, session_id=new_root, persona_id=PERSONA, title="new", required=True
    )
    _Turn("turn-open", root=new_root).start()
    batch = _batch_since(start)
    types = [event.type for _, event in batch]
    assert "persona_instance.chat_opened" in types

    assert batch_turn_roots(batch) is None
    assert batch_turn_roots(batch, opens=True) == [(new_root, batch[-1][0])]

    builds = _BuildCounter(monkeypatch)
    frames = _gate(batch, start=start, accepted=OPENING)
    assert [frame["type"] for frame in frames] == ["persona_chat_turn"]
    assert builds.calls == 0
    frame = frames[0]
    assert frame["root_chat_session_id"] == new_root
    assert frame["persona_instance"]["default_chat_session_id"] == new_root

    core = to_jsonable(build_snapshot())
    kept = {row["session_id"] for row in core["persona_chat_history"]}
    assert new_root in kept and len(kept) == 50
    assert frame["evicted_roots"] and not set(frame["evicted_roots"]) & kept
    seeded = {ROOT, new_root, *(_session_root(index) for index in range(1, 50))}
    assert seeded - kept == set(frame["evicted_roots"])

    # A room that declared only the turn token keeps today's core for the open.
    from agent_runtime import turn_section_reuse

    turn_section_reuse.clear()
    demoted = [f for f in _gate(batch, start=start, accepted=DECLARING) if f["type"] != "heartbeat"]
    assert [f["type"] for f in demoted] == ["delta"]


def test_an_open_only_covers_the_instance_it_opened():
    from datetime import datetime, timezone

    from agent_runtime.models import Event

    def event(event_type, payload):
        return Event(ts=datetime.now(timezone.utc), type=event_type, task_id=None, run_id=None,
                     persona_id=PERSONA, payload=payload, session_id=None)

    opened = event("persona_instance.chat_opened", {"persona_instance_id": INSTANCE, "session_id": ROOT})
    window = lambda *events: [(index + 1, item) for index, item in enumerate(events)]  # noqa: E731
    patch = lambda **extra: event("state.patched", {"entity": "persona_instance", "id": INSTANCE, "op": "upsert", **extra})  # noqa: E731
    assert batch_turn_roots(window(patch(), opened), opens=True) == [(ROOT, 2)]
    for refused in (
        event("state.patched", {"entity": "persona_instance", "id": "personainst_other", "op": "upsert"}),
        patch(created=True),
        event("state.patched", {"entity": "persona_instance", "id": INSTANCE, "op": "refresh"}),
        event("state.patched", {"entity": "office_actor", "id": "ws/actor", "op": "upsert"}),
    ):
        assert batch_turn_roots(window(refused, opened), opens=True) is None, refused.payload
    assert PERSONA_CHAT_TURN_CAPABILITY in DECLARING and set(HISTORICAL_FOLD_ENTITIES) <= set(OPENING)


# ── no stand-aside in the worker; the start section is read once ──────────────


@pytest.mark.timeout(240)
def test_a_worker_read_does_not_stand_aside_for_a_hot_window(isolate_agent_runtime_root, home, monkeypatch, caplog):
    """Live 01:25 (main b3205d4725): every start section waited 2.4-3.6 s, 1.2-2.5 s
    of it ``yielded_ms``. In the worker the read holds no serve GIL, so it must not wait.

    *Killing mutation:* wrap the worker call in ``build_yield_scope`` + a yield
    point → the hot window is polled and the read waits → red.
    """

    import agent_runtime.turn_activity as turn_activity

    _seed_chat()
    start = _log_end()
    _Turn("turn-hot-worker").start()
    batch = _batch_since(start)
    assert executor_mod.bind(_home())
    assert executor_mod.execute_turn_section(ROOT, named=(INSTANCE,)) is not None  # warm the worker
    polls = {"n": 0}

    def _always_hot():
        polls["n"] += 1
        return 1

    monkeypatch.setattr(turn_activity, "hot_turn_windows", _always_hot)
    caplog.set_level("INFO")
    frames = persona_chat_turn_frames(batch, batch_turn_roots(batch), base_offset=start)
    assert frames is not None
    assert polls["n"] == 0
    line = next(r.getMessage() for r in caplog.records if r.getMessage().startswith("turn_section "))
    fields = dict(token.split("=", 1) for token in line.split() if "=" in token)
    assert fields["executor"] == "worker" and fields["yielded_ms"] == "-"
    assert int(fields["waited_ms"]) < 1000, line


@pytest.mark.timeout(120)
def test_the_second_lanes_start_section_is_the_first_lanes_read(isolate_agent_runtime_root, home, monkeypatch):
    """The second lane's start batch closes WHILE the first lane stands aside
    (the turn appended past the first lane's batch): the first lane takes its
    position after the wait, so one read covers both lanes.

    *Killing mutation:* take the position before the stand-aside (the old
    order) → the second lane's floor is past it → it reads again → red.
    """

    import agent_runtime.stream.frames as frames_module
    import agent_runtime.turn_activity as turn_activity
    from agent_runtime import turn_section_reuse

    _seed_chat()
    start = _log_end()
    _Turn("turn-two-lanes").start()
    first_batch = _batch_since(start)
    roots = batch_turn_roots(first_batch)
    hot = threading.Event()
    hot.set()
    monkeypatch.setattr(turn_activity, "hot_turn_windows", lambda: 1 if hot.is_set() else 0)
    reads = []
    real = frames_module.read_turn_sections
    monkeypatch.setattr(frames_module, "read_turn_sections", lambda *a, **k: reads.append(a) or real(*a, **k))
    turn_section_reuse.clear()
    out = {}
    first = threading.Thread(target=lambda: out.setdefault(
        "hub", persona_chat_turn_frames(first_batch, roots, base_offset=start, caller="hub")))
    first.start()
    time.sleep(0.3)  # the hub lane is standing aside
    EventLog().append(_event("run.progress", session_id=ROOT, payload={"message": "thinking"}))
    second_batch = _batch_since(start)
    second = threading.Thread(target=lambda: out.setdefault("cli", persona_chat_turn_frames(
        second_batch, batch_turn_roots(second_batch), base_offset=start, caller="cli")))
    second.start()
    time.sleep(0.3)
    hot.clear()
    first.join(30)
    second.join(30)
    assert out["hub"] and out["cli"]
    assert len(reads) == 1
    assert out["cli"][0]["watermark"]["event_offset"] == second_batch[-1][0]
