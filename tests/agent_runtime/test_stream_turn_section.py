"""A chat turn's batch ships one ``persona_chat_turn`` frame per root, not a core.

Plan h-turn1 §2 C1/C2 (``docs/agent-runtime-harness/planned/turn-latency-h-turn1-2026-10-05.md``).
Measured live 2026-10-05: every turn demoted the stream to a full core on each
of the two subscribers (2.2–3.6 s of build, 3–13 s of wait, per core), because
``persona_chat.turn_started`` / ``.turn_ended`` are uncovered. A subscriber that
declares ``persona_chat_turn`` is now handed the root's sections instead, read
by the core's own builders — and these cases pin that those sections ARE the
core's rows, that the batch rule refuses anything outside a turn, and that a
subscriber that did not declare still gets today's frames.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

import agent_runtime.stream as stream_mod
from agent_runtime import running_work, turn_section_reuse
from agent_runtime.chat_turn_presence import ChatTurnPresence
from agent_runtime.events import EventLog
from agent_runtime.models import Event
from agent_runtime.patch_coverage import HISTORICAL_FOLD_ENTITIES, PERSONA_CHAT_TURN_CAPABILITY
from agent_runtime.serde import to_jsonable
from agent_runtime.stream import batch_turn_roots, persona_chat_turn_frames, stream_frames
from agent_runtime.stream.build import _batch_frames_with_liveness
from tests._downstream.split_package_source import patch_where_bound
from tests.agent_runtime.stream_liveness_helpers import is_boot_liveness

PERSONA = "dev"
INSTANCE = "personainst_dev"
ROOT = f"persona_chat_{INSTANCE}_0123456789ab"
OTHER_ROOT = f"persona_chat_{INSTANCE}_fedcba987654"
DECLARING = sorted(HISTORICAL_FOLD_ENTITIES | {PERSONA_CHAT_TURN_CAPABILITY})


@pytest.fixture
def home(tmp_path, monkeypatch):
    head = tmp_path / "home"
    head.mkdir(parents=True, exist_ok=True)
    for module in (
        running_work.rows,
        running_work.ownership,
        running_work.lanes_process,
        running_work.lanes_chat,
        running_work.surface,
    ):
        if "_head_home" in vars(module):
            monkeypatch.setattr(module, "_head_home", lambda: (head, "test_home"))
    turn_section_reuse.clear()
    yield head
    turn_section_reuse.clear()


def _seed_chat(root: str = ROOT, *, messages: int = 2):
    """A real instance bound to a real, durable chat root with real messages."""

    from agent_runtime.persona_assignments import PersonaInstanceStore
    from agent_runtime.persona_chat_durability import (
        default_persona_session_db,
        ensure_persona_chat_session,
    )

    instance = PersonaInstanceStore().open_chat(persona_id=PERSONA, session_id=root)
    db = default_persona_session_db()
    assert ensure_persona_chat_session(
        session_db=db, session_id=root, persona_id=PERSONA, title="turn section", required=True
    )
    for index in range(messages):
        db.append_message(root, "user" if index % 2 == 0 else "assistant", f"message {index}")
    return instance


def _event(event_type: str, *, root: str = ROOT, session_id: str | None = None, payload=None) -> Event:
    return Event(
        ts=datetime.now(timezone.utc),
        type=event_type,
        task_id=None,
        run_id=None,
        persona_id=PERSONA,
        payload=dict(payload or {"persona_instance_id": INSTANCE, "root_chat_session_id": root}),
        session_id=session_id,
    )


class _Turn:
    def __init__(self, turn_id: str, root: str = ROOT) -> None:
        self.turn_id = turn_id
        self.root = root
        self.presence = ChatTurnPresence()

    def start(self) -> None:
        assert self.presence.publish_started(
            session_id=self.root,
            client_message_id=self.turn_id,
            turn_id=self.turn_id,
            persona_id=PERSONA,
            persona_instance_id=INSTANCE,
            active_session_id=self.root,
        )

    def end(self) -> None:
        EventLog().append(
            _event(
                "persona_chat.projected",
                root=self.root,
                session_id=self.root,
                payload={
                    "persona_instance_id": INSTANCE,
                    "root_chat_session_id": self.root,
                    "client_message_id": self.turn_id,
                    "turn_id": self.turn_id,
                    "change_kind": "reply",
                },
            )
        )
        assert self.presence.publish_ended()


def _batch_since(offset: int) -> list[tuple[int, Event]]:
    return [(int(o), e) for o, e in EventLog().iter_from_offset(offset)]


def _log_end() -> int:
    batch = _batch_since(0)
    return batch[-1][0] if batch else 0


# ── C2: the batch rule ────────────────────────────────────────────────────────


def _window(*types_and_sessions):
    return [(index + 1, event) for index, event in enumerate(types_and_sessions)]


def test_the_six_turn_windows_of_c0_1_classify_as_measured():
    """C0.1's shapes: four warm turns name their root; the two cold Neko turns,
    which carried ``gateway.peer.updated``, refuse (ruling C2-r3).

    *Killing mutation:* let ``gateway.peer.updated`` (any event outside the six
    turn types) through → the two cold windows return a root → red.
    """

    start = _window(_event("persona_chat.turn_started"))
    trace_end = _window(
        _event("run.progress", session_id=ROOT, payload={"message": "x"}),
        _event("run.tool.started", session_id=ROOT, payload={"tool": "t"}),
        _event("run.tool.finished", session_id=ROOT, payload={"tool": "t"}),
        _event("persona_chat.projected"),
        _event("persona_chat.turn_ended"),
    )
    end = _window(_event("persona_chat.projected"), _event("persona_chat.turn_ended"))
    trace_only = _window(_event("run.progress", session_id=ROOT, payload={"message": "y"}))
    for warm in (start, trace_end, end, trace_only):
        assert batch_turn_roots(warm) == [(ROOT, len(warm))]
    peer = _event("gateway.peer.updated", payload={"peer_id": "p"})
    cold_start = _window(peer, _event("persona_chat.turn_started"))
    cold_end = _window(_event("persona_chat.projected"), peer, _event("persona_chat.turn_ended"))
    assert batch_turn_roots(cold_start) is None
    assert batch_turn_roots(cold_end) is None


def test_anything_outside_a_turn_refuses_the_batch():
    assert batch_turn_roots([]) is None
    # A session-less run.* is a task-run trace, not a chat turn's.
    assert batch_turn_roots(_window(_event("run.progress", payload={"message": "z"}))) is None
    patched = _event("state.patched", payload={"entity": "persona_instance", "id": INSTANCE, "op": "upsert"})
    assert batch_turn_roots(_window(_event("persona_chat.turn_started"), patched)) is None
    rootless = _event("persona_chat.turn_started", payload={"persona_instance_id": INSTANCE})
    assert batch_turn_roots(_window(rootless)) is None


def test_two_roots_are_ordered_by_their_last_event_and_chain():
    batch = _window(
        _event("persona_chat.turn_ended", root=OTHER_ROOT),
        _event("persona_chat.turn_ended", root=ROOT),
        _event("run.progress", session_id=OTHER_ROOT, payload={"message": "late"}),
    )
    assert batch_turn_roots(batch) == [(ROOT, 2), (OTHER_ROOT, 3)]


# ── C1: the overlay equals the core's rows ────────────────────────────────────


def _core_rows(core: dict, root: str, instance_id: str) -> dict:
    core = to_jsonable(core)
    history = [row for row in core["persona_chat_history"] if row.get("session_id") == root]
    channel = next(
        row for row in core["operator_channels"].values() if row.get("persona_instance_id") == instance_id
    )
    return {
        "persona_chat_history": history[0] if history else None,
        "operator_channel": channel,
        "persona_instance": core["persona_instances"][instance_id],
        "running_work_rows": core["running_work"]["rows"],
    }


def test_the_overlay_is_the_full_cores_rows_for_its_root(isolate_agent_runtime_root, home):
    """The C0.3 equality, against a real core built at the same position.

    *Killing mutation:* narrow the history by session BEFORE the creation-order
    bound (``only_session_ids`` applied to the candidates instead of the visible
    slice) — with a second, newer chat on the same instance and a bound of one,
    the root's row hydrates in the overlay while the core omits it → red in
    ``test_a_root_outside_the_bound_ships_the_cores_omission``; here the rows
    themselves are compared field for field.
    """

    from agent_runtime.snapshot import build_snapshot

    instance = _seed_chat()
    start = _log_end()
    turn = _Turn("turn-equal")
    turn.start()
    turn.end()
    batch = _batch_since(start)
    roots = batch_turn_roots(batch)
    assert roots == [(ROOT, batch[-1][0])]

    core = build_snapshot()
    frames = persona_chat_turn_frames(batch, roots, base_offset=start)

    assert frames is not None and len(frames) == 1
    frame = frames[0]
    expected = _core_rows(core, ROOT, instance.id)
    # Positive control: the core really carries a hydrated history row here.
    assert expected["persona_chat_history"] is not None
    assert expected["persona_chat_history"]["message_count"] == 2
    assert frame["persona_chat_history"] == expected["persona_chat_history"]
    assert frame["operator_channel"] == expected["operator_channel"]
    assert frame["persona_instance"] == expected["persona_instance"]
    assert frame["running_work"]["rows"] == expected["running_work_rows"]
    assert frame["omitted"] is False
    assert frame["type"] == "persona_chat_turn"
    assert frame["schema_version"] == 2
    assert frame["base_offset"] == start
    assert frame["watermark"]["event_offset"] == batch[-1][0]
    assert frame["coalesced_count"] == len(batch)
    assert frame["root_chat_session_id"] == ROOT
    assert frame["persona_instance_id"] == instance.id
    assert "core" not in frame and "prompt_observability" not in frame and "events" not in frame


def test_an_unreadable_section_answers_none(isolate_agent_runtime_root, home, monkeypatch):
    import agent_runtime.stream.frames as frames_module

    _seed_chat()
    start = _log_end()
    _Turn("turn-broken").start()
    batch = _batch_since(start)

    def _boom():
        raise RuntimeError("store unreadable")

    monkeypatch.setattr(frames_module, "build_running_work", _boom)
    assert persona_chat_turn_frames(batch, batch_turn_roots(batch), base_offset=start) is None


def test_an_unowned_root_answers_none(isolate_agent_runtime_root, home):
    _seed_chat()
    start = _log_end()
    stranger = "persona_chat_personainst_nobody_0123456789ab"
    EventLog().append(_event("run.progress", session_id=stranger, payload={"message": "?"}))
    batch = _batch_since(start)
    assert persona_chat_turn_frames(batch, batch_turn_roots(batch), base_offset=start) is None


# ── C1: the reuse across the two subscribers ──────────────────────────────────


def test_the_second_lane_reuses_at_or_below_the_read_position(isolate_agent_runtime_root, home):
    sections = {"persona_instance_id": INSTANCE, "omitted": False}
    assert turn_section_reuse.remember(ROOT, sections, position=100)
    assert turn_section_reuse.consult(ROOT, floor=100) == sections
    assert turn_section_reuse.consult(ROOT, floor=90) == sections
    # A batch that closed past the read: the read cannot carry its events.
    assert turn_section_reuse.consult(ROOT, floor=101) is None
    assert turn_section_reuse.consult(OTHER_ROOT, floor=1) is None
    assert turn_section_reuse.consult(ROOT, floor=None) is None
    # A slower, older read never replaces a fresher one.
    assert not turn_section_reuse.remember(ROOT, {"stale": True}, position=50)
    assert turn_section_reuse.consult(ROOT, floor=100) == sections


def test_the_second_subscriber_of_one_batch_reads_nothing(isolate_agent_runtime_root, home, monkeypatch):
    import agent_runtime.stream.frames as frames_module

    _seed_chat()
    start = _log_end()
    _Turn("turn-shared").start()
    batch = _batch_since(start)
    roots = batch_turn_roots(batch)
    first = persona_chat_turn_frames(batch, roots, base_offset=start, caller="hub")
    reads = []
    real = frames_module._read_persona_chat_turn_sections
    monkeypatch.setattr(
        frames_module,
        "_read_persona_chat_turn_sections",
        lambda *a, **k: reads.append(a) or real(*a, **k),
    )
    second = persona_chat_turn_frames(batch, roots, base_offset=start, caller="cli")
    assert reads == []
    strip = lambda frame: {k: v for k, v in frame.items() if k not in {"generated_at", "watermark"}}
    assert [strip(f) for f in second] == [strip(f) for f in first]


# ── C2: the gate ──────────────────────────────────────────────────────────────


class _BuildCounter:
    def __init__(self, monkeypatch):
        self.calls = 0
        real = stream_mod.build_snapshot

        def counting(*args, **kwargs):
            self.calls += 1
            return real(*args, **kwargs)

        patch_where_bound(monkeypatch, stream_mod, "build_snapshot", counting)


def _gate(batch, *, start, accepted, promote=None):
    return list(
        _batch_frames_with_liveness(
            batch,
            base_offset=start,
            delta_patches=True,
            resync=False,
            heartbeat_interval_seconds=60,
            fold_entities=accepted,
            promote_fold_entities=promote,
        )
    )


def test_a_declaring_room_gets_the_overlay_and_no_core(isolate_agent_runtime_root, home, monkeypatch):
    """*Killing mutation:* remove the turn branch from ``_batch_frames_with_liveness``
    → the declaring room gets a ``delta`` with a led core → red."""

    _seed_chat()
    builds = _BuildCounter(monkeypatch)
    start = _log_end()
    turn = _Turn("turn-gate")
    turn.start()
    started = _batch_since(start)
    mid = started[-1][0]
    turn.end()
    ended = _batch_since(mid)

    for batch, base in ((started, start), (ended, mid)):
        frames = _gate(batch, start=base, accepted=DECLARING)
        assert [frame["type"] for frame in frames] == ["persona_chat_turn"]
        assert frames[0]["base_offset"] == base
        assert frames[0]["watermark"]["event_offset"] == batch[-1][0]
    assert builds.calls == 0


def test_a_silent_room_still_demotes_to_the_core(isolate_agent_runtime_root, home):
    _seed_chat()
    start = _log_end()
    _Turn("turn-silent").start()
    batch = _batch_since(start)
    frames = _gate(batch, start=start, accepted=sorted(HISTORICAL_FOLD_ENTITIES))
    assert [frame["type"] for frame in frames] == ["delta"]


def test_a_mixed_room_splits_overlay_and_core_per_subscriber(isolate_agent_runtime_root, home):
    """The ``test_the_hub_hands_each_subscriber_its_own_half`` shape: one
    subscriber declared the token, one did not."""

    from agent_runtime.stream import resolve_fold_variant

    _seed_chat()
    start = _log_end()
    _Turn("turn-mixed").start()
    batch = _batch_since(start)
    frames = [
        frame
        for frame in _gate(
            batch,
            start=start,
            accepted=sorted(HISTORICAL_FOLD_ENTITIES),
            promote=DECLARING,
        )
        if frame.get("type") != "heartbeat"
    ]
    assert [frame["type"] for frame in frames] == ["fold_variants"]
    declaring = resolve_fold_variant(frames[0], DECLARING)
    silent = resolve_fold_variant(frames[0], sorted(HISTORICAL_FOLD_ENTITIES))
    assert declaring["type"] == "persona_chat_turn"
    assert silent["type"] == "delta"
    assert silent["watermark"]["event_offset"] == declaring["watermark"]["event_offset"]


def test_a_batch_joined_by_a_peer_update_still_demotes(isolate_agent_runtime_root, home):
    _seed_chat()
    start = _log_end()
    _Turn("turn-cold").start()
    batch = _batch_since(start)
    peer = (batch[-1][0] + 1, _event("gateway.peer.updated", payload={"peer_id": "p"}))
    frames = _gate([*batch, peer], start=start, accepted=DECLARING)
    assert [frame["type"] for frame in frames] == ["delta"]


# ── the stream end to end ─────────────────────────────────────────────────────


def _content(frames):
    for frame in frames:
        if not is_boot_liveness(frame):
            yield frame


def test_a_declaring_stream_carries_a_turn_without_a_core(isolate_agent_runtime_root, home, monkeypatch):
    _seed_chat()
    builds = _BuildCounter(monkeypatch)
    patch_where_bound(monkeypatch, stream_mod, "delta_patches_enabled", lambda config=None: True)
    frames = _content(
        stream_frames(
            poll_interval_seconds=0.01,
            heartbeat_interval_seconds=60,
            delta_debounce_seconds=0.05,
            max_frames=3,
            fold_entities=DECLARING,
        )
    )
    hydrate = next(frames)
    assert hydrate["type"] == "hydrate"
    assert PERSONA_CHAT_TURN_CAPABILITY in hydrate["fold_entities"]
    held = hydrate["watermark"]["event_offset"]
    builds_before = builds.calls

    turn = _Turn("turn-stream")
    turn.start()
    first = next(frames)
    assert first["type"] == "persona_chat_turn"
    assert first["base_offset"] == held
    turn.end()
    # The END batch: the running_work section frame first (unchanged), then
    # the overlay, which applies from the START frame's watermark.
    seen = [next(frames)]
    if seen[0]["type"] == "running_work":
        seen.append(next(frames))
    assert seen[-1]["type"] == "persona_chat_turn"
    assert seen[-1]["base_offset"] == first["watermark"]["event_offset"]
    assert builds.calls == builds_before


def test_the_hub_hands_the_overlay_to_the_declarer_and_the_core_to_the_other(
    isolate_agent_runtime_root, home
):
    """Over the real ``StreamHub`` fan-out: the declaring subscriber's sink sees
    the overlay, the silent one's the core, and neither sees the envelope."""

    import threading
    import time

    from agent_runtime.serve_stream_hub import StreamHub

    _seed_chat()
    start = _log_end()
    _Turn("turn-hub").start()
    batch = _batch_since(start)
    (envelope,) = [
        frame
        for frame in _gate(
            batch, start=start, accepted=sorted(HISTORICAL_FOLD_ENTITIES), promote=DECLARING
        )
        if frame.get("type") != "heartbeat"
    ]
    released = threading.Event()

    def _source():
        yield {"type": "hydrate", "core": {}}
        yield envelope
        released.wait(5.0)

    hub = StreamHub(_source)
    declarer: list[dict] = []
    silent: list[dict] = []
    try:
        hub.subscribe("declarer", sink=declarer.append, declared=DECLARING)
        hub.subscribe("silent", sink=silent.append, declared=sorted(HISTORICAL_FOLD_ENTITIES))
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline and (len(declarer) < 2 or len(silent) < 2):
            time.sleep(0.02)
    finally:
        released.set()
        hub.stop()

    assert [frame["type"] for frame in declarer[:2]] == ["hydrate", "persona_chat_turn"]
    assert [frame["type"] for frame in silent[:2]] == ["hydrate", "delta"]
    assert declarer[1]["root_chat_session_id"] == ROOT


def test_the_office_lane_skips_the_overlay_without_a_resync():
    """The overlay replaces a turn batch's ``delta``, which the office lane
    already skipped as touching no workspace; an unknown-type resync here would
    restart the shared producer once per turn."""

    from agent_runtime.serve_office_subscriptions import office_patch_sink

    sent: list[dict] = []
    sink = office_patch_sink(workspace_id="ws_main", baseline_offset=10, emit=sent.append)
    frame = {
        "type": "persona_chat_turn",
        "schema_version": 2,
        "base_offset": 10,
        "watermark": {"event_offset": 50},
        "root_chat_session_id": ROOT,
    }
    sink(frame)
    assert sent == []
    # Positive control: the same frame under an untaught type resyncs.
    sink({**frame, "type": "persona_chat_turn_v9"})
    assert [message["params"]["reason"] for message in sent] == ["unknown_frame_type"]
