"""The three lanes keyed on a chat session's durable store: background
delegations, in-flight mission-chat turns (live: with their foreground
``tool_call`` children) and detached dispatches."""

from __future__ import annotations

from ..model_route import ACTIVE_MODEL_ROUTE, MODEL_ROUTE

import json
import sqlite3
from collections.abc import Mapping
from pathlib import Path
from types import MappingProxyType
from typing import Any

from ..clock import parse_iso_utc
from ..projection_accountant import ProjectionAccountant

from ..builds.vocabulary import OUTCOME_LOST
from .chat_turn_facts import (
    _chat_titles,
    _checking_runs,
    _dispatch_parent,
    _plan_progress,
    _promotable,
    _run_pass,
    _takes_steer,
    _titles_in,
    _turn_quiet,
)
from .ended import (
    ENDED_TURN_STATES,
    MAX_ENDED_ROWS_PER_LANE,
    OUTCOME_BY_DELEGATION_STATE,
    OUTCOME_BY_DISPATCH_STATE,
    OUTCOME_BY_TURN_STATE,
    ended_since,
    mark_ended,
)
from .ownership import _head_home, _owner_of, _pid_identity
from .row_context import RowContext, plan_items
from .rows import (
    LanePass,
    _iso,
    _module,
    _preview,
    _progress,
    _source,
    _stale_thresholds,
    bounded_operator_text,
    elapsed_seconds,
    work_id_of,
    work_row,
)
from .vocabulary import (
    CHECKING_TITLE,
    PHASE_CHECKING,
    DELEGATION_STATE_FINALIZING,
    KIND_CHAT_TURN,
    KIND_DELEGATION,
    KIND_DISPATCH,
    KIND_TOOL_CALL,
    LANE_DURABLE,
    LANE_LIVE,
    PID_DEAD,
    PID_RECYCLED,
    SOURCE_OK,
    SOURCE_UNAVAILABLE,
    STATUS_COMPLETED,
    STATUS_ERROR,
    STATUS_FINALIZING,
    STATUS_RUNNING,
    STATUS_STALLED,
    STATUS_STALLING,
    STATUS_UNKNOWN,
    STALLING_FRACTION,
    _MAX_ROWS_PER_SOURCE,
    _STATE_DB_FILENAME,
    _UNDELIVERABLE_WINDOW_SECONDS,
)

__layer__ = "lanes"


#: The delegation store's own record words (upstream ``tools.async_delegation``'s
#: ``status`` / ``state`` values) mapped onto the shared status vocabulary — the
#: table :func:`_delegation_status` reads. ``running`` is deliberately NOT a key:
#: it is the one word whose verdict needs the progress token (running vs stalled),
#: so it is read by name below. A word in neither is ``unknown``, never a guess.
DELEGATION_STATUS_BY_RECORD: Mapping[str, str] = MappingProxyType(
    {
        "stalled": STATUS_STALLED,
        "stalling": STATUS_STALLING,
        "finalizing": STATUS_FINALIZING,
        "completed": STATUS_COMPLETED,
        "ok": STATUS_COMPLETED,
        "success": STATUS_COMPLETED,
        "error": STATUS_ERROR,
        "failed": STATUS_ERROR,
        "interrupted": STATUS_ERROR,
    }
)
#: The delegation record's in-flight word. The same spelling as this package's
#: ``STATUS_RUNNING`` and the turn journal's ``TURN_STATE_RUNNING``, but a
#: different question: what the delegation STORE wrote, not what the row says.
DELEGATION_RECORD_RUNNING = "running"


def _stoppable_here(turn_id: str) -> bool:
    from agent_runtime.live_turns import stoppable_here

    return stoppable_here(turn_id)

def _delegation_status(
    record: dict[str, Any], *, idle_stale: float, in_tool_stale: float
) -> str:
    """Map a delegation record onto the shared status vocabulary.

    The stale monitor sweeps every 30s, so a child can be frozen well past the
    threshold while its record still reads ``running``. Deriving the verdict
    from the progress token here — the same token and the same thresholds the
    monitor uses — means the projection never shows ``running`` for something
    that demonstrably stopped progressing.
    """

    raw = str(record.get("status") or record.get("state") or "").strip().lower()
    verdict = DELEGATION_STATUS_BY_RECORD.get(raw)
    if verdict is not None:
        return verdict
    if raw != DELEGATION_RECORD_RUNNING:
        return STATUS_UNKNOWN

    quiet = record.get("seconds_since_progress")
    if isinstance(quiet, (int, float)):
        threshold = in_tool_stale if record.get("in_tool") else idle_stale
        if float(quiet) >= threshold:
            return STATUS_STALLED
    return STATUS_RUNNING


def _store_unreadable(exc: BaseException) -> dict[str, Any]:
    return _source(
        SOURCE_UNAVAILABLE,
        lane=LANE_DURABLE,
        reason="store_unreadable",
        detail=type(exc).__name__,
    )


class DelegationLane(LanePass):
    """Durable ``async_delegations`` rows, enriched from the live record map.

    The durable read opens the database only when the file already exists and
    never runs DDL: this projection must not be the thing that CREATES a
    ``state.db`` (or upgrades its schema) as a side effect of an operator
    reading a HUD.

    Phases, named as the terminal lane's are (the same shape):
    :meth:`read_durable` → :meth:`durable_row` per record → :meth:`enrich_live`
    (:meth:`live_row` per live record) → :meth:`LanePass.finish`.
    """

    kind = KIND_DELEGATION

    def __init__(self, *, now: float, accountant: ProjectionAccountant | None) -> None:
        super().__init__(now=now, accountant=accountant)
        self.rows: dict[str, dict[str, Any]] = {}
        self.idle_stale, self.in_tool_stale = _stale_thresholds()
        self.lane = LANE_DURABLE
        self.live_error = ""

    def collect(self) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        head, _provenance = _head_home()
        if head is None:
            return [], _source(SOURCE_UNAVAILABLE, lane=LANE_DURABLE, reason="home_unresolved")

        db_path = head / _STATE_DB_FILENAME
        # Whether `state.db` exists yet is deliberately NOT reported. It is a
        # filesystem observation rather than a fact about work, and — uniquely
        # corrosive — it was one this very projection used to perturb: the
        # chat-turn lane's import chain CREATED the file through the tool
        # singleton's constructor (retired — see the module docstring), so build 1
        # and build 2 of the same process would disagree about it. Keeping the
        # fact off the wire remains correct regardless: storage layout is not
        # lane health.
        if db_path.exists():
            fetched, refusal = self.read_durable(db_path)
            if refusal is not None:
                return [], refusal
            for record in fetched:
                self.durable_row(record)
            for record in self.read_ended(db_path):
                self.ended_row(record)
        self.enrich_live()
        return (
            self.finish(list(self.rows.values())),
            _source(SOURCE_OK, lane=self.lane, live_enrichment_error=self.live_error),
        )

    def read_durable(self, db_path: Path) -> tuple[list[Any], dict[str, Any] | None]:
        """The in-flight rows, read-only, or a typed ``unavailable`` source entry."""

        try:
            conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=5)
        except Exception as exc:
            return [], _store_unreadable(exc)
        try:
            cursor = conn.execute(
                """SELECT delegation_id, origin_session, parent_session_id, state,
                          dispatched_at, owner_pid, owner_started_at, task_json
                   FROM async_delegations
                   WHERE state IN ('running','finalizing')"""
            )
            return cursor.fetchall(), None
        except sqlite3.OperationalError as exc:
            # A state.db that predates the delegation table is a store with no
            # delegations, not an unreadable store — the same answer as a table
            # with no rows. Same ruling as the absent checkpoint: schema layout
            # is not lane health.
            if "no such table" not in str(exc).lower():
                return [], _store_unreadable(exc)
            return [], None
        except Exception as exc:
            return [], _store_unreadable(exc)
        finally:
            try:
                conn.close()
            except Exception:
                pass

    def read_ended(self, db_path: Path) -> list[Any]:
        """Delegations that settled inside the retention window, newest first (D2); fail-safe: none."""

        try:
            conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=5)
        except Exception:
            return []
        try:
            return conn.execute(
                """SELECT delegation_id, origin_session, parent_session_id, state,
                          dispatched_at, owner_pid, owner_started_at, task_json, completed_at
                   FROM async_delegations
                   WHERE state NOT IN ('running','finalizing') AND completed_at >= ?
                   ORDER BY completed_at DESC LIMIT ?""",
                (ended_since(self.now), MAX_ENDED_ROWS_PER_LANE),
            ).fetchall()
        except Exception:  # an older store or a busy one: the running rows still stand
            return []
        finally:
            try:
                conn.close()
            except Exception:
                pass

    def ended_row(self, record: tuple[Any, ...]) -> None:
        """A settled delegation's row: its outcome and end stamp, no Stop, no owner-PID check."""

        *head, completed_at = record
        delegation_id = bounded_operator_text(head[0], limit=200)
        if not delegation_id or f"{KIND_DELEGATION}:{delegation_id}" in self.rows:
            return
        self.durable_row(tuple(head), ended=True)
        row = self.rows.get(f"{KIND_DELEGATION}:{delegation_id}")
        if row is not None:
            started = head[4]
            mark_ended(row, outcome=OUTCOME_BY_DELEGATION_STATE.get(str(head[3] or "").lower(), OUTCOME_LOST),
                       finished=float(completed_at) if isinstance(completed_at, (int, float)) else None,
                       started=float(started) if isinstance(started, (int, float)) else None)

    def durable_row(self, record: tuple[Any, ...], *, ended: bool = False) -> None:
        (
            delegation_id,
            origin_session,
            parent_session_id,
            state,
            dispatched_at,
            owner_pid,
            owner_started_at,
            task_json,
        ) = record
        delegation_id = bounded_operator_text(delegation_id, limit=200)
        if not delegation_id:
            return
        self.consider()
        _alive, verified, verdict = (False, False, "") if ended else _pid_identity(owner_pid, owner_started_at)
        if verdict == PID_DEAD:
            # The owning process is gone. ``recover_abandoned_delegations``
            # is the authority that reclassifies these; reporting them as
            # running here would contradict it.
            self.drop(
                "owner_exited",
                entity_id=delegation_id,
                detail="delegation owner process no longer exists",
                by_design=True,
            )
            return
        if verdict == PID_RECYCLED:
            self.drop(
                "pid_recycled",
                entity_id=delegation_id,
                detail="owner PID was recycled",
                by_design=True,
            )
            return
        try:
            task = json.loads(task_json or "{}")
        except Exception:
            task = {}
        goal = task.get("goal") if isinstance(task, dict) else ""
        status = (
            STATUS_FINALIZING
            if str(state or "") == DELEGATION_STATE_FINALIZING
            else (STATUS_RUNNING if verified else STATUS_UNKNOWN)
        )
        session_id = bounded_operator_text(parent_session_id or origin_session, limit=200)
        owner_persona, owner_instance = _owner_of(session_id, memo=self.owners)
        durable = work_row(
            kind=KIND_DELEGATION,
            stable_id=delegation_id,
            label=bounded_operator_text(goal, limit=160) or delegation_id,
            status=status,
            source_lane=LANE_DURABLE,
            pid=owner_pid,
            pid_verified=verified,
            persona_id=owner_persona,
            persona_instance_id=owner_instance,
            session_id=session_id,
            started_at=_iso(dispatched_at),
            elapsed_seconds=elapsed_seconds(
                float(dispatched_at) if isinstance(dispatched_at, (int, float)) else None,
                now=self.now,
            ),
            # No progress token survives a process boundary — say so rather
            # than emitting zeros that would read as "idle".
            progress=_progress(available=False),
            cancellable=True,
        )
        self.rows[durable["work_id"]] = durable

    def enrich_live(self) -> None:
        mod = _module("tools.async_delegation")
        if mod is None:
            return
        try:
            live_records = mod.list_async_delegations()
            # Same rule as the terminal lane: rows prove ownership, residency
            # does not.
            if live_records:
                self.lane = LANE_LIVE
            for record in live_records:
                self.live_row(record)
        except Exception as exc:
            self.live_error = type(exc).__name__

    def live_row(self, record: Any) -> None:
        if not isinstance(record, dict):
            return
        delegation_id = bounded_operator_text(record.get("delegation_id"), limit=200)
        if not delegation_id:
            return
        status = _delegation_status(
            record, idle_stale=self.idle_stale, in_tool_stale=self.in_tool_stale
        )
        work_id = f"{KIND_DELEGATION}:{delegation_id}"
        if status in {STATUS_COMPLETED, STATUS_ERROR}:
            # An ended row the store already settled stays (D2); a running row the store has not
            # settled yet leaves until the store's own settle lists it as ended.
            if self.rows.get(work_id, {}).get("finished_at"):
                return
            if self.rows.pop(work_id, None) is not None:
                self.drop(
                    "delegation_settled",
                    entity_id=delegation_id,
                    detail="live record reports a terminal status",
                    by_design=True,
                )
            return
        existing = self.rows.get(work_id)
        if existing is None:
            existing = self.rows[work_id] = self._live_only_row(record, delegation_id, status)
        else:
            existing["source_lane"] = LANE_LIVE
            existing["status"] = status
            if not existing.get("label") or existing["label"] == delegation_id:
                existing["label"] = (
                    bounded_operator_text(record.get("goal"), limit=160) or delegation_id
                )
        existing["progress"] = _progress(
            api_calls=_first_child_api_calls(record),
            in_tool=record.get("in_tool"),
            seconds_since_progress=record.get("seconds_since_progress"),
            available=True,
        )

    def _live_only_row(self, record: dict[str, Any], delegation_id: str, status: str) -> dict[str, Any]:
        """A delegation the live map holds and the durable store did not list."""

        self.consider()
        dispatched = record.get("dispatched_at")
        session_id = bounded_operator_text(
            record.get("parent_session_id") or record.get("session_key"),
            limit=200,
        )
        owner_persona, owner_instance = _owner_of(session_id, memo=self.owners)
        return work_row(
            kind=KIND_DELEGATION,
            stable_id=delegation_id,
            label=bounded_operator_text(record.get("goal"), limit=160) or delegation_id,
            status=status,
            source_lane=LANE_LIVE,
            persona_id=owner_persona,
            persona_instance_id=owner_instance,
            session_id=session_id,
            started_at=_iso(dispatched),
            elapsed_seconds=elapsed_seconds(
                float(dispatched) if isinstance(dispatched, (int, float)) else None,
                now=self.now,
            ),
            cancellable=True,
        )


def _first_child_api_calls(record: dict[str, Any]) -> Any:
    """The first child's ``api_calls`` off a live record, else None."""

    activity = record.get("children_activity")
    if isinstance(activity, list) and activity and isinstance(activity[0], dict):
        return activity[0].get("api_calls")
    return None


def _collect_delegations(
    *, now: float, accountant: ProjectionAccountant | None
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """The delegation lane's collector: one :class:`DelegationLane` pass."""

    return DelegationLane(now=now, accountant=accountant).collect()


class ChatTurnLane(LanePass):
    """In-flight turn-journal records — the durable "an agent is thinking" fact —
    enriched LIVE where this process is the one executing the turn.

    The journal is written from whichever process executes the turn and read
    from anywhere, so the durable row needs no enrichment to be honest. A record
    stuck in an in-flight state after its executor died is a corpse the
    serve-boot sweep and the next-send repair flip to ``interrupted``; until one
    of them runs it is reported ``unknown`` rather than ``running`` when its
    start stamp is missing, because with no anchor there is nothing to age.

    RW1/RW2. The durable row used to be the whole answer: ``label`` was the
    instance id, ``progress`` was ``unavailable`` on every turn, and a turn
    blocked for minutes on a silent foreground ``flutter build`` read exactly
    like a hung one. Now ``label`` is the agent's display name (the instance id
    stays ``owner.persona_instance_id``), ``title`` is the conversation's, and
    when :mod:`agent_runtime.live_turns` holds the turn — i.e. this projection
    is running inside the executing serve — the row carries ``current_tool``,
    real ``progress`` (api calls, the tool in flight, seconds since progress)
    and a ``running`` / ``stalling`` / ``stalled`` verdict from it, and each
    foreground command the turn is blocked on becomes a ``tool_call`` child row.

    Phases: :meth:`collect` → :meth:`turn_row` per record (→ :meth:`enrich_live`)
    → :meth:`attach_titles` → :meth:`LanePass.finish`.
    """

    kind = KIND_CHAT_TURN

    def __init__(self, *, now: float, accountant: ProjectionAccountant | None) -> None:
        super().__init__(now=now, accountant=accountant)
        self.rows: list[dict[str, Any]] = []
        # instance handle -> display name, resolved at most once per pass (the
        # same memo and the same fail-safe reader as DispatchLane.named).
        self.names: dict[str, str] = {}
        self.lane = LANE_DURABLE
        self.idle_stale, self.in_tool_stale = _stale_thresholds()
        self.running_states: frozenset[str] = frozenset()
        self.context = RowContext()

    def collect(self) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        try:
            from ..mission_chat_turns.reads import running_work_turn_rows
            from ..mission_chat_turns.states import (
                INFLIGHT_TURN_STATES,
                TURN_STATE_OUTCOME_UNKNOWN,
            )

            records, settled = running_work_turn_rows(
                settled_states=ENDED_TURN_STATES, settled_since=ended_since(self.now),
                settled_limit=MAX_ENDED_ROWS_PER_LANE,
            )
        except Exception as exc:
            return [], _source(
                SOURCE_UNAVAILABLE,
                lane=LANE_DURABLE,
                reason="journal_unreadable",
                detail=type(exc).__name__,
            )
        self.running_states = frozenset(INFLIGHT_TURN_STATES - {TURN_STATE_OUTCOME_UNKNOWN})
        for record in records:
            if isinstance(record, dict):
                self.turn_row(record)
        for record in settled:
            if isinstance(record, dict):
                self.turn_row(record, ended=True)
        for bound in _checking_runs():
            self.checking_row(bound)
        self.attach_titles()
        return self.finish(self.rows), _source(SOURCE_OK, lane=self.lane)

    def named(self, instance_id: str) -> str:
        if not instance_id:
            return ""
        if instance_id not in self.names:
            from ..persona_assignments import persona_instance_display_name

            self.names[instance_id] = persona_instance_display_name(instance_id)
        return self.names[instance_id]

    def turn_row(self, record: dict[str, Any], *, ended: bool = False) -> None:
        """One journal record's row; ``ended``: a settled record, kept for the retention window."""

        self.consider()
        turn_id = bounded_operator_text(record.get("turn_id") or record.get("client_message_id"), limit=200)
        if not turn_id:
            self.drop("unidentified_turn", detail="record carries no turn id")
            return
        started_at = bounded_operator_text(record.get("started_at"), limit=80)
        started = parse_iso_utc(started_at)
        state = str(record.get("state") or "")
        instance_id = bounded_operator_text(record.get("persona_instance_id"), limit=200)
        session_id = bounded_operator_text(
            record.get("session_id")
            or record.get("root_chat_session_id")
            or record.get("active_session_id"),
            limit=240,
        )
        # C1h-bis: the persona comes from the shared authority (``_owner_of`` →
        # ``chat_session_owner_persona``), never derived here, per honesty rule
        # 5. The record's OWN ``persona_instance_id`` stays the row's instance —
        # the journal recorded which instance ran this turn, a stronger fact
        # than a re-derivation from the root's current binding — and when the
        # two disagree the persona is left BLANK rather than pairing this turn's
        # instance with another instance's persona.
        owner_persona, owner_instance = _owner_of(session_id, memo=self.owners)
        if instance_id and owner_instance and owner_instance != instance_id:
            owner_persona = ""
        instance = instance_id or owner_instance
        # A pass of an UNTIL_DONE Work run says which pass it is, and its Stop (``runtime.work.cancel``)
        # ends the whole run (RT-WORK-CLAIM-RUNS-UNTIL-DONE); any other chat turn is unchanged.
        run_pass = {} if ended else _run_pass(session_id, record.get("client_message_id"))
        route = record.get(MODEL_ROUTE if ended else ACTIVE_MODEL_ROUTE)
        row = work_row(
            kind=KIND_CHAT_TURN,
            stable_id=turn_id,
            label=self.named(instance) or instance or turn_id,
            # The journal state IS the status: the journal's own in-flight set
            # means a turn is running, EXCEPT ``outcome_unknown`` — the provider
            # outcome was never observed, which is exactly the shared
            # ``unknown`` and must not be dressed up as running.
            status=STATUS_RUNNING if state in self.running_states else STATUS_UNKNOWN,
            source_lane=LANE_DURABLE,
            persona_id=owner_persona,
            persona_instance_id=instance,
            session_id=session_id,
            started_at=started_at,
            elapsed_seconds=elapsed_seconds(
                started.timestamp() if started is not None else None, now=self.now
            ),
            progress=_progress(available=False),
            # The conversation's Stop, through ``cancel_work`` (RT-STOP-REACHES-EVERY-RUNNING-REPLY-
            # THROUGH-ONE-SEAM): offered for a Work pass (it ends the run) and for any reply this
            # process can reach now — never advertised for one it cannot.
            cancellable=bool(run_pass) or (not ended and _stoppable_here(turn_id)),
            # Whether a steer sent now lands in THIS turn — the steer door's own read, so the client
            # never infers it from the turn's kind or its id (a Work turn takes one, a forged one not).
            extra={"title": "", "current_tool": None, **run_pass,
                   **({MODEL_ROUTE: route} if route else {}),
                   "steerable": not ended and _takes_steer(session_id, record.get("client_message_id")),
                   # D12: who asked and the folder are known only where the turn runs
                   # (``enrich_live``); the workspace is the instance's, read here.
                   "asked_by": None, "cwd": None, **self.context.workspace(instance),
                   **_dispatch_parent(record)},
        )
        self.rows.append(row)
        if ended:
            settled = parse_iso_utc(bounded_operator_text(record.get("updated_at"), limit=80))
            mark_ended(row, outcome=OUTCOME_BY_TURN_STATE.get(state, OUTCOME_LOST),
                       finished=settled.timestamp() if settled is not None else None,
                       started=started.timestamp() if started is not None else None)
        elif state in self.running_states:
            self.enrich_live(row, turn_id)

    def checking_row(self, bound: Any) -> None:
        """An until-done run checking a pass that ended: it holds its chat, so it is listed as running.

        No turn is in the journal then — the pass ended and the next is not queued — yet the pass's queue
        entry holds the root while the goal judge's model call runs (``goal_turns._checked``), and a message
        sent meanwhile waits behind it. Listed as the run's pass (``work_request`` / ``goal``, the same Stop
        that ends the whole run), titled for what it does, taking no steer: there is no turn to steer
        (RT-CHAT-HELD-BETWEEN-UNTIL-DONE-PASSES-LISTS-NOTHING-RUNNING).
        """

        self.consider()
        args = bound.turn_args if isinstance(bound.turn_args, Mapping) else {}
        session_id = bounded_operator_text(bound.root_session_id, limit=240)
        owner_persona, owner_instance = _owner_of(session_id, memo=self.owners)
        instance = bounded_operator_text(args.get("persona_instance_id"), limit=200) or owner_instance
        from ..chat_goal import MAX_PASSES

        self.rows.append(work_row(
            kind=KIND_CHAT_TURN,
            stable_id=bounded_operator_text(bound.cmid, limit=200),
            label=self.named(instance) or instance or session_id,
            status=STATUS_RUNNING,
            source_lane=LANE_DURABLE,
            persona_id=owner_persona,
            persona_instance_id=instance,
            session_id=session_id,
            started_at=_iso(bound.checking_since),
            elapsed_seconds=elapsed_seconds(bound.checking_since, now=self.now),
            progress=_progress(available=False),
            cancellable=True,
            extra={"title": CHECKING_TITLE, "current_tool": None, "phase": PHASE_CHECKING,
                   "work_request": bound.request_id,
                   "goal": {"pass": bound.turns + 1, "max_passes": MAX_PASSES}, "steerable": False},
        ))

    def enrich_live(self, row: dict[str, Any], turn_id: str) -> None:
        """The executing process's view of the turn; nothing when it runs elsewhere."""

        try:
            from ..live_turns import live_turn_view

            live = live_turn_view(turn_id)
        except Exception:
            live = None
        if live is None:
            return
        self.lane = LANE_LIVE
        row["source_lane"] = LANE_LIVE
        current = live.tools[-1] if live.tools else None
        quiet, in_tool = _turn_quiet(live, current)
        row["status"] = self.verdict(quiet, in_tool=bool(in_tool))
        row["progress"] = _progress(
            api_calls=live.api_calls, in_tool=in_tool, seconds_since_progress=quiet, available=True
        )
        if current is not None:
            row["current_tool"] = {
                "call_id": current.call_id,
                "name": current.tool_name,
                "preview": bounded_operator_text(current.preview, limit=240),
                "elapsed_seconds": int(current.elapsed_seconds),
                "timeout_seconds": current.timeout_seconds,
                # The running card's "Send to background" (``runtime.work.background.promote``).
                "promotable": _promotable(turn_id, current.call_id),
            }
        row["asked_by"] = self.context.asked_by_marker(live.asked_by_marker)
        row["cwd"] = bounded_operator_text(live.workdir, limit=1024) or None
        plan = _plan_progress(live.plan)
        if plan is not None:
            # RT-RUNNING-CHAT-TURN-CARRIES-PLAN-PROGRESS: ``{done, total, current, current_index}``; absent = no plan.
            # D12: and its steps, each with its state (no time per step is kept).
            row["plan"] = {**plan, "items": plan_items(live.plan)}
        for call in live.tools:
            if call.foreground is not None:
                self.foreground_row(row, turn_id, call)

    def verdict(self, quiet: float | None, *, in_tool: bool) -> str:
        """``running`` / ``stalling`` / ``stalled`` from quiet seconds, on the
        delegation monitor's own thresholds (one authority)."""

        if quiet is None:
            return STATUS_RUNNING
        threshold = self.in_tool_stale if in_tool else self.idle_stale
        if quiet >= threshold:
            return STATUS_STALLED
        if quiet >= threshold * STALLING_FRACTION:
            return STATUS_STALLING
        return STATUS_RUNNING

    def foreground_row(self, turn: dict[str, Any], turn_id: str, call: Any) -> None:
        """RW2: the foreground command a live turn is blocked on, as its child."""

        self.consider()
        command = call.foreground
        owner = turn.get("owner") or {}
        timeout = int(command.timeout_seconds) if command.timeout_seconds is not None else call.timeout_seconds
        self.rows.append(
            work_row(
                kind=KIND_TOOL_CALL,
                stable_id=f"{turn_id}:{call.call_id}",
                label=bounded_operator_text(call.command or command.command or call.tool_name, limit=120),
                command=bounded_operator_text(command.command or call.command, limit=400),
                status=self.verdict(command.seconds_since_output, in_tool=True),
                source_lane=LANE_LIVE,
                pid=command.pid,
                # In-process ownership is the identity proof, as for a live
                # terminal-registry row: this process spawned and waits on it.
                pid_verified=command.pid is not None,
                persona_id=owner.get("persona_id") or "",
                persona_instance_id=owner.get("persona_instance_id") or "",
                session_id=owner.get("session_id") or "",
                started_at=_iso(command.started_at),
                elapsed_seconds=int(command.elapsed_seconds),
                progress=_progress(
                    in_tool=call.tool_name,
                    seconds_since_progress=command.seconds_since_output,
                    available=True,
                ),
                tail_preview=_preview(command.tail, self.accountant),
                # That call's own thread gets the interrupt bit; the turn carries on — see ``cancel_work``.
                cancellable=True,
                extra={
                    "parent_work_id": turn["work_id"],
                    "tool_name": call.tool_name,
                    "tool_call_id": call.call_id,
                    "timeout_seconds": timeout,
                    "seconds_since_output": command.seconds_since_output,
                    "output_chars": command.output_chars,
                },
            )
        )

    def attach_titles(self) -> None:
        turns = [row for row in self.rows if row.get("kind") == KIND_CHAT_TURN]
        sessions = {(row.get("owner") or {}).get("session_id") or "" for row in turns}
        titles = _chat_titles(sessions - {""})
        for row in turns:
            row["title"] = titles.get((row.get("owner") or {}).get("session_id") or "", "")


def _collect_chat_turns(
    *, now: float, accountant: ProjectionAccountant | None
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """The chat-turn lane's collector: one :class:`ChatTurnLane` pass."""

    return ChatTurnLane(now=now, accountant=accountant).collect()


class DispatchLane(LanePass):
    """In-flight detached dispatches — durable-only, and honestly so.

    The dispatch store is the whole truth here: a dispatch's row is written
    BEFORE its turn starts and settled when it ends, from whichever process ran
    it, so any lane reads the same answer and no live enrichment exists to add.
    That is unusual among these lanes and it is a property of the store, not an
    omission.

    Owner identity is verified like every other lane — a row whose recorded PID
    is gone is work that cannot still be running, and a recycled number is a
    stranger. The difference from the terminal/delegation lanes is what happens
    next: an orphaned dispatch is NOT lost, because
    ``restore_undelivered_dispatches`` reclassifies it into a deliverable
    ``unknown`` outcome at the next serve boot. So dropping it from the HUD is
    honest — it stopped running — rather than a silent loss.

    Phases: :meth:`read` → :meth:`running_row` per record (a dead owner is
    REPORTED, not dropped) → :meth:`undeliverable_rows` → :meth:`LanePass.finish`.
    """

    kind = KIND_DISPATCH

    def __init__(self, *, now: float, accountant: ProjectionAccountant | None) -> None:
        super().__init__(now=now, accountant=accountant)
        self.collected: list[dict[str, Any]] = []
        # instance handle → operator-facing name, resolved AT MOST ONCE per pass.
        #
        # The label is the only part of a dispatch row an operator actually reads,
        # and it named the target by persona id ("dev: run the suite") while the
        # agent that owns the row is called something else entirely. The memo is what
        # keeps that a projection concern rather than a cost one: this lane is polled,
        # each miss is a small row read, and a burst of dispatches to one teammate
        # must not pay for the same name N times. A resolution that fails is memoized
        # as "" too — a name that cannot be read now will not read on the next row
        # either, and retrying it per row is how a slow store becomes a slow panel.
        self.names: dict[str, str] = {}
        self.context = RowContext()

    def collect(self) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        try:
            from .. import dispatch_store

            rows = dispatch_store.running_dispatches(limit=_MAX_ROWS_PER_SOURCE * 2)
        except Exception as exc:
            return [], _store_unreadable(exc)
        for record in rows:
            self.running_row(record)
        self.undeliverable_rows(dispatch_store)
        self.ended_rows(dispatch_store)
        return self.finish(self.collected), _source(SOURCE_OK, lane=LANE_DURABLE)

    def ended_rows(self, dispatch_store: Any) -> None:
        """Requests that ended inside the retention window, with how they ended (D2); fail-safe."""

        try:
            ended = dispatch_store.settled_dispatches(since=ended_since(self.now), limit=MAX_ENDED_ROWS_PER_LANE)
        except Exception:  # the running rows already collected are still true
            ended = []
        for record in ended:
            row = self.running_row(record)
            if row is None:
                continue
            started, finished = record.get("dispatched_at"), record.get("completed_at")
            mark_ended(row, outcome=OUTCOME_BY_DISPATCH_STATE.get(str(record.get("state") or ""), OUTCOME_LOST),
                       finished=float(finished) if isinstance(finished, (int, float)) else None,
                       started=float(started) if isinstance(started, (int, float)) else None)

    def named(self, record: dict[str, Any]) -> str:
        """The target's display name, else its persona id, else ``""``."""

        from ..persona_assignments import persona_instance_display_name

        persona = bounded_operator_text(record.get("target_persona"), limit=120)
        handle = bounded_operator_text(record.get("target_instance_id"), limit=200)
        if not handle:
            return persona
        if handle not in self.names:
            # Fail-safe at the source: this returns "" for an absent or
            # unreadable row rather than raising into a projection whose
            # exceptions blank the whole lane.
            self.names[handle] = persona_instance_display_name(handle)
        return self.names[handle] or persona

    def running_row(self, record: Any) -> dict[str, Any] | None:
        if not isinstance(record, dict):
            return None
        dispatch_id = bounded_operator_text(record.get("dispatch_id"), limit=200)
        if not dispatch_id:
            return None
        self.consider()
        pid = record.get("owner_pid")
        _alive, verified, verdict = _pid_identity(pid, record.get("owner_started_at"))
        # A dead or recycled owner is REPORTED here, not dropped — the one place
        # this lane deliberately differs from the terminal and delegation lanes,
        # and the difference is a property of the store rather than a relaxation
        # of the rule.
        #
        # There, a dead PID means the work is over and nobody is owed anything;
        # dropping the row is the honest end of it. Here, a dead PID means the
        # CHILD PROCESS running a dispatch died while a SENDER IS STILL WAITING
        # for its answer. Hiding it would make the one dispatch most worth
        # looking at — the one that just died — the only invisible one, and to an
        # operator its disappearance reads as "it finished". So it surfaces as
        # ``unknown`` with ``pid_verified: false``: something was dispatched, its
        # process is gone, and nothing has settled it yet. The periodic orphan
        # sweep converts it into a deliverable ``unknown`` completion within its
        # cadence, and the row then leaves this projection because it is no
        # longer running work.
        orphaned = verdict in {PID_DEAD, PID_RECYCLED}
        started = record.get("dispatched_at")
        target = bounded_operator_text(record.get("target_persona"), limit=120)
        # The LABEL names the teammate the way the operator does; ``persona_id``
        # below keeps the machine identity. Two fields, two audiences — putting a
        # display name in ``persona_id`` would be a lie a consumer could route on.
        named = self.named(record) or target
        label = bounded_operator_text(record.get("title"), limit=160) or (
            f"{named}: {bounded_operator_text(record.get('ask'), limit=120)}" if named else dispatch_id
        )
        self.collected.append(
            work_row(
                kind=KIND_DISPATCH,
                stable_id=dispatch_id,
                label=label,
                status=STATUS_RUNNING if (verified and not orphaned) else STATUS_UNKNOWN,
                source_lane=LANE_DURABLE,
                pid=pid,
                pid_verified=verified and not orphaned,
                persona_id=target,
                persona_instance_id=bounded_operator_text(record.get("target_instance_id"), limit=200),
                # The SENDER's chat root: the thread the answer is owed to, and
                # the row an operator would click through to.
                session_id=bounded_operator_text(record.get("sender_session_id"), limit=240),
                started_at=_iso(started),
                elapsed_seconds=elapsed_seconds(
                    float(started) if isinstance(started, (int, float)) else None, now=self.now
                ),
                # The target's turn owns its own progress signal; none of it
                # survives to this store, so say so rather than emit zeros.
                progress=_progress(available=False),
                tail_preview=_preview(record.get("ask"), self.accountant),
                # Stop is ``surface._cancel_dispatch`` → ``request_cancel``: the
                # supervisor tree-kills the child and settles the row and the
                # sender's delivery; a row another process supervises gets the
                # durable mark its cancel watch acts on; and a row whose process
                # has already ended (this row's ``unknown``) is settled at once.
                # Every one of those answers, so the button keeps its promise —
                # it used to be False here long after that seam landed, which
                # left a dead or running request on the HUD with no way to stop
                # it (MC-RUNNING-NOW-LISTS-LANE-WORK-WHOSE-PROCESS-HAS-ENDED-AND-CANNOT-STOP-IT).
                cancellable=True,
                extra=self.asked_where(record),
            )
        )
        return self.collected[-1]

    def asked_where(self, record: dict[str, Any]) -> dict[str, Any]:
        """D12: the asking agent (the sender's chat root's owner), the target's workspace; the folder is the child's, unknown here."""

        sender_persona, sender_instance = _owner_of(record.get("sender_session_id"), memo=self.owners)
        return {
            "asked_by": self.context.agent(record.get("sender_persona_id") or sender_persona, sender_instance),
            "cwd": None,
            **self.context.workspace(record.get("target_instance_id")),
        }

    def undeliverable_rows(self, dispatch_store: Any) -> None:
        # UNDELIVERABLE completions ride this lane too, and they are the reason it
        # is not purely "running" work.
        #
        # Three paths abandon a finished dispatch without ever forging a delivery
        # turn — no sender session, an unresolvable sender, and the attempt cap —
        # and all three used to leave nothing behind but an EventLog row that no
        # consumer reads. So an agent asked for work, the work RAN, an answer came
        # back, and then the answer was discarded in silence: no delivery, no
        # notification, and a HUD that says everything is fine. Surfacing them here
        # is the cheapest honest fix, because this is already the surface an
        # operator looks at to ask "what is my machine doing about that request".
        #
        # They are `error`, not `unknown`: nothing here is uncertain. We know the
        # dispatch settled, and we know its answer will never be delivered.
        try:
            dropped = dispatch_store.undeliverable_dispatches(
                limit=_MAX_ROWS_PER_SOURCE,
                since=self.now - _UNDELIVERABLE_WINDOW_SECONDS,
            )
        except Exception:
            # A read that fails here must not take the whole lane down with it — the
            # running rows above are already collected and are still true.
            dropped = []
        for record in dropped:
            self.undeliverable_row(record)

    def undeliverable_row(self, record: Any) -> None:
        if not isinstance(record, dict):
            return
        dispatch_id = bounded_operator_text(record.get("dispatch_id"), limit=200)
        if not dispatch_id:
            return
        self.consider()
        target = bounded_operator_text(record.get("target_persona"), limit=120)
        named = self.named(record) or target
        reason = bounded_operator_text(record.get("delivery_error"), limit=160) or "undelivered"
        settled = record.get("completed_at") or record.get("updated_at")
        self.collected.append(
            work_row(
                kind=KIND_DISPATCH,
                stable_id=dispatch_id,
                label=(
                    f"undelivered reply from {named}"
                    if named
                    else f"undelivered reply ({dispatch_id})"
                ),
                status=STATUS_ERROR,
                source_lane=LANE_DURABLE,
                persona_id=target,
                persona_instance_id=bounded_operator_text(
                    record.get("target_instance_id"), limit=200
                ),
                session_id=bounded_operator_text(record.get("sender_session_id"), limit=240),
                started_at=_iso(settled),
                elapsed_seconds=0,
                progress=_progress(available=False),
                # The drop REASON is the whole value of the row: "your answer
                # could not be delivered" is useless without "because".
                tail_preview=_preview(
                    f"delivery abandoned: {reason}", self.accountant
                ),
                cancellable=False,
            )
        )


def _collect_dispatches(
    *, now: float, accountant: ProjectionAccountant | None
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """The dispatch lane's collector: one :class:`DispatchLane` pass."""

    return DispatchLane(now=now, accountant=accountant).collect()
