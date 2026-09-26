"""The running_work vocabulary: the projection name, the limits, the kinds and
sources, the status words, the lane and source tokens, the stale fallbacks,
the two durable store filenames and the ``_pid_identity`` verdicts.

A vocabulary module (sheet ``running_work.md`` §1): exempt from the 100-line floor."""

from __future__ import annotations

__layer__ = "models"


PROJECTION = "running_work"

#: Hard cap on the inline output preview carried on every row. Declared
#: ``by_design`` through the accountant whenever it actually truncates.
TAIL_PREVIEW_LIMIT = 200
#: Hard cap on the ``work peek`` tail. Deliberately small: the peek exists so an
#: operator can see what a process is doing without flooding an agent's context.
PEEK_TAIL_LIMIT = 2048

KIND_TERMINAL = "terminal"
KIND_DELEGATION = "delegation"
KIND_CHAT_TURN = "chat_turn"
KIND_CRON_JOB = "cron_job"
#: Detached agent-to-agent dispatches (``agent_chat_send(wait=false)``), backed
#: by :mod:`agent_runtime.dispatch_store`. Declared in this tuple one wave
#: BEFORE its producer existed, so the wire vocabulary was complete from the
#: first landing and no consumer had to re-derive it when the lane arrived.
KIND_DISPATCH = "dispatch"

#: How far back an UNDELIVERABLE dispatch keeps surfacing on the Activity
#: projection. A day, because "your agent's answer was thrown away" is worth
#: seeing on the next session start, and not forever, because the HUD reports
#: what the machine is doing now rather than serving as an incident archive.
#:
#: BOUND, STATED: past this window the row goes silent here with no "N older"
#: affordance. That is a deliberate limit of THIS surface, not a claim that
#: nothing older happened — the drop is still in the EventLog
#: (``dispatch.dropped``), still on the store row, and still reported to the
#: dispatching agent through ``agent_chat_dispatches``. A counted-older
#: affordance belongs here eventually; until it exists, a reader must not treat
#: an empty dispatch lane as "nothing was ever abandoned".
_UNDELIVERABLE_WINDOW_SECONDS = 24 * 60 * 60

RUNNING_WORK_KINDS = (
    KIND_TERMINAL,
    KIND_DELEGATION,
    KIND_CHAT_TURN,
    KIND_CRON_JOB,
    KIND_DISPATCH,
)

#: The lanes that report a ``sources`` entry on every build. ``dispatch`` joined
#: at WP-H2, when it acquired a producer (:mod:`agent_runtime.dispatch_store`);
#: until then declaring a source for a lane nothing could write would have been
#: the dead-by-emptiness the parity rules forbid.
RUNNING_WORK_SOURCES = (
    KIND_TERMINAL,
    KIND_DELEGATION,
    KIND_CHAT_TURN,
    KIND_CRON_JOB,
    KIND_DISPATCH,
)

STATUS_RUNNING = "running"
STATUS_STALLING = "stalling"
STATUS_STALLED = "stalled"
STATUS_FINALIZING = "finalizing"
STATUS_COMPLETED = "completed"
STATUS_ERROR = "error"
STATUS_UNKNOWN = "unknown"

STATUS_VALUES = (
    STATUS_RUNNING,
    STATUS_STALLING,
    STATUS_STALLED,
    STATUS_FINALIZING,
    STATUS_COMPLETED,
    STATUS_ERROR,
    STATUS_UNKNOWN,
)

SOURCE_OK = "ok"
SOURCE_UNAVAILABLE = "unavailable"

LANE_LIVE = "live"
LANE_DURABLE = "durable"

#: Reason a lane reports ``unavailable`` because its truth is a process-global
#: that only the owning process can answer.
REASON_NOT_IN_PROCESS = "not_in_process"

#: Fallback stale thresholds, used ONLY when ``tools.async_delegation`` is not
#: resident (i.e. the durable lane, where no progress token exists anyway and
#: these are therefore unreachable). When the module IS resident its constants
#: are read directly so this file never becomes a second authority for them.
_FALLBACK_STALE_IDLE_SECONDS = 450.0
_FALLBACK_STALE_IN_TOOL_SECONDS = 1200.0

#: Per-lane row cap. A runaway subsystem must not be able to inflate the
#: snapshot; overflow is accounted (``lane_capped``, by design) rather than
#: dropped in silence.
_MAX_ROWS_PER_SOURCE = 200

_CHECKPOINT_FILENAME = "processes.json"
_STATE_DB_FILENAME = "state.db"


#: ``_pid_identity`` verdicts. The split between the last two matters more than
#: it looks: "a different process holds this number" and "I could not read this
#: number's start time" lead to OPPOSITE actions. The first is proof the work is
#: gone (drop the row); the second is an absence of proof (keep the row, admit
#: it is unverified). Collapsing them — which the first implementation did —
#: means a psutil hiccup or an access-denied probe silently deletes a running
#: build from the operator's HUD and files it under "recycled PID".
PID_VERIFIED = "verified"
PID_DEAD = "dead"
PID_RECYCLED = "recycled"
PID_NO_BASELINE = "no_baseline"
PID_START_TIME_UNREADABLE = "start_time_unreadable"

#: Boundary words read off the stores and seams this projection consumes, each
#: with one reader: the live process registry's ``status`` for a child that has
#: exited (``lanes_process``), the ``async_delegations.state`` a settling
#: delegation carries (``lanes_chat``), and the kill seam's answer when it held
#: no such session (``surface.cancel_work``).
REGISTRY_EXITED = "exited"
DELEGATION_STATE_FINALIZING = "finalizing"
KILL_NOT_FOUND = "not_found"
