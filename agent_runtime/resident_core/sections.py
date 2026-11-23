"""A demoted batch answered by re-reading only the sections its events move.

The patch, overlay and running-work lanes leave a few event kinds they cannot
express, and each used to cost a full core (3-10 s on the owner's box): the
demote receipt's ``kinds=`` names them. For a kind this table names, the hub
takes the resident core (held at the batch's base offset), re-reads just the
sections the kind moves with the core's own section builders
(:class:`~agent_runtime.snapshot.sections.SnapshotFrameBuild`), and ships that
core in the same ``delta`` frame a full build would have filled. Any other
kind, or no resident core, builds as before.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterable
from typing import Any

from hermes_time import now

from ..models import Event
from .holder import logger, resident_core_enabled, root_held

__layer__ = "lanes"

__all__ = ["BUILD_ROLE_SECTIONS", "batch_sections", "rebuild_sections", "section_core_for"]

#: A ``snapshot_build reason=demote`` receipt's role when only named sections were re-read.
BUILD_ROLE_SECTIONS = "sections"

#: The persona-chat projections whose completeness rows and drop samples ride
#: the parity envelope beside the three sections they account for.
_PERSONA_CHAT_HOPS = ("persona_chat_history", "persona_chat_trace", "operator_conversation")

SECTION_WORKSPACES = "workspaces"
SECTION_PERSONA_CHAT = "persona_chat"


def _kind_sections(event: Event) -> frozenset[str] | None:
    payload = event.payload if isinstance(event.payload, dict) else {}
    event_type = getattr(event, "type", None)
    if event_type == "workspace.updated" and payload.get("change") == "task_activity":
        # The card's task counts (``read_activity``): the workspaces rows alone.
        return frozenset({SECTION_WORKSPACES})
    if event_type == "state.reconciled" and payload.get("source") == "stream_watchdog":
        families = payload.get("families")
        if isinstance(families, list) and families and set(families) <= {"chat_db", "running_work"}:
            # A chat-database move the watchdog could not name down to roots: the
            # recent chats, their traces and channels (running_work rides every
            # frame's own read).
            return frozenset({SECTION_PERSONA_CHAT} if "chat_db" in families else ())
    return None


def batch_sections(batch: Iterable[tuple[int, Event]]) -> frozenset[str] | None:
    """The sections a demoted batch moves, or ``None`` when one event is not in the table."""

    sections: set[str] = set()
    for _offset, event in batch:
        named = _kind_sections(event)
        if named is None:
            return None
        sections |= named
    return frozenset(sections)


def _rebuild_persona_chat(build: Any, working: dict[str, Any], parity: dict[str, Any]) -> None:
    """The persona-chat phase, as a full build runs it, and its completeness and drops."""

    from ..serde import to_jsonable

    build.data = {}
    build.persona_chat()
    for key in ("persona_chat_history", "persona_chat_trace", "operator_channels"):
        working[key] = to_jsonable(build.data[key])
    accountants = (build.history_accountant, build.trace_accountant, build.conversation_accountant)
    completeness = dict(parity.get("completeness") or {})
    for hop, accountant in zip(_PERSONA_CHAT_HOPS, accountants):
        completeness[hop] = to_jsonable(accountant.summary())
    parity["completeness"] = completeness
    kept = [row for row in parity.get("drops") or () if isinstance(row, dict) and row.get("hop") not in _PERSONA_CHAT_HOPS]
    fresh = [sample for accountant in accountants for sample in to_jsonable(accountant.drop_samples())]
    parity["drops"] = fresh + kept


def _rebuild_workspaces(build: Any, working: dict[str, Any], parity: dict[str, Any]) -> None:
    from ..serde import to_jsonable
    from ..snapshot.summaries import workspace_summary

    working["workspaces"] = to_jsonable([
        workspace_summary(item, persona_instances=build.topology_persona_instances, active_id=build.workspace_store.active_id())
        for item in build.workspaces
    ])


_REBUILDERS: dict[str, Callable[[Any, dict[str, Any], dict[str, Any]], None]] = {
    SECTION_WORKSPACES: _rebuild_workspaces,
    SECTION_PERSONA_CHAT: _rebuild_persona_chat,
}


def rebuild_sections(core: dict[str, Any], sections: frozenset[str], *, watermark: dict[str, Any]) -> tuple[dict[str, Any], dict[str, int]]:
    """``core`` with ``sections`` and ``running_work`` re-read now, stamped at ``watermark``.

    The scope a full build opens (runtime resolution, the chat database, the
    provider-probe memo), the build's own scope and roster phases, then only the
    named sections' phases. ``running_work`` is read here too, as every full
    build does, from this process's live lanes.
    """

    from ..projection_accountant import ProjectionAccountant
    from ..provider_probes import provider_probe_build_scope
    from ..resolution import runtime_resolution_scope
    from ..running_work import build_running_work
    from ..serde import to_jsonable
    from ..snapshot.details import persona_session_db_scope
    from ..snapshot.sections import SnapshotFrameBuild

    timings: dict[str, int] = {}
    working = dict(core)
    parity = dict(core.get("parity") or {})
    with runtime_resolution_scope(), persona_session_db_scope() as session_db, provider_probe_build_scope():
        build = SnapshotFrameBuild(session_db=session_db)
        build.resolve_scope()
        # The roster appends the instance rows to the readiness rows; neither is
        # re-read here (``agents`` is not a section this table rebuilds).
        build.agent_summaries = []
        build.personas_by_id = {str(getattr(agent, "id", "") or ""): agent for agent in build.agents}
        build.persona_roster()
        for name in sorted(sections):
            started = time.perf_counter()
            _REBUILDERS[name](build, working, parity)
            timings[name] = int((time.perf_counter() - started) * 1000)
    accountant = ProjectionAccountant("running_work")
    working["running_work"] = to_jsonable(build_running_work(accountant))
    completeness = dict(parity.get("completeness") or {})
    completeness["running_work"] = to_jsonable(accountant.summary())
    parity["completeness"] = completeness
    parity["drops"] = [row for row in parity.get("drops") or () if isinstance(row, dict) and row.get("hop") != "running_work"] + to_jsonable(accountant.drop_samples())
    parity["watermark"] = dict(watermark)
    parity["event_log_bytes"] = int(watermark.get("event_offset") or 0)
    working["parity"] = parity
    return working, timings


def section_core_for(
    batch: list[tuple[int, Event]], *, base_offset: int
) -> tuple[dict[str, Any], frozenset[str], dict[str, int]] | None:
    """The core for a demoted batch, re-read section by section from the resident
    core, or ``None`` (the caller builds the full core as before).

    Only when the switch is on, every event of the batch is in the table, and the
    resident core is held at exactly the batch's ``base_offset`` — the state the
    batch applies to. A rebuild that raises answers ``None``: the cost of a miss
    is the old full core, never a wrong section.
    """

    if not batch or not resident_core_enabled():
        return None
    sections = batch_sections(batch)
    held = root_held()
    if sections is None or held is None or held.offset != base_offset:
        return None
    last_offset, last_event = batch[-1]
    watermark = {"event_offset": int(last_offset or 0), "last_event_ts": last_event.ts, "captured_at": now()}
    try:
        core, timings = rebuild_sections(held.core, sections, watermark=watermark)
    except Exception:  # health: allow BLE001 -- a failed section read falls back to the full core
        logger.warning("resident_core sections failed; building the full core", exc_info=True)
        return None
    return core, sections, timings
