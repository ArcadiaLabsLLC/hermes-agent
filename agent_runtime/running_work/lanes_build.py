"""The ``build`` lane: agent-started, announced and detected builds as ONE row kind.

Plan ``docs/agent-runtime-harness/planned/build-running-work-2026-10-04.md`` §1, §2, §8, §9.

* **agent** — a terminal row whose command the Flutter recognizer classifies as a build is
  REPLACED IN PLACE by a build row carrying ``origin_work_id`` (accounted
  ``reclassified_build``, by design). The lane runs AFTER the terminal lane and is handed
  the frame's rows so far — one producer step, so ``counts`` never double. Stage and
  progress come from the live registry session's own output in the owning process; from
  the durable lane the stage is ``unknown`` and ``progress_signal: none``.
* **announced** — one record per job in ``<background-work home>/builds/``, written by the
  job's own writer (``builds.registry``, whose reader rules decide liveness and expiry).
* **detected** — reported as its own sub-source (the scan lands in ``builds.detect``).

``sources.build`` is ONE entry with three sub-healths, because the three sources fail
independently and "I could not look" must be sayable per source. Every row resolves its
``workspace_id`` / ``slot_id`` from this machine's bound repo slots (deepest wins) and names
its starting persona instance through ``_owner_of`` — or says, as a typed unknown, that it
could not.
"""

from __future__ import annotations

import os
from typing import Any

from ..builds import registry as build_registry
from ..builds.flutter_argv import COMMAND_OTHER, recognize_command
from ..builds.liveness import PROGRESS, liveness_for
from ..builds.recognizer_flutter import FlutterRecognizer
from ..builds.unknowns import UNKNOWN_WRITER_UNIDENTIFIED
from ..builds.vocabulary import (
    BUILD_REGISTRY_DIRNAME,
    BUILD_STAGES,
    CONTROL_ALLOWED,
    CONTROL_REASON_ARGV_UNKNOWN,
    CONTROL_REASON_NOT_RUNNING,
    CONTROL_REASON_OWNER_NOT_HERE,
    CONTROL_REASON_WRITER_DECLINES,
    CONTROL_REFUSED,
    ENV_SOURCE_PROCESS,
    ENV_SOURCE_UNKNOWN,
    LIVENESS_DEAD,
    LIVENESS_LIVE,
    LIVENESS_UNKNOWN,
    PROGRESS_SIGNAL_CPU,
    PROGRESS_SIGNAL_HEARTBEAT,
    PROGRESS_SIGNAL_NONE,
    PROGRESS_SIGNAL_OUTPUT,
    RECORD_CONTROL_NONE,
    RECORD_RESTART_COMMAND,
    SOURCE_AGENT,
    SOURCE_ANNOUNCED,
    SOURCE_DETECTED,
    STAGE_UNKNOWN,
    STARTED_BY_AGENT,
    STARTED_BY_EXTERNAL,
    SUB_REASON_REGISTRY_UNREADABLE,
)
from ..projection_accountant import ProjectionAccountant
from .build_rows import BuildFacts, apply_slot, build_row, label_for, note_starter, slot_env_source
from .lanes_process import _read_checkpoint
from .ownership import _head_home, _owner_of, _pid_identity
from .rows import LanePass, _iso, _module, _preview, _source, elapsed_seconds
from .vocabulary import (
    KIND_BUILD,
    KIND_TERMINAL,
    LANE_DURABLE,
    LANE_LIVE,
    SOURCE_OK,
    SOURCE_UNAVAILABLE,
    STATUS_RUNNING,
    STATUS_STALLING,
    _CHECKPOINT_FILENAME,
)

__layer__ = "lanes"


def _sub(status: str, reason: str = "", **cost: Any) -> dict[str, Any]:
    return {"status": status, "reason": reason, **cost}


def _census() -> Any:
    """This machine's slot census: how many slots the realm declares, and the ones bound here."""

    from ..workspace_slots import SlotCensus, slot_census

    try:
        return slot_census()
    except Exception:  # noqa: BLE001 — no slot store is "no slot", typed per row as slot_unresolved
        return SlotCensus(0, ())


#: The process table the detected scan reads; None = psutil (a seam for the fixture and tests).
_detect_table: Any = None
#: The scan's clock; None = ``time.perf_counter`` (a seam so a golden's ``scan_ms`` is fixed).
_detect_clock: Any = None


class BuildLane(LanePass):
    """One pass over the three build sources; the agent pass edits ``frame_rows`` in place."""

    kind = KIND_BUILD

    def __init__(self, *, now: float, accountant: ProjectionAccountant | None, frame_rows: list[dict[str, Any]]) -> None:
        super().__init__(now=now, accountant=accountant)
        self.frame_rows = frame_rows
        self.census = _census()
        self.bound = list(self.census.bound)

    def collect(self) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        subs = {SOURCE_AGENT: self.reclassify()}
        announced, subs[SOURCE_ANNOUNCED] = self.announced()
        detected, subs[SOURCE_DETECTED] = self.detected(owned=_pids(self.frame_rows) | _pids(announced))
        rows = self.finish(announced + detected)
        any_ok = any(sub["status"] == SOURCE_OK for sub in subs.values())
        entry = _source(SOURCE_OK if any_ok else SOURCE_UNAVAILABLE, lane=LANE_DURABLE)
        entry["sub"] = subs
        return rows, entry

    #: The detected scan's measured cost, for ``parity.sections_ms["running_work.build_detect"]``.
    scan_ms = 0

    def slot_of(self, facts: BuildFacts, path: str) -> None:
        from ..workspace_slots import slot_for_path

        apply_slot(facts, path, slot_for_path(path, self.bound) if path else None, len(self.bound), now=self.now)

    # ── agent: reclassify terminal rows ──────────────────────────────────────

    def reclassify(self) -> dict[str, Any]:
        head, _provenance = _head_home()
        entries: dict[str, Any] = {}
        if head is not None:
            listed, _refusal = _read_checkpoint(head / _CHECKPOINT_FILENAME)
            entries = {str(e.get("session_id")): e for e in listed if isinstance(e, dict)}
        registry = _module("tools.process_registry")
        seen: set[Any] = set()
        for index, row in enumerate(self.frame_rows):
            if row.get("kind") != KIND_TERMINAL:
                continue
            session_id = str(row.get("work_id") or "").partition(":")[2]
            session = _registry_session(registry, session_id)
            replaced = self.agent_row(row, session_id, entries.get(session_id) or {}, session, seen)
            if replaced is not None:
                self.frame_rows[index] = replaced
        PROGRESS.prune(seen, SOURCE_AGENT)
        return _sub(SOURCE_OK)

    def agent_row(self, row: dict[str, Any], session_id: str, entry: dict[str, Any], session: Any,
                  seen: set[Any]) -> dict[str, Any] | None:
        cwd = str(getattr(session, "cwd", None) or entry.get("cwd") or "")
        recognition = recognize_command(str(row.get("command") or ""), cwd or os.curdir)
        command = recognition.command
        if command is None or command.kind == COMMAND_OTHER:
            return None
        self.consider()
        self.drop("reclassified_build", entity_id=row.get("work_id"), detail="terminal row is a build", by_design=True)
        root = str(command.project_dir) if cwd else ""
        owner = row.get("owner") or {}
        facts = BuildFacts(
            source=SOURCE_AGENT, stable_id=session_id, command=str(row.get("command") or ""),
            label=label_for(command.toolchain, command.kind, command.target, root), pid=row.get("pid"),
            pid_verified=bool(row.get("pid_verified")), persona_id=owner.get("persona_id") or "",
            persona_instance_id=owner.get("persona_instance_id") or "", session_id=owner.get("session_id") or "",
            started_at=str(row.get("started_at") or ""), elapsed_seconds=int(row.get("elapsed_seconds") or 0),
            tail_preview=str(row.get("tail_preview") or ""), source_lane=str(row.get("source_lane") or LANE_DURABLE),
            project_root=root, toolchain=command.toolchain, target=command.target, mode=command.mode,
            started_by={"kind": STARTED_BY_AGENT, "label": owner.get("persona_id") or "agent"},
            origin_work_id=str(row.get("work_id") or ""),
            restart={"argv": list(recognition.words), "cwd": root} if recognition.words and root else None,
        )
        self.slot_of(facts, root)
        facts.env_source = slot_env_source(facts.slot_id, ENV_SOURCE_PROCESS)
        note_starter(facts, f"session {owner.get('session_id') or '(none)'} resolved to no persona instance", now=self.now)
        self._agent_progress(facts, row, session, seen)
        facts.stop = (CONTROL_ALLOWED, "") if session is not None else (CONTROL_REFUSED, CONTROL_REASON_OWNER_NOT_HERE)
        facts.restart_control = (CONTROL_ALLOWED, "") if facts.restart else (CONTROL_REFUSED, CONTROL_REASON_ARGV_UNKNOWN)
        return build_row(facts, self.accountant)

    def _agent_progress(self, facts: BuildFacts, row: dict[str, Any], session: Any, seen: set[Any]) -> None:
        if row.get("status") not in (STATUS_RUNNING, STATUS_STALLING):
            facts.liveness = LIVENESS_UNKNOWN
            return
        if session is None:
            facts.liveness, facts.progress_signal = LIVENESS_LIVE, PROGRESS_SIGNAL_NONE
            return
        with session._lock:  # noqa: SLF001 — the buffer's only guard, read-only
            buffered, total = session.output_buffer or "", int(getattr(session, "total_output_chars", 0) or 0)
        recognizer = FlutterRecognizer(cwd=facts.project_root)
        recognizer.feed(buffered, seen_at=self.now)
        facts.stage, facts.stage_detail, facts.artifact = recognizer.stage, recognizer.stage_detail, recognizer.artifact
        for entry in recognizer.unknowns.wire():
            facts.unknowns.add(entry["kind"], entry["evidence"], entry["seen_at"])
        key = (SOURCE_AGENT, facts.stable_id)
        seen.add(key)
        facts.seconds_since_progress = PROGRESS.observe(key, total, self.now)
        facts.liveness, facts.stalling = liveness_for(facts.seconds_since_progress)
        facts.progress_signal, facts.source_lane = PROGRESS_SIGNAL_OUTPUT, LANE_LIVE

    # ── announced: the registry ──────────────────────────────────────────────

    def announced(self) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        # The SAME home the checkpoint resolves to (``running_work_store_paths`` names this
        # directory), never a second resolution that could disagree with it.
        head, _provenance = _head_home()
        if head is None:
            return [], _sub(SOURCE_UNAVAILABLE, SUB_REASON_REGISTRY_UNREADABLE, detail="home_unresolved")
        try:
            files, error = build_registry.read_records(head / BUILD_REGISTRY_DIRNAME)
        except Exception as exc:  # noqa: BLE001 — "I could not look" is a typed sub-health
            files, error = [], type(exc).__name__
        if error:
            return [], _sub(SOURCE_UNAVAILABLE, SUB_REASON_REGISTRY_UNREADABLE, detail=error)
        rows = []
        for item in files:
            self.consider()
            if item.record is None:
                self.drop("build_record_unreadable", entity_id=item.path.name, detail=item.error)
                continue
            verdict = build_registry.evaluate(item.record, now=self.now, pid_identity=_pid_identity)
            if verdict.expired:
                self.drop("build_record_expired", entity_id=item.path.name, detail="past expires_at", by_design=True)
                continue
            rows.append(build_row(self.announced_facts(item.path.name, item.record, verdict), self.accountant))
        return rows, _sub(SOURCE_OK)

    def announced_facts(self, filename: str, record: dict[str, Any], verdict: Any) -> BuildFacts:
        session = str(record.get("session_key") or "")
        persona_id, instance_id = _owner_of(session, memo=self.owners)
        started = _number(record.get("started_at"))
        finished = _number(record.get("finished_at"))
        root = str(record.get("project_root") or "")
        facts = BuildFacts(
            source=SOURCE_ANNOUNCED, stable_id=str(record.get("job_id") or filename.rsplit(".", 1)[0]),
            command=" ".join(str(a) for a in ((record.get("restart") or {}).get("argv") or [])),
            label=str(record.get("label") or "") or label_for(str(record.get("toolchain") or ""), "build",
                                                              str(record.get("target") or ""), root),
            pid=record.get("build_pid"), pid_verified=self._build_pid_verified(record, verdict),
            persona_id=persona_id, persona_instance_id=instance_id, session_id=session,
            started_at=_iso(started), elapsed_seconds=elapsed_seconds(started, now=finished or self.now),
            tail_preview=_preview(record.get("tail"), self.accountant), project_root=root,
            toolchain=str(record.get("toolchain") or "unknown"), target=str(record.get("target") or ""),
            mode=str(record.get("mode") or ""), liveness=verdict.liveness, outcome=verdict.outcome,
            stage=record.get("stage") if record.get("stage") in BUILD_STAGES else STAGE_UNKNOWN,
            stage_detail=str(record.get("stage_detail") or ""), stalling=verdict.status == STATUS_STALLING,
            progress_signal=PROGRESS_SIGNAL_HEARTBEAT, seconds_since_progress=verdict.heartbeat_age,
            expected_ms=_whole_ms(record.get("expected_ms")), exit_code=record.get("exit_code"),
            artifact=record.get("artifact") if isinstance(record.get("artifact"), dict) else None,
            finished_at=_iso(finished), started_by=_started_by(record.get("started_by")),
            restart=_restart_spec(record.get("restart")), mcp_job=_mcp_job(record.get("mcp_job")),
            announcement=_announcement(filename, record, verdict),
        )
        self._announced_unknowns(facts, record, verdict, session)
        facts.stop, facts.restart_control = _announced_controls(record, verdict, facts.restart)
        return facts

    def _announced_unknowns(self, facts: BuildFacts, record: dict[str, Any], verdict: Any, session: str) -> None:
        facts.unknowns.extend_wire(record.get("unknowns"))
        if not verdict.writer_identified:
            writer = record.get("writer") or {}
            facts.unknowns.add(UNKNOWN_WRITER_UNIDENTIFIED,
                               f"writer pid {writer.get('pid')} start {writer.get('host_start_time')}: identity unproven", self.now)
        self.slot_of(facts, facts.project_root)
        facts.env_source = slot_env_source(facts.slot_id, ENV_SOURCE_UNKNOWN)
        note_starter(facts, f"session {session or '(none)'} resolved to no persona instance", now=self.now)

    def _build_pid_verified(self, record: dict[str, Any], verdict: Any) -> bool:
        if record.get("build_pid") is None:
            return bool(verdict.writer_verified)
        return bool(_pid_identity(record.get("build_pid"), record.get("build_host_start_time"))[1])

    # ── detected: its own module (``builds.detect``) ─────────────────────────

    def detected(self, *, owned: set[int]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        from ..builds.detect import scan

        kwargs = {"clock": _detect_clock} if _detect_clock is not None else {}
        result = scan(now=self.now, census=self.census, owned=owned, table=_detect_table, **kwargs)
        self.scan_ms = result.scan_ms
        seen: set[Any] = set()
        rows = [build_row(self.detected_facts(build, seen), self.accountant) for build in result.builds]
        for _row in rows:
            self.consider()
        PROGRESS.prune(seen, SOURCE_DETECTED)
        return rows, result.sub()

    def detected_facts(self, build: Any, seen: set[Any]) -> BuildFacts:
        from ..builds.detect import restart_unknowns

        command = build.command
        facts = BuildFacts(
            source=SOURCE_DETECTED, stable_id=f"{build.pid}-{build.start}", command=" ".join(build.argv),
            label=label_for(command.toolchain, command.kind, command.target, str(command.project_dir)),
            pid=build.pid, pid_verified=True, source_lane=LANE_LIVE, project_root=str(command.project_dir),
            workspace_id=build.slot.workspace_id, slot_id=build.slot.slot, env_source=slot_env_source(build.slot.slot, ""),
            toolchain=command.toolchain, target=command.target, mode=command.mode,
            started_by={"kind": STARTED_BY_EXTERNAL, "label": build.exe}, progress_signal=PROGRESS_SIGNAL_CPU,
            restart={"argv": list(build.argv), "cwd": build.cwd},
            stop=(CONTROL_ALLOWED, ""), restart_control=(CONTROL_ALLOWED, ""),
        )
        key = (SOURCE_DETECTED, build.pid, build.start)
        seen.add(key)
        facts.seconds_since_progress = PROGRESS.observe(key, round(build.cpu, 2), self.now)
        facts.liveness, facts.stalling = liveness_for(facts.seconds_since_progress)
        for entry in restart_unknowns(build, now=self.now).wire():
            facts.unknowns.add(entry["kind"], entry["evidence"], entry["seen_at"])
        note_starter(facts, "detected: no session", now=self.now)
        return facts


def _pids(rows: list[dict[str, Any]]) -> set[int]:
    """The pids the agent and announced sources already own (the detected scan skips them and their children)."""

    return {int(row["pid"]) for row in rows if isinstance(row.get("pid"), int)}


def _registry_session(registry: Any, session_id: str) -> Any:
    if registry is None or not session_id:
        return None
    try:
        return registry.process_registry.get(session_id)
    except Exception:  # noqa: BLE001 — a registry that cannot answer owns nothing here
        return None


def _number(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _whole_ms(value: Any) -> int | None:
    number = _number(value)
    return None if number is None or number < 0 else int(number)


def _started_by(value: Any) -> dict[str, str]:
    value = value if isinstance(value, dict) else {}
    return {"kind": str(value.get("kind") or "tool"), "label": str(value.get("label") or "")}


def _restart_spec(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict) or not isinstance(value.get("argv"), list) or not value["argv"]:
        return None
    return {"argv": [str(item) for item in value["argv"]], "cwd": str(value.get("cwd") or "")}


def _mcp_job(value: Any) -> dict[str, str] | None:
    if not isinstance(value, dict):
        return None
    return {"server": str(value.get("server") or ""), "job_id": str(value.get("job_id") or "")}


def _announcement(filename: str, record: dict[str, Any], verdict: Any) -> dict[str, Any]:
    age = verdict.heartbeat_age
    return {"record": filename, "writer_pid": (record.get("writer") or {}).get("pid"),
            "heartbeat_age_seconds": None if age is None else round(age, 1)}


def _announced_controls(record: dict[str, Any], verdict: Any, restart: Any) -> tuple[tuple[str, str], tuple[str, str]]:
    controls = record.get("controls") if isinstance(record.get("controls"), dict) else {}
    running = verdict.outcome is None and verdict.liveness != LIVENESS_DEAD
    if not running:
        stop = (CONTROL_REFUSED, CONTROL_REASON_NOT_RUNNING)
    elif controls.get("stop") in (None, RECORD_CONTROL_NONE):
        stop = (CONTROL_REFUSED, CONTROL_REASON_WRITER_DECLINES)
    else:
        stop = (CONTROL_ALLOWED, "")
    if controls.get("restart") != RECORD_RESTART_COMMAND:
        restart_control = (CONTROL_REFUSED, CONTROL_REASON_WRITER_DECLINES)
    else:
        restart_control = (CONTROL_ALLOWED, "") if restart else (CONTROL_REFUSED, CONTROL_REASON_ARGV_UNKNOWN)
    return stop, restart_control


def _collect_builds(
    *, now: float, accountant: ProjectionAccountant | None, frame_rows: list[dict[str, Any]] | None = None
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """The build lane's collector: one :class:`BuildLane` pass over the frame so far."""

    return BuildLane(now=now, accountant=accountant, frame_rows=frame_rows if frame_rows is not None else []).collect()


#: ``build_running_work`` hands this collector the rows the lanes before it produced.
_collect_builds.takes_frame_rows = True  # type: ignore[attr-defined]
