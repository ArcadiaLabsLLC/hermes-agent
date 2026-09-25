"""``persona_chat_history_summary``: the persona's chat sessions, newest first, with their bound instance.

Separate because it is the roster entry point (snapshot, status, peer
directory, the agent-chat tool) and composes the row stores below it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from .. import chat_session_scope
from ..clock import iso_timestamp
from ..models import PersonaInstance
from ..parity import ProjectionAccountant
from ..persona_assignments import (
    retired_persona_instance_ids,
    safe_assignment_text,
    safe_assignment_token,
)
from ..persona_chat_continuity import PERSONA_CHAT_SESSION_SOURCE
from .history_rows import (
    _get_session_row,
    _history_row,
    _infer_persona_id,
    _list_sessions,
    _mission_assignment_for,
    _model_config,
    _persisted_persona_instance_id,
    _persona_chat_candidate_sort_key,
)
from .vocabulary import DEFAULT_PERSONA_CHAT_MESSAGE_TAIL, canonical_chat_persona_id

__layer__ = "lanes"
__all__ = [
    "Candidate",
    "HistorySummary",
    "persona_chat_history_summary",
]


def persona_chat_history_summary(
    *,
    persona_instances: Iterable[PersonaInstance],
    session_db: Any | None = None,
    limit: int = 50,
    message_tail: int = DEFAULT_PERSONA_CHAT_MESSAGE_TAIL,
    accountant: ProjectionAccountant | None = None,
    persona_assignments: Iterable[Any] | None = None,
    omitted_session_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Return redaction-safe persona chat-history rows for Harness snapshots.

    The Harness snapshot is the Launcher contract boundary. This helper only
    projects sessions already bound to a persona instance; it includes a
    bounded redaction-safe message tail and never starts/ticks a model turn. The
    optional ``session_db`` parameter keeps tests hermetic and lets production
    use the normal ``hermes_state.SessionDB`` lazily. ``persona_assignments``
    is an already-loaded assignment list — synthetic live-mission rows anchor
    their timestamps to the bound assignment's persisted ``created_at`` (R3);
    this helper never scans the assignment store itself.

    NO PRODUCTION CALLER SUPPLIES IT since AX2 (2026-08-31): the snapshot and
    status builders were the two, and both stopped opening the assignment store
    when the ``persona_assignments`` wire block left the frame. The parameter and
    the R3 anchor are exercised by tests only, and they are kept rather than cut
    because they belong to the ``task_bound`` synthetic-mission-row lane BELOW
    them, not to the assignment lane: that whole arm — the ``task_bound`` mode
    check, the synthetic row, this anchor — retires together under
    ``planned/task-bound-vocabulary-retirement.md``. Cutting the anchor here
    would leave the row it dates still being emitted, with its timestamps
    silently degraded to ``null``, which is a worse tree than the one this note
    describes.

    Built by :class:`HistorySummary`: index the instances, then the candidates
    from the session pools, the bound sessions and the live missions, then the
    creation-order bound.
    """

    summary = HistorySummary(
        persona_instances=persona_instances,
        limit=limit,
        message_tail=message_tail,
        accountant=accountant,
        persona_assignments=persona_assignments,
        omitted_session_ids=omitted_session_ids,
    )
    summary.index_instances()
    # A summary is a read: the fallback never opens a writer (which would
    # create the store or run upstream's migration from a read path).
    db = session_db or chat_session_scope.open_chat_session_db(read_only=True)
    if db is None:
        return []
    summary.session_candidates(db)
    summary.bound_candidates(db)
    summary.live_mission_candidates()
    return summary.rows(db)


#: One candidate row: ``(raw session row, instance, session id, kind, task id)``.
Candidate = tuple[dict[str, Any], PersonaInstance, str, str, "str | None"]


@dataclass
class HistorySummary:
    """One roster build: the instance indexes, the candidates, and the dedupe set."""

    persona_instances: Iterable[PersonaInstance]
    limit: int
    message_tail: int
    accountant: ProjectionAccountant | None
    persona_assignments: Iterable[Any] | None
    omitted_session_ids: set[str] | None
    bound_by_session: dict[str, PersonaInstance] = field(default_factory=dict)
    instances_by_id: dict[str, PersonaInstance] = field(default_factory=dict)
    instances_by_persona: dict[str, PersonaInstance] = field(default_factory=dict)
    # Candidate discovery/accounting stays lightweight. Message tails, lineage,
    # and runtime observations are hydrated only after the creation-order bound
    # is applied; on a busy runtime this avoids reading every historical chat to
    # render the newest 50.
    candidates: list[Candidate] = field(default_factory=list)
    seen: set[str] = field(default_factory=set)
    # The retirement archive listing, read AT MOST ONCE per build and only when an
    # unresolved binding actually appears: a healthy runtime with no orphans pays
    # nothing, and a runtime with fifty orphans still pays one listing, never one
    # per session.
    retired_instance_ids: frozenset[str] | None = None

    def index_instances(self) -> None:
        for instance in self.persona_instances:
            instance_id = safe_assignment_text(getattr(instance, "id", None), limit=160)
            if instance_id:
                self.instances_by_id[instance_id] = instance
            persona_id = canonical_chat_persona_id(getattr(instance, "persona_id", None))
            if persona_id:
                self.instances_by_persona[persona_id] = instance
            session_id = safe_assignment_text(
                getattr(instance, "default_chat_session_id", None), limit=200
            )
            active_session_id = safe_assignment_text(
                getattr(instance, "session_id", None), limit=200
            )
            # A task-bound mission mirrors its live run id into the default-chat
            # pointer. That id belongs to the mission/event lane, not SessionDB;
            # the synthetic mission row below is its authoritative projection.
            if (
                safe_assignment_token(getattr(instance, "mode", None)) == "task_bound"
                and getattr(instance, "current_task_id", None)
                and session_id
                and session_id == active_session_id
            ):
                session_id = None
            if session_id:
                self.bound_by_session[session_id] = instance

    def _session_pool(self, db: Any) -> list[Any]:
        pool_size = max(self.limit * 4, len(self.bound_by_session), 1)
        broad_sessions = _list_sessions(
            db,
            exclude_sources=["tool"],
            limit=pool_size,
            include_children=False,
        )
        source_sessions = _list_sessions(
            db,
            source=PERSONA_CHAT_SESSION_SOURCE,
            limit=pool_size,
            include_children=True,
        )
        try:
            return list(source_sessions) + list(broad_sessions)
        except Exception:
            return list(broad_sessions)

    def session_candidates(self, db: Any) -> None:
        for raw in self._session_pool(db) or []:
            if not isinstance(raw, dict):
                continue
            session_id = safe_assignment_text(raw.get("id"), limit=200)
            if not session_id or session_id in self.seen:
                continue
            is_source_chat = safe_assignment_token(raw.get("source")) == PERSONA_CHAT_SESSION_SOURCE
            root_meta = _model_config(raw.get("model_config")).get("mission_chat_root_id")
            if root_meta and safe_assignment_text(root_meta, limit=200) != session_id:
                # Compression descendants are projected through their stable root.
                self.seen.add(session_id)
                continue
            # Only persona-chat sessions and sessions bound to a live instance are
            # candidates for this projection. Unrelated SessionDB sources (cron,
            # telegram, cli, scratch) can never render as chat rows — counting them
            # as no_instance_match drops floods parity with by-design noise.
            if not is_source_chat and session_id not in self.bound_by_session:
                self.seen.add(session_id)
                continue
            if self.accountant is not None:
                self.accountant.consider(1)
            persisted_instance_id = _persisted_persona_instance_id(raw)
            inferred_persona = _infer_persona_id(raw, session_id=session_id)
            instance = (
                self.bound_by_session.get(session_id)
                or self.instances_by_id.get(persisted_instance_id or "")
                or (
                    self.instances_by_persona.get(inferred_persona)
                    if is_source_chat and inferred_persona
                    else None
                )
            )
            if instance is None:
                self._drop_unmatched(session_id, persisted_instance_id)
                # A session id can appear in both the source and broad pools;
                # mark it seen so a drop is only accounted once.
                self.seen.add(session_id)
                continue
            self.candidates.append((raw, instance, session_id, "chat", None))
            self.seen.add(session_id)

    def _drop_unmatched(self, session_id: str, persisted_instance_id: str | None) -> None:
        accountant = self.accountant
        if accountant is None:
            return
        # Two very different facts wear the same shape here, and only the
        # archive tells them apart: a session whose instance the operator
        # RETIRED through the first-class verb (normal lifecycle — the
        # placement ended, the chat stays inspectable) versus a binding
        # that resolves nowhere at all (lost or inconsistent data). Left
        # undifferentiated, the first grew the "projection drops" chip by
        # one on every retire, forever, and buried the second.
        #
        # The classification is declared HERE, at the emission site, per
        # ``parity.py``'s contract — a counter that special-cased the code
        # would be the stale reader-side allowlist that contract retired.
        if self.retired_instance_ids is None:
            self.retired_instance_ids = retired_persona_instance_ids()
        if persisted_instance_id and persisted_instance_id in self.retired_instance_ids:
            # By design: still nonzero on a perfectly healthy runtime,
            # purely because retiring placements is normal lifecycle.
            accountant.drop(
                "instance_retired",
                entity_id=session_id,
                detail=persisted_instance_id,
                by_design=True,
            )
        else:
            accountant.drop("no_instance_match", entity_id=session_id)

    def bound_candidates(self, db: Any) -> None:
        # Create/open paths now persist persona chat sessions before exposing them.
        # If the active instance still points at a session that SessionDB no longer
        # knows about, treat SessionDB as authoritative: the operator may have
        # deleted that chat, and resurrecting it as an empty placeholder is worse
        # than temporarily hiding a failed write.
        for session_id, instance in self.bound_by_session.items():
            if session_id in self.seen:
                continue
            raw = _get_session_row(db, session_id)
            if raw is None:
                if self.accountant is not None:
                    # Anomalous on purpose: the instance still points at a session
                    # SessionDB no longer has. Hiding the row is correct here (this
                    # projection is READ-ONLY), but the stale binding is a real
                    # defect a write path must clear —
                    # ``PersonaInstanceStore.repair_missing_chat_session_bindings``
                    # via ``harness persona-instance reconcile``.
                    self.accountant.consider(1)
                    self.accountant.drop("session_not_in_db", entity_id=session_id)
                continue
            self.candidates.append((raw, instance, session_id, "chat", None))
            self.seen.add(session_id)
            if self.accountant is not None:
                self.accountant.consider(1)

    def live_mission_candidates(self) -> None:
        # Live mission sessions. A task-bound instance runs its mission turns in a
        # session that lives in the run/event stream, not the operator SessionDB, so
        # the loops above never surface it — leaving the console on a stale operator
        # chat with nothing to switch to. Emit a minimal, live-marked row (no
        # messages; the persona_chat_trace lane carries the actual mission activity)
        # so the session is selectable and the console can switch to what is running.
        # This is NOT resurrecting a deleted chat: it is an active mission, and the
        # row only exists while the instance is bound to a task.
        assignment_rows = [item for item in (self.persona_assignments or []) if item is not None]
        assignments_by_id: dict[str, Any] = {}
        for item in assignment_rows:
            assignment_id = safe_assignment_text(getattr(item, "id", None), limit=160)
            if assignment_id:
                assignments_by_id[assignment_id] = item
        for instance in self.persona_instances:
            if safe_assignment_token(getattr(instance, "mode", None)) != "task_bound":
                continue
            session_id = safe_assignment_text(getattr(instance, "session_id", None), limit=200)
            task_id = safe_assignment_text(getattr(instance, "current_task_id", None), limit=160)
            if not session_id or not task_id or session_id in self.seen:
                continue
            goal = safe_assignment_text(getattr(instance, "current_chat_goal", None), limit=120)
            # R3 anchor: PersonaInstance persists no assigned_at, and its updated_at
            # restamps on every derive_from_workers pass — the bound assignment's
            # created_at is the only byte-stable "assigned at" truth in reach. Both
            # synthetic timestamps use it (never build time); unknown stays null so
            # it sorts as unknown rather than newest.
            assignment = _mission_assignment_for(instance, assignments_by_id, assignment_rows, task_id=task_id)
            assigned = iso_timestamp(getattr(assignment, "created_at", None)) if assignment is not None else None
            if assigned is None:
                assigned = iso_timestamp(getattr(instance, "assigned_at", None))
            synthetic = {
                "id": session_id,
                "title": goal or "Mission run",
                "message_count": 0,
                "started_at": assigned,
                "last_active": assigned,
            }
            self.candidates.append((synthetic, instance, session_id, "mission", task_id))
            self.seen.add(session_id)
            if self.accountant is not None:
                self.accountant.consider(1)

    def rows(self, db: Any) -> list[dict[str, Any]]:
        candidates = self.candidates
        # The directory contract is creation order, not activity order. Opening or
        # continuing an older chat may advance ``updated_at`` but must never move it
        # above a conversation created later. Resolve every eligible row first, then
        # sort and truncate so an active old chat cannot crowd a newer chat out of
        # the bounded projection. Session id is the deterministic tie-breaker for
        # legacy rows whose creation timestamp is missing. Candidate fields are the
        # same fields ``_history_row`` projects into the final row, so selection is
        # byte-equivalent while hydration is bounded to the visible slice.
        candidates.sort(key=_persona_chat_candidate_sort_key, reverse=True)
        visible_candidates = candidates[: max(0, self.limit)]
        if self.omitted_session_ids is not None:
            self.omitted_session_ids.update(
                session_id
                for _raw, _instance, session_id, _kind, _task_id in candidates[len(visible_candidates):]
                if session_id
            )
        visible: list[dict[str, Any]] = []
        for raw, instance, session_id, kind, task_id in visible_candidates:
            row = _history_row(
                raw,
                instance,
                session_id=session_id,
                session_db=db,
                message_tail=self.message_tail,
                kind=kind,
            )
            if task_id is not None:
                row["task_id"] = task_id
            visible.append(row)
        if self.accountant is not None:
            self.accountant.include(len(visible))
            omitted = len(candidates) - len(visible)
            if omitted > 0:
                # Deliberate bound: the directory keeps the newest ``limit`` rows by
                # creation order and every omitted row stays fetchable per-session.
                # A busy runtime drops here on EVERY build — steady state, not a
                # symptom — so it is declared by-design; a reader that counts it as
                # an anomaly pins its health pill amber forever.
                self.accountant.drop("limit", count=omitted, by_design=True)
                self.accountant.mark_truncated()
        return visible
