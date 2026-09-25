"""``build_snapshot`` — consult the persisted core, coalesce concurrent builds,
build, persist.
"""

from __future__ import annotations

import copy
import time

from agent_runtime import core_cache, snapshot_build_ledger
from agent_runtime.resolution import runtime_resolution_scope

from agent_runtime.snapshot.receipts import (
    BUILD_ROLE_CACHE,
    BUILD_ROLE_LED,
    BUILD_ROLE_RODE,
    BUILD_ROLE_SHARED_NEXT,
    _BUILD_COALESCE,
    _build_coalesce_state,
)
from agent_runtime.snapshot.build_log import (
    _build_caller,
    _log_snapshot_build_core,
    _record_build_info,
)
from agent_runtime.snapshot.sections import _build_snapshot_in_runtime_scope
from agent_runtime.snapshot.details import persona_session_db_scope
from agent_runtime.snapshot.summaries import _maybe_reconcile_profile_personas

__all__ = [
    "_build_snapshot_uncoalesced",
    "build_snapshot",
]


def build_snapshot(
    agent_store=None,
    event_log=None,
    prompt_skills_catalogs=None,
    *,
    accept_inflight: bool = False,
    build_info: dict | None = None,
) -> dict:
    """Build the read-model core, coalescing concurrent builds (see above).

    ``accept_inflight`` opts a caller into sharing the build that is ALREADY
    running rather than waiting for the next one. It is not a freshness
    shortcut and must only be used where the payload carries its own
    watermark and the consumer replays everything after it — the stream
    hydrate is the one such caller (``agent_runtime.stream.hydrate_frame``):
    its ``watermark.event_offset`` comes from the snapshot itself and the
    stream loop tails events from exactly that offset, so a core built one
    build-duration earlier loses no event, it only delays it to the first
    delta frame. Without this opt-in, a background prewarm build and the
    hydrate that arrives moments later would cost TWO sequential builds
    (strict coalescing makes the second caller wait for the first AND then
    lead its own) — worse than no prewarm at all.

    ``build_info`` is one dict used in both directions, and the asymmetry is the
    point. IN: the caller may pre-seed ``{"caller": "hub"|"cli"|"prewarm"|…}``,
    the one fact the builder cannot derive. OUT: the builder fills ``role``
    (:data:`BUILD_ROLE_LED` / :data:`BUILD_ROLE_RODE` /
    :data:`BUILD_ROLE_SHARED_NEXT`), ``caller``, ``generation`` and ``build_ms``,
    so the caller can say which of those three things happened to IT rather than
    logging a wait that reads like a build. Pure out-param otherwise: the return
    value and the coalesce behaviour are untouched by its presence, and a caller
    that passes nothing gets today's function exactly.

    **The persisted core (EG-3.1).** On the default-store path, while this
    process has not yet completed a build of its own, the ~20 s reconstruction is
    replaced by VALIDATION: :func:`agent_runtime.core_cache.first_core` stats
    every build input and, when nothing moved since the persisted core was
    written, hands that core back labeled ``core_source=cache``. Every
    successful default-store build writes the core back. Callers see the same
    shape either way; ``build_info["role"]`` says which happened
    (:data:`BUILD_ROLE_CACHE`).
    """

    caller = _build_caller(build_info)
    custom_stores = any(value is not None for value in (agent_store, event_log))
    if custom_stores or prompt_skills_catalogs is not None:
        # Injected stores (tests, doctors) must observe exactly their own
        # fixtures — never a coalesced result built from the default stores.
        # A detail-fetch catalog capture likewise needs the exact build's
        # transient bodies; the shared result intentionally contains hashes
        # only, so it cannot satisfy that internal projection request.
        injected = _build_snapshot_uncoalesced(
            agent_store=agent_store,
            event_log=event_log,
            prompt_skills_catalogs=prompt_skills_catalogs,
        )
        # An injected-store build leads its own by definition (it never touched
        # the coalescer), so the role is honest — but it has no generation in
        # the default path's sequence and it emits no receipt line: see
        # ``_log_snapshot_build_core`` for why a fixture must not print one.
        _record_build_info(
            build_info,
            role=BUILD_ROLE_LED,
            caller=caller,
            generation=None,
            snapshot=injected,
        )
        return injected
    # Profile discovery is a bounded write-side admission step, not a projection
    # guessed by Launcher. Run it before the persisted-core fingerprint so a
    # newly promoted Persona invalidates that cache in this very request.
    # Injected-store builds above remain read-only fixture projections.
    _maybe_reconcile_profile_personas()
    # The persisted core is consulted BEFORE the coalescer, deliberately. A
    # fingerprint check is ~50 ms of stat work with no shared state; putting it
    # behind the build lock would serialize the cheap answer behind whatever
    # expensive build happens to be running, which is the opposite of the point.
    decision = core_cache.consult(caller=caller)
    if decision.core is not None:
        cached = decision.core
        _record_build_info(
            build_info,
            role=BUILD_ROLE_CACHE,
            caller=caller,
            generation=None,
            snapshot=cached,
        )
        # The shadow-validation window (EG-3.1): a cache-hit boot also runs the
        # full build in the background and compares field-for-field, so an
        # input-closure gap surfaces as a receipt in the field instead of a
        # silently stale canvas. At most once per process, on a daemon thread,
        # and it is marked as a shadow so completing it does not close the lane.
        core_cache.maybe_start_shadow_validation(
            cached,
            caller=caller,
            build=lambda: _build_snapshot_uncoalesced(),
        )
        return cached
    state = _build_coalesce_state
    with _BUILD_COALESCE:
        # The first build STARTED at/after arrival is the one that satisfies
        # this caller; an in-flight build began earlier and may miss writes
        # this caller has already observed. ``accept_inflight`` callers opt out
        # of that guarantee (see the docstring) and join the running build —
        # only the RUNNING one: while ``running`` is true ``done`` is strictly
        # behind ``started``, so this can never hand back a finished build's
        # leftover result.
        rode_inflight = bool(accept_inflight and state["running"])
        target = state["started"] + (0 if rode_inflight else 1)
        while True:
            if state["done"] >= target and state["result"] is not None:
                payload = copy.deepcopy(state["result"])
                if state["waiters"] == 0:
                    state["result"] = None
                # Two different things end here and they are NOT the same
                # attribution: a caller that opted into the build already
                # running (``rode``) and a caller that waited for a build
                # started after it arrived and got somebody else's copy of it
                # (``shared_next``). ``rode_inflight`` is read at ARRIVAL, above,
                # because by now the build it named has finished and the state
                # can no longer answer which one this caller asked for.
                _record_build_info(
                    build_info,
                    role=BUILD_ROLE_RODE if rode_inflight else BUILD_ROLE_SHARED_NEXT,
                    caller=caller,
                    generation=target,
                    snapshot=payload,
                )
                return payload
            if not state["running"]:
                state["running"] = True
                state["started"] += 1
                generation = state["started"]
                break
            state["waiters"] += 1
            _BUILD_COALESCE.wait()
            state["waiters"] -= 1
    result = None
    # Stage 4 attribution (chat-turn latency): the LEADER's span, on the same
    # monotonic clock a chat turn anchors on, so "did a build overlap this
    # turn?" is a counted fact instead of a log correlation. Only the leader —
    # a rider paid a wait, not a build, and recording both would double every
    # coalesced build. See ``agent_runtime.snapshot_build_ledger``.
    build_span_started = time.monotonic()
    try:
        # PRE-build, deliberately: a stat set taken after the build would absorb
        # any write that landed while the build ran, and the next process would
        # then serve a core missing that write as authoritative. See
        # ``core_cache.write_back``'s docstring for the full direction argument.
        #
        # ``pre_build_fingerprint`` rather than a second ``build_input_fingerprint``
        # call: this leader's own consult walked the same store milliseconds ago,
        # and reusing that key stays on the safe side of the direction above (an
        # OLDER key can only cost the next process a rebuild). It falls through to
        # a full walk whenever no consult stands — a cold store, a disarmed lane,
        # or a persisted pair that moved since.
        pre_build_fingerprint = core_cache.pre_build_fingerprint()
        result = _build_snapshot_uncoalesced()
        if decision.demoted:
            # A persisted core WAS available and was rejected, so this core has a
            # provenance question to answer: it is the rebuild that replaced it.
            # A build with no persisted core to decide between stamps nothing —
            # see ``core_cache.label_core`` for why that keeps the goldens still.
            core_cache.label_core(
                result, source=core_cache.CORE_SOURCE_REBUILT, stale=False
            )
        _record_build_info(
            build_info,
            role=BUILD_ROLE_LED,
            caller=caller,
            generation=generation,
            snapshot=result,
        )
        # The build's OWN line, on the thread that paid for it, before the
        # waiters are notified below — so the receipt for a build always
        # precedes the wait lines of the callers that rode it, in the order an
        # operator reads the log. A build that raised logs nothing: there is no
        # envelope to read the cost off, and the exception is the receipt.
        _log_snapshot_build_core(
            caller=caller, generation=generation, snapshot=result
        )
        # EG-3.1's write half: EVERY successful default-store build persists the
        # core it just produced, plus the sidecar that says which inputs it was
        # built from. Not only boot builds — a process that built once and never
        # wrote back would leave the NEXT process paying the full 20 s for state
        # this one already has in hand, which is how ``snapshot.json`` came to be
        # two days stale on the live store.
        #
        # Best effort by contract (a failed write logs and changes nothing here),
        # and it happens AFTER the receipt so the build's own line is never
        # delayed behind an I/O stall.
        core_cache.write_back(result, fingerprint=pre_build_fingerprint)
        # The process now owns its own truth: the cache lane closes, and every
        # later build in this process is an ordinary build.
        core_cache.note_full_build_completed()
        return result
    finally:
        # Recorded even when the build RAISED: it occupied this process for the
        # span either way, and a turn that overlapped it paid the same price.
        snapshot_build_ledger.record_build(
            started=build_span_started, ended=time.monotonic()
        )
        with _BUILD_COALESCE:
            state["running"] = False
            if result is not None:
                state["done"] = generation
                state["result"] = None
                if state["waiters"]:
                    try:
                        state["result"] = copy.deepcopy(result)
                    except Exception:
                        # Uncopyable core: waiters fall back to building
                        # their own — never raise from finally (it would
                        # replace the builder's own return value).
                        state["result"] = None
            _BUILD_COALESCE.notify_all()


def _build_snapshot_uncoalesced(
    agent_store=None,
    event_log=None,
    prompt_skills_catalogs=None,
) -> dict:
    # The chat SessionDB is acquired HERE, by the build's outermost frame, so
    # that one owner opens it and the same owner closes it (MCF-27). It sits
    # INSIDE ``runtime_resolution_scope`` because the acquisition resolves its
    # scope from the runtime this build resolved, exactly as it did when the
    # binding lived in the section below.
    with runtime_resolution_scope(), persona_session_db_scope() as session_db:
        return _build_snapshot_in_runtime_scope(
            agent_store=agent_store,
            event_log=event_log,
            prompt_skills_catalogs=prompt_skills_catalogs,
            session_db=session_db,
        )
