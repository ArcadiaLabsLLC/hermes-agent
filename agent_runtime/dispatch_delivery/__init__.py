"""Serve-hosted delivery drain — the half that makes ``wait: false`` honest.

``agent_chat_send(wait=false)`` promises the sender "their answer will come back
to you". This module is where that promise is kept: a daemon thread inside the
serve process walks the durable dispatch store, and for every completion whose
sender is IDLE it forges a new mission-chat turn into that sender's thread
carrying the result.

Why a forged TURN and not an injected message
---------------------------------------------
The completion has to become a real turn, in the sender's real thread, when the
sender is idle — never spliced into a conversation mid-flight. That invariant
is inherited from the delegation lane (``tools/async_delegation``) and it is
load-bearing twice over: message-role alternation must stay legal, and past
context must never be mutated (which would invalidate the prompt cache and can
corrupt a provider's view of the conversation). So delivery goes through the
SAME ``_cmd_mission_chat_message`` handler an operator message goes through —
one chat lane, no second write path, and the transcript, live log, turn journal
and Mission Control projection all get it for free.

Idle is checked twice, deliberately
-----------------------------------
First a zero-timeout probe of the sender's chat-root lease plus a scan of the
turn journal for in-flight records; then the handler's own lease acquisition
inside the forge. The probe is an optimisation that avoids paying for a turn
setup we know will be refused; the handler's lease is the actual guard, because
anything else would be a time-of-check/time-of-use race against an operator who
starts typing. A busy sender is never an error here — the claim is released and
the completion waits for a quieter moment.

The lease is probed and RELEASED before forging, never held across it: the
handler takes the same lease itself, and a same-process re-entrant acquisition
is exactly the deadlock this would otherwise be.

What "delivered" is allowed to mean
-----------------------------------
A forged turn coming back ``ok`` proves the TURN ran, not that the operator saw
an answer: the handler returns ``ok: True`` with an empty ``reply`` when the
model produces no content, and on 2026-08-11 it did exactly that, three retries
deep, on a real completion notice. So the drain classifies every successful
forge (:func:`_delivery_outcome`) and records ``delivered_silent`` when the
turn produced nothing visible. The classification itself is NOT made here: it
is read off the typed block the handler stamps, whose one authority is
``agent_runtime.turn_visibility`` — the drain consumes it exactly like any
other consumer, and a silence it cannot prove stays a plain delivery.

Where the chat database comes from
----------------------------------
Head-home scope ONLY. Persona turns flip ``HERMES_HOME`` process-globally for
their duration and they share this process, so a drain that read the ambient
home would resolve a different profile's SessionDB depending on what happened to
be mid-turn at that instant — and would forge a delivery into a database the
operator's console never opens.

Package map (lane B3, sheet ``god-file-layout-sheets/dispatch_delivery.md`` §1)
---------------------------------------------------------------------------------
Entry points are what the outside calls; everything else is reached only from
inside. Layers point down (models <- policy <- stores <- lanes <- wiring); this
map is ``lanes`` because the highest layer it re-exports is ``lanes``.

    agent_runtime/dispatch_delivery/
      __init__.py       lanes    this docstring and map; re-exports the importer and test names
      vocabulary.py     models   DELIVERY_REQUESTED_BY and the requested_by marker (build /
                                 parse, delivery_client_message_id), REPLY_LIMIT, the drain
                                 bounds, the DELIVERED_* reasons, DRAIN_STATE_FILENAME,
                                 STEER_ACK_SECONDS, the terminal / transient refusal classes,
                                 BOUNCE_GATES + IDLE_SUB_REASONS (the closed outcome vocabulary)
      accounting.py     stores   [A] IdleProbe, _DrainTelemetry (record_bounce refuses a gate
                                 outside BOUNCE_GATES) + the process singleton,
                                 _event_key, _delivery_outcome, _record_sender_busy, and the
                                 cross-process mirror file (read_delivery_drain_state)
      forge.py          lanes    format_dispatch_delivery, idle gating, DrainPolicy
                                 (_probe_sender_idle, _sender_is_idle, _sender_persona),
                                 forge_delivery_turn (through agent_runtime.mission_chat_door)
      completions.py    lanes    the background-completion lane: ownership (_chat_root_of_
                                 completion, _orphaned_persona_root), the durable claim/settle,
                                 the steer, drain_background_completions = BackgroundDrain
                                 (own -> probe -> claim -> forge_turn -> settle per event)
      drain.py          lanes    drain_once = DispatchDrain (the same five phases per row),
                                 sweep_orphaned_dispatches, start_delivery_drain and
                                 its thread; delivery_drain_status / delivery_drain_is_live

    entry point                                     opens
    start_delivery_drain (serve boot)               drain -> completions, accounting
    drain_once                                      drain -> forge, accounting
    drain_background_completions                    completions -> forge, accounting
    forge_delivery_turn (also chat_history_writes)  forge
    delivery_drain_status / delivery_drain_is_live  drain -> accounting

The drain's two decisions are INJECTED, never patched by name: ``forge.DrainPolicy``
(``sender_is_idle``, ``sender_persona``, defaulting to ``_sender_is_idle`` /
``_sender_persona``) is what ``DispatchDrain`` / ``BackgroundDrain`` consult, and
``drain_once`` / ``drain_background_completions`` / ``start_delivery_drain`` take
``policy=``. ``_sender_persona`` stays re-exported here because the agent-chat
tool's detached lane reads it off this package at call time (lane W3-B).
"""

from __future__ import annotations

from . import accounting, completions, drain, forge, vocabulary
from .accounting import (
    DrainBounce,
    IdleProbe,
    _DrainTelemetry,
    _LAST_IDLE_PROBE,
    __layer__,
    _delivery_outcome,
    _drain_state_path,
    _event_key,
    _paths_store_root,
    _record_sender_busy,
    _telemetry,
    _write_drain_state,
    read_delivery_drain_state,
)
from .completions import (
    BackgroundDrain,
    __layer__,
    _background_attempts,
    _chat_root_of_completion,
    _claim_durable_completion,
    _orphaned_persona_root,
    _owns_event_with_accounting,
    _settle_durable_completion,
    _steer_into_busy_turn,
    drain_background_completions,
)
from .drain import (
    DispatchDrain,
    __layer__,
    delivery_drain_is_live,
    delivery_drain_status,
    drain_once,
    start_delivery_drain,
    sweep_orphaned_dispatches,
)
from .forge import (
    DEFAULT_DRAIN_POLICY,
    DrainPolicy,
    __layer__,
    _probe_sender_idle,
    _sender_is_idle,
    _sender_persona,
    forge_delivery_turn,
    format_dispatch_delivery,
    format_elapsed,
)
from .vocabulary import (
    BOUNCE_GATES,
    DEFAULT_DRAIN_INTERVAL_SECONDS,
    DELIVERED_REASON,
    DELIVERED_SILENT_REASON,
    DELIVERY_REASONS,
    DELIVERY_REQUESTED_BY,
    DRAIN_DETAIL_LIMIT,
    DRAIN_MIRROR_HEARTBEAT_SECONDS,
    DRAIN_OWNERLESS_WARN_AFTER,
    DRAIN_REPEAT_LOG_EVERY,
    DRAIN_STATE_FILENAME,
    GATE_ABANDONED,
    GATE_EMPTY_TEXT,
    GATE_FORGE_BUSY,
    GATE_FORGE_FAILED,
    GATE_FORGE_REJECTED,
    GATE_NOT_OWNED,
    GATE_NO_ROOT,
    GATE_OWNER_UNRESOLVED,
    GATE_PERSONA_INSTANCE_MISSING,
    GATE_SENDER_BUSY,
    GATE_STEERED,
    GATE_UNCLAIMED,
    IDLE_JOURNAL_INFLIGHT,
    IDLE_JOURNAL_UNREADABLE,
    IDLE_LEASE_BUSY_OWNED,
    IDLE_LEASE_BUSY_OWNERLESS,
    IDLE_LEASE_PROBE_ERROR,
    IDLE_SUB_REASONS,
    IDLE_UNKNOWN,
    IDLE_UNPROBED,
    MAX_BACKGROUND_DELIVERY_ATTEMPTS,
    MAX_DELIVERIES_PER_PASS,
    MAX_DRAIN_OUTCOME_ROWS,
    ORPHAN_SWEEP_INTERVAL_SECONDS,
    REPLY_LIMIT,
    STEER_ACK_SECONDS,
    __layer__,
    bounce_reason,
    delivery_client_message_id,
    delivery_requested_by,
    parse_delivery_requested_by,
    refused_bounce_reason,
    terminal_forge_rejections,
    transient_forge_refusals,
)

__layer__ = "lanes"

__all__ = [
    "BOUNCE_GATES",
    "IDLE_SUB_REASONS",
    "BackgroundDrain",
    "DEFAULT_DRAIN_POLICY",
    "DispatchDrain",
    "DrainPolicy",
    "format_elapsed",
    "terminal_forge_rejections",
    "transient_forge_refusals",
    "DELIVERED_REASON",
    "DELIVERED_SILENT_REASON",
    "DELIVERY_REASONS",
    "DELIVERY_REQUESTED_BY",
    "MAX_BACKGROUND_DELIVERY_ATTEMPTS",
    "ORPHAN_SWEEP_INTERVAL_SECONDS",
    "delivery_client_message_id",
    "delivery_drain_is_live",
    "delivery_drain_status",
    "delivery_requested_by",
    "drain_background_completions",
    "drain_once",
    "format_dispatch_delivery",
    "parse_delivery_requested_by",
    "read_delivery_drain_state",
    "start_delivery_drain",
    "sweep_orphaned_dispatches",
]
