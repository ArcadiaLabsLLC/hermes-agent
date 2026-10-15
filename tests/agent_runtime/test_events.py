import json

import pytest

from hermes_time import now

from agent_runtime import paths
from agent_runtime.errors import EventPayloadTooLarge
from agent_runtime.events import EventLog
from agent_runtime.models import Event


def test_event_log_appends_jsonl_and_tails_events(isolate_agent_runtime_root):
    log = EventLog()
    first = Event(ts=now(), type="persona_instance.created", task_id="task_1", run_id=None, persona_id=None)
    second = Event(
        ts=now(),
        type="persona_instance.steered",
        task_id="task_1",
        run_id=None,
        persona_id="pm",
        payload={"from": "created", "to": "pm_triage"},
    )

    log.append(first)
    log.append(second)

    raw_lines = (isolate_agent_runtime_root / "events.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(raw_lines) == 2
    assert json.loads(raw_lines[1])["payload"] == {"from": "created", "to": "pm_triage"}
    assert log.tail(1) == [second]
    assert [event for _, event in log.iter_from_offset(0) if event.ts >= first.ts] == [first, second]


def test_event_log_for_task_filters_before_decoding_and_preserves_order(isolate_agent_runtime_root):
    log = EventLog()
    for index in range(6):
        log.append(Event(ts=now(), type="persona_instance.created", task_id=f"task_noise_{index}", run_id=None, persona_id=None))
        log.append(
            Event(
                ts=now(),
                type="run.progress",
                task_id="task_target",
                run_id=f"run_{index}",
                persona_id="dev",
                payload={"summary": f"target {index}"},
            )
        )

    all_events = log.for_task("task_target", limit=0)
    assert [event.run_id for event in all_events] == [f"run_{index}" for index in range(6)]

    limited_events = log.for_task("task_target", limit=2)
    assert [event.run_id for event in limited_events] == ["run_4", "run_5"]


def test_event_log_for_session_filters_session_lane_and_ignores_task_events(isolate_agent_runtime_root):
    log = EventLog()
    # A task-run event: keyed on task_id, no session lineage.
    log.append(
        Event(
            ts=now(),
            type="run.tool.finished",
            task_id="task_run",
            run_id="run_1",
            persona_id="dev",
            payload={"tool_name": "pytest", "status": "passed"},
        )
    )
    # Two chat-turn events on the target session, interleaved with another session.
    log.append(
        Event(
            ts=now(),
            type="run.tool.started",
            task_id=None,
            run_id=None,
            persona_id="neko_supervisor",
            payload={"tool_name": "terminal"},
            session_id="chat_target",
        )
    )
    log.append(
        Event(
            ts=now(),
            type="run.tool.started",
            task_id=None,
            run_id=None,
            persona_id="neko_supervisor",
            payload={"tool_name": "terminal"},
            session_id="chat_other",
        )
    )
    log.append(
        Event(
            ts=now(),
            type="run.tool.finished",
            task_id=None,
            run_id=None,
            persona_id="neko_supervisor",
            payload={"tool_name": "terminal", "status": "passed"},
            session_id="chat_target",
        )
    )

    rows = log.for_session("chat_target")
    assert [event.type for event in rows] == ["run.tool.started", "run.tool.finished"]
    assert all(event.session_id == "chat_target" for event in rows)
    # The task-run event never leaks into the session lane.
    assert all(event.task_id is None for event in rows)
    assert log.for_session("chat_target", limit=1)[0].type == "run.tool.finished"


def test_event_log_for_session_decodes_legacy_rows_without_session_field(isolate_agent_runtime_root):
    # A legacy JSONL row written before Event grew a session_id field must still
    # decode (session_id defaults to None) and must not match a session query.
    path = isolate_agent_runtime_root / "events.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "ts": now().isoformat().replace("+00:00", "Z"),
                "type": "run.progress",
                "task_id": "legacy_task",
                "run_id": "run_legacy",
                "persona_id": "dev",
                "payload": {"summary": "legacy"},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    log = EventLog()
    assert log.for_session("anything") == []
    assert log.tail(1)[0].session_id is None


def test_cached_event_log_matches_base_and_reads_once(isolate_agent_runtime_root, monkeypatch):
    from agent_runtime.events import CachedEventLog, _event_view_cache_clear

    base = EventLog()
    for index in range(4):
        base.append(Event(ts=now(), type="run.tool.started", task_id="task_a", run_id=f"r{index}", persona_id="dev", payload={"tool_name": "x"}))
    base.append(
        Event(
            ts=now(),
            type="run.tool.finished",
            task_id=None,
            run_id=None,
            persona_id="neko_supervisor",
            payload={"tool_name": "terminal", "status": "passed"},
            session_id="chat_z",
        )
    )

    cached = CachedEventLog()
    # Equivalence with the base log across every read method.
    assert [e.run_id for e in cached.for_task("task_a")] == [e.run_id for e in base.for_task("task_a")]
    assert cached.for_task("task_a", limit=2)[-1].run_id == base.for_task("task_a", limit=2)[-1].run_id
    assert [e.type for e in cached.for_session("chat_z")] == [e.type for e in base.for_session("chat_z")]
    assert [e.type for e in cached.tail(2)] == [e.type for e in base.tail(2)]
    assert len(list(cached.iter_from_offset(0))) == len(list(base.iter_from_offset(0)))

    # The live slice is read exactly once regardless of how many reads happen.
    from agent_runtime import events as events_module

    reads: list[int] = []
    real_read = events_module._read_live_from

    def counting_read(path, start):
        reads.append(start)
        return real_read(path, start)

    monkeypatch.setattr(events_module, "_read_live_from", counting_read)
    _event_view_cache_clear()
    fresh = CachedEventLog()
    fresh.for_task("task_a")
    fresh.for_session("chat_z")
    fresh.tail(1)
    assert reads == [0]

    # A new build-scoped object reuses the process view while the live slice
    # is unchanged.
    CachedEventLog().tail(1)
    assert reads == [0]

    # An append moves the live slice's size: the next build reads only from the
    # last consumed newline on, and sees the new row.
    consumed = paths.events_path().stat().st_size
    base.append(
        Event(
            ts=now(),
            type="run.tool.started",
            task_id="task_b",
            run_id="r-new",
            persona_id="dev",
            payload={"tool_name": "x"},
        )
    )
    assert CachedEventLog().tail(1)[0].run_id == "r-new"
    assert reads == [0, consumed - 1]


def test_event_log_for_task_type_filter_counts_matches_not_raw_rows(isolate_agent_runtime_root):
    # Live failure shape (task_bd98d444, 2026-07-05): a budget-incident loop
    # floods the newest task events with hundreds of non-trace rows, starving
    # any fetch window that counts raw rows before type filtering.
    log = EventLog()
    trace_types = {"run.tool.started", "run.tool.finished", "run.progress"}
    for index in range(10):
        log.append(
            Event(
                ts=now(),
                type="run.tool.started",
                task_id="task_flooded",
                run_id=f"run_{index}",
                persona_id="dev",
                payload={"tool_name": "read_file", "summary": f"tool {index}"},
            )
        )
    for _ in range(300):
        log.append(Event(ts=now(), type="persona.updated", task_id="task_flooded", run_id=None, persona_id="dev", payload={"persona_id": "dev"}))

    # Untyped fetch: the window is consumed by the flood (documents the trap).
    untyped = log.for_task("task_flooded", limit=10)
    assert all(event.type == "persona.updated" for event in untyped)

    # Typed fetch: limit counts matched trace rows, so the flood cannot starve it.
    typed = log.for_task("task_flooded", limit=10, types=trace_types)
    assert [event.run_id for event in typed] == [f"run_{index}" for index in range(10)]
    assert all(event.type == "run.tool.started" for event in typed)

    # A tighter typed limit still returns the newest matches, oldest-first.
    newest_two = log.for_task("task_flooded", limit=2, types=trace_types)
    assert [event.run_id for event in newest_two] == ["run_8", "run_9"]


def test_event_log_for_session_type_filter_counts_matches_not_raw_rows(isolate_agent_runtime_root):
    log = EventLog()
    trace_types = {"run.tool.started", "run.tool.finished", "run.progress"}
    for index in range(4):
        log.append(
            Event(
                ts=now(),
                type="run.tool.finished",
                task_id=None,
                run_id=None,
                persona_id="base",
                payload={"tool_name": "terminal", "status": "passed", "summary": f"turn {index}"},
                session_id="chat_flooded",
            )
        )
    # Filler is any registered type OUTSIDE ``trace_types``; S25 retargeted it
    # off run.opened (de-registered with its writer) onto a live chat-lane type.
    for index in range(50):
        log.append(
            Event(
                ts=now(),
                type="persona_instance.created",
                task_id=None,
                run_id=None,
                persona_id="base",
                payload={"persona_instance_id": f"personainst_flood_{index}"},
                session_id="chat_flooded",
            )
        )

    typed = log.for_session("chat_flooded", limit=4, types=trace_types)
    assert [event.payload["summary"] for event in typed] == [f"turn {index}" for index in range(4)]


def test_operator_events_receive_redaction_safe_summaries(isolate_agent_runtime_root):
    log = EventLog()
    samples = [
        # S25 retargeted two samples: off run.opened and off repo_bundle.delivered
        # (both de-registered with their writers) onto live operator-summary arms.
        # S52 retargeted the two that remained, for the same reason one lane
        # further along: repo_bundle.assigned / repo_bundle.updated were the last
        # repo_bundle.* summary types, and they left OPERATOR_SUMMARY_EVENT_TYPES
        # with the RepoBundleStore write lane that emitted them. The assertion on
        # the "Updated ... bundle to running." sentence went with the formatter
        # arm that produced it; run.progress takes its place as a live arm whose
        # sentence is derived from the payload rather than a constant.
        Event(now(), "run.progress", "task_1", "run_1", "dev", {"phase": "proof", "step": "compile", "status": "running"}),
        Event(now(), "run.tool.started", "task_1", "run_1", "dev", {"tool_name": "terminal"}),
        Event(now(), "run.tool.finished", "task_1", "run_1", "dev", {"tool_name": "terminal", "status": "passed"}),
    ]

    for event in samples:
        log.append(event)

    events = [event for _, event in log.iter_from_offset(0)]
    assert all(str(event.payload.get("summary") or "").strip() for event in events)
    progress = next(event for event in events if event.type == "run.progress")
    assert progress.payload["summary"] == "Progress: proof compile running."


def test_run_progress_receives_stable_event_id(isolate_agent_runtime_root):
    log = EventLog()

    log.append(
        Event(
            now(),
            "run.progress",
            "task_1",
            "run_1",
            "dev",
            {"phase": "proof", "step": "proof_command_running", "status": "running", "command_index": 1},
        )
    )

    event = list(log.iter_from_offset(0))[0][1]
    assert event.payload["event_id"] == "progress:run_1:proof:proof_command_running:1"
    assert event.payload["summary"] == "Progress: proof proof_command_running running."


def test_cached_event_log_type_filter_matches_base(isolate_agent_runtime_root):
    from agent_runtime.events import CachedEventLog

    base = EventLog()
    trace_types = {"run.tool.started", "run.tool.finished", "run.progress"}
    for index in range(6):
        base.append(
            Event(
                ts=now(),
                type="run.progress",
                task_id="task_typed",
                run_id=f"run_{index}",
                persona_id="dev",
                payload={"summary": f"progress {index}"},
            )
        )
        base.append(Event(ts=now(), type="persona.updated", task_id="task_typed", run_id=None, persona_id="dev", payload={"persona_id": "dev"}))

    cached = CachedEventLog()
    for limit in (0, 3, 6):
        assert [e.run_id for e in cached.for_task("task_typed", limit=limit, types=trace_types)] == [
            e.run_id for e in base.for_task("task_typed", limit=limit, types=trace_types)
        ]
    assert all(e.type == "run.progress" for e in cached.for_task("task_typed", limit=0, types=trace_types))


def test_cached_event_log_does_not_duplicate_events_whose_payload_echoes_their_id(isolate_agent_runtime_root):
    # A row that repeats the task id inside its own payload serializes with the
    # ``"task_id":"…"`` token TWICE. The cached index must still hand that line
    # to the scan once.
    #
    # S53 retargeted the sample off ``lane.created``, which used to be the real
    # example (``GoalRuntimeInstanceStore.save`` echoed the task id) but was
    # de-registered with the lane write lane, so ``append`` now refuses it.
        # ``persona_instance.steered`` is the live replacement and can echo the
        # task id in its detail payload alongside the envelope column.
    from agent_runtime.events import CachedEventLog

    base = EventLog()
    base.append(
        Event(
            ts=now(),
                type="persona_instance.steered",
            task_id="task_lane",
            run_id=None,
            persona_id=None,
            payload={
                "persona_instance_id": "pi_abc123",
                    "task_id": "task_lane",
                    "goal_id": "task_lane",
            },
        )
    )
    base.append(
        Event(
            ts=now(),
            type="run.progress",
            task_id="task_lane",
            run_id="run_1",
            persona_id="dev",
            payload={"summary": "after the lane"},
        )
    )

    cached = CachedEventLog()
    expected = base.for_task("task_lane", limit=0)
    actual = cached.for_task("task_lane", limit=0)
    assert len(actual) == len(expected)
    assert [e.type for e in actual] == [e.type for e in expected]
    assert [e.run_id for e in actual] == [e.run_id for e in expected]
    # Duplicates would also burn the caller's window.
    assert [e.type for e in cached.for_task("task_lane", limit=1)] == [
        e.type for e in base.for_task("task_lane", limit=1)
    ]


def test_cached_event_log_indexes_one_line_under_each_distinct_token(isolate_agent_runtime_root):
    # One line legitimately carrying two DIFFERENT tokens must resolve once from
    # each index — deduping per line must not collapse task and session lanes.
    from agent_runtime.events import CachedEventLog

    base = EventLog()
    base.append(
        Event(
            ts=now(),
            type="run.tool.finished",
            task_id="task_dual",
            run_id="run_1",
            persona_id="dev",
            payload={"tool_name": "pytest", "status": "passed"},
            session_id="chat_dual",
        )
    )

    cached = CachedEventLog()
    assert [e.run_id for e in cached.for_task("task_dual")] == [e.run_id for e in base.for_task("task_dual")]
    assert len(cached.for_task("task_dual")) == 1
    assert [e.run_id for e in cached.for_session("chat_dual")] == [e.run_id for e in base.for_session("chat_dual")]
    assert len(cached.for_session("chat_dual")) == 1


def test_event_log_rejects_payloads_over_4kb_and_does_not_write(isolate_agent_runtime_root):
    log = EventLog()
    event = Event(
        ts=now(),
        type="persona_instance.created",
        task_id="task_1",
        run_id=None,
        persona_id=None,
        payload={"blob": "x" * 5000},
    )

    with pytest.raises(EventPayloadTooLarge):
        log.append(event)

    assert not (isolate_agent_runtime_root / "events.jsonl").exists()


# ── S1 (h-snap-events): the appending event view ─────────────────────────────


def _view_of(cached):
    """A reader's pinned view: its lines and its id-token index, by line text."""

    lines = cached._cached_lines()[: cached._line_count]
    index = {
        token: [lines[at] for at in positions if at < cached._line_count]
        for token, positions in (cached._positions_by_id_token or {}).items()
    }
    return lines, {token: rows for token, rows in index.items() if rows}


def _fresh_view():
    from agent_runtime.events import CachedEventLog, _event_view_cache_clear

    _event_view_cache_clear()
    return _view_of(CachedEventLog())


def _append_rows(log, start, count, *, session_id="chat_s1"):
    for index in range(start, start + count):
        log.append(
            Event(
                ts=now(),
                type="run.tool.started",
                task_id=f"task_{index % 3}",
                run_id=f"r{index}",
                persona_id="dev",
                payload={"tool_name": "x"},
                session_id=session_id if index % 2 else None,
            )
        )


@pytest.fixture
def live_reads(monkeypatch):
    from agent_runtime import events as events_module

    reads: list[tuple[int, int]] = []
    real_read = events_module._read_live_from

    def counting_read(path, start):
        data = real_read(path, start)
        reads.append((start, len(data)))
        return data

    monkeypatch.setattr(events_module, "_read_live_from", counting_read)
    return reads


def test_appended_view_equals_a_fresh_full_read_and_reads_only_the_append(isolate_agent_runtime_root, live_reads):
    from agent_runtime.events import CachedEventLog

    log = EventLog()
    _append_rows(log, 0, 6)
    before = CachedEventLog()
    before_view = _view_of(before)
    consumed = paths.events_path().stat().st_size

    _append_rows(log, 6, 4)
    grown = paths.events_path().stat().st_size
    live_reads.clear()
    after = CachedEventLog()
    after_view = _view_of(after)
    # One seek-read of exactly the appended bytes (plus the guard newline).
    assert live_reads == [(consumed - 1, grown - consumed + 1)]
    # A second append refreshes from where the FIRST refresh stopped.
    _append_rows(log, 10, 2)
    final = paths.events_path().stat().st_size
    live_reads.clear()
    again = CachedEventLog()
    again_view = _view_of(again)
    assert live_reads == [(grown - 1, final - grown + 1)]
    # Token-for-token the same view a whole re-read builds; the earlier reader
    # holds exactly that view's prefix.
    assert again_view == _fresh_view()
    assert after_view[0] == again_view[0][: len(after_view[0])]
    # Every reader agrees with the whole-file base log.
    assert [e.run_id for e in again.for_task("task_1", limit=0)] == [e.run_id for e in log.for_task("task_1", limit=0)]
    assert [e.run_id for e in again.for_session("chat_s1", limit=0)] == [e.run_id for e in log.for_session("chat_s1", limit=0)]
    assert [e.run_id for e in again.tail(20)] == [e.run_id for e in log.tail(20)]
    assert [o for o, _e in again.iter_from_offset(0)] == [o for o, _e in log.iter_from_offset(0)]
    assert [e.run_id for e in after.tail(20)] == [f"r{i}" for i in range(10)]
    # The reader pinned before the append still answers from its own moment.
    assert _view_of(before) == before_view
    assert [e.run_id for e in before.tail(20)] == [f"r{i}" for i in range(6)]
    assert [e.run_id for e in before.for_task("task_0", limit=0)] == ["r0", "r3"]
    assert len(list(before.iter_from_offset(0))) == 6


def test_a_torn_final_line_waits_for_its_newline(isolate_agent_runtime_root, live_reads):
    from agent_runtime.events import CachedEventLog

    log = EventLog()
    _append_rows(log, 0, 3)
    CachedEventLog().tail(1)
    line = json.dumps(
        {"ts": now().isoformat().replace("+00:00", "Z"), "type": "run.progress", "task_id": "task_torn",
         "run_id": "r-torn", "persona_id": "dev", "payload": {"summary": "torn"}},
        separators=(",", ":"),
    )
    live = paths.events_path()
    consumed = live.stat().st_size
    with open(live, "ab") as handle:
        handle.write(line[:17].encode("utf-8"))
    torn = CachedEventLog()
    assert [e.run_id for e in torn.tail(5)] == ["r0", "r1", "r2"]
    assert _view_of(torn) == _fresh_view()

    with open(live, "ab") as handle:
        handle.write((line[17:] + "\n").encode("utf-8"))
    live_reads.clear()
    whole = CachedEventLog()
    assert [e.run_id for e in whole.tail(1)] == ["r-torn"]
    # The completed line is read from the consumed newline on, not from 0.
    assert live_reads == [(consumed - 1, len(line) + 2)]
    assert _view_of(whole) == _fresh_view()


def test_a_live_slice_that_shrank_or_was_rewritten_rebuilds_the_view(isolate_agent_runtime_root, live_reads):
    from agent_runtime.events import CachedEventLog

    log = EventLog()
    _append_rows(log, 0, 5)
    CachedEventLog().tail(1)
    live = paths.events_path()
    rows = live.read_bytes().splitlines(keepends=True)

    # Truncated below the consumed size.
    live.write_bytes(b"".join(rows[:2]))
    live_reads.clear()
    shrunk = CachedEventLog()
    assert [e.run_id for e in shrunk.tail(9)] == ["r0", "r1"]
    assert [start for start, _n in live_reads] == [0]
    assert _view_of(shrunk) == _fresh_view()

    # Grown again, but the consumed prefix was rewritten (the guard newline moved).
    CachedEventLog().tail(1)
    live.write_bytes(rows[0][:-1] + b" \n" + b"".join(rows[1:]))
    live_reads.clear()
    rewritten = CachedEventLog()
    assert [e.run_id for e in rewritten.tail(9)] == [f"r{i}" for i in range(5)]
    # The guard read at the consumed newline found the prefix moved: whole re-read.
    assert [start for start, _n in live_reads][-1] == 0
    assert _view_of(rewritten) == _fresh_view()


def test_a_live_slice_replaced_by_a_new_file_rebuilds_the_view(isolate_agent_runtime_root, live_reads):
    # The replacement keeps a newline at the consumed boundary, so only the
    # slice's identity (its inode) tells the view its prefix is not its own.
    import os

    from agent_runtime.events import CachedEventLog

    log = EventLog()
    _append_rows(log, 0, 3)
    CachedEventLog().tail(1)
    live = paths.events_path()
    rows = live.read_bytes().splitlines(keepends=True)
    replacement = live.with_name("events.replacement")
    replacement.write_bytes(rows[0].replace(b'"r0"', b'"rZ"') + b"".join(rows[1:]) + rows[2].replace(b'"r2"', b'"r3"'))
    os.replace(replacement, live)
    live_reads.clear()
    replaced = CachedEventLog()
    assert [e.run_id for e in replaced.tail(9)] == ["rZ", "r1", "r2", "r3"]
    assert [start for start, _n in live_reads] == [0]
    assert _view_of(replaced) == _fresh_view()
