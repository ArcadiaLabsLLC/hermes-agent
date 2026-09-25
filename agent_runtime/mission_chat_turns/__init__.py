"""The chat-turn journal — one file per chat session (the package map, rule 16).

Owner doc: ``docs/agent-runtime-harness/05-chat-turn-lane.md`` (the turn journal).

Entry points (what calls in), and the modules an agent opens to follow each:

* ``persist_mission_chat_turn`` / ``transition_mission_chat_turn`` /
  ``abandon_mission_chat_turn`` (``harness_parts/persona/chat_turn_commit/*``,
  ``chat_admission``, ``chat_tickets_commands``) -> ``journal`` -> ``storage``
  (lock, read, write, cap) and ``records`` (the record's shape); ``states`` for
  ``next_turn_state`` and the transition table.
* ``mission_chat_turn_record(s)`` / ``mission_chat_turn_elements``
  (``persona_chat_history``, ``dispatch_delivery``, ``chat_turn_presence``) ->
  ``reads`` -> ``storage``, ``records``.
* ``inflight_chat_session_roots`` then ``mark_stale_inflight_turns_interrupted``
  (the serve-boot orphan sweep, ``persona_chat_continuity``) and
  ``inflight_turn_rows`` (``running_work``) -> ``reads`` / ``journal`` ->
  ``storage``.

Modules, lowest layer first (no module imports one above it — W0-G6):

========  ======  ==========================================================
module    layer   owns
========  ======  ==========================================================
states    models  VOCABULARY/TABLE (floor-exempt): the turn states, the
                  lifecycle buckets, the decision sets, the transition table,
                  the import-time guard, ``next_turn_state``, the two state
                  readers
records   policy  the durable record shape: ``_safe_record``, the journal
                  metadata whitelist, profile timing, provider refusal; the
                  elements (segment / tool) and their bounded sub-shapes
storage   stores  the store on disk: layout constants + every path, the
                  per-session lock, read / write / archive of one session
                  file, the per-session turn cap, the session-file GC, the
                  one-time monolith migration
journal   stores  the four writes over ``_mutate_session`` — the ONE write
                  chokepoint
reads     stores  elements / record / records / in-flight roots / rows
========  ======  ==========================================================

Stores written: ``<store_root>/mission_chat_turns/<safe_session_key>.json`` +
``.lock``, ``mission_chat_turns_archive/``, and the legacy monolith's rename
(``storage`` only, every write through ``journal._mutate_session``).
Must never import: ``hermes_cli``; nothing in this package imports this map.
"""

from __future__ import annotations

from agent_runtime.mission_chat_turns import (  # noqa: F401 — every family, lowest layer first
    states,
    records,
    storage,
    journal,
    reads,
)
from agent_runtime.mission_chat_turns.states import (
    ALL_TURN_STATES,
    INFLIGHT_TURN_STATES,
    JOURNAL_TURN_STATES,
    LEGACY_TURN_STATES,
    OPERATOR_RESOLVABLE_TURN_STATES,
    REPLY_RECOVERABLE_TURN_STATES,
    RESEND_BLOCKING_TURN_STATES,
    SETTLING_TURN_STATES,
    TERMINAL_TURN_STATES,
    TURN_STATE_ABANDONED,
    TURN_STATE_BUDGET_EXHAUSTED,
    TURN_STATE_COMPLETED,
    TURN_STATE_EXECUTING,
    TURN_STATE_FAILED,
    TURN_STATE_INTERRUPTED,
    TURN_STATE_NATIVE_COMMITTED,
    TURN_STATE_OUTCOME_UNKNOWN,
    TURN_STATE_PENDING,
    TURN_STATE_PROJECTED,
    TURN_STATE_PROVIDER_REFUSED,
    TURN_STATE_RUNNING,
    MissionChatTurnPersistOutcome,
    next_turn_state,
)
from agent_runtime.mission_chat_turns.records import (
    TURN_PROFILE_TIMING_KEY,
    _safe_todo_state,  # noqa: F401 — test seam (test_profile_runner)
    safe_provider_refusal,
    safe_turn_profile_timing,
)
from agent_runtime.mission_chat_turns.storage import _store_dir  # noqa: F401 — test seam
from agent_runtime.mission_chat_turns.journal import (
    abandon_mission_chat_turn,
    mark_stale_inflight_turns_interrupted,
    persist_mission_chat_turn,
    transition_mission_chat_turn,
)
from agent_runtime.mission_chat_turns.reads import (
    inflight_chat_session_roots,
    inflight_turn_rows,
    mission_chat_turn_elements,
    mission_chat_turn_record,
    mission_chat_turn_records,
)

__layer__ = "wiring"

__all__ = [
    "ALL_TURN_STATES",
    "INFLIGHT_TURN_STATES",
    "JOURNAL_TURN_STATES",
    "LEGACY_TURN_STATES",
    "MissionChatTurnPersistOutcome",
    "OPERATOR_RESOLVABLE_TURN_STATES",
    "REPLY_RECOVERABLE_TURN_STATES",
    "RESEND_BLOCKING_TURN_STATES",
    "SETTLING_TURN_STATES",
    "TERMINAL_TURN_STATES",
    "TURN_PROFILE_TIMING_KEY",
    "TURN_STATE_ABANDONED",
    "TURN_STATE_BUDGET_EXHAUSTED",
    "TURN_STATE_COMPLETED",
    "TURN_STATE_EXECUTING",
    "TURN_STATE_FAILED",
    "TURN_STATE_INTERRUPTED",
    "TURN_STATE_NATIVE_COMMITTED",
    "TURN_STATE_OUTCOME_UNKNOWN",
    "TURN_STATE_PENDING",
    "TURN_STATE_PROJECTED",
    "TURN_STATE_PROVIDER_REFUSED",
    "TURN_STATE_RUNNING",
    "abandon_mission_chat_turn",
    "inflight_chat_session_roots",
    "inflight_turn_rows",
    "mark_stale_inflight_turns_interrupted",
    "mission_chat_turn_elements",
    "mission_chat_turn_record",
    "mission_chat_turn_records",
    "next_turn_state",
    "persist_mission_chat_turn",
    "safe_provider_refusal",
    "safe_turn_profile_timing",
    "transition_mission_chat_turn",
]
