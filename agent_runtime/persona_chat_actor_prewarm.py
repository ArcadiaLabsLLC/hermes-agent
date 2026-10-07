"""Build a chat's resident actor BEFORE its first message arrives.

Why this module exists
----------------------
``write_ahead → agent_ready`` is bimodal. On the second and later turns of one
chat root it is 60-600 ms; on the FIRST turn of a chat root — the exact turn an
operator is watching after opening a chat, and the only turn a fresh chat ever
has — it is 3.0-3.6 s, because that is where ``ProfileRunner._execute_agent_run``
constructs the agent: the OpenAI SDK client, the tool-definition build with its
own ``check_fn`` sweep, and ``tool_search`` activation. Live receipts, 2026-08-23
(serve booted with ``persona_chat.hot_sessions_enabled: true``):

* ``17:33:01Z`` — first message after the boot: ``agent_init_cold=true``,
  bootstrap 3,782 ms of which ``agent_construct_ms=3000``, first byte 10.0 s.
* ``17:33:17Z`` — second message, same chat: ``resident_actor_reused=1``,
  ``agent_init_cold=false``, bootstrap 62 ms, first byte 3.4 s.

The registry and the factory that make the second number possible already
exist (``profile_runner.py``'s ``acquire()`` branch). What did not exist was
anything that called them off the turn's critical path. That is this module: the
same construction, run on a background worker, so the first turn of a chat finds
an already-registered resident entry and pays the second number.

The one property everything here serves: BYTE-MATCH
---------------------------------------------------
``PersonaChatRuntimeRegistry.acquire`` reuses an entry only when the caller's
``signature`` and ``revision`` match the stored ones exactly; a mismatch CLOSES
the entry and rebuilds. So a pre-built actor whose signature the next turn does
not reproduce is not merely useless — it is pure cost, and worse than no prewarm
at all. (This is not hypothetical: the 2026-08-23T14:45:14Z live turn recorded
``resident_rebuild_runtime_signature_changed`` because the signature folded
persona-instance row liveness. That defect is fixed; this module must not
reintroduce its shape.)

Three rules follow, and they explain every awkward-looking import below:

1. **The signature is COMPUTED by the turn's own code, never re-derived.**
   :func:`agent_runtime.mission_chat_turn_context.mission_chat_runtime_signature`
   is the single authority, called here with the same arguments
   ``build_mission_chat_turn_context`` passes it. This module's job is to
   reproduce the INPUTS, and it reproduces each of them through the turn's own
   resolver as well: ``_persona_by_id`` for the persona,
   ``apply_instance_model_overrides`` for the instance tier,
   ``_chat_effective_model_payload`` for the model cascade,
   ``_session_model_config`` for the chat-scoped override,
   ``load_agent_runtime_config`` for the config, ``chat_lane_bundle`` (through
   the signature's own resolvers) for the tool contract and permission state.
2. **The revision and the active session id are read from the SAME places.**
   ``_persona_chat_native_revision`` and ``_persona_chat_native_tip``, the
   helpers the send path calls, on a SessionDB opened exactly as the send path
   opens it. A revision mismatch is a rebuild, not a re-prepare.
3. **The construction runs under the real scope stack.** Not a hand-rolled
   context: ``ProfileAgentRunner.prewarm`` runs ``_execute_agent_run`` with
   ``prewarm_only=True``, so the agent is built inside ``_WORKDIR_LOCK``,
   ``persona_profile_context`` (the profile ``.env``), the workdir,
   tool-execution / chat-root / terminal-envelope / skill scopes, and this
   persona's MCP admission — and torn down the same way. An agent constructed
   under different scopes would be a different agent.

What it will not do
-------------------
**It never guesses a turn input it cannot know.** One input is genuinely
unknowable here: ``--agents-file``, the operator's workspace ``AGENTS.md``,
which the launcher attaches per turn from a selection it holds client-side. This
module prewarms with no workspace file (the state of every chat that has none).
For a WORKSPACE-BOUND chat the first turn's signature therefore differs and
``acquire`` rebuilds — that turn pays exactly what it pays today, and the
prewarmed actor is discarded. That is the honest cost, stated rather than
papered over with a guessed path; the alternative (fabricating a workspace
pointer) would ground a real agent's terminal at a directory the operator never
chose.

**It sends nothing to a model.** Construction builds an OpenAI client object —
``OpenAI client created (agent_init, shared=True)`` — which is local object
creation over already-resolved credentials; the first byte on the wire is
``codex_stream_request``, which lives in ``run_conversation`` and is on the far
side of this module's early return. So no prompt, no completion, no token spend.

**Two side effects it does inherit from the real path, named rather than
denied.** Both are the first turn's own work, performed earlier:

* ``_resolve_request_runtime`` → ``resolve_runtime_provider`` reads credentials.
  On ``openai-codex`` (this lane's live provider) that is a local ``auth.json``
  read, but the resolver is provider-shaped: a Vertex persona mints a short-lived
  OAuth2 access token, and a Nous credential pool may refresh an expired agent
  key. Those are network calls — the SAME ones the chat's first turn would make,
  and its result is cached for the turn behind it
  (``RUNTIME_RESOLVE_CACHE_TTL_SECONDS``), so the prewarm pays them instead of
  the operator. It is not a new class of call, and it is not sent to a model.
* MCP admission spawns this persona's declared servers and registers their
  tools, exactly as the first turn would have — and tears them down on the way
  out, while the run still holds ``_WORKDIR_LOCK``.

**It yields to real work.** ``_WORKDIR_LOCK`` serializes every run in the
process, so a construction holding it while an operator message arrives ADDS
~3 s to that turn instead of removing it. The guard is
``turn_activity.chat_turns_admitted()`` OR ``profile_runner.agent_runs_in_flight()``
— read immediately before the scope stack is entered, and again after
``_prepare``: if a turn is admitted or any real run is in flight this item
stands down (``skipped_turn_active``) rather than queueing behind it.

The admitted half is chat-turn-prep Stage 7 (CP-2), and it is the half that
fires. ``agent_runs_in_flight()`` counts from ``ProfileAgentRunner.run()``;
a mission-chat turn is admitted at the handler's anchor and spends its whole
pre-admit assembly before any runner exists. §0.2 measured the consequence:
this prewarm ran ``elapsed_ms=5750`` across the ENTIRE pre-admit span of the
turn the operator was typing — into the same chat root it was warming — and
the run gauge read zero throughout.

h-prewarm-order adds the window before the anchor: a turn the serve has
ACCEPTED (``turn_activity.chat_turns_accepted()``, held from the pool submit to
the anchor) stands a prewarm down too. And a boot item yields to a chat the
operator opened after it started (``preempted_by_open``, requeued behind it).

``turn_activity``'s process-wide count is the sole admission authority, and it
covers the same-root case by construction: when any turn is admitted this
stands down, the same-root prewarm included. That is the NO-OP case, now taken
deliberately instead of raced — the turn would have built this exact actor
itself, and instead finds it. Constructions are serialized one at a time on a
single daemon worker, so at most one is ever in flight. A turn arriving DURING
a construction (h-turn-wait) is no longer bounded by the whole construction: the
run asks ``_stand_down_outcome`` at each phase boundary inside ``_WORKDIR_LOCK``
and while MCP admission waits, and unwinds (``persona_chat_actor_prewarm_yielded``)
so the turn takes the lock within one phase step.

Triggers
--------
* **serve boot** — one pass after the ready frame, behind the read-model build
  and the provider warmup on the same thread (see ``serve.py``'s ordering
  doctrine), warming at most ``persona_chat.max_hot_sessions`` chats,
  most-recently-active first.
* **chat open** — ``persona instance open-chat``, the capability the launcher
  fires when an operator opens or creates a chat. Deliberately NOT
  ``PersonaInstanceStore.open_chat``, which the SEND path re-enters on every
  turn: hooking there would fire a background construction against every live
  turn.

Both go through :func:`request_chat_actor_prewarm`, which is a no-op whenever
``persona_chat_runtime_registry()`` is ``None`` — so a CLI one-shot, which never
calls ``initialize_persona_chat_runtime_registry``, pays nothing and starts no
thread.
"""

from __future__ import annotations

import itertools
import logging
import queue
import threading
import time
from typing import Any

from .launcher_link_prewarm import LauncherLinkPreparation, launcher_link_prewarm_scope

__layer__ = "lanes"

logger = logging.getLogger(__name__)


# ── the construction ledger (chat-turn-prep Stage 6, CP-2's second recorder) ──
#
# ``builds_overlapped`` on a turn record answers "did a snapshot build steal
# time from this turn", and on 2026-09-07 it acquitted or convicted three turns
# by itself. The OTHER thing running in that window has no such receipt: the
# chat-open prewarm for the very root the operator was typing into ran 5,750 ms
# across the whole of turn 1's pre-admit span (plan §0.2) — an LRU eviction
# closing eight OpenAI clients over ~1.1 s, a full ``check_fn`` sweep and a
# ``tool_search`` activation — and the only trace was a log line nobody joins to
# a turn.
#
# So a construction records its span exactly the way
# ``agent_runtime.snapshot_build_ledger`` records a build's: monotonic spans in
# a bounded ring, intersected against the turn's own window, and ``None`` — not
# ``0`` — for a process that has never prewarmed and therefore cannot see the
# lane at all. Stage 7 does not move the eviction this bills; it names it, and
# says a stage for it is written only if this receipt convicts it.
#
# What is NOT a construction: the yields. ``prewarm_chat_actor`` stands down
# before assembling anything when a run is in flight, and a refusal that cost
# nothing must not be counted as a span some turn overlapped.

#: Enough history to cover any turn's window several times over. Bounded so a
#: long-lived serve cannot grow it.
_MAX_CONSTRUCTION_SPANS = 256

_span_lock = threading.Lock()
_construction_spans: list[tuple[float, float]] = []
#: Has this process ever RUN a construction? Distinct from the list's length
#: because the ring evicts; once true it stays true, and it is what separates
#: "none overlapped" from "not observable here".
_constructed_any = False
#: Starts of constructions still running. Counted as overlaps for the same
#: reason ``snapshot_build_ledger._open`` is (h-chatperf): a turn reads this at
#: ``stream_done``, and a construction still in flight then was invisible.
_open_constructions: dict[int, float] = {}


def record_construction(*, started: float, ended: float) -> None:
    """Record one construction's monotonic span. Never raises.

    A construction that RAISED is recorded: it occupied the process for that
    span whether or not it left an actor resident, and a turn beside it paid the
    same price. Same rule as ``snapshot_build_ledger.record_build``.
    """

    global _constructed_any
    try:
        start = float(started)
        end = float(ended)
    except (TypeError, ValueError):
        return
    if end < start:
        return
    with _span_lock:
        _constructed_any = True
        _construction_spans.append((start, end))
        if len(_construction_spans) > _MAX_CONSTRUCTION_SPANS:
            del _construction_spans[:-_MAX_CONSTRUCTION_SPANS]


def overlapping_constructions(*, start: float, end: float) -> int | None:
    """How many recorded constructions intersect ``[start, end]``.

    ``None`` when this process has never constructed one — the honest answer for
    a CLI child, or for a serve whose hot-session registry is off. ``0`` when it
    has and none touched this window: that is a measurement, and it is the
    answer that acquits the prewarm for a turn.

    Closed interval on both ends, for the same reason
    ``snapshot_build_ledger.overlapping_builds`` uses one: everything around
    this is millisecond-resolution, so the conservative reading is the right one.
    """

    try:
        window_start = float(start)
        window_end = float(end)
    except (TypeError, ValueError):
        return None
    if window_end < window_start:
        return None
    with _span_lock:
        if not _constructed_any:
            return None
        spans = list(_construction_spans)
        open_starts = list(_open_constructions.values())
    closed = sum(
        1
        for span_start, span_end in spans
        if span_end >= window_start and span_start <= window_end
    )
    return closed + sum(1 for span_start in open_starts if span_start <= window_end)


def reset_construction_spans_for_tests() -> None:
    """Drop every recorded span AND the observed flag. Tests only."""

    global _constructed_any
    with _span_lock:
        _construction_spans.clear()
        _open_constructions.clear()
        _constructed_any = False


class _ConstructionSpan:
    """Times a construction and records it on exit. Never swallows."""

    __slots__ = ("_started",)

    def __enter__(self) -> "_ConstructionSpan":
        global _constructed_any
        self._started = time.monotonic()
        with _span_lock:
            _constructed_any = True
            _open_constructions[id(self)] = self._started
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        with _span_lock:
            _open_constructions.pop(id(self), None)
        try:
            record_construction(started=self._started, ended=time.monotonic())
        except Exception:  # pragma: no cover - an instrument never fails a prewarm
            pass
        return False


# ── receipts ─────────────────────────────────────────────────────────────────
#
# TIMINGS AND IDS ONLY, in the vocabulary of the emitter list in
# ``docs/agent-runtime-harness/07-observability.md``: how long, about which
# root, and what happened. Never a persona display name, never a resolved
# toolset, never anything the construction read.

#: One INFO line per prewarm the worker finishes, with THAT item's outcome and
#: cost. The per-entry half of the receipt — a pass line with only totals cannot
#: answer "which chat was it that took four seconds", and a prewarm whose whole
#: claim is a race against the operator's first message has to be answerable at
#: that grain.
CHAT_ACTOR_PREWARM_DONE_RECEIPT = (
    "persona_chat_actor_prewarm root=%s outcome=%s elapsed_ms=%d"
)

#: One INFO line per boot pass, emitted when the pass has been QUEUED (not when
#: the last item finishes — the worker owns that, one line each). ``candidates``
#: is what the roster offered, ``queued`` what the cap and the dedupe let
#: through; the difference is the cap doing its job, stated rather than inferred.
CHAT_ACTOR_PREWARM_PASS_RECEIPT = (
    "persona_chat_actor_prewarm pass candidates=%d queued=%d skipped=%d elapsed_ms=%d"
)

#: h-turn-wait: a prewarm stood down INSIDE the run lock for a turn; ``phase`` names
#: the boundary (``lock_acquired`` .. ``system_prompt_stashed``), ``reason`` the outcome
#: the worker reports for the item.
CHAT_ACTOR_PREWARM_YIELDED_RECEIPT = (
    "persona_chat_actor_prewarm_yielded root=%s phase=%s reason=%s"
)

#: An actor was constructed and is now resident for this chat root.
OUTCOME_WARMED = "warmed"

#: The registry already held an entry for this root under this exact signature
#: and revision — a real turn (or an earlier prewarm) got there first.
#: ``acquire`` returned it and nothing was built. Success, not a miss.
OUTCOME_ALREADY_RESIDENT = "already_resident"

#: ``persona_chat.hot_sessions_enabled`` is off, so there is no registry to put
#: an actor in. Every hook is inert in this state; reported rather than silent
#: so "why did nothing warm" has an answer.
OUTCOME_REGISTRY_OFF = "registry_off"

#: A real agent run was in flight in this process. The prewarm stood down rather
#: than queue behind it on ``_WORKDIR_LOCK``. See the module docstring.
OUTCOME_SKIPPED_TURN_ACTIVE = "skipped_turn_active"

#: h-prewarm-order: a BOOT item stood down because the operator opened a chat
#: meanwhile; the worker requeues it behind the open (``_drain``).
OUTCOME_PREEMPTED_BY_OPEN = "preempted_by_open"

#: No chat root was named, or no persona instance owns the one that was.
OUTCOME_SKIPPED_NO_CHAT_ROOT = "skipped_no_chat_root"

#: The instance names a persona the roster does not resolve.
OUTCOME_SKIPPED_PERSONA_UNRESOLVED = "skipped_persona_unresolved"

#: The persona binds no usable Hermes profile, or its provider is unhealthy.
#: A real turn refuses for the same reason; there is nothing to warm.
OUTCOME_SKIPPED_PROFILE_UNREADY = "skipped_profile_unready"

#: h-chatperf (2026-10-03): the chat's FIRST turn found this prewarmed actor
#: and threw it away (``resident_signature_diff``). Written after the fact by
#: the registry, the only place that can know; see
#: ``persona_chat_continuity.runtime_registry.PREWARM_DISCARDED_RECEIPT``. Cold
#: turn ``1e4c06ba`` was this: 61 deferred tools prewarmed, 71 at the turn.
OUTCOME_DISCARDED_SIGNATURE_MISMATCH = "discarded_signature_mismatch"

#: Construction itself raised. The next real turn pays the cold cost it would
#: have avoided and reports its own error — never this one.
OUTCOME_SKIPPED_CONSTRUCT_FAILED = "skipped_construct_failed"


# ── the unit of work ─────────────────────────────────────────────────────────


def prewarm_chat_actor(root_session_id: str, *, instance: Any = None) -> str:
    """Construct and register one chat root's resident actor. Returns an outcome.

    Synchronous and self-contained: everything from resolving the chat's owner
    to the ``acquire()`` that leaves the actor resident. The return value is one
    of the ``OUTCOME_*`` tokens above — this function reports, it never raises
    for an ordinary refusal, and its one raise-through (a construction fault) is
    caught at the bottom and reported as :data:`OUTCOME_SKIPPED_CONSTRUCT_FAILED`.

    Callable directly (a test, an operator diagnosing a chat that will not
    warm); the worker below is just a queue in front of it.
    """

    from .persona_chat_continuity import persona_chat_runtime_registry

    if persona_chat_runtime_registry() is None:
        return OUTCOME_REGISTRY_OFF
    root = str(root_session_id or "").strip()
    if not root:
        return OUTCOME_SKIPPED_NO_CHAT_ROOT

    # The yield decision, taken BEFORE anything expensive and before the scope
    # stack. See the module docstring: standing down costs a warm actor; queueing
    # behind a live turn costs that turn ~3 s.
    #
    # Stage 7 / CP-2: an ADMITTED turn owns the GIL, not only a RUNNING one.
    # §0.2's chat-open prewarm billed ``elapsed_ms=5750`` across the WHOLE of
    # turn 1's pre-admit span, for the very root the operator was typing into,
    # and this read saw nothing the entire time because ``_counted_agent_run``
    # does not increment until ``ProfileAgentRunner.run()``.
    #
    # ``turn_activity``'s process-wide count is the SOLE admission authority and
    # it already covers the same-root case: when any turn is admitted this
    # stands down, including the prewarm for that turn's own root — which is the
    # no-op the module docstring names (that turn would build this exact actor
    # itself, and instead finds it). No per-root admission map is minted here;
    # the GIL this yields to is process-wide, so the counter that guards it is
    # too.
    stand_down = _stand_down_outcome()
    if stand_down is not None:
        return stand_down

    # Stage 6's span opens PAST the yield and covers everything after it: the
    # §0.2 line this bills (``elapsed_ms=5750``) is the whole of
    # ``_prepare`` + ``prewarm``, and ``_prepare`` is not free — it reads
    # SessionDB, resolves the lane bundle and composes the runtime signature.
    # A stand-down above this point recorded nothing, which is the truth about
    # a refusal that constructed nothing.
    with _ConstructionSpan():
        try:
            prepared = _prepare(root, instance)
        except _PrewarmRefused as refusal:
            return refusal.outcome
        except Exception:
            logger.debug(
                "chat-actor prewarm could not assemble a request for %s",
                root,
                exc_info=True,
            )
            return OUTCOME_SKIPPED_CONSTRUCT_FAILED

        request, runner = prepared
        # Re-read the gauges: assembling the request above reads SessionDB and
        # resolves the lane bundle, which is where a turn that arrived meanwhile
        # would now be. Cheap insurance against the widest part of the window —
        # and under Stage 7 it is the check that actually fires, because a turn
        # arriving during ``_prepare`` is ADMITTED long before it runs.
        #
        # Refusing here still leaves the preparation span honestly recorded:
        # ``_prepare`` really did run and really did cost something. What this
        # prevents is the CONSTRUCTION — the expensive half — colliding with the
        # turn.
        stand_down = _stand_down_outcome()
        if stand_down is not None:
            return stand_down
        # h-turn-wait: both reads above sit BEFORE the run lock. Live 2026-10-06
        # 20:23:58 a turn on another root was accepted after them and its
        # `agent_ready` waited 18.5 s on `_WORKDIR_LOCK` while this prewarm sat in a
        # 20 s MCP admission. The run asks the same gauge at every phase boundary
        # inside the lock (and while admission waits) and unwinds when it answers.
        from .profile_runner.errors import PrewarmYielded

        request.prewarm_yield = _stand_down_outcome
        try:
            timing = runner.prewarm(request)
        except PrewarmYielded as yielded:
            logger.info(CHAT_ACTOR_PREWARM_YIELDED_RECEIPT, root, yielded.phase, yielded.reason)
            return str(yielded.reason)
        except Exception:
            logger.debug(
                "chat-actor prewarm construction failed for %s", root, exc_info=True
            )
            return OUTCOME_SKIPPED_CONSTRUCT_FAILED
        # h-turn1 A3/A4: what the prewarm moved off the first turn, by key; a
        # key absent is work it did not do (the actor already had a prompt, the
        # provider is loopback or has no httpx client).
        # h-prewarm-order: every phase the run timed, so a silent span between
        # two log lines (5.3 s on 2026-10-06 01:24:59) is named by the receipt.
        logger.info(
            "persona_chat_actor_prewarm_first_turn root=%s runtime_resolve_ms=%s mcp_admission_ms=%s"
            " system_prompt_build_ms=%s connect_ms=%s"
            " construct_ms=%s first_turn_warmup_ms=%s mcp_teardown_ms=%s",
            root,
            timing.get("runtime_resolve_ms", "absent"),
            timing.get("mcp_admission_ms", "absent"),
            timing.get("prewarm_system_prompt_build_ms", "absent"),
            timing.get("prewarm_connect_ms", "absent"),
            timing.get("agent_construct_ms", "absent"),
            timing.get("prewarm_first_turn_warmup_ms", "absent"),
            timing.get("mcp_teardown_ms", "absent"),
        )
        return (
            OUTCOME_ALREADY_RESIDENT
            if timing.get("resident_actor_reused")
            else OUTCOME_WARMED
        )


def _stand_down_outcome() -> str | None:
    """Why this item must not construct now, or None. Read at both yield points.

    A turn ACCEPTED on the dispatcher but not yet anchored in its handler counts
    (h-prewarm-order): turn ``5377d205`` was accepted 01:25:04.23 and anchored
    04.909, and a same-root prewarm passed the admitted/running reads at 04.73
    and constructed through that turn's pre-admit. And a BOOT item yields to a
    chat the operator has opened since it started (``_open_waiting``).
    """

    from .profile_runner import agent_runs_in_flight
    from .turn_activity import chat_turns_accepted, chat_turns_admitted

    if chat_turns_accepted() > 0 or chat_turns_admitted() > 0 or agent_runs_in_flight() > 0:
        return OUTCOME_SKIPPED_TURN_ACTIVE
    with _lock:
        preempt = _running_priority == PRIORITY_BOOT and _open_waiting_locked()
    return OUTCOME_PREEMPTED_BY_OPEN if preempt else None


class _PrewarmRefused(Exception):
    """An ordinary, typed refusal from :func:`_prepare`."""

    def __init__(self, outcome: str):
        super().__init__(outcome)
        self.outcome = outcome


def _prepare(root: str, instance: Any) -> tuple[Any, Any]:
    """Assemble the EXACT ``AgentRunRequest`` this chat's first turn would build.

    Every value here is produced by the same authority the send path uses. The
    imports from ``hermes_cli.harness_parts.persona_commands`` are the point,
    not an accident: those six helpers ARE the turn's answers, and a private
    copy of any of them is a second answer that would drift from the first
    exactly when it mattered (the drift is silent — it costs a rebuild, not an
    error). They are function-local because that module is large and this one is
    imported at serve boot.
    """

    from agent_runtime.persona_chat_session import (
        _chat_effective_model_payload,
        _chat_model_override_from_config,
        _persona_chat_native_revision,
        _persona_chat_native_tip,
        _session_model_config,
    )
    from hermes_cli.harness_parts.persona.chat_target import _persona_by_id

    from pathlib import Path

    from . import paths
    from .chat_lane_bundle import chat_lane_bundle
    from .config import load_agent_runtime_config
    from .mcp_admission import LANE_MISSION_CHAT
    from .mission_chat_turn_context import (
        mission_chat_runtime_signature_components,
        mission_chat_runtime_signature_digests,
        mission_chat_runtime_signature_from_components,
    )
    from .mission_chat_workdir import mission_chat_workdir_for_persona
    from .models import apply_instance_model_overrides
    from .persona_chat_durability import default_persona_session_db
    from .persona_runtime import PERSONA_CHAT_SCRATCH_SOURCE
    from .persona_chat_continuity import persona_chat_runtime_registry
    from .profile_context import resolve_persona_profile
    from .profile_runner import AgentRunRequest, ProfileAgentRunner
    from .provider_health import assert_provider_health_for_persona
    from .terminal_envelope import scope_for_persona as terminal_envelope_scope_for_persona

    if instance is None:
        instance = _instance_for_root(root)
    if instance is None:
        raise _PrewarmRefused(OUTCOME_SKIPPED_NO_CHAT_ROOT)

    cfg = load_agent_runtime_config()
    persona = _persona_by_id(cfg, str(getattr(instance, "persona_id", "") or ""))
    if persona is None:
        raise _PrewarmRefused(OUTCOME_SKIPPED_PERSONA_UNRESOLVED)
    instance = _instance_as_the_send_path_stamps_it(persona, instance, root)
    # The send path folds the instance model-override tier into the persona
    # BEFORE it resolves anything else (persona_commands: `persona =
    # apply_instance_model_overrides(persona, instance)`), and the folded
    # persona is what reaches both the signature and the runtime. Folding it
    # anywhere but here would key the actor on a persona nobody runs.
    persona = apply_instance_model_overrides(persona, instance)

    binding = resolve_persona_profile(persona)
    if binding.readiness == "missing_profile":
        raise _PrewarmRefused(OUTCOME_SKIPPED_PROFILE_UNREADY)

    session_db = default_persona_session_db()
    session_model_config = _session_model_config(session_db, root)
    model_selection = _chat_effective_model_payload(
        persona=persona,
        config=cfg,
        override=_chat_model_override_from_config(session_model_config),
        instance=instance,
    )
    runtime_provider = model_selection.get("effective_provider") or getattr(
        persona, "provider", None
    )
    runtime_model = model_selection.get("effective_model") or getattr(
        persona, "model", None
    ) or ""
    try:
        _assert_provider_health(
            assert_provider_health_for_persona, persona, runtime_provider, runtime_model
        )
    except Exception:
        # A turn on this persona would refuse before it ran; warming an actor it
        # cannot use is work for nobody. Reported, not raised.
        raise _PrewarmRefused(OUTCOME_SKIPPED_PROFILE_UNREADY)

    # Composed, then folded exactly as the turn folds it: the composite is the
    # reuse key, the per-component digests ride along so the first real turn's
    # refusal (if any) names the component that moved. Seeding them HERE is
    # what makes the prewarm-vs-turn half of that diff answerable at all — an
    # entry with no component map can only report that the composite changed.
    signature_components = mission_chat_runtime_signature_components(
        persona=persona,
        instance=instance,
        config=cfg,
        session_id=root,
        session_model_config=session_model_config,
        model_selection=model_selection,
        # No ``--agents-file``: see the module docstring's "what it will not do".
        # A chat with no workspace selection matches exactly; a workspace-bound
        # one rebuilds on its first turn and costs what it costs today — and now
        # says so, as ``resident_rebuild_component_workspace_agents``.
        workspace_agents_receipt=_slot_receipt(instance),
        surface_prompt="",
    )
    signature = mission_chat_runtime_signature_from_components(signature_components)
    # The tip and the revision the FIRST turn will pass to ``acquire``. Both are
    # read here, from the same helpers that turn calls; a chat that is written
    # between this read and that turn rebuilds, which is correct — its history
    # moved.
    active_session_id = _persona_chat_native_tip(session_db, root)
    native_revision = _persona_chat_native_revision(session_db, root)

    lane_bundle = chat_lane_bundle(persona, session_id=root)
    workdir = mission_chat_workdir_for_persona(persona, workspace_agents_path=None, primary_slot_path=_slot_primary(instance))
    envelope_scope = terminal_envelope_scope_for_persona(
        persona,
        lane=LANE_MISSION_CHAT,
        session_id=root,
        runtime_root=paths.store_root(),
        permission_mode=lane_bundle.permission_mode,
    )

    request = AgentRunRequest(
        prewarm_only=True,
        profile=binding.hermes_profile,
        provider=runtime_provider,
        model=runtime_model,
        api_mode=getattr(persona, "api_mode", None),
        reasoning_effort=getattr(instance, "reasoning_effort", None),
        terminal_envelope_scope=envelope_scope,
        mcp_admission=lane_bundle.admission,
        enabled_toolsets=list(lane_bundle.enabled_toolsets),
        blocked_tool_names=list(lane_bundle.blocked_tool_names),
        quiet_mode=True,
        skip_context_files=not bool(getattr(persona, "include_core_context_files", False)),
        skip_memory=not bool(getattr(persona, "include_profile_memory", False)),
        platform=PERSONA_CHAT_SCRATCH_SOURCE,
        system_message=_first_turn_system_message(persona, instance),
        skill_surface="mission_chat",
        skill_root_node_mode=False,
        session_id=active_session_id,
        **_prompt_surface_kwargs(persona, instance, root, lane_bundle),
        tool_execution_scope_id=root,
        root_chat_session_id=root,
        persona_chat_runtime_registry=persona_chat_runtime_registry(),
        persona_chat_runtime_signature=signature,
        persona_chat_runtime_signature_components=(
            mission_chat_runtime_signature_digests(signature_components)
        ),
        persona_chat_native_revision=native_revision,
        runtime_root=paths.store_root(),
        workdir=Path(workdir.path) if workdir.grounded else None,
        # Every callback stays None. A prewarm has no operator watching it, no
        # stream to feed and no turn record to decorate; the resident actor's
        # per-turn handles are (re)bound by
        # ``_prepare_resident_persona_chat_agent`` on the first real turn, which
        # is the seam that exists for exactly this.
    )
    runner = ProfileAgentRunner(session_db=session_db)
    return request, runner


def _assert_provider_health(assert_fn: Any, persona: Any, provider: Any, model: Any) -> None:
    """``assert_provider_health_for_persona`` against the EFFECTIVE model tier.

    Mirrors ``mission_chat_reply``: the health check runs on a copy carrying the
    provider/model this run would actually use, never on the roster row's
    declared pair.
    """

    from .models import AgentPersona

    health_persona = AgentPersona(
        **{
            field: getattr(persona, field)
            for field in getattr(persona, "__dataclass_fields__", {})
        }
    )
    health_persona.provider = provider
    health_persona.model = model
    assert_fn(health_persona)


def _instance_as_the_send_path_stamps_it(persona: Any, instance: Any, root: str) -> Any:
    """*instance* after the store write the send path makes before it signs.

    h-turn1-conn. The send path runs ``PersonaInstanceStore.ensure_for_personas``
    on every non-auxiliary turn (``hermes_cli/harness_parts/persona/chat_turn_message.py``),
    and ``ensure_for_persona`` re-stamps a persona's canonical instance with the
    persona's ``display_name``; ``persona_assignments/chat_binding.py::open_chat``
    mints that row with a template or operator name. Two writers: a row minted
    "Dev" for a persona named "Dev Persona" moved ``instance_revision`` between
    the prewarm's signature and turn 1's, and the actor was discarded
    (``discarded_signature_mismatch``). The prewarm makes the same write first
    -- this persona only, the row the send path would touch for it -- so both
    sign one row. Fail-open: the instance as given.
    """

    from .auxiliary_chat import is_auxiliary_chat
    from .persona_assignments import PersonaInstanceStore
    from .persona_lifecycle import is_runtime_persona

    instance_id = str(getattr(instance, "id", "") or "")
    if not instance_id or is_auxiliary_chat(instance_id, root) or not is_runtime_persona(persona):
        return instance
    try:
        store = PersonaInstanceStore()
        store.ensure_for_persona(persona)
        return store.get(instance_id)
    except Exception:
        logger.debug("prewarm could not re-read instance %s after the send path's stamp", instance_id,
                     exc_info=True)
        return instance


def _instance_for_root(root: str) -> Any:
    """The persona instance whose bound chat root is *root*."""

    from .persona_assignments import PersonaInstanceStore

    try:
        instances = PersonaInstanceStore().list_all()
    except Exception:
        return None
    for instance in instances:
        bound = str(
            getattr(instance, "default_chat_session_id", None)
            or getattr(instance, "session_id", None)
            or ""
        ).strip()
        if bound == root:
            return instance
    return None


# ── the background worker ────────────────────────────────────────────────────
#
# The same single-daemon-worker shape as ``persona_prewarm``, for a stronger
# reason: there the argument was cache thrash, here it is the workdir lock. Two
# workers would be two constructions racing for a lock every real turn also
# needs, which is the contention this module exists to avoid — so the queue is
# not merely serialized by preference, it is serialized by contract.
#
# h-prewarm-order: ORDER, not a second worker. An open goes ahead of every queued
# boot item, and a boot item still before its construction stands down at either
# yield point (``preempted_by_open``) and is requeued behind the open. A boot
# item already constructing finishes: it holds ``_WORKDIR_LOCK``, which a second
# worker's construction would wait on anyway.

#: h-prewarm-order: a chat the operator OPENS goes ahead of the boot pass. On
#: 2026-10-06 01:24:53 a boot item (the previously-open chat) held this worker
#: 11.7 s; the opened chat queued FIFO behind it and ran beside its first turn.
PRIORITY_OPEN = 0
PRIORITY_BOOT = 1

#: ``(priority, sequence, root)``; FIFO within a priority. An entry whose
#: priority no longer matches ``_pending[root]`` was superseded by a promotion.
_queue: "queue.PriorityQueue[tuple[int, int, str]]" = queue.PriorityQueue()
_lock = threading.Lock()
#: root -> the priority it is queued at (or running at, until the worker ends it).
_pending: dict[str, int] = {}
_sequence = itertools.count()
#: The item the worker is running (root, priority); None while it waits.
_running_root: str | None = None
_running_priority: int | None = None
_worker: threading.Thread | None = None
#: How long the worker waits for an open's app-function refresh before it
#: prepares anyway (the reply normally lands in one round trip).
LINK_REFRESH_WAIT_SECONDS = 10.0


#: Both the opening connection and its discovery, not just the discovery
#: thread: availability is checked in the worker's construction context.
_links: dict[str, LauncherLinkPreparation] = {}


_deferred_until_idle: dict[str, int] = {}


def _resume_after_turn() -> None:
    """Requeue yielded roots once the turn authority observes an idle boundary."""
    if _stand_down_outcome() == OUTCOME_SKIPPED_TURN_ACTIVE:
        return
    with _lock:
        for root, priority in tuple(_deferred_until_idle.items()):
            if _pending.get(root) == priority:
                _queue.put((priority, next(_sequence), root))
        _deferred_until_idle.clear()


def _drain() -> None:
    """Warm one chat root at a time, forever, and never die.

    Every failure is contained here. A raise that escaped would kill the thread
    and silently turn every LATER prewarm into a no-op — the failure shape that
    is hardest to notice, since its only symptom is the slow first turn the
    prewarm was supposed to prevent.
    """

    global _running_priority, _running_root
    while True:
        priority, _, root = _queue.get()
        with _lock:
            if _pending.get(root) != priority:
                # Superseded by a promotion (the open's entry already ran it).
                _queue.task_done()
                continue
            _running_priority, _running_root = priority, root
            link = _links.pop(root, None)
        started = time.monotonic()
        try:
            with launcher_link_prewarm_scope(link, timeout=LINK_REFRESH_WAIT_SECONDS):
                outcome = prewarm_chat_actor(root)
        except Exception:
            outcome = OUTCOME_SKIPPED_CONSTRUCT_FAILED
            logger.warning(
                "chat-actor prewarm raised for %s after %d ms; the next turn on "
                "that chat pays the cold construction it would have avoided",
                root,
                int(max(0.0, time.monotonic() - started) * 1000),
                exc_info=True,
            )
        logger.info(
            CHAT_ACTOR_PREWARM_DONE_RECEIPT,
            root,
            outcome,
            int(max(0.0, time.monotonic() - started) * 1000),
        )
        with _lock:
            _running_priority, _running_root = None, None
            if outcome == OUTCOME_SKIPPED_TURN_ACTIVE and _pending.get(root) == priority:
                _deferred_until_idle[root] = priority
                if link is not None:
                    _links[root] = link
            elif outcome == OUTCOME_PREEMPTED_BY_OPEN and _pending.get(root) == priority:
                # Behind the open that preempted it; it built nothing yet.
                _queue.put((priority, next(_sequence), root))
            else:
                _pending.pop(root, None)
                # An open during construction can leave a late preparation.
                # It belongs to this completed item, never a later boot pass.
                _links.pop(root, None)
        _queue.task_done()
        # Closes the race where the last turn exits before this item parks.
        _resume_after_turn()


def _open_waiting_locked() -> bool:
    """Is a chat-open item queued? Call under ``_lock``."""

    return any(priority == PRIORITY_OPEN for priority in _pending.values())


from .turn_activity import register_turn_idle_listener
register_turn_idle_listener(_resume_after_turn)


def _ensure_worker() -> None:
    """Start the single daemon worker on first use. Call under ``_lock``."""

    global _worker
    if _worker is not None and _worker.is_alive():
        return
    _worker = threading.Thread(
        target=_drain, name="persona-chat-actor-prewarm", daemon=True
    )
    _worker.start()


def request_chat_actor_prewarm(
    root_session_id: str | None, *, launcher_link: Any = None, priority: int = PRIORITY_OPEN
) -> str:
    """Queue a chat root for background prewarm. Returns what it did.

    ``registry_off`` — and no thread, no queue entry — whenever
    ``persona_chat_runtime_registry()`` is ``None``. That is the state of every
    CLI one-shot and of any serve whose root config leaves
    ``persona_chat.hot_sessions_enabled`` off, so every hook in the harness is
    inert by default and this module costs an import.

    Idempotent by chat root: a root already queued or in flight is reported as
    ``already_running`` rather than queued twice, so a hook that fires on every
    chat-open gesture cannot grow the queue. An OPEN of a root still queued by
    the boot pass promotes it ahead of the rest (``promoted``).

    ``priority``: the open hooks take the default; the boot pass passes
    :data:`PRIORITY_BOOT`, and a boot item yields to any open queued after it.
    """

    from .persona_chat_continuity import persona_chat_runtime_registry

    if persona_chat_runtime_registry() is None:
        return OUTCOME_REGISTRY_OFF
    root = str(root_session_id or "").strip()
    if not root:
        return OUTCOME_SKIPPED_NO_CHAT_ROOT
    with _lock:
        if launcher_link is not None:
            _links[root] = LauncherLinkPreparation.start(launcher_link)
        held = _pending.get(root)
        if held is not None and (priority >= held or root == _running_root):
            return "already_running"
        _pending[root] = priority
        _ensure_worker()
        # Inside the lock: the worker drops a root from ``_pending`` only after
        # it has finished the item, so enqueueing here cannot race a removal
        # into a state where a queued root looks absent.
        _queue.put((priority, next(_sequence), root))
    return "started" if held is None else "promoted"


# ── the boot pass ────────────────────────────────────────────────────────────


def prewarm_chat_actors_on_boot() -> dict[str, int]:
    """Queue the operator's most recently active chats, up to the registry cap.

    Runs on ``serve``'s existing prewarm thread, AFTER the read-model build and
    the provider warmup (ordering doctrine: ``serve.py``). Third rather than
    first for two reasons — the launcher's canvas is waiting on the build, and
    an agent construction that runs after ``_load_openai_cls`` is far cheaper
    than one that pays the SDK import itself.

    ``max_hot_sessions`` is the cap and it is the registry's own: warming more
    chats than the registry can hold would evict the earliest warms before
    anyone used them. Most-recently-active first, because that is the order an
    operator is likely to reopen them in and the order eviction would preserve.

    Gated on ``hot_sessions_enabled`` and nothing else — see the note in
    :class:`agent_runtime.runtime_config.PersonaChatConfig` for why this pass
    does not get its own key.

    Returns the pass's counts (also emitted as
    :data:`CHAT_ACTOR_PREWARM_PASS_RECEIPT`); it never raises, because a warm
    that did not happen costs latency and never correctness.
    """

    started = time.monotonic()
    counts = {"candidates": 0, "queued": 0, "skipped": 0}
    try:
        from .config import load_root_runtime_config
        from .persona_chat_continuity import persona_chat_runtime_registry

        if persona_chat_runtime_registry() is None:
            return counts
        persona_chat_cfg = load_root_runtime_config().persona_chat
        roots = _boot_candidates(limit=max(1, int(persona_chat_cfg.max_hot_sessions)))
        counts["candidates"] = len(roots)
        for root in roots:
            if request_chat_actor_prewarm(root, priority=PRIORITY_BOOT) == "started":
                counts["queued"] += 1
            else:
                counts["skipped"] += 1
    except Exception:  # pragma: no cover - a boot must never die on a warmup
        logger.debug("chat-actor boot prewarm pass did not complete", exc_info=True)
        return counts
    logger.info(
        CHAT_ACTOR_PREWARM_PASS_RECEIPT,
        counts["candidates"],
        counts["queued"],
        counts["skipped"],
        int(max(0.0, time.monotonic() - started) * 1000),
    )
    return counts


def _boot_candidates(*, limit: int) -> list[str]:
    """Bound chat roots, most-recently-active first, capped at *limit*.

    Only an instance that HAS a bound chat root is a candidate: a placement with
    no ``default_chat_session_id`` has no root to key a resident actor on, and
    minting one here would be this module writing store state — which it does
    not do.

    Recency is ``updated_at``, the field every instance write stamps. Rows that
    carry none sort last rather than being dropped: an unsorted candidate is
    still a real chat, and a missing timestamp must not read as "never used".
    """

    from .persona_assignments import PersonaInstanceStore

    try:
        instances = list(PersonaInstanceStore().list_all())
    except Exception:
        return []
    dated: list[tuple[str, str]] = []
    undated: list[str] = []
    seen: set[str] = set()
    for instance in instances:
        root = str(getattr(instance, "default_chat_session_id", None) or "").strip()
        if not root or root in seen:
            continue
        seen.add(root)
        stamp = str(getattr(instance, "updated_at", "") or "").strip()
        if stamp:
            dated.append((stamp, root))
        else:
            undated.append(root)
    # ISO-8601 stamps sort lexicographically, newest last — hence the reverse.
    # ``sorted`` is stable, so equal stamps keep store order.
    ordered = [root for _, root in sorted(dated, key=lambda row: row[0], reverse=True)]
    return (ordered + undated)[:limit]


__all__ = [
    "CHAT_ACTOR_PREWARM_DONE_RECEIPT",
    "CHAT_ACTOR_PREWARM_PASS_RECEIPT",
    "OUTCOME_ALREADY_RESIDENT",
    "OUTCOME_PREEMPTED_BY_OPEN",
    "OUTCOME_REGISTRY_OFF",
    "OUTCOME_SKIPPED_CONSTRUCT_FAILED",
    "OUTCOME_SKIPPED_NO_CHAT_ROOT",
    "OUTCOME_SKIPPED_PERSONA_UNRESOLVED",
    "OUTCOME_SKIPPED_PROFILE_UNREADY",
    "OUTCOME_SKIPPED_TURN_ACTIVE",
    "OUTCOME_WARMED",
    "PRIORITY_BOOT",
    "PRIORITY_OPEN",
    "overlapping_constructions",
    "prewarm_chat_actor",
    "prewarm_chat_actors_on_boot",
    "record_construction",
    "request_chat_actor_prewarm",
    "reset_construction_spans_for_tests",
]


def _slot_receipt(instance: Any) -> dict[str, Any] | None:
    """An assigned instance's repo-slot receipt (build plan §3.3): the SAME receipt the turn
    folds, from the same loader, so an assigned chat matches its first turn instead of
    rebuilding on it. None without an assignment — exactly what an unassigned turn folds."""

    from .mission_chat_turn_context import DEFAULT_RESOLVERS, _workspace_context

    slot_context = DEFAULT_RESOLVERS.load_slot_context(instance)
    return None if slot_context is None else _workspace_context(DEFAULT_RESOLVERS, None, slot_context)[1]


def _prompt_surface_kwargs(persona: Any, instance: Any, root: str, lane_bundle: Any) -> dict[str, Any]:
    """The prompt-surface inputs the first turn passes, from the turn's own setters (h-prompt S1/S3/S6).

    The deferred tools, the persona's skills index and the instance-scoped prompt
    cache key -- each from the one helper the turn path uses, so the warmed actor's
    request matches the first turn's byte for byte."""

    from .cache_routing import persona_cache_scope_id
    from .chat_lane_skill_index import chat_lane_index_skills

    return {
        "chat_lane_defer_tools": list(lane_bundle.defer_tools),
        "cache_scope_id": persona_cache_scope_id(getattr(instance, "id", None), root),
        "chat_lane_index_skills": chat_lane_index_skills(persona, lane_bundle.operating_skills),
    }


def _first_turn_system_message(persona: Any, instance: Any) -> str:
    """The system message the first turn will pass, through the turn's own builder (h-turn1 A3).

    The prompt the prewarm builds from it is the one that turn adopts, and it adopts
    only on a byte-equal message -- so this is the turn's builder, never a copy."""

    from .persona_runtime import _mission_chat_surface_message

    return _mission_chat_surface_message(
        persona, "", workspace_agents_content=_workspace_agents_content(instance)
    )


def _workspace_agents_content(instance: Any) -> str | None:
    """The workspace content the turn folds into its system message, as the turn reads it.

    ``MissionChatTurnContext.workspace_agents_content`` under an assignment: the slot
    context's content. Without one the turn reads the launcher's per-turn
    ``--agents-file``, which this module never guesses (module docstring) -- None."""

    from .mission_chat_turn_context import DEFAULT_RESOLVERS

    slot_context = DEFAULT_RESOLVERS.load_slot_context(instance)
    return None if slot_context is None else (slot_context.content or None)


def _slot_primary(instance: Any) -> str | None:
    """The primary slot's bound path — workdir rung 2 under an assignment, as the turn resolves it."""

    from .mission_chat_turn_context import DEFAULT_RESOLVERS

    slot_context = DEFAULT_RESOLVERS.load_slot_context(instance)
    return None if slot_context is None else slot_context.primary_path
