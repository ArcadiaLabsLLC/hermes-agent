"""The admission half of a mission-chat turn: busy outcome, delivery lease, visibility bundle reuse.

Separate because it decides WHETHER and HOW a turn may start (replay, defer,
refuse) before anything runs; the run itself is ``chat_turn_commit``.
"""

from __future__ import annotations

import functools
from dataclasses import dataclass
from enum import Enum, auto
from types import MappingProxyType
from typing import Any, Callable, Final, Mapping

from agent_runtime.mission_chat_outcome import ChatErrorKind, ExecutionState
from agent_runtime.mission_chat_turns.reads import mission_chat_turn_record
from agent_runtime.mission_chat_turns.states import (
    RESEND_BLOCKING_TURN_STATES,
    TURN_STATE_EXECUTING,
    TURN_STATE_NATIVE_COMMITTED,
    TURN_STATE_PENDING,
    TURN_STATE_PROJECTED,
)
from agent_runtime.persona_assignments import safe_assignment_token
from .chat_events import _mission_chat_emit, _publish_persona_chat_send_refused_event
from .chat_history_writes import (
    PERSONA_CHAT_REPLY_LIMIT,
    _persona_chat_existing_turn,
    _redact_persona_chat_text,
)
from .chat_reply_stamps import _stamp_reply_media, _stamp_turn_visibility

__layer__ = "lanes"
__all__ = [
    "_bind_mission_chat_delivery_capability",
    "_mission_chat_busy_outcome",
    "_mission_chat_lease_provenance",
    "_normalize_deferred_thread_policy",
    "_prewarm_constructions_overlapped",
    "_registry_probe_rounds",
    "_safe_pre_admit_timings",
    "_snapshot_builds_overlapped",
    "_turn_skill_resolver",
    "_visibility_bundle_builds",
    "_visibility_bundle_diff_cursor",
    "_discover_plugin_tools_before_the_bundle",
    "_bundle_cursor_after_plugin_discovery",
    "_visibility_bundle_rebuild_components",
    "_within_admitted_turn",
]


#: The journal states that mean "the root's CURRENT turn is this very
#: ``client_message_id``". Narrower than ``INFLIGHT_TURN_STATES`` on purpose:
#: ``outcome_unknown`` is in-flight-ish but already has its own honest refusal
#: (``chat_turn_outcome_unknown``, which routes to ``turn-resolve``), and
#: ``running`` is the legacy pre-journal spelling no live transition produces.
_DUPLICATE_IN_FLIGHT_TURN_STATES = frozenset(
    {TURN_STATE_PENDING, TURN_STATE_EXECUTING}
)


class BusyOutcome(Enum):
    """Whose turn a busy chat root is running, as far as the journal can prove it."""

    # ``auto()``, not strings: the member is a decision, never a wire value, so
    # it must not shadow the journal-state spellings it classifies (W0-G5).
    DUPLICATE_IN_FLIGHT = auto()
    OUTCOME_UNKNOWN = auto()
    REPLAY = auto()
    BUSY = auto()


#: A journal state class -> the outcome it proves. Read in this order and the
#: first match wins: ``executing`` is in both of the first two classes and is a
#: duplicate in flight. A state in none of them (no record, an unreadable one,
#: a settled state with nothing to serve) is ``BUSY`` — the degraded answer,
#: never a wrong one.
_BUSY_STATE_CLASSES: Final[tuple[tuple[BusyOutcome, frozenset[str]], ...]] = (
    (BusyOutcome.DUPLICATE_IN_FLIGHT, _DUPLICATE_IN_FLIGHT_TURN_STATES),
    (BusyOutcome.OUTCOME_UNKNOWN, frozenset(RESEND_BLOCKING_TURN_STATES)),
    (BusyOutcome.REPLAY, frozenset({TURN_STATE_PROJECTED, TURN_STATE_NATIVE_COMMITTED})),
)


def _busy_outcome_for(journal_state: str | None) -> BusyOutcome:
    return next(
        (outcome for outcome, states in _BUSY_STATE_CLASSES if journal_state in states),
        BusyOutcome.BUSY,
    )


@dataclass(frozen=True)
class _BusySend:
    """A send that lost the chat-root lease, and what the journal says about its id."""

    args: Any
    session_db: Any
    session_id: str
    client_message_id: str
    normalized_persona: str
    persona_instance_id: Any
    session_established: Any
    exc: Any
    journal: dict
    journal_state: str | None
    turn_id: Any


def _busy_duplicate_in_flight(send: _BusySend) -> int:
    data = {
        "ok": False,
        "capability_id": "mission.chat.message",
        "execution_state": ExecutionState.BLOCKED,
        "error_kind": ChatErrorKind.CHAT_TURN_DUPLICATE_IN_FLIGHT,
        "duplicate_in_flight": True,
        # Explicitly NOT busy. A consumer that switches on this flag must
        # not see a duplicate-in-flight as a lost message.
        "chat_busy": False,
        "turn_resolution_required": False,
        "journal_state": send.journal_state,
        "root_chat_session_id": send.session_id,
        "session_id": send.session_id,
        "client_message_id": send.client_message_id,
        "turn_id": send.turn_id,
        "lease_owner": send.exc.owner,
        "error": (
            "this client_message_id is the turn currently running on this root"
        ),
        "next_expected": (
            "do not resend a new id and do not resolve; re-present this same "
            "client_message_id after the turn settles to replay its committed reply"
        ),
    }
    _publish_persona_chat_send_refused_event(
        session_id=send.session_id,
        client_message_id=send.client_message_id,
        persona_id=send.normalized_persona,
        persona_instance_id=send.persona_instance_id,
        error_kind=ChatErrorKind.CHAT_TURN_DUPLICATE_IN_FLIGHT,
        lease_owner=send.exc.owner,
    )
    _mission_chat_emit(send.args, data)
    return 2


def _busy_outcome_unknown(send: _BusySend) -> int:
    # Only ``outcome_unknown`` can reach here (``executing`` is a duplicate in
    # flight, first in the class order). The record already IS the state the
    # leased path would move it to, so the same refusal is served without the
    # transition.
    data = {
        "ok": False,
        "capability_id": "mission.chat.message",
        "execution_state": ExecutionState.BLOCKED,
        "error_kind": ChatErrorKind.CHAT_TURN_OUTCOME_UNKNOWN,
        "journal_state": send.journal_state,
        "root_chat_session_id": send.session_id,
        "session_id": send.session_id,
        "client_message_id": send.client_message_id,
        "turn_id": send.turn_id,
        "error": (
            "the prior provider outcome cannot be proven; resolve this turn "
            "before resending"
        ),
        "next_expected": (
            "resolve the exact outcome_unknown turn with action=abandon, then "
            "send a new client_message_id"
        ),
    }
    _mission_chat_emit(send.args, data)
    return 2


def _busy_replay(send: _BusySend) -> int | None:
    """The idempotent replay, served read-only; ``None`` when there is no reply to serve."""

    stored_reply = send.journal.get("stored_reply")
    if stored_reply is None:
        replay = _persona_chat_existing_turn(
            session_db=send.session_db,
            session_id=send.session_id,
            client_message_id=send.client_message_id,
        )
        assistant = replay.get("assistant")
        if isinstance(assistant, dict):
            stored_reply = assistant.get("content")
    if stored_reply is None:
        return None
    reply_text = _redact_persona_chat_text(
        stored_reply, limit=PERSONA_CHAT_REPLY_LIMIT
    )
    data = {
        "ok": True,
        "capability_id": "mission.chat.message",
        "persona_id": send.normalized_persona,
        "persona_instance_id": send.persona_instance_id,
        "root_chat_session_id": send.session_id,
        "active_session_id": send.journal.get("active_session_id") or send.session_id,
        "session_id": send.session_id,
        "chat_session_id": send.session_id,
        # A replay reports the same thread lineage the original turn
        # did — see the leased replay branch in the commit phase.
        "session_established": send.session_established,
        "client_message_id": send.client_message_id,
        "turn_id": send.turn_id,
        "execution_state": ExecutionState.COMPLETED,
        "reply": reply_text,
        "idempotent_replay": True,
        "journal_state": send.journal_state,
        # ``native_committed`` still owes the settling→projected walk.
        # It is deliberately NOT done here (it is a journal WRITE); the
        # next lease-holding presentation of this id finishes it.
        "next_expected": (
            "duplicate client message id replayed from the turn journal "
            "while another turn holds this chat root"
        ),
    }
    _stamp_turn_visibility(data, reply_text)
    _stamp_reply_media(data, reply_text, send.args)
    _mission_chat_emit(
        send.args, data, f"mission chat reply for {send.normalized_persona}"
    )
    return 0


def _busy_refused(send: _BusySend) -> int:
    # No record, an unreadable record, or a settled state with no reply to
    # serve: the root is busy with something that is not provably this message.
    data = {
        "ok": False,
        "capability_id": "mission.chat.message",
        "execution_state": ExecutionState.REJECTED,
        "error_kind": ChatErrorKind.CHAT_BUSY,
        "chat_busy": True,
        "root_chat_session_id": send.session_id,
        "session_id": send.session_id,
        "lease_owner": send.exc.owner,
        "client_message_id": send.client_message_id,
        "error": str(send.exc),
    }
    # Durable FIRST, then the wire. A refused send is the one turn outcome
    # that writes nothing by construction — every durable write lives inside
    # the lease this branch never acquired — so before 2026-08-09 an
    # operator message lost to a busy root left no trace anywhere: not in
    # the transcript, not in the turn journal, not in the EventLog. The
    # refusal envelope on stdout was the only evidence, and it died with the
    # banner that rendered it.
    _publish_persona_chat_send_refused_event(
        session_id=send.session_id,
        client_message_id=send.client_message_id,
        persona_id=send.normalized_persona,
        persona_instance_id=send.persona_instance_id,
        error_kind=ChatErrorKind.CHAT_BUSY,
        lease_owner=send.exc.owner,
    )
    _mission_chat_emit(send.args, data)
    return 2


#: The outcome -> its answer. A ``None`` from an answer (a replay with nothing
#: to replay) falls through to ``BUSY``'s.
_BUSY_OUTCOMES: Final[Mapping[BusyOutcome, Callable[[_BusySend], int | None]]] = MappingProxyType(
    {
        BusyOutcome.DUPLICATE_IN_FLIGHT: _busy_duplicate_in_flight,
        BusyOutcome.OUTCOME_UNKNOWN: _busy_outcome_unknown,
        BusyOutcome.REPLAY: _busy_replay,
        BusyOutcome.BUSY: _busy_refused,
    }
)


def _mission_chat_busy_outcome(
    *,
    args,
    session_db,
    session_id: str,
    client_message_id: str,
    normalized_persona: str,
    persona_instance_id,
    session_established,
    exc,
) -> int:
    """Answer a send that lost the chat-root lease. Emits, returns the exit code.

    **Reads only.** Every branch here runs OUTSIDE the lease it just failed to
    acquire, against a root another turn is actively writing, so it may not
    transition the journal, may not publish the projection event (that helper
    writes a ``projection_event_emitted`` marker through
    ``transition_mission_chat_turn``), and may not touch SessionDB. The turn
    journal is per-session JSON on disk and readable without the lease; that
    read is the whole mechanism.

    Why this exists (2026-08-24 incident). ``_cmd_mission_chat_message`` splits
    plan → commit, and ALL of the lane's dedupe/idempotent-replay logic lives
    inside ``_mission_chat_commit_turn`` — i.e. AFTER the lease. So a duplicate
    of the turn that is CURRENTLY RUNNING died ``chat_busy`` before any dedupe
    could see it. ``chat_busy`` means "someone else holds the root", which a
    caller is entitled to read as "your message never landed": the Launcher's
    streaming-inactivity fallback re-presented its own still-running
    ``client_message_id``, got ``chat_busy``, and painted a delivered turn as a
    rejection while the agent's reply committed 20 seconds later.

    The distinction this restores is: *whose* turn is the busy root running?

    * this message's, still going  → ``chat_turn_duplicate_in_flight`` (BLOCKED,
      non-terminal: do not resend a new id, do not resolve, re-present THIS id)
    * this message's, already answered → the idempotent replay, served read-only
    * this message's, unprovable   → the existing ``chat_turn_outcome_unknown``
    * somebody else's              → ``chat_busy``, exactly as before

    A torn or missing journal read simply falls through to ``chat_busy`` — the
    degraded answer, never a wrong one.
    """

    journal = (
        mission_chat_turn_record(
            session_id=session_id, client_message_id=client_message_id
        )
        or {}
    )
    journal_state = safe_assignment_token(journal.get("state"))
    send = _BusySend(
        args=args,
        session_db=session_db,
        session_id=session_id,
        client_message_id=client_message_id,
        normalized_persona=normalized_persona,
        persona_instance_id=persona_instance_id,
        session_established=session_established,
        exc=exc,
        journal=journal,
        journal_state=journal_state,
        turn_id=journal.get("turn_id") or client_message_id,
    )
    code = _BUSY_OUTCOMES[_busy_outcome_for(journal_state)](send)
    return _busy_refused(send) if code is None else code


def _bind_mission_chat_delivery_capability() -> bool:
    """Answer ``async_delivery_supported()`` HONESTLY for this lane. Returns it.

    ``terminal(notify_on_complete / watch_patterns)`` and
    ``delegate_task(background=true)`` consult that flag before promising to
    deliver a result after the turn ends, and they were being told ``True`` on
    the mission-chat lane for the worst possible reason: nothing had ever bound
    the contextvar, so the default answered for it. Nothing in the serve process
    drained the completion queue at all, which made every one of those promises
    unkeepable — the tool registered a watcher, the turn ended, and the result
    went nowhere.

    Now the answer is bound to ONE fact: ``delivery_drain_is_live()``.

    * **a turn in a process with a LIVE DRAIN ⇒ True.** The drain is the
      consumer the promise names — it walks the durable dispatch store and
      forges completions back into the sender's thread — and it runs in exactly
      one place, the serve loop. So its liveness already distinguishes a
      serve-hosted turn from everything else; no second serve detector needed.
    * **cold one-shot CLI turn ⇒ False.** No drain was ever started there. The
      process exits when the turn does: ``terminal``'s notifications live only
      in this process's in-memory queue and die with it, so that promise is
      simply false. ``delegate_task``'s completions ARE durable and a later
      serve boot could deliver them — but "your subagent result may reappear in
      some future session" is a worse outcome than the inline/synchronous
      fallback ``False`` selects, which returns the result inside the turn that
      asked for it. Refusing the promise is the honest and the more useful
      answer.

    This used to ALSO require ``persona_chat_runtime_registry() is not None``,
    believing the registry "tells serve from CLI". It does not: the registry
    exists only when ``agent_runtime.persona_chat.hot_sessions_enabled`` is set,
    and that flag is an unrelated resident-agent CACHE policy which defaults to
    False and is off in production. The conjunct therefore answered False on
    every default-config serve — with the drain alive and perfectly able to
    deliver — and ``agent_chat_send(wait=false)`` refused on the exact lane it
    was built for, from the day it shipped (2026-08-09 live incident; see
    ``test_a_serve_with_hot_sessions_disabled_still_delivers``). A capability
    must gate on the consumer's own liveness, never on a proxy owned by a
    different feature.
    """

    from agent_runtime.dispatch_delivery import delivery_drain_is_live
    from agent_runtime.delivery_capability import declare_async_delivery_channel
    from gateway.session_context import declare_stateless_channel

    can_deliver = delivery_drain_is_live()
    if can_deliver:
        declare_async_delivery_channel()
    else:
        declare_stateless_channel()
    return can_deliver


def _mission_chat_lease_provenance() -> tuple[str | None, str]:
    """``(owner_id, observer_kind)`` for the message-turn root lease.

    ONE fact answers both fields: the serve frame-protocol request id, read from
    the context serve's ``_run`` bound it in. Non-None means this turn arrived
    as a serve request — so the request id itself becomes the lease
    ``owner_id`` (correlating the lease owner file, and the ``lease_owner``
    block a ``chat_busy`` refusal surfaces, with the exact serve frame that
    holds the root) and the observer is labelled ``serve``. None means a
    one-shot CLI turn: no request to correlate (the lease falls back to its
    ``pid-<n>`` owner), labelled ``cli``.

    History, because this line has now lied twice (2026-08-09 investigation):
    ``observer_kind`` was derived from ``persona_chat_runtime_registry() is not
    None`` — the hot-sessions CACHE flag, default off, so every live serve turn
    was labelled ``cli`` in exactly the forensics a ``chat_busy`` incident
    reaches for — and ``owner_id`` read ``args.serve_request_id``, an attribute
    nothing in the tree has ever set, so every owner file carried the
    ``pid-<n>`` fallback instead of the request id the name promised. Both
    fields now read the one authority: :func:`current_serve_request_id`.
    """

    # serve is a real module; this import is lazy to keep the CLI
    # path from paying serve's import weight before it needs it.
    from hermes_cli.harness_parts.serve import current_serve_request_id

    serve_request_id = current_serve_request_id()
    return serve_request_id, ("serve" if serve_request_id is not None else "cli")


def _normalize_deferred_thread_policy(args) -> None:
    """Restore the tri-state ``new_session`` argparse cannot express.

    ``--new-session`` is ``store_true``: present is True, absent is False
    ("continue the target's current default thread"). There is no spelling for
    UNSET — "no opinion, let ``agent_runtime.mission_chat.dispatch_session_policy``
    decide" — which is exactly what the in-process dispatch lane forwards, and
    what a DETACHED dispatch has to reproduce across an argv boundary now that
    its turn runs in a child process. Without it every dispatch would silently
    stop opening its own task thread and pile back into one sticky per-pair
    thread.

    Changing ``--new-session``'s own default to ``None`` would express it too,
    and would also start minting a fresh thread for every bare CLI send that
    omits the flag. So the unset case gets its own explicit flag, normalized
    HERE — once, at the boundary where args are first consumed — leaving the
    policy resolver downstream to see exactly the three states it was written
    for, with no second spelling anywhere behind it.
    """

    if getattr(args, "defer_thread_policy", False):
        args.new_session = None


def _registry_probe_rounds():
    """This thread's cumulative tool-registry probe rounds, or ``None``.

    ``None`` is the honest answer when the registry cannot be consulted at all
    (an import shape this file cannot assume — every import here is
    function-local by convention). The caller
    turns an unknown END or an unknown BASELINE into an ABSENT
    ``registry_probe_rounds`` rather than a zero, because "the registry probed
    nothing" is a finding and "I could not ask" is not.
    """

    try:
        from tools.registry import probe_rounds_this_thread

        return int(probe_rounds_this_thread())
    except Exception:
        return None


def _visibility_bundle_builds():
    """This thread's cumulative chat-lane bundle BUILDS, or ``None``.

    Same contract, and the same reason for it, as
    :func:`_registry_probe_rounds`: cumulative, thread-local, never reset here,
    and ``None`` when the module cannot be consulted at all so the caller leaves
    ``visibility_bundle_builds`` ABSENT rather than reporting a zero it never
    measured.
    """

    try:
        from agent_runtime.chat_lane_bundle import bundle_builds_this_thread

        return int(bundle_builds_this_thread())
    except Exception:
        return None


def _within_admitted_turn(handler):
    """Hold chat-turn-prep CP-2's admitted count for one whole turn handler.

    **Why a decorator and not a ``with`` inside the body.** The rule is
    "incremented at the handler anchor, decremented when the handler exits by
    ANY path", and the handler has more than a dozen refusal returns above the
    lease plus fourteen terminal transitions below it. A ``with`` block would
    re-indent ~700 lines of the most-live code in the harness — a diff whose
    risk is out of all proportion to a counter — and an explicit
    increment/decrement pair would have to be repeated at every one of those
    exits, which is precisely the shape that leaks one and wedges the demote
    lane for the life of the process once Stage 7 reads it.

    The window this opens is the handler's first instruction; the anchor
    (``TurnPhaseMarks()``) is two local imports later, so the counted window and
    the measured window begin at the same instant for every purpose this
    counter has. ``functools.wraps`` keeps the wrapped function reachable, which
    is what the AST/source gates over this handler read.

    Nothing decides on the counter in Stage 6 — see
    ``agent_runtime.turn_activity``.
    """

    @functools.wraps(handler)
    def _admitted(args) -> int:
        # Function-local, like every other import in this file.
        from agent_runtime.turn_activity import admitted_turn

        with admitted_turn():
            return handler(args)

    return _admitted


def _discover_plugin_tools_before_the_bundle() -> None:
    """Run plugin discovery at turn setup, BEFORE CP-7's cursor is sampled.

    Plugin tools register into the tool registry on a home's first discovery,
    and that registration moves the registry epoch the chat-lane bundle keys
    on. Left to happen mid-turn (the visibility resolve reaches
    ``tool_visibility._ensure_plugin_tools_registered`` a few steps later), the
    first turn in a home rebuilt its bundle and reported
    ``visibility_bundle_rebuild_component_registry_epoch`` for a move nobody
    caused. Ruled 2026-09-25 (owner): discover first. The call is the same
    idempotent function the visibility resolve uses, so the later call is a
    no-op and the cost moves rather than doubles.

    Never raises: a failed scan is not cached as discovered, so the in-turn
    call retries it and surfaces the failure where it always did.
    """

    try:
        from agent_runtime.tool_visibility import _ensure_plugin_tools_registered

        _ensure_plugin_tools_registered()
    except Exception:
        return None


def _bundle_cursor_after_plugin_discovery():
    """Discover plugin tools, THEN sample CP-7's cursor — the turn's one call.

    The order is the ruling (2026-09-25, owner: discover first): a cursor
    sampled before discovery reads the registry epoch that discovery itself
    moves, and the first turn in a home reports a rebuild nobody caused. One
    helper so the turn function cannot sample without discovering, and so the
    grandfathered ``_cmd_mission_chat_message`` stays at its recorded length.
    """
    _discover_plugin_tools_before_the_bundle()
    return _visibility_bundle_diff_cursor()


def _visibility_bundle_diff_cursor():
    """The near end of CP-7's moved-component window, or ``None``.

    Same contract as :func:`_visibility_bundle_builds`, and for the same
    reason: the module's list is cumulative and thread-local, so the turn's
    reading is a tail taken from a cursor sampled at the anchor. ``None`` when
    the module cannot be consulted at all, which leaves the turn naming no
    component rather than claiming the previous turn's.
    """

    try:
        from agent_runtime.chat_lane_bundle import key_material_moves_this_thread

        return int(key_material_moves_this_thread())
    except Exception:
        return None


def _visibility_bundle_rebuild_components(cursor):
    """The key components that MOVED during this turn. Empty when unknowable.

    An empty tuple for a turn that rebuilt nothing is the truth about it, and
    an empty tuple for a turn whose cursor was never sampled is honest too: the
    receipt is a set of named flags, and a flag nobody measured is simply not
    written. Never raises — an instrument may not be a reason a turn fails.
    """

    if cursor is None:
        return ()
    try:
        from agent_runtime.chat_lane_bundle import key_material_moves_since

        names = key_material_moves_since(int(cursor))
    except Exception:
        return ()
    # The name lands in a durable record's key namespace, so it is bounded here
    # as well as at its source: lowercase ASCII words only, never a value and
    # never anything a path or an id could survive as.
    return tuple(
        name
        for name in names
        if isinstance(name, str)
        and 0 < len(name) <= 40
        and name.replace("_", "").isalnum()
        and name.islower()
    )


#: chat-turn-prep Stage 6 item 2: the closed set of pre-admit sub-span keys the
#: two builders may contribute to a turn's ``profile_timing``.
#:
#: A closed set and not a prefix rule, at the fold rather than only at the store:
#: ``profile_timing`` is a durable record's key namespace, and "whatever the
#: builder put in its timings mapping" is not a decision anybody took. The
#: store's ``safe_turn_profile_timing`` bounds the shapes; this bounds the
#: MEMBERSHIP, so a new sub-span is a two-line edit here and a census row there
#: rather than a silent wire change.
_PRE_ADMIT_TIMING_KEYS = frozenset(
    {
        "context_skill_preload_ms",
        "context_hud_ms",
        "context_signature_ms",
        "observability_skill_rows_ms",
        "observability_catalog_walk_ms",
        "observability_shared_catalog_ms",
        "observability_catalog_cached",
    }
)


def _turn_skill_resolver(root_registries: dict[str, Any]) -> Any:
    """The turn lane's prompt-observability resolver, built around ONE walk.

    chat-turn-prep CP-5. Until Stage 8 the turn lane passed no resolver at all,
    so ``mission_chat_prompt_observability`` constructed a bare one per call —
    every memo on it cold, and its registry map empty, which is why the row
    re-walked every skill root the preload policy had just walked.

    ``None`` on any failure, which restores exactly the pre-Stage-8 behaviour:
    the row builds its own resolver and pays its own walk. A turn must not fail
    because an optimisation could not be constructed.
    """

    try:
        from agent_runtime.prompt_observability import _SkillObservabilityResolver

        return _SkillObservabilityResolver(root_registries=root_registries)
    except Exception:
        return None


def _safe_pre_admit_timings(value):
    """The sub-spans a builder measured, as non-negative ints. Never raises.

    Drops what it cannot read and supplies NOTHING — the same one-directional
    defense ``safe_turn_phases`` and ``safe_turn_profile_timing`` apply, held
    here as well because this is where an unmeasured span would become a zero
    if anyone let it. A builder that recorded no mapping (an older object, a
    build that raised part-way) contributes no keys.
    """

    if not isinstance(value, dict):
        return {}
    folded = {}
    for key in _PRE_ADMIT_TIMING_KEYS:
        raw = value.get(key)
        # bool is an int subclass, and a True in a millisecond slot is
        # corruption rather than a one-millisecond span.
        if isinstance(raw, bool) or not isinstance(raw, int):
            continue
        if raw < 0:
            continue
        folded[key] = raw
    return folded


def _prewarm_constructions_overlapped(marks, *, until_ms):
    """chat-turn-prep Stage 6: chat-actor prewarms whose span intersects
    ``anchor → until_ms``. The same window, the same clock and the same
    absent-never-zero rule as :func:`_snapshot_builds_overlapped` — the two
    receipts differ only in which competitor for the GIL they count.

    The window's near end IS the admitted window's near end: ``admitted_turn()``
    is entered in the same statement that takes this anchor, so "ran inside the
    admitted window" and "intersects the turn's window" are one question.
    """

    if until_ms is None:
        return None
    try:
        from agent_runtime import persona_chat_actor_prewarm

        anchor = marks.anchor_monotonic
        return persona_chat_actor_prewarm.overlapping_constructions(
            start=anchor, end=anchor + (float(until_ms) / 1000.0)
        )
    except Exception:
        return None


def _snapshot_builds_overlapped(marks, *, until_ms):
    """Stage 4: snapshot builds whose span intersects ``anchor → until_ms``.

    ``until_ms`` is a mark off the same monotonic anchor (``stream_done``), so
    the window is reconstructed on the build ledger's own clock — never from
    wall stamps, and never across processes.

    Returns ``None`` — leaving the key ABSENT — for a window that was never
    marked (the turn did not reach ``stream_done``) or for a process that has
    never led a build and therefore cannot see the lane. A ``0`` from here is a
    real measurement: builds happened in this process and none of them touched
    this turn. That distinction is the entire point of the counter, because the
    warm sample turn stayed fast WITH a concurrent build and the remedy
    decision turns on whether that generalizes.
    """

    if until_ms is None:
        return None
    try:
        from agent_runtime import snapshot_build_ledger

        anchor = marks.anchor_monotonic
        return snapshot_build_ledger.overlapping_builds(
            start=anchor, end=anchor + (float(until_ms) / 1000.0)
        )
    except Exception:
        return None
