"""Live, greppable mirror of a persona-chat transcript.

Why this exists (operator ask, 2026-08-03)
------------------------------------------
A head agent (Neko Mission Lead) could not see a teammate thread's full
history: ``agent_chat_open`` caps at a 40-message tail and the transcript lives
in SessionDB, which no agent tool can grep or glob. The ask was explicitly for a
**live** artifact, not a point-in-time export — a path the head can ``grep`` /
``tail`` *while the teammate is mid-task* and watch it grow.

So this module maintains one append-only JSONL file per chat session:

    <head-home>/chat_live_logs/<session_id>.jsonl

Line kinds, all bounded:

    {"ts": ..., "kind": "message", "role": "operator|agent|system",
     "text": ..., "turn_id"?: ..., "client_message_id"?: ...,
     "relay_sender_persona_id"?: ..., "relay_sender_instance_id"?: ...}
    {"ts": ..., "kind": "tool", "tool": ..., "status": ..., "turn_id"?: ...}

plus a ``{"kind": "log_opened"}`` header written when the file is created,
carrying the backfill state (see below).

WHAT THE LIVE STREAM ACTUALLY CARRIES (honesty boundary — do not overstate)
--------------------------------------------------------------------------
Mirrored **as they happen**:

* the incoming operator/relay message of each mission-chat turn (write-ahead),
* text steered into a turn that is already running
  (``mission_chat_steer``, stamped ``steered: true``),
* the recorded final reply of each mission-chat turn (native commit),
* every row the explicit persona-chat append seam writes — the relay lane
  and the child return-summary lane,
* tool start/finish lines from :class:`~agent_runtime.progress.ChatProgressSink`.

NOT mirrored as they happen: the runtime's NON-FINAL rows — the intermediate
assistant messages between tool calls that the native session flush persists
(``run_agent`` writes those straight to SessionDB, outside every seam this
module hooks). They are in SessionDB and therefore appear when a file is built
or completed from the projection, so never claim the live tail is a complete
transcript. ``agent_chat_log_path``'s schema states the same boundary to the
model.

Contract
--------
* **Regenerable artifact, never authority.** SessionDB remains the transcript
  of record; every line here is rebuildable from it. Deleting a mirror file
  loses nothing but convenience — the next ``agent_chat_log_path`` call
  materializes it again from the projection.
* **Backfill happens on the TOOL lane, never the chat hot path.** The one-shot
  materialization re-runs the curated projection (which re-parses the turn
  journal per row), so doing it synchronously inside a chat persist seam would
  stall a live turn for seconds on a long session. The persist / progress lanes
  therefore only ever create a header (``backfill_pending``) and append; the
  deliberate ``agent_chat_log_path`` request fills the history in.
* **Publication is atomic.** Materialization writes a claim/temp file and
  ``os.replace()``s it into position, so a concurrent reader or appender sees
  either no file or a complete one — and an appended line is never overwritten
  by the creator's next buffered flush.
* **Redaction-safe by construction.** Every text this module writes goes
  through :data:`~agent_runtime.redaction.TEXT_SECRET_ASSIGNMENT_RE` — the ONE
  secret-assignment authority — with per-line masking, exactly like the read
  projection. Callers already hand over redacted text; the pass here is
  belt-and-braces, because "the caller already did it" is how a redaction
  boundary rots.
* **Best effort, counted.** A mirror write must NEVER fail a chat turn. IO
  failures are swallowed but tallied (:func:`chat_live_log_failures`) and
  logged ONCE per process, so a silently broken mirror is still discoverable.
* **Bounded.** Per-line text cap :data:`LIVE_LOG_TEXT_LIMIT`; size-capped
  rotation at :data:`LIVE_LOG_ROTATE_BYTES` into a single ``.1`` sibling (one
  generation kept — this is a convenience mirror, not an archive).

THE HERMES_HOME TRAP (read before touching the path resolution)
---------------------------------------------------------------
``agent_runtime.profile_context.persona_profile_context`` flips
``os.environ["HERMES_HOME"]`` **process-globally** to ``profiles/<persona>``
for the duration of a persona turn — which is precisely when these writes
happen. Resolving the directory from the ambient home at write time would
scatter one conversation's mirror across per-persona profile directories, away
from the SessionDB that actually holds the transcript.

So the root is **captured once** per process
(:func:`capture_chat_live_log_root`) and reused for every later write:

1. the directory of the chat ``SessionDB`` handed to the persist seam
   (``session_db.db_path.parent``) — the strongest answer, because it is
   literally where the transcript this mirrors landed;
2. otherwise ``chat_session_scope.resolve_process_chat_scope().head_home`` —
   the same head-home ladder the SessionDB acquisition itself uses.

A capture from a real ``session_db`` upgrades an earlier scope-derived capture
exactly once; nothing else re-resolves. ``reset_chat_live_log_state()`` exists
for tests only.

The package map (rule 16)
-------------------------
Entry points, and the modules an agent opens to follow each:

* ``record_chat_message`` / ``record_chat_tool`` (the persist seams,
  ``progress.ChatProgressSink``, ``mission_chat_steer``) -> ``writes`` ->
  ``files`` (ensure, dedupe, append) and ``lines`` (the line's shape);
* ``ensure_chat_live_log(materialize=True)`` (``agent_chat_log_path``) ->
  ``writes`` -> ``files`` (claim) -> ``backfill`` (create / complete + the rows);
* ``chat_live_log_stats`` -> ``backfill`` -> ``files``;
* ``capture_chat_live_log_root`` (the SessionDB acquisition) -> ``files``.

Modules, lowest layer first (no module imports one above it — W0-G6):

========  ======  ==========================================================
module    layer   owns
========  ======  ==========================================================
lines     policy  the shape of one line: role normalization, the logical
                  client key, the origin fields, the session-id guard, secret
                  masking + bound, encode / decode
files     stores  the file on disk and the process state over it: the
                  captured root, the path, claim + publish + wait, append +
                  rotate, the replay-dedupe index, the failure tally
backfill  lanes   the tool lane's materialization (the paged projection walk,
                  create / complete under a claim) and ``chat_live_log_stats``
writes    lanes   the hot lane: the append seam, ``record_chat_message``,
                  ``record_chat_tool``, ``ensure_chat_live_log``
========  ======  ==========================================================

Stores written: ``<head_home>/chat_live_logs/<session>.jsonl`` (+ ``.1``,
``.materializing``), by ``files`` only.
"""

from __future__ import annotations

from agent_runtime.chat_live_log import (  # noqa: F401 — every family, lowest layer first
    lines,
    files,
    backfill,
    writes,
)
from agent_runtime.chat_live_log.lines import LIVE_LOG_TEXT_LIMIT
from agent_runtime.chat_live_log.files import (
    CHAT_LIVE_LOG_DIRNAME,
    LIVE_LOG_ROTATE_BYTES,
    capture_chat_live_log_root,
    chat_live_log_failures,
    chat_live_log_path,
    reset_chat_live_log_state,
)
from agent_runtime.chat_live_log.backfill import (
    LIVE_LOG_BACKFILL_MESSAGE_CAP,
    LIVE_LOG_BACKFILL_WALL_SECONDS,
    chat_live_log_stats,
)
from agent_runtime.chat_live_log.writes import (
    ensure_chat_live_log,
    mirrored_persona_chat_append,
    record_chat_message,
    record_chat_tool,
)

__layer__ = "wiring"

__all__ = [
    "CHAT_LIVE_LOG_DIRNAME",
    "LIVE_LOG_BACKFILL_MESSAGE_CAP",
    "LIVE_LOG_BACKFILL_WALL_SECONDS",
    "LIVE_LOG_ROTATE_BYTES",
    "LIVE_LOG_TEXT_LIMIT",
    "capture_chat_live_log_root",
    "chat_live_log_failures",
    "chat_live_log_path",
    "chat_live_log_stats",
    "ensure_chat_live_log",
    "mirrored_persona_chat_append",
    "record_chat_message",
    "record_chat_tool",
    "reset_chat_live_log_state",
]
