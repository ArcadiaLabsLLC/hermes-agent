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
    real = frames_module.read_turn_sections
    monkeypatch.setattr(
        frames_module,
        "read_turn_sections",
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


# ── lane h-demote-census: what the live test's six demoting batches carried ───
#
# 2026-10-06 00:14-00:16 (five Neko turns): the 6 led ``reason=demote`` cores
# were (a) the two lanes' batch of two watchdog ``state.reconciled`` (the old
# chat's ``ended_at`` at a new-chat open), (b) the two lanes' batch of
# ``state.patched`` persona_instance + ``persona_instance.chat_opened`` + turn 1,
# (c) the two lanes' batch of a mid-turn watchdog reconcile + ``run.progress``.
# (a) and (c) now name the chat rows that moved and ride the overlay; (b) still
# demotes (a brand-new chat moves the history bound, which the launcher's turn
# fold cannot evict).


def _reconcile(*, families=None, chat_roots=None, source="stream_watchdog") -> Event:
    payload = {"fingerprint": "f00d", "source": source}
    if families is not None:
        payload["families"] = families
    if chat_roots is not None:
        payload["chat_roots"] = chat_roots
    return Event(
        ts=datetime.now(timezone.utc),
        type="state.reconciled",
        task_id=None,
        run_id=None,
        persona_id=None,
        payload=payload,
        session_id=None,
    )


def _auto_title(root: str = ROOT, change_kind: str = "auto_title_updated") -> Event:
    return _event(
        "persona_chat.metadata_updated",
        root=root,
        session_id=root,
        payload={"persona_instance_id": INSTANCE, "root_chat_session_id": root, "change_kind": change_kind},
    )


def test_the_census_batches_classify_as_measured():
    """*Killing mutation:* let an UNATTRIBUTED reconcile through (drop the
    ``families`` check in ``_turn_event_roots``) → the legacy-payload window
    names a root → red; drop the ``chat_roots`` requirement → the chat-db
    window without roots names one → red."""

    attributed = _reconcile(families=["chat_db"], chat_roots=[ROOT])
    mid_turn = _window(attributed, _event("run.progress", session_id=ROOT, payload={"message": "x"}))
    assert batch_turn_roots(mid_turn) == [(ROOT, 2)]
    # (a): the open's reconcile names the PREVIOUS chat, and alone it is a root.
    previous_chat = _window(_reconcile(families=["chat_db"], chat_roots=[OTHER_ROOT]))
    assert batch_turn_roots(previous_chat) == [(OTHER_ROOT, 1)]
    # The turn's auto-title rides with its turn.
    assert batch_turn_roots(_window(_event("persona_chat.turn_ended"), _auto_title())) == [(ROOT, 2)]
    # running_work alone moves no root; beside a turn it rides the overlay.
    assert batch_turn_roots(_window(_reconcile(families=["running_work"]))) is None
    beside = _window(_event("persona_chat.turn_started"), _reconcile(families=["running_work"]))
    assert batch_turn_roots(beside) == [(ROOT, 1)]
    for refused in (
        _reconcile(),  # the legacy payload: says nothing about what moved
        _reconcile(families=["chat_db"]),  # the chat db moved, rows unproven
        _reconcile(families=["chat_db"], chat_roots=[]),
        _reconcile(families=["scope"], chat_roots=[ROOT]),
        _reconcile(families=["chat_db", "scope"], chat_roots=[ROOT]),
        _reconcile(families=["chat_db"], chat_roots=[ROOT], source="operator"),
        _auto_title(change_kind="renamed"),
    ):
        assert batch_turn_roots(_window(_event("persona_chat.turn_started"), refused)) is None, refused.payload
    # (b): the open's patch pair beside turn 1 is still not a turn batch.
    opened = _window(
        _event("state.patched", payload={"entity": "persona_instance", "id": INSTANCE, "op": "upsert"}),
        _event("persona_instance.chat_opened", payload={"persona_instance_id": INSTANCE, "session_id": ROOT}),
        _event("persona_chat.turn_started"),
    )
    assert batch_turn_roots(opened) is None


def test_a_census_batch_ships_the_overlay_and_no_core(isolate_agent_runtime_root, home, monkeypatch):
    """A declaring room handed (c)'s shape — the turn's start, its trace, a
    watchdog reconcile naming its own root, its auto-title — gets the overlay and
    no core; the same batch with an unattributed reconcile still demotes.

    *Killing mutation:* refuse every ``state.reconciled`` in ``_turn_event_roots``
    → the first gate returns a ``delta`` with a led core → red.
    """

    _seed_chat()
    builds = _BuildCounter(monkeypatch)
    start = _log_end()
    _Turn("turn-census").start()
    log = EventLog()
    log.append(_event("run.progress", session_id=ROOT, payload={"message": "thinking"}))
    log.append(_reconcile(families=["chat_db"], chat_roots=[ROOT]))
    log.append(_auto_title())
    batch = _batch_since(start)
    frames = _gate(batch, start=start, accepted=DECLARING)
    assert [frame["type"] for frame in frames] == ["persona_chat_turn"]
    assert frames[0]["watermark"]["event_offset"] == batch[-1][0]
    assert builds.calls == 0

    legacy = (batch[-1][0] + 1, _reconcile())
    demoted = [frame for frame in _gate([*batch, legacy], start=start, accepted=DECLARING) if frame["type"] != "heartbeat"]
    assert [frame["type"] for frame in demoted] == ["delta"]
    assert builds.calls >= 1


def test_the_watchdog_names_the_chat_rows_that_moved(isolate_agent_runtime_root, home):
    """The attribution half, against a real SessionDB: a message on one chat
    names that chat; a brand-new chat, or a read with nothing moved, names none.

    *Killing mutation:* drop the ``before.keys() != after.keys()`` refusal in
    ``_content_moved_roots`` → the minted chat's reconcile names it as if it
    were an existing row → red on the ``minted`` assertion.
    """

    from agent_runtime.persona_chat_durability import default_persona_session_db, ensure_persona_chat_session
    from agent_runtime.stream.fingerprint import scope_move_attribution, scope_reading

    _seed_chat()
    known = scope_reading()
    assert known.chat_sessions is not None and ROOT in known.chat_sessions
    default_persona_session_db().append_message(ROOT, "user", "the turn's own user message")
    moved = scope_reading(previous=known)
    assert scope_move_attribution(known, moved) == {"families": ["chat_db"], "chat_roots": [ROOT]}
    assert scope_move_attribution(moved, scope_reading(previous=moved)) == {"families": []}

    assert ensure_persona_chat_session(
        session_db=default_persona_session_db(), session_id=OTHER_ROOT, persona_id=PERSONA, title="new", required=True
    )
    minted = scope_reading(previous=moved)
    attribution = scope_move_attribution(moved, minted)
    assert attribution["families"] == ["chat_db"]
    assert "chat_roots" not in attribution


def test_an_archived_chat_is_a_membership_move_and_names_nothing(isolate_agent_runtime_root, home):
    import sqlite3

    from agent_runtime.chat_session_scope import chat_session_db_path
    from agent_runtime.stream.fingerprint import scope_move_attribution, scope_reading

    _seed_chat()
    known = scope_reading()
    connection = sqlite3.connect(chat_session_db_path())
    try:
        connection.execute("UPDATE sessions SET archived = 1 WHERE id = ?", (ROOT,))
        connection.commit()
    finally:
        connection.close()
    moved = scope_reading(previous=known)
    assert scope_move_attribution(known, moved) == {"families": ["chat_db"]}


def test_a_narrower_held_reconcile_does_not_stand_in_for_ours(isolate_agent_runtime_root):
    """The two-lane guard: the other lane's reconcile of the same fingerprint is
    skipped only when it claims at least what this lane would.

    *Killing mutation:* skip on fingerprint alone (the old guard) → the narrower
    held event stands in and this lane's batch is covered for less than moved
    → red.
    """

    from agent_runtime.stream.frames import _append_state_reconciled

    log = EventLog()

    def _held():
        return [event for event in log.tail(10) if event.type == "state.reconciled"]

    assert _append_state_reconciled(log, "fp1", {"families": ["chat_db"], "chat_roots": [ROOT]})
    assert _append_state_reconciled(log, "fp1", {"families": ["chat_db"], "chat_roots": [ROOT]})
    assert len(_held()) == 1
    assert _append_state_reconciled(log, "fp1", {"families": ["chat_db"], "chat_roots": [ROOT, OTHER_ROOT]})
    assert len(_held()) == 2 and _held()[-1].payload["chat_roots"] == [ROOT, OTHER_ROOT]
    # An unattributed held event demotes everything: it stands in for anything.
    assert _append_state_reconciled(log, "fp2", {"families": ["scope"]})
    assert _append_state_reconciled(log, "fp2", {"families": ["chat_db"], "chat_roots": [ROOT]})
    assert [event.payload["fingerprint"] for event in _held()].count("fp2") == 1


def test_the_overlay_read_stands_aside_for_a_hot_turn_window(isolate_agent_runtime_root, home, monkeypatch, caplog):
    """The read waits out a live turn's latency-critical window, then ships the
    core's rows (the equality test above holds unchanged).

    *Killing mutation:* drop ``build_yield_scope`` around the read → the window
    is never polled and ``yielded_ms=0`` → red.
    """

    import logging

    import agent_runtime.turn_activity as turn_activity

    _seed_chat()
    start = _log_end()
    _Turn("turn-hot").start()
    batch = _batch_since(start)
    polls = {"n": 0}

    def _hot():
        polls["n"] += 1
        return 1 if polls["n"] <= 4 else 0

    monkeypatch.setattr(turn_activity, "hot_turn_windows", _hot)
    with caplog.at_level(logging.INFO, logger="agent_runtime.stream"):
        frames = persona_chat_turn_frames(batch, batch_turn_roots(batch), base_offset=start)
    assert frames is not None and frames[0]["persona_chat_history"] is not None
    assert polls["n"] > 4
    line = next(record.getMessage() for record in caplog.records if "turn_section reason=" in record.getMessage())
    assert "yielded_ms=" in line and "yielded_ms=0 " not in line


def test_the_second_lane_waits_for_the_first_lanes_read(isolate_agent_runtime_root):
    """In flight: a read covering the floor is waited for, not repeated; one
    below the floor is not waited for."""

    import threading

    turn_section_reuse.clear()
    key = turn_section_reuse.begin(ROOT, position=100)
    assert key is not None
    got = {}

    def _second():
        got["sections"] = turn_section_reuse.await_inflight(ROOT, floor=90, timeout_s=5.0)

    waiter = threading.Thread(target=_second)
    waiter.start()
    turn_section_reuse.remember(ROOT, {"persona_instance_id": INSTANCE}, position=100)
    turn_section_reuse.finish(key)
    waiter.join(5.0)
    assert got["sections"] == {"persona_instance_id": INSTANCE}
    key = turn_section_reuse.begin(ROOT, position=200)
    assert turn_section_reuse.await_inflight(ROOT, floor=201, timeout_s=5.0) is None
    turn_section_reuse.finish(key)
    turn_section_reuse.clear()


def test_a_lane_below_an_inflight_claim_claims_its_own_read(isolate_agent_runtime_root):
    """h-section-dup: a claim below the floor does not stop a lane claiming; the
    next lane at that floor waits for that lane's read instead of reading again."""

    turn_section_reuse.clear()
    low = turn_section_reuse.begin(ROOT, position=100)
    assert low is not None
    second = turn_section_reuse.begin(ROOT, floor=200)
    assert second is not None, "the lane above the low claim read unclaimed"
    assert turn_section_reuse.begin(ROOT, floor=200) is None, "a third lane at the floor would read again"
    turn_section_reuse.started(second, 210)
    turn_section_reuse.remember(ROOT, {"persona_instance_id": INSTANCE}, position=210)
    turn_section_reuse.finish(second)
    assert turn_section_reuse.await_inflight(ROOT, floor=200, timeout_s=0.1) == {"persona_instance_id": INSTANCE}
    turn_section_reuse.finish(low)
    turn_section_reuse.clear()
