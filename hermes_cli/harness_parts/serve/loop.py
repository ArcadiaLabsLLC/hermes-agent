"""``serve_loop`` — the dispatch loop over explicit streams.
"""

from __future__ import annotations

import inspect
import json
import os
import sys
import threading
import time
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any, Callable, TextIO

from hermes_cli.harness_parts.serve.constants import (
    DEFAULT_DRAIN_DEADLINE_SECONDS,
    DEFAULT_POOL_SIZE,
    DRAINING_EXIT_CODE,
    DRAIN_TIMEOUT_EXIT_CODE,
    FINGERPRINT_HOME_BOOT_SITE,
    SERVE_SCHEMA_VERSION,
    _CACHEABLE_ARGV,
    _DRAIN_ABANDON_GRACE_SECONDS,
    _DRAIN_DEADLINE_FLOOR_SECONDS,
    _DRAIN_EXIT_DEADLINE_SECONDS,
    _DRAIN_POLL_INTERVAL_SECONDS,
    _DRAIN_PROGRESS_INTERVAL_SECONDS,
    _DRAIN_SOCKET_MINIMUM_DEADLINE_SECONDS,
    _READ_CACHE_MAX_AGE_SECONDS,
    _REQUEST_SILENCE_SECONDS,
    _SERVICE_PARK_POLL_SECONDS,
)
from hermes_cli.harness_parts.serve.manifest import (
    _is_gateway,
    _pairing_block,
    ops_manifest,
)
from hermes_cli.harness_parts.serve.gateway_listener import (
    gateway_block_when_no_listener,
    start_gateway_listener,
)
from hermes_cli.harness_parts.serve.end_reason import (
    _ServeEndReason,
    _install_console_ctrl_reason_handler,
    _install_service_stop_signal,
    _install_signal_reason_handlers,
    _restore_service_stop_signal,
)
from hermes_cli.harness_parts.serve.boot import (
    _annotate_import_tax,
    _maybe_inject_boot_fault,
    _repoint_logging_root_stderr,
    _runtime_state_fingerprint,
)
from hermes_cli.harness_parts.serve.frames import (
    _FrameWriter,
    _LineFrameProxy,
    _PollResponseCache,
    _SafeSink,
    _emit_deferred_reply,
    _request_id,
    _request_sink,
)
from hermes_cli.harness_parts.serve.argv_lane import (
    ArgvRootUnsupported,
    HandlerExit,
    _ArgvRequest,
    _clean_argv_root,
    _system_exit_code,
    dispatch_argv,
)
from hermes_cli.harness_parts.serve.drain import (
    _DrainState,
    _drain_deadline_seconds,
)

__layer__ = "lanes"

__all__ = [
    "serve_loop",
]


def serve_loop(
    reader: TextIO,
    writer: TextIO,
    *,
    pool_size: int = DEFAULT_POOL_SIZE,
    dispatch: Callable[[list[str]], int] = dispatch_argv,
    fingerprint: Callable[[], tuple | None] = _runtime_state_fingerprint,
    read_cache_max_age: float = _READ_CACHE_MAX_AGE_SECONDS,
    liveness_pump_interval_seconds: float = 5.0,
    boot_timeline: Any = None,
    snapshot_prewarm: Callable[[], None] | None = None,
    provider_prewarm: Callable[[], None] | None = None,
    actor_prewarm: Callable[[], None] | None = None,
    root_anchor: Callable[[], Any] | None = None,
    skill_install: Callable[[], str] | None = None,
    drain_deadline_seconds: float = DEFAULT_DRAIN_DEADLINE_SECONDS,
    drain_socket_minimum_deadline_seconds: float = (
        _DRAIN_SOCKET_MINIMUM_DEADLINE_SECONDS
    ),
    drain_poll_interval_seconds: float = _DRAIN_POLL_INTERVAL_SECONDS,
    drain_wakeup: Callable[[], None] | None = None,
    hard_exit: Callable[[int], None] | None = None,
    socket_lane: bool = False,
    service: bool = False,
    record_end_reason: bool = False,
    stream_source_factory: Callable[[], Any] | None = None,
    stream_buffer_limit: int | None = None,
    stream_byte_limit: int | None = None,
) -> int:
    """Core dispatch loop over explicit streams. stdio is transport #1; the
    localhost socket is transport #2, and both feed THIS dispatcher.

    ``socket_lane`` is injected and OFF by default — the same contract as
    ``root_anchor`` and ``hard_exit`` — so every pre-socket test observes the
    byte-identical stdio loop, and a caller that wants the durable service says
    so explicitly. When it is on, this loop races for the per-root socket lock,
    binds an ephemeral loopback port before ``ready`` (so the ready frame and
    the registry entry can both carry it), and starts accepting only after the
    request pool exists.

    ``service`` is L-h: the runtime's lifetime stops being the stdin's. OFF by
    default and injected like every other lever here, so a serve that nobody
    asked to outlive its starter behaves exactly as it always has — stdin EOF
    ends everything, byte for byte.

    With it ON, EOF means one thing only: **the starter detached.** The loop
    logs ``stdio_owner_detached``, swaps the stdio frame sink for a null sink
    (the pipe has no reader left, and a service must not die of its observer
    leaving), keeps BOTH socket lanes serving, and parks the main thread on a
    stop event. Three things set that event and nothing else does: a
    ``{"op":"drain","force":true}`` over the socket (the operator's restart
    verb, from outside), ``SIGTERM`` where the platform delivers one, and — the
    unchanged case — a stdio ``shutdown`` received BEFORE EOF, which never
    reaches the park at all. When the park ends, the finalization below runs
    exactly as it does for a stdio EOF: pool shutdown, terminal frame,
    ``_close_socket_lane``, ``_unregister_instance``, the same exit codes.

    ``record_end_reason`` is RL-16, and takes the SAME injection contract as
    ``root_anchor`` and ``skill_install`` for a sharper version of their reason:
    turning it on registers an ``atexit`` hook, a Windows console control
    handler and ``SIGTERM``/``SIGHUP`` dispositions ON THE HOST PROCESS. In a
    ``serve_loop`` unit test the host process is pytest — which would then
    acquire a serve's signal handlers and write a sidecar into a long-deleted
    ``tmp_path`` at interpreter exit. So the mechanism is OFF here and ON in
    ``_cmd_serve``, where the host process really is the runtime; the reasons
    themselves are proven against spawned children
    (``test_serve_ended_sidecar_child_e2e.py``), which is the only honest seam
    for "what happens when this process is killed" anyway.

    ``stream_source_factory`` is the shared subscription producer, likewise
    injectable: the default builds the real ``agent_runtime.stream``
    generator, and a test hands over a finite fake so a subscription test costs
    milliseconds instead of a projection build.

    ``drain_wakeup`` and ``hard_exit`` are the two process-level levers the
    drain needs and a unit test must not be given: the first unblocks a reader
    parked on an idle pipe once the drain has finished (the real entry point
    closes the protocol descriptor), the second takes the process down when
    in-flight work outlived the deadline. The timeout case CANNOT be a plain
    return: ``concurrent.futures`` registers an atexit hook that JOINS every
    worker thread, so an interpreter carrying a stuck worker hangs on the way
    out — which is the same "forever" the deadline exists to bound. Both are
    injected and OFF by default, the same contract as ``snapshot_prewarm`` and
    ``root_anchor``, so ``serve_loop``'s own tests observe the frames and the
    return code without ever exiting the test process.

    ``boot_timeline`` is the caller's already-running :class:`BootTimeline`
    (``_cmd_serve`` starts one at the process's first hermes instruction, so
    ``interpreter_ms`` covers the import tax); the loop starts its own when a
    caller supplies none. ``snapshot_prewarm`` is the post-``ready`` warmup
    policy — injected, and OFF unless the real entry point turns it on, so the
    loop's own unit tests never fire a multi-second projection build.

    ``provider_prewarm`` is the chat turn's one-time costs (lazy OpenAI SDK
    import, SSL context / CA verification, tool-definition registry) and takes
    the SAME injection contract for the same reason — it was an unconditional
    ``Thread.start()`` in this loop, which meant every unit test of the loop
    imported the OpenAI SDK. It runs on the snapshot prewarm's thread, after it
    (EG-3.2); see the comment at the thread start below for why the ordering is
    the whole stage.

    ``actor_prewarm`` is the persona-chat resident-actor pass and rides the same
    thread THIRD, on the same injection contract: it queues real agent
    constructions, so a loop unit test must never fire it by default.

    ``skill_install`` re-joins the runtime's installed canonical skill packages
    to this repo's copies (:func:`install_harness_skills_at_boot`) and takes the
    SAME injection contract as ``root_anchor``, for the same reason and with more
    at stake: it WRITES into the machine-global ``get_shared_skills_dir()``, so a
    loop unit test that fired it by default would edit the operator's live
    runtime. On, therefore, only where the real entry point turns it on. It runs
    SYNCHRONOUSLY and before the pool exists — the whole point is that no request
    is ever dispatched against a stale package — and it is bounded work (a hash
    per canonical package; ``install_harness_skill`` writes nothing when they
    match), unlike the prewarms it sits beside.
    """

    from agent_runtime.boot_timeline import BootTimeline

    timeline = boot_timeline if boot_timeline is not None else BootTimeline()
    _annotate_import_tax(timeline)
    frames = _FrameWriter(writer, detachable=service)
    # Emitted before ANY heavy boot work (the agent_runtime import, root
    # config load, registry init, and the pre-ready orphan sweep below): a
    # supervising launcher can tell a live cold boot from a wedged child by
    # this frame alone. A cold-cache boot can run past any short watchdog
    # before ``ready``; killing it mid-boot respawns into another cold boot
    # forever (2026-07-26 launcher kill-loop incident). Consumers that
    # predate this frame ignore unknown events, so it is purely additive.
    #
    # ``boot``: the self-attributing cold-boot stamp (T9). A >25s cold boot has
    # been recorded and is not reproducible on demand (the OS file cache is
    # warm on any machine that just ran the launcher), so the boot measures
    # itself instead: ``interpreter_ms`` here is the interpreter + hermes CLI
    # import tax the supervisor can see NO other way, and the ``ready`` frame
    # below carries the per-phase breakdown of everything after it.
    frames.emit(
        {
            "event": "booting",
            "pid": os.getpid(),
            "schema_version": SERVE_SCHEMA_VERSION,
            "boot": timeline.stamps(),
        }
    )
    # ── The fingerprint home, captured HERE and nowhere later (HC-1) ─────────
    #
    # WHY THIS INSTANT, named against what is on either side of it.
    #
    # BEFORE: process creation, the interpreter + hermes import tax, and
    # ``hermes_cli.main._apply_profile_override`` — which is where HERMES_HOME
    # is resolved from --profile / the active-profile marker, at main's MODULE
    # import, long before this command was dispatched. HERMES_HEAD_HOME is the
    # launcher's spawn env and is likewise fixed by now. So the two authorities
    # ``get_hermes_head_home`` reads are already final at this line; there is no
    # earlier point in this process where they are BOTH valid.
    #
    # AFTER: everything that could take a fingerprint, and everything that could
    # install a context-local home override. Specifically — the root runtime
    # config load, the chat-session registry, the chat-head publish, the root
    # anchor, the store-root resolve, the service foundations, the orphaned-turn
    # and dispatch sweeps, the ready frame, the prewarm thread (whose first act
    # is a full read-model build), and every dispatched request after it. A
    # persona scope can only exist inside one of those, so a capture here cannot
    # be taken under one.
    #
    # THE DEFECT THIS RETIRES. ``resolved_fingerprint_home`` is capture-once but
    # was LAZY, so the capture instant was whichever build or consult won the
    # race — and on a persona turn that is a thread with
    # ``persona_profile_context``'s override live. The install this runs on has
    # ONE profile and still demoted ``reason=home_mismatch`` on three callers in
    # a single boot, twice (2026-08-21 16:04:32, 2026-08-22 13:36), each time
    # followed by a cold 7.6s build.
    #
    # COST, measured rather than assumed: importing ``core_cache`` here is 93ms
    # cold, of which ~90ms is its dependency set (paths, dispatch_delivery,
    # parity, serve_auth, serve_registry, serve_socket) — every one of which the
    # boot below imports anyway, before ``ready``. The module itself is 2.5ms.
    # This moves the import earlier; it does not add it.
    #
    # The declaration is a SEPARATE call on purpose — see
    # ``core_cache.declare_fingerprint_home_boot_site``. It is what makes a boot
    # that stops capturing SAY so, instead of silently going back to lazy.
    from agent_runtime import core_cache as _core_cache

    _core_cache.declare_fingerprint_home_boot_site(FINGERPRINT_HOME_BOOT_SITE)
    _core_cache.capture_fingerprint_home()
    # THIS SERVE'S OWN HERMES HOME, captured at the same instant and for the
    # same reason — and then handed to every argv request below (see ``_run``).
    #
    # The fingerprint capture above protects the snapshot cache's closure from a
    # concurrent persona scope. This protects the REQUESTS. Same mechanism, same
    # boot instant, different victim, and it is worth stating why one capture
    # cannot serve both: ``capture_fingerprint_home`` resolves through
    # ``get_hermes_head_home()`` and reports whether that answer was
    # authoritative, because a cache key must know when its home is a guess. A
    # request does not want the head — under an operator-supplied
    # ``HERMES_HEAD_HOME`` (the launcher sets it so the Mission Control
    # transcript store stays put while ``HERMES_HOME`` selects a profile) the
    # head and the runtime home are DIFFERENT directories on purpose, and an
    # argv request belongs to the runtime one. So this reads ``get_hermes_home``
    # directly.
    #
    # WHAT IT FIXES (measured 2026-08-27, operator's screen). This process is
    # booted onto one home and then runs ``persona_chat_actor_prewarm`` over
    # every placed persona; each warm binds ``persona_profile_context`` with the
    # ``os.environ`` mirror ON — necessarily, because a spawned MCP server and a
    # raw-env in-process plugin have no other channel. On the incident boot that
    # was four instances on the profile ``launcher-qa``, 20:56:06-20:56:14, the
    # first bind held 11.25 s. For that whole span every pool worker without a
    # binding of its own resolved ``get_hermes_home()`` to ``launcher-qa``:
    # ``harness characters status --draft 20260827-150945-7ba0cb`` read
    # ``profiles\launcher-qa\characters\.drafts`` and reported a base-authored
    # draft as nonexistent.
    #
    # Captured, never re-read per request: at this instant no persona scope can
    # exist in the process (the anchor, the store-root resolve, the sweeps, the
    # ready frame and the prewarm thread all come after), whereas a read at
    # request entry would inherit a flip that was already live — which is half
    # the field cases.
    from hermes_constants import get_hermes_home as _get_hermes_home

    serve_request_home = _get_hermes_home()
    # The METHOD lane's registry + its manifest. Imported here rather than at
    # module scope for the same reason as everything else in this function —
    # nothing agent_runtime-shaped is paid for before ``booting`` is out — and
    # it is cheap: ``serve_rpc`` imports only stdlib, and each method reaches
    # for its stores function-locally when it is actually called.
    from agent_runtime import serve_rpc

    # The one function that turns a live connection into an authorization
    # identity (chokepoint plan A2). Beside ``serve_rpc`` because it is the same
    # lane and the same stdlib-only cost.
    from agent_runtime.call_authorization import caller_for_connection

    from agent_runtime.persona_chat_continuity import (
        initialize_persona_chat_runtime_registry,
    )
    from agent_runtime.config import load_root_runtime_config

    persona_chat_cfg = load_root_runtime_config().persona_chat
    initialize_persona_chat_runtime_registry(
        enabled=persona_chat_cfg.hot_sessions_enabled,
        max_entries=persona_chat_cfg.max_hot_sessions,
        ttl_seconds=persona_chat_cfg.idle_ttl_seconds,
    )
    timeline.mark("chat_registry_ms")
    # Publish this process's EXPLICIT chat head home into the shared runtime
    # store root — the ONE writer of that pointer. The Launcher always starts
    # serve with HERMES_HEAD_HOME; a plain CLI turn started later names no head
    # and, without the pointer, degrades to its own profile database, minting
    # the transcript where the cockpit never looks while writing the binding
    # into the shared store (the 2026-07-27 read-lane gap). No-op when this
    # process named no head of its own, and best effort by contract.
    from agent_runtime.chat_session_scope import publish_chat_head_home

    publish_chat_head_home()
    timeline.mark("head_publish_ms")
    # Publish the machine root anchor: `agent_runtime.store_root` into the
    # PLATFORM DEFAULT home's config.yaml, so a later ambient process (no
    # HERMES_HOME, no HERMES_AGENT_RUNTIME_ROOT) resolves this serve's real
    # runtime root — and therefore finds the chat-head pointer above — instead
    # of the %LOCALAPPDATA% shadow runtime (the 2026-08-12 ambient
    # chat-history incident: `ok: true, count: 0` from the wrong root).
    # Injected and OFF unless the real entry point turns it on — the same
    # contract as ``snapshot_prewarm`` — so the loop's unit tests can never
    # write the machine-global config. Best effort by contract, but ACCOUNTED:
    # the typed outcome is emitted as its own frame either way, because a
    # silent skip here is exactly the false-all-clear class the anchor
    # retires. Consumers that predate this frame ignore unknown events.
    #
    # Since 2026-08-13 the same call also DECLARES `agent_runtime.head_home`
    # when this serve was started with an explicit head, and the frame carries
    # that outcome additively under `head`. That is the runtime declaring its
    # own identity: the Launcher's `HERMES_HEAD_HOME` pin demotes from sole
    # authority to an override plus a consistency check, and the launcher
    # compares its pin against this frame (a disagreement is a durable
    # `root_declaration_mismatch` transport receipt, never a silent divergence).
    if root_anchor is not None:
        try:
            anchor_report = root_anchor()
            anchor_frame = {"event": "root_anchor", **anchor_report.payload()}
        except Exception as exc:  # must never take the boot down
            anchor_frame = {
                "event": "root_anchor",
                "outcome": "unwritable",
                "detail": type(exc).__name__,
            }
        frames.emit(anchor_frame)
    timeline.mark("root_anchor_ms")
    # ── The installed-skill join, at the moment a CONSUMER acquires drift ─────
    #
    # See :func:`install_harness_skills_at_boot` for what it repairs and why the
    # pre-push hook was the wrong trigger for it. Three things about the PLACE:
    #
    # * AFTER ``booting``, so the frame a supervising launcher uses to tell a
    #   live cold boot from a wedged child is already out. Nothing goes in front
    #   of that frame (2026-07-26 kill-loop incident, above);
    # * AFTER the root anchor, which is the call that declares this machine's
    #   ``agent_runtime.head_home``. The install destination derives from the
    #   resolved hermes home, so the declaration that names it is published
    #   first — the same ordering the verify script's resolution ladder assumes;
    # * BEFORE the stdout/stderr swap on the line below. ``sys.stderr`` is still
    #   the inherited descriptor here — the serve log lane — so the summary
    #   CANNOT reach the NDJSON stdout bridge even by accident. That is the
    #   stdout discipline made structural instead of careful.
    #
    # Loud, never fatal: a chat runtime that refuses to boot because a package
    # would not copy is worse than one that boots carrying a stale package and
    # says so, and the next boot retries for free.
    if skill_install is not None:
        try:
            print(skill_install(), file=sys.stderr, flush=True)
        except Exception as exc:
            print(
                f"harness serve: skill install FAILED — {type(exc).__name__}: {exc}"
                " (booting anyway; the installed packages may be stale)",
                file=sys.stderr,
                flush=True,
            )
    timeline.mark("skill_install_ms")
    stdout_proxy = _LineFrameProxy(frames, "line")
    stderr_proxy = _LineFrameProxy(frames, "stderr")
    read_cache = _PollResponseCache(read_cache_max_age)
    from agent_runtime.snapshot import SnapshotBuildContext

    read_build_context = SnapshotBuildContext()

    inflight: dict[str, _ArgvRequest] = {}
    # Futures by request id so ``{"op":"cancel"}`` can drop work that is
    # still queued behind the pool. A running request is uninterruptible —
    # cancel() then returns False and the client is told the side effect may
    # still land.
    inflight_futures: dict[str, Future] = {}
    inflight_lock = threading.Lock()

    # Drain state. ``None`` until a `drain` op arrives; from then on it is the
    # single answer to "are we still accepting work", read by the request path
    # and written once by the op.
    drain_state: _DrainState | None = None
    drain_exit_code = 0
    drain_finished = threading.Event()
    #: Latched the instant a drain DECIDES how it ended, before it publishes
    #: anything. A drain has exactly one terminal frame: without this latch a
    #: mid-drain EOF could publish ``drain_abandoned`` after a completed drain
    #: had already published ``drain_complete``, telling a supervisor that a
    #: successful restart gave up — and exiting 3 on it.
    drain_terminal_published = threading.Event()
    drain_terminal_lock = threading.Lock()
    reader_unwound = threading.Event()
    pool_shutdown_wait = True
    boot_id = uuid.uuid4().hex
    #: WHO started this runtime, read NOW and never again. In service mode the
    #: whole point is that the starter goes away, and a parent read after that
    #: names the reaper/init that adopted us — a different process, and on
    #: Windows often no process at all. Published on the greeting frames and the
    #: registry row so an attaching client can tell "the launcher I am running
    #: in started this" from "this was already here", which is the difference
    #: between RL-4's ``started by this launcher`` and ``attached``.
    starter_pid: int | None
    try:
        starter_pid = int(os.getppid())
    except Exception:  # pragma: no cover - os.getppid exists everywhere we run
        starter_pid = None
    #: The service park's only wakeup. Set by the drain's terminal path, by
    #: SIGTERM where the platform delivers one, and by nothing else.
    service_stop = threading.Event()
    #: RL-16's recorder, armed below once the store root is known AND the caller
    #: asked for it. ``None`` until then — and forever, in every ``serve_loop``
    #: unit test — which is why every use goes through the two shims beside it
    #: rather than through the attribute.
    end_reason: Any = None
    #: RL-19's file handle, opened below for the ``--service`` arm only and
    #: ``None`` in every other serve and every unit test. Held as a name because
    #: the uncaught arm at the bottom of this function writes the one thing the
    #: rest of the wiring cannot deliver — see there.
    service_stderr_log: Any = None

    def _note_end(reason: str) -> None:
        """Latch WHY this runtime is ending. Inert when unarmed; never raises."""

        if end_reason is not None:
            end_reason.note(reason)

    def _write_end(reason: str | None = None) -> None:
        """Put the record on disk NOW, for a path that will not reach ``atexit``.

        The drain's exit is ``os._exit``; a signal handler's is the OS. Both run
        no interpreter shutdown at all, so the fallback hook is not a fallback
        for them.
        """

        if end_reason is not None:
            end_reason.write(reason)

    # ── socket lane state (all None unless ``socket_lane`` is on AND this
    # serve wins the per-root ownership lock) ────────────────────────────────
    socket_server: Any = None
    socket_lock: Any = None
    #: The SECOND listener (remote-gateway Stage 1). ``None`` unless
    #: ``remote_gateway.listen`` names an interface AND this serve owns the
    #: loopback lane — the gateway lane is not a separate ownership question, it
    #: is the same dispatcher answering on a second door, so a serve that lost
    #: the per-root lock must not open one either. It shares the loopback lane's
    #: lock, its pool, its stream hub and its drain; what it does not share is
    #: the credential (per device, not per root) and the encryption (TLS).
    gateway_server: Any = None
    #: The ONE stream producer, built on the first ``subscribe`` and stopped
    #: when the last subscriber leaves. Never per client: a delta batch rebuilds
    #: a full snapshot core, so N generators would cost N of them.
    stream_hub: Any = None
    #: ONE lock over all three lane handles above. They used to be swapped by
    #: bare ``nonlocal`` assignment from the drain path, the shutdown path, and
    #: the EOF path — three threads racing an unsynchronised read-modify-write
    #: on the objects whose whole job is to be released exactly once. Held for
    #: the SWAP only, never across a join: the point is that two closers cannot
    #: both take the same handle, not that teardown is serialised.
    lane_lock = threading.Lock()
    #: Per-subscriber patch-fold declarations: connection key → the entity
    #: classes that client said it can fold, or None when it said nothing (which
    #: is NOT the empty set — see ``patch_coverage.HISTORICAL_FOLD_ENTITIES``).
    #: Guarded by ``lane_lock`` because the producer thread reads it while a
    #: request thread is writing it. The producer is SHARED, so what it may
    #: promote is the INTERSECTION over this table, not any one client's answer.
    stream_fold_entities: dict[str, Any] = {}

    def _busy_frame() -> dict[str, Any]:
        with inflight_lock:
            pending = len(inflight)
            chat_turns = sum(1 for item in inflight.values() if item.is_chat_turn)
            long_runs = sum(1 for item in inflight.values() if item.is_long_run)
            subscriptions = sum(
                1 for item in inflight.values() if item.is_runtime_stream
            )
        # ``long_runs`` and ``subscriptions``/``work`` are ADDITIVE.
        # ``chat_turns`` and ``pending`` keep their exact meanings and their
        # exact names because the launcher decodes them by those names
        # (`mission_control_serve_session_io.dart`, the `busy` case →
        # `MissionServeBusySignal.chatTurns`), and a supervisor that learned to
        # read a renamed key would be a supervisor that stopped reading the old
        # one mid-upgrade.
        #
        # ``subscriptions`` counts the STANDING requests — `harness stream`,
        # infinite by design, which the launcher holds two of for the life of
        # the attachment. ``work`` is everything else. The distinction is not
        # cosmetic: an attached launcher used to make an IDLE runtime answer
        # `pending: 2` forever (measured 2026-09-05), so `pending > 0` — the
        # only "is it working?" test the frame offered — was true on a service
        # doing nothing at all. ``work`` is the number that goes back to zero,
        # and it is what the liveness pump keys on.
        return {
            "event": "busy",
            "chat_turns": chat_turns,
            "long_runs": long_runs,
            "pending": pending,
            "subscriptions": subscriptions,
            "work": pending - subscriptions,
        }

    def _report_quiet_requests(pending: list[_ArgvRequest]) -> None:
        """Describe every request that has gone quiet, to the lane that asked.

        ``busy`` says the SERVICE is alive and carries a count. It cannot
        answer the question a waiting client actually has, which is about ONE
        request: has mine started, or is it behind the pool? This does, by id,
        on that request's own sink — so the answer arrives on the connection
        that is waiting for it rather than on stdout, where a socket client
        cannot see it.

        The budget is read from the module on every lap, so a test lowers it.

        ``harness stream`` is deliberately excluded: it is the infinite
        subscription, it is silent between events BY DESIGN, and it has the
        stream lane's own liveness. Everything else that produces nothing for
        this long is a fact an operator wants.
        """

        budget = max(0.0, float(_REQUEST_SILENCE_SECONDS))
        now = time.monotonic()
        depth = len(pending)
        for request in pending:
            if request.is_runtime_stream:
                continue
            waited = now - request.submitted_monotonic
            if waited < budget:
                continue
            last = request.progress_monotonic
            if last is not None and (now - last) < budget:
                continue
            request.progress_monotonic = now
            started = request.started_monotonic
            frame = {
                "id": request.rid,
                "event": "request_progress",
                # The one field that matters. "queued" means no handler code
                # has run, so nothing has been mutated and a retry is free;
                # "running" means side effects may already have landed.
                "state": "running" if started is not None else "queued",
                "waited_ms": int(waited * 1000),
                "running_ms": (
                    0 if started is None else int((now - started) * 1000)
                ),
                "pending": depth,
                "pool_size": pool_size,
            }
            target = request.sink if request.sink is not None else frames
            try:
                target.emit(frame)
            except Exception:
                # Same contract as the pump that calls this: telemetry must
                # never take down the loop it describes.
                pass

    def _service_log(payload: dict[str, Any]) -> None:
        """One structured line per transport event, on the serve's own stderr.

        Which means it arrives at the supervisor as an ordinary
        ``{"id":null,"event":"stderr","line":…}`` frame — the lane serve already
        uses for everything a handler writes to stderr. No new frame type, no
        new sink, and correlatable by ``boot_id`` against the ready frame.
        """

        try:
            sys.stderr.write(
                json.dumps(payload, ensure_ascii=False, default=str) + "\n"
            )
        except Exception:
            pass

    def _run(request: _ArgvRequest) -> None:
        from agent_runtime.profile_context import process_home_scope
        from agent_runtime.request_control import request_cancel_scope

        # FIRST act of the worker, before any import or any handler code: from
        # here on the request is RUNNING, and the liveness pump says so instead
        # of reporting it as queued. A stamp taken later would describe a
        # request that is inside its handler as still waiting for a worker,
        # which is the exact confusion this field exists to end.
        request.started_monotonic = time.monotonic()
        token = _request_id.set(request.rid)
        # Answers go back to whoever asked. ``request.sink`` is None on stdio,
        # which leaves the contextvar unset and the proxy on stdout — the
        # pre-socket path, unchanged.
        sink_token = _request_sink.set(request.sink)
        sink: Any = request.sink if request.sink is not None else frames
        code = 1
        cache_key = _CACHEABLE_ARGV.get(tuple(request.argv))
        request_fingerprint: tuple | None = None
        served_from_cache = False
        cache_age_ms = 0
        capturing = False
        try:
            cached = None
            if cache_key is not None:
                request_fingerprint = fingerprint()
                cached = read_cache.get(
                    cache_key, request_fingerprint, time.monotonic()
                )
            if cached is not None:
                served_from_cache = True
                cache_age_ms = int(
                    (time.monotonic() - cached.built_monotonic) * 1000
                )
                code = cached.code
                for line in cached.lines:
                    sink.emit({"id": request.rid, "event": "line", "line": line})
                return
            if cache_key is not None and request_fingerprint is not None:
                stdout_proxy.begin_capture(request.rid)
                capturing = True
            try:
                # THE REQUEST'S OWN HOME, pinned for the width of the dispatch.
                #
                # A ContextVar, so it is per-worker and out-ranks
                # ``os.environ["HERMES_HOME"]`` in ``get_hermes_home()``'s
                # ladder — which is exactly the asymmetry the fix needs. A
                # persona lane that mirrors the env keeps the global channel it
                # genuinely requires (spawns, raw-env plugins), and this lane
                # stops being a passenger on it. See
                # ``profile_context.process_home_scope`` for the measured
                # incident and for what the scope deliberately does not cover.
                #
                # Placed OUTSIDE ``request_cancel_scope`` and around the whole
                # dispatch, not around a resolver: the bled reader was
                # ``agent.charsheet.draft.drafts_dir()``, four call frames deep
                # inside a ``_cmd_*`` handler, and there is no list of such
                # readers worth maintaining — every handler that resolves a home
                # is one. Binding at the seam covers all of them, including the
                # ones added tomorrow.
                #
                # Chat turns arrive here too, on both lanes (the RPC
                # ``spawn_chat_turn`` builds an ``_ArgvRequest`` and submits it
                # to this same ``_run``). This does not disturb them: a turn's
                # own ``persona_profile_context`` binds INSIDE this scope and
                # its ContextVar override nests over this one, so the persona
                # still gets its profile home. What changes is only the turn's
                # STARTING home, which is now this serve's rather than whatever
                # another lane last left in the environment.
                with process_home_scope(serve_request_home), request_cancel_scope(
                    request.cancel_event
                ):
                    if cache_key is not None:
                        from agent_runtime.snapshot import snapshot_build_context_scope

                        with snapshot_build_context_scope(read_build_context):
                            code = dispatch(list(request.argv))
                    else:
                        code = dispatch(list(request.argv))
            except ArgvRootUnsupported as exc:
                # RL-24, refused before a parser existed. Ordered ABOVE the
                # generic ``SystemExit`` arm because both of RL-24's new types
                # are ``SystemExit`` subclasses — which is what keeps every
                # non-serve caller of ``dispatch_argv`` behaving as it did.
                code = _system_exit_code(exc)
                sink.emit(
                    {
                        "id": request.rid,
                        "event": "error",
                        "error": "argv_root_unsupported",
                        "root": _clean_argv_root(exc.root),
                        "detail": (
                            "the serve argv lane owns the 'harness' parser only; "
                            "this root is a CLI verb the caller runs itself"
                        ),
                    }
                )
            except HandlerExit as exc:
                # The handler ran and then exited. Its effect, whatever it was,
                # has already happened — so this frame carries the code and NOT
                # the parser's word, and the launcher treats it as terminal for
                # the attempt rather than as a stale child to replay.
                code = exc.handler_code
                sink.emit(
                    {
                        "id": request.rid,
                        "event": "error",
                        "error": "handler_exit",
                        "code": code,
                        "detail": (
                            "the request handler exited; any effect it had "
                            "already happened and must not be replayed"
                        ),
                    }
                )
            except SystemExit as exc:  # argparse usage errors land here
                code = _system_exit_code(exc)
                if code != 0:
                    sink.emit(
                        {
                            "id": request.rid,
                            "event": "error",
                            "error": "argv_parse_failed",
                            "detail": "argparse rejected the request argv; usage was forwarded as stderr frames",
                        }
                    )
            except BaseException as exc:  # dispatch() already enveloped harness errors
                sink.emit(
                    {
                        "id": request.rid,
                        "event": "error",
                        "error": "dispatch_failed",
                        "detail": f"{type(exc).__name__}",
                    }
                )
        finally:
            if request.turn_request_id:
                # Gateway Stage 3. The accept receipt learns its worker ended,
                # and the code goes on it.
                #
                # Placed FIRST in the finally, and that position was found by a
                # test rather than reasoned to. It has to be before the exit
                # frame, or a client that reads the exit and immediately retries
                # the same ``turn_request_id`` can observe a receipt still
                # saying ``accepted``. But putting it between the inflight POP
                # and the frame is worse than either: the drain monitor polls
                # the pending set, so a request that is out of ``inflight`` and
                # not yet emitted is a window in which the drain can complete
                # and close the lane UNDER the exit frame — reproduced, as a
                # lost exit, the first time this was written that way. Before
                # the pop, the monitor still counts this request and the window
                # does not exist.
                #
                # Best-effort by contract (``settle_chat_turn`` never raises):
                # the ack it settles is long since on the wire, the receipt's
                # REPLAY answer does not depend on the exit code, and a
                # bookkeeping failure must never take the place of a turn's own
                # exit frame.
                from agent_runtime.chat_turn_reservations import settle_chat_turn

                settle_chat_turn(
                    turn_request_id=request.turn_request_id, exit_code=code
                )
            stdout_proxy.flush_request(request.rid)
            stderr_proxy.flush_request(request.rid)
            if capturing:
                read_cache.put(
                    cache_key,
                    request_fingerprint,
                    stdout_proxy.end_capture(request.rid),
                    code,
                    time.monotonic(),
                )
            _request_id.reset(token)
            _request_sink.reset(sink_token)
            with inflight_lock:
                inflight.pop(request.key, None)
                inflight_futures.pop(request.key, None)
                # Accounted here rather than by the monitor's before/after
                # arithmetic: the monitor only ever sees the pending SET, so a
                # request that both started and finished during the drain would
                # be invisible to it.
                #
                # And accounted INSIDE the same critical section as the pop,
                # which it did not used to be. With the increment outside, a
                # request sat in a window where it was gone from ``inflight``
                # and not yet in ``completed`` — the monitor could observe an
                # empty pending set and publish ``drain_complete`` with a
                # completion count LOWER than the number of exits it had
                # actually let land (reproduced: 5 reported for 8 exits). The
                # counters are the drain's only evidence, so an under-count
                # reads to an operator as work the restart dropped.
                #
                # Lock order is inflight_lock → _DrainState.lock, and it is the
                # only nesting of the two: every other site takes them one after
                # the other, never one inside the other.
                if drain_state is not None:
                    drain_state.note_completed()
            exit_frame: dict[str, Any] = {
                "id": request.rid,
                "event": "exit",
                "code": code,
            }
            if served_from_cache:
                exit_frame["served_from_cache"] = True
                exit_frame["cache_age_ms"] = cache_age_ms
            sink.emit(exit_frame)

    original_stdout, original_stderr = sys.stdout, sys.stderr
    local_llama_bound_root = None
    discussion_owner = None
    sys.stdout, sys.stderr = stdout_proxy, stderr_proxy
    try:
        store_root_path: Any = None
        try:
            from agent_runtime import paths as _paths

            store_root_path = _paths.store_root()
            runtime_root = str(store_root_path)
        except Exception:
            store_root_path = None
            runtime_root = None
        timeline.mark("store_root_ms")
        # ── Durable-service foundations (slice 2) ───────────────────────────
        #
        # These three run BEFORE ``ready`` because ``ready`` is the frame that
        # carries them: a client that has to ask a second question to learn
        # what code it just connected to has a window in which it does not
        # know, and windows like that are how a stale service serves a whole
        # session before anyone notices.
        #
        # 1. WHICH CODE. Today serve is a per-client child, so a launcher
        #    restart picks up landed fixes for free and nobody ever had to
        #    ask. A durable service silently pins last week's code instead —
        #    the shape of the dispatch dead-flag-proxy incident, which ran
        #    green for a week. Resolved once per process and cached.
        try:
            from agent_runtime.build_stamp import build_stamp

            build_block = build_stamp().frame_payload()
        except Exception as exc:  # an instrument must never take the boot down
            build_block = {
                "commit": None,
                "dirty": None,
                "source": "unknown",
                "resolved_at": None,
                "reason": f"stamp_failed:{type(exc).__name__}",
                # RS-6's keys are present on the failure arm too, and BOTH are
                # null: a reader that fell back to the commit comparison must
                # be able to tell "this hermes has no code tree" from "this
                # hermes predates the key", and an absent key says the second.
                # The rule is null because the module that owns it is exactly
                # what did not import.
                "code_tree": None,
                "code_tree_rule": None,
                "code_tree_reason": f"stamp_failed:{type(exc).__name__}",
            }
        # 2. THE SECRET. Unwired to any transport (stdio needs none), minted
        #    now so the socket slice starts with a lock already on the door
        #    rather than shipping open. The frame carries the POSTURE only —
        #    the token value must never appear in a frame, a log, or an event.
        auth_block: dict[str, Any] = {"token_file": "error:root_unresolved"}
        if store_root_path is not None:
            try:
                from agent_runtime.serve_auth import ensure_token

                auth_block = ensure_token(store_root_path).payload()
            except Exception as exc:
                auth_block = {"token_file": f"error:{type(exc).__name__}"}
        # 2b. WHICH INSTALL. The secret above says a caller MAY talk to this
        #     runtime; this says WHICH runtime it reached. Two facts, two
        #     mechanisms, deliberately — an id that both names and authorises is
        #     how "I know your install id" becomes "I am you", and the gateway
        #     plan's device/peer tiers (Stage 1/6) hang their credentials off the
        #     auth block, never off this one. Nothing here is secret: the id and
        #     the operator-set name travel in the clear on every greeting.
        #
        #     Mint-iff-absent, per root, and NOT the monitoring/telemetry
        #     ``install_id``s — those are rotatable and home/db-scoped, and the
        #     argument is written out in ``agent_runtime/gateway_identity.py``.
        install_block: dict[str, Any] = {
            "install_id": None,
            "display_name": None,
            "state": "error:root_unresolved",
        }
        if store_root_path is not None:
            try:
                from agent_runtime.gateway_identity import ensure_install_identity

                install_block = ensure_install_identity(store_root_path).frame_payload()
            except Exception as exc:
                install_block = {
                    "install_id": None,
                    "display_name": None,
                    "state": f"error:{type(exc).__name__}",
                }
        # 3. THE TRANSPORT (slice 3). One serve per root owns the socket lane,
        #    decided by an OS-held exclusive lock rather than by who booted
        #    first: two serves against one root is a real, ordinary concurrency
        #    (a launcher restart overlaps its replacement), and "connect to the
        #    service for root X" must have exactly one answer. The loser keeps
        #    serving stdio and SAYS so on the ready frame — a socket that
        #    silently never came up is indistinguishable from one that is
        #    broken.
        #
        #    Bound here, BEFORE the registry entry and the ready frame, so both
        #    can carry the real port; accepting starts later, once the request
        #    pool exists (see ``start_accepting`` below). A client that connects
        #    in between waits in the listen backlog, which is what a backlog is
        #    for.
        socket_block: dict[str, Any] = {"outcome": "disabled"}
        socket_transport = "stdio"
        if socket_lane and store_root_path is not None:
            try:
                from agent_runtime.serve_socket import (
                    SOCKET_HOST,
                    ServeSocketServer,
                    SocketOwnerLock,
                    read_socket_owner,
                )
                from agent_runtime.serve_auth import read_token as _read_serve_token

                # ``log`` is what makes R-L2's takeover an OPERATOR-visible
                # event rather than a field on a frame nobody kept: the
                # ``serve_socket_owner_takeover`` line lands on the same service
                # log as ``serve_instances_pruned``, correlatable by boot_id
                # against this boot's ready frame.
                socket_lock = SocketOwnerLock(store_root_path, log=_service_log)
                lock_result = socket_lock.acquire()
                if lock_result.acquired:
                    from agent_runtime.local_llama_adapter.rpc import bind as bind_local_llama
                    from agent_runtime.config import harness_root_config_path
                    bind_local_llama(store_root_path, harness_root_config_path())
                    local_llama_bound_root = store_root_path
                    # A corrupt optional discussion store must not take the
                    # ordinary native socket/chat lane down with it.
                    try:
                        from agent_runtime.discussions.service import bind as bind_discussions
                        from agent_runtime.profile_home import get_hermes_head_home
                        discussion_owner = bind_discussions(
                            store_root_path, get_hermes_head_home(), install_block["install_id"])
                    except Exception:
                        import logging as _discussion_logging
                        _discussion_logging.getLogger(__name__).warning(
                            "discussion runtime unavailable; ordinary chat remains enabled",
                            exc_info=True,
                        )
                    socket_server = ServeSocketServer(
                        store_root_path,
                        boot_id=boot_id,
                        # Late-bound on purpose: these two closures are defined
                        # further down (they need the pool and the drain state),
                        # and a Python closure resolves its enclosing names at
                        # CALL time — which cannot happen before the accept loop
                        # starts, which is after both exist.
                        dispatch_line=lambda line, connection: _handle_socket_line(
                            line, connection
                        ),
                        hello_payload=lambda message, connection: _hello_ok_frame(
                            message, connection
                        ),
                        # THIS root's secret, read per handshake and used as an
                        # HMAC key over a per-connection nonce. It is the key
                        # and never the message, so nothing derived from it and
                        # put on the wire discloses it — which is the whole
                        # reason the hello stopped carrying the token at all.
                        token_provider=lambda: _read_serve_token(store_root_path),
                        frame_contract=SERVE_SCHEMA_VERSION,
                        on_disconnect=lambda connection: _on_connection_closed(
                            connection
                        ),
                        log=_service_log,
                    )
                    port = socket_server.bind()
                    socket_lock.publish_owner(
                        {
                            "pid": os.getpid(),
                            "boot_id": boot_id,
                            "host": SOCKET_HOST,
                            "port": port,
                            "started_at": socket_server.started_at,
                            "store_root": runtime_root,
                        }
                    )
                    socket_transport = "stdio+socket"
                    socket_block = {
                        "outcome": "listening",
                        "host": SOCKET_HOST,
                        "port": port,
                        "started_at": socket_server.started_at,
                    }
                    # R-L2. Present only when this boot inherited a PROVEN-dead
                    # owner's lane, which makes it the receipt for a recovered
                    # restart: a launcher that respawned a serve and sees
                    # ``took_over_from`` naming the pid it killed knows the
                    # replacement is the socket owner, rather than inferring it
                    # from the absence of ``lock_held_by``.
                    if lock_result.took_over_from is not None:
                        socket_block["took_over_from"] = lock_result.took_over_from
                        socket_block["owner_started_at"] = lock_result.owner_started_at
                else:
                    socket_block = lock_result.payload()
                    if service:
                        # L-h item 2, and F1's explicit requirement: a
                        # ``--service`` starter that loses the ownership race
                        # SERVES NOTHING.
                        #
                        # A stdio serve that loses this lock has a job to do and
                        # keeps doing it — that is the pre-existing contract and
                        # it is untouched above. A SERVICE that lost it does
                        # not: it was asked to be "the runtime for this root",
                        # there already is one, and the only thing it could do
                        # by carrying on is become a second execution process
                        # against the same store — an extra stdio executor
                        # nobody discovers, nobody drains, and nobody knows to
                        # stop. So it names the winner and leaves, before the
                        # request pool, the registry row and the ready frame
                        # exist, which is what "serves nothing" means literally.
                        #
                        # Exit code 0: losing this race is the ORDINARY outcome
                        # of two starters (a launcher that respawned, two
                        # launchers on one machine), and the caller's next act
                        # is to re-read the registry and attach to the winner —
                        # RL-4. A nonzero code would read as "the runtime failed
                        # to start" for a root that has a healthy runtime.
                        #
                        # Both a FRAME and a service-log line, because the two
                        # have different audiences and either can be the only
                        # one present: a launcher that spawned us over pipes
                        # reads the frame, and a launcher that spawned us
                        # DETACHED (which is the normal case — RL-2) has no
                        # stdout to read at all.
                        try:
                            owner_record = read_socket_owner(store_root_path)
                        except Exception:
                            owner_record = {}
                        owner_port = owner_record.get("port")
                        exists = {
                            "event": "serve_owner_exists",
                            # The WINNER's pid, from the sidecar — not ours.
                            "pid": lock_result.pid,
                            "port": owner_port if isinstance(owner_port, int) else None,
                            "boot_id": boot_id,
                            "starter_pid": starter_pid,
                            "runtime_root": runtime_root,
                            "owner_started_at": lock_result.owner_started_at,
                            "socket": socket_block,
                        }
                        _service_log(exists)
                        frames.emit(exists)
                        try:
                            socket_lock.release()
                        except Exception:
                            pass
                        return 0
            except Exception as exc:
                # A transport that failed to come up must not take the runtime
                # with it: stdio still works, and the typed outcome is how an
                # operator learns the socket did not.
                try:
                    if socket_lock is not None:
                        socket_lock.release()
                except Exception:
                    pass
                socket_server = None
                socket_lock = None
                socket_block = {"outcome": f"error:{type(exc).__name__}"}
        # 3b. THE SECOND DOOR (remote-gateway Stage 1). Off unless an operator
        #     names an interface in `remote_gateway.listen`, and the block SAYS
        #     which of those it is either way — `disabled` is a different fact
        #     from `error:port_in_use`, and a listener that silently failed to
        #     come up while the config said it should is the false-all-clear
        #     shape the `socket` block beside it already exists to retire.
        #
        #     Three things differ from the lane above and nothing else does: the
        #     bind (an operator-chosen interface and usually a fixed port), the
        #     credential (per DEVICE — `serve_gateway_auth`, not the per-root
        #     token), and the link (TLS, R1). Same dispatcher, same ops, same
        #     stream hub, same drain.
        # R-IP16 / R-S2-1: the capability list rides EVERY outcome, including
        # ``disabled``. "Does this hermes know the verb" and "is the LAN door
        # open" are different questions, and S3's request loop asks the first
        # over loopback argv against a serve that may legitimately have the
        # second answered ``no``. Stamped in exactly two places — here, and on
        # the listener's own block below — so ``ready`` / ``hello_ok`` /
        # ``version`` are untouched and cannot disagree.
        #
        # R-L1: THE BLOCK IS NEVER SILENT AND NEVER GUESSES. The listener can
        # only be opened by the serve that owns the loopback lane (one process
        # per root binds the operator's port, or the second one loses that race
        # too), so every failure of the lane above is also a boot with no
        # listener — and until 2026-09-04 all of them said ``disabled``, the same
        # word as "the operator never asked". That is the sentence the launcher
        # could not read: it had just WRITTEN ``remote_gateway.listen`` and
        # respawned, and the greeting told it the feature was off.
        # ``gateway_block_when_no_listener`` splits those apart.
        from agent_runtime.gateway_capabilities import with_capabilities

        gateway_block: dict[str, Any]
        if socket_server is not None and store_root_path is not None:
            gateway_server, gateway_block = start_gateway_listener(
                store_root_path,
                boot_id=boot_id,
                display_name=install_block.get("display_name"),
                dispatch_line=lambda line, connection: _handle_socket_line(
                    line, connection
                ),
                hello_payload=lambda message, connection: _hello_ok_frame(
                    message, connection
                ),
                on_disconnect=lambda connection: _on_connection_closed(connection),
                log=_service_log,
                frame_contract=SERVE_SCHEMA_VERSION,
            )
            gateway_block = with_capabilities(gateway_block)
            if gateway_server is not None and socket_lock is not None:
                # RE-PUBLISH the ownership sidecar, now that the second door has
                # a real port. The first publish happens before this block on
                # purpose (the loopback port must be advertised as early as
                # possible, and the gateway lane must not be able to delay it),
                # so the gateway endpoint can only arrive in a second write.
                #
                # It has to arrive somewhere: `harness gateway pair` runs in the
                # operator's shell, not in this process, and the pairing payload
                # it prints has to name a port a phone can dial. With an
                # ephemeral port that number exists nowhere else — the registry
                # entry carries the LOOPBACK port, and the `ready` frame goes to
                # a launcher rather than to a terminal.
                socket_lock.publish_owner(
                    {
                        "pid": os.getpid(),
                        "boot_id": boot_id,
                        "host": SOCKET_HOST,
                        "port": socket_server.port,
                        "started_at": socket_server.started_at,
                        "store_root": runtime_root,
                        # Additive: a reader that predates this lane finds the
                        # keys it knows, unchanged and in the same places.
                        "gateway": {
                            "host": gateway_block.get("host"),
                            "port": gateway_block.get("port"),
                            "cert_fingerprint": gateway_block.get("cert_fingerprint"),
                        },
                    }
                )
        else:
            gateway_block = with_capabilities(
                gateway_block_when_no_listener(
                    socket_block, root_resolved=store_root_path is not None
                )
            )
        # S2c. ONE announce per boot, on a background thread, telling every
        # usable peer where this install is now reachable and what certificate
        # it presents. It is the push that makes a machine which changed
        # networks findable again without an operator re-running a ceremony they
        # had no reason to suspect was needed — the far side's cache endpoints
        # are tried before its pairing-time ones (`dial_peer`), so the new
        # address wins on the next call.
        #
        # Once per boot and never on a timer: this is news, and news that
        # repeats is a poll wearing a push's clothes. A peer that was off simply
        # rests `unreachable` in our cache until its own next hello refreshes
        # both sides.
        if gateway_block.get("outcome") == "listening" and store_root_path is not None:
            try:
                from agent_runtime.gateway_announce import announce_in_background
                from hermes_cli.harness_parts.gateway_commands import (
                    _candidate_endpoints,
                )

                announce_in_background(
                    store_root_path,
                    {
                        "endpoints": _candidate_endpoints(store_root_path),
                        "cert_fingerprint": gateway_block.get("cert_fingerprint"),
                        "display_name": install_block.get("display_name"),
                    },
                )
            except Exception:  # noqa: BLE001 — courtesy channel, never the boot
                pass

        # 4. DISCOVERY. Multiple runtime roots legitimately coexist on this
        #    machine (QA lanes, isolated worktree roots), and until now
        #    "how many serves are running against this root, on what code"
        #    had no answer at all. The entry is removed on every clean exit
        #    (shutdown AND drain); a crash leaves it, which is why liveness is
        #    proven at READ time and never trusted from the file.
        #
        #    The socket fields ride the SAME entry (additive): a client
        #    discovering "the service for root X" reads the port from the
        #    instance whose liveness the registry has just classified, rather
        #    than from a second file with its own staleness story.
        instance_block: dict[str, Any] = {"outcome": "error:root_unresolved"}
        if store_root_path is not None:
            try:
                from agent_runtime.serve_registry import register_serve_instance

                # WHICH HOME this child resolved (D-3). store_root answers a
                # DIFFERENT question — one root is shared by serves on
                # different profile homes — so from outside the process
                # nothing could say which home a running serve was on.
                # Resolved HERE, not in the registry: that module stays free
                # of hermes_constants and unit-testable against a string.
                # A resolution failure degrades to None (written as null);
                # bookkeeping must never be the thing that fails a boot.
                try:
                    from hermes_constants import get_hermes_home

                    resolved_home: str | None = str(get_hermes_home())
                except Exception:
                    resolved_home = None
                instance_block = register_serve_instance(
                    store_root_path,
                    transport=socket_transport,
                    build=build_block,
                    boot_id=boot_id,
                    port=socket_server.port if socket_server is not None else None,
                    socket_started_at=(
                        socket_server.started_at if socket_server is not None else None
                    ),
                    hermes_home=resolved_home,
                    # L-h item 3. The row is what an attach-first client reads
                    # BEFORE it dials anything, so "is this runtime going to
                    # outlive the launcher that started it" has to be answerable
                    # from the file — not only from a greeting you get after
                    # connecting.
                    service=service,
                    starter_pid=starter_pid,
                ).payload()
            except Exception as exc:
                instance_block = {"outcome": f"error:{type(exc).__name__}"}
        # ── RL-19: the service runtime keeps its own stderr ─────────────────
        #
        # BEFORE the RL-16 block below, for two reasons that are both ordering:
        # the sidecar prune down there now floors this family too, and this
        # boot's own log has to exist by then so that it is the NEWEST of its
        # family and can never be the file the prune picks; and an arming that
        # happens after the recorder would miss nothing but is harder to read.
        #
        # And BEFORE the row prune below, which is RO-3's ordering: the prune
        # now says row by row what it removed and what it refused, and on a
        # ``--service`` runtime the only place that can be READ is this file.
        # Armed after it, the boot prune's verdicts would go to the DEVNULL
        # stderr RL-17 hands a service — which is the exact silence RO-3 exists
        # to end. It is safe this early for the same reason the prune is: the
        # log is not a registry row (``_NON_ROW_SUFFIXES``), so no scan and no
        # prune between here and there can see it.
        #
        # ``service`` only. A serve started the old way is a child whose parent
        # is holding its stderr pipe open and reading it as frames — moving that
        # output into a file would take it away from the process that asked for
        # it (pinned by the non-service arm of the child e2e).
        if service and store_root_path is not None:
            try:
                from agent_runtime.serve_registry import open_serve_stderr_log

                service_stderr_log = open_serve_stderr_log(
                    store_root_path, boot_id=boot_id, build=build_block
                )
            except Exception:  # pragma: no cover - the opener never raises
                service_stderr_log = None
            if service_stderr_log is not None:
                stderr_proxy.set_mirror(service_stderr_log)
                _repoint_logging_root_stderr(
                    service_stderr_log,
                    previous=(original_stderr, sys.__stderr__, stderr_proxy),
                )
                # What ``sys.stderr`` becomes again when this loop unwinds. The
                # mirror above covers the loop's own lifetime; this covers
                # everything written to stderr AFTER it — an interpreter-level
                # message, a late ``atexit`` hook, a warning during teardown.
                # Named as defence and not as the traceback's route: the
                # traceback is written explicitly by the uncaught arm below,
                # because nothing in this process prints one (see there).
                original_stderr = service_stderr_log
                # Never closed on purpose: the writes worth having are the ones
                # made on the way down, and the OS closes it when the process
                # ends. Line-buffered, so nothing is owed a flush.

        if store_root_path is not None:
            # ...and, having registered and armed the log, drop the records that
            # are provably wreckage. AFTER registration on purpose: this serve's
            # own entry then exists and classifies `live`, so the sweep can
            # never be the thing that removes it.
            #
            # WHY THIS DOES NOT CONTRADICT "listing never prunes"
            # ---------------------------------------------------
            # serve_registry's docstring argues, correctly, that a READ must not
            # destroy the evidence it is reporting: an operator asking "why do I
            # have four serves" must see the wreckage. A boot is not that
            # moment. It is a WRITE moment - the line above just created a file
            # in this directory - and, decisively, the evidence does not vanish:
            # prune_stale_serve_instances returns pid, boot_id, path,
            # classification and reason for every record, deleted and kept
            # alike, and that report goes onto the service log correlatable by
            # boot_id against this boot's ready frame. The wreckage moves from a
            # directory nobody reads into a log the operator already reads.
            #
            # It is needed because clean exit removes its own entry and the
            # crash path deliberately does not - and the launcher's boot hygiene
            # sweep taskkill /F's orphan serves, which is a crash by
            # construction: those serves are never given the chance to
            # unregister. Measured on the operator's runtime: 14 serve boots in
            # ~19 h left 2 records behind (13856, 35080), while a third (21440)
            # exited cleanly and removed its own.
            #
            # SCOPE, stated plainly: this is tidiness plus forensics, not a
            # correctness fix. The leftover records are already harmless -
            # resolve_socket_target returns only rows classified `live`, the
            # launcher never reads this directory, and it is excluded from every
            # freshness fingerprint (see the module docstring).
            #
            # What is pruned is NOT widened here: stale_dead_pid only, which is
            # the registry's own rule. stale_recycled_pid names a live process
            # this registry no longer understands, and `unknown` means a probe
            # could not answer - deleting on a failed probe is how a sweep
            # removes a RUNNING service's record, and this repo has already been
            # bitten once by a recycled pid killing an unrelated process.
            #
            # Silent when it found nothing to do: a line every boot saying it
            # deleted zero files is the kind of noise that trains an operator to
            # stop reading the channel this report needs to be seen on.
            #
            # RO-3 keeps that rule and adds the row-level story the aggregate
            # could not carry: ``emit=_service_log`` writes one
            # ``serve_registry_pruned`` line per row REMOVED or REFUSED, at the
            # instant it happens, on the same channel and joinable by the same
            # ``boot_id``. A live row — this boot's own entry, every time —
            # writes nothing, so a quiet machine's log stays quiet.
            try:
                from agent_runtime.serve_registry import (
                    prune_stale_serve_instances,
                )

                prune_report = prune_stale_serve_instances(
                    store_root_path, emit=_service_log, boot_id=boot_id
                )
                if prune_report.get("deleted_count") or any(
                    "error" in row for row in prune_report.get("kept") or ()
                ):
                    _service_log(
                        {
                            "event": "serve_instances_pruned",
                            "boot_id": boot_id,
                            "pid": os.getpid(),
                            **prune_report,
                        }
                    )
            except Exception:
                # Bookkeeping must never take a boot with it.
                pass

        # ── RL-16: arm the end-reason recorder ──────────────────────────────
        #
        # HERE, and not earlier, because the recorder writes into the directory
        # the row above just created — and not later, because from the ready
        # frame onward this runtime can be killed, and an ending it cannot
        # record is an ending nobody can explain. Everything below is best
        # effort by construction: a bookkeeping arm that could fail a boot would
        # be a worse defect than the one it exists to diagnose.
        if record_end_reason and store_root_path is not None:
            end_reason = _ServeEndReason(store_root_path, boot_id=boot_id)
            _install_console_ctrl_reason_handler(end_reason)
            _install_signal_reason_handlers(end_reason)
            try:
                import atexit as _atexit

                # The floor under every other mechanism: a route none of them
                # know about still leaves ``unknown_exit`` rather than silence,
                # and silence is reserved for the hard kill (see the registry
                # module's sidecar section — absence is a reading).
                _atexit.register(end_reason.write)
            except Exception:  # pragma: no cover - atexit is always importable
                pass
            # Retention, beside the row prune and for the mirror-image reason:
            # a row is removed when its runtime exits cleanly, but nothing ever
            # consumes a REASON, so without a floor this directory grows for the
            # life of the machine.
            try:
                from agent_runtime.serve_registry import prune_serve_ended

                prune_serve_ended(store_root_path)
            except Exception:
                pass

        # ── RL-23: the floor under credential supersession ──────────────────
        #
        # Beside the two sidecar prunes and for the third version of the same
        # reason: a redeem now REVOKES the rows it replaces rather than leaving
        # them live, and a revoked row nobody ever deletes is growth with a
        # different name. Thirty days is how long "why did my Mac stop
        # connecting" stays a question worth answering.
        #
        # NOT gated on ``record_end_reason``: that flag says this runtime is a
        # SERVICE and owes an end reason, while the device store is the root's
        # regardless of how the runtime that opened it was started. Deleting
        # only revoked rows past the retention is what makes running it on every
        # boot safe — a live credential is never a candidate at any age.
        #
        # Silent and swallowed, like its neighbours: bookkeeping must never be
        # the thing that fails a boot.
        if store_root_path is not None:
            try:
                from agent_runtime.serve_gateway_auth import prune_revoked_devices

                prune_revoked_devices(store_root_path)
            except Exception:
                pass
        timeline.mark("service_foundations_ms")
        # Orphaned-turn sweep BEFORE the ready frame: serve boot is the moment
        # a launcher restart replaces a dead runtime, and the first hydrate is
        # only requested after ready — so records a dead executor left frozen
        # in-flight (lease provably free) already project as typed
        # ``turn_interrupted`` markers in that hydrate instead of a console
        # stuck "running" forever. Bounded (≤50 session files) and fail-open.
        orphaned_repaired: list[str] = []
        try:
            from agent_runtime.persona_chat_continuity import repair_orphaned_chat_turns

            orphaned_repaired = repair_orphaned_chat_turns()
        except Exception:
            orphaned_repaired = []
        timeline.mark("orphaned_turn_sweep_ms")
        # Same moment, same reason, for detached dispatches: a row still marked
        # ``running`` whose owning process is provably gone can never finish, and
        # the sender is owed that answer too. Reclassifying it here — BEFORE the
        # drain starts — turns "the agent I dispatched went silent forever" into
        # a delivered "the outcome is unknown, re-send if you still need it".
        # Identity-verified (a recycled PID is not the old owner) and fail-open.
        dispatches_restored = 0
        try:
            from agent_runtime.dispatch_store import restore_undelivered_dispatches

            dispatches_restored = int(
                (restore_undelivered_dispatches() or {}).get("restored") or 0
            )
        except Exception:
            dispatches_restored = 0
        timeline.mark("dispatch_restore_ms")
        ready_frame: dict[str, Any] = {
            "event": "ready",
            "pid": os.getpid(),
            "schema_version": SERVE_SCHEMA_VERSION,
            "runtime_root": runtime_root,
            # Additive, always present (never conditional on success): a
            # missing block would read as "old runtime", while a block whose
            # own fields say `unknown`/`error:…` reads as what it is — the
            # measurement was attempted and this is what it found.
            "boot_id": boot_id,
            # L-h item 3, on all three greeting frames by the same rule as
            # ``boot_id`` above: always present, never inferred from absence. A
            # client reads ``service`` to know whether closing its end of this
            # pipe DETACHES from a runtime that keeps going or KILLS it, and
            # ``starter_pid`` to know whether the process it is looking at is
            # the one it started itself.
            "service": service,
            "starter_pid": starter_pid,
            "build": build_block,
            "auth": auth_block,
            # WHICH INSTALL this is, by the same "always present, states its own
            # outcome" rule as ``auth`` above — a picker with two installs in it
            # needs a stable id and a human name, and absence would be
            # indistinguishable from a runtime that predates the lane.
            "install": install_block,
            "instance": instance_block,
            # ``disabled`` (no socket lane asked for), ``listening`` with the
            # port, ``lock_held_by`` with the winner's pid, or ``error:<reason>``
            # — the outcome is stated either way, never inferred from absence.
            "socket": socket_block,
            # The SECOND door, by the same rule and for a sharper reason. An
            # operator who sets ``remote_gateway.listen`` and restarts has one
            # question — can my phone reach this install — and every way the
            # answer is no is quiet: the port was taken, the certificate could
            # not be minted, the socket lane never came up, the config key was
            # never read. ``disabled`` when nobody asked, ``listening`` with
            # host/port and the ``cert_fingerprint`` a client pins,
            # ``socket_unavailable`` (R-L1) with the ``reason`` / ``pid`` /
            # ``owner_started_at`` of the lane that is holding this one shut, or
            # ``error:<reason>``. Never absent, never inferred, and — since
            # R-L1 — never ``disabled`` for a listener the config asked for.
            "gateway": gateway_block,
            # The METHOD lane's capability manifest — ``{"contract":N,
            # "methods":[…]}``. This is stdio's greeting, so this is where a
            # stdio client learns the method set; the socket's equivalent is
            # ``hello_ok``, and both are restated on the re-askable ``version``
            # reply. Same shape of promise as ``hello_contract``: the server
            # advertises, the client asserts, and a runtime that predates the
            # lane carries no ``rpc`` key at all — which reads as "argv only"
            # rather than as a failure.
            "rpc": serve_rpc.manifest(),
            # The OP lane's half of the same promise (TC-1/C-1). ``ready`` is
            # stdio's greeting, so this is where a stdio client learns that
            # ``{"op":"subscribe","lane":"stream"}`` is carried here rather than
            # having to send one and read the answer's tea leaves.
            "ops": ops_manifest(transport="stdio", service=service),
        }
        if orphaned_repaired:
            ready_frame["orphaned_turns_repaired"] = len(orphaned_repaired)
        if dispatches_restored:
            ready_frame["dispatches_restored"] = dispatches_restored
        # Every phase this boot actually paid, on the frame the supervisor
        # already waits for — and the same line in agent.log, because the boot
        # worth attributing (the cold one) is the boot nobody is watching a
        # console for. Emission is defensive: a broken instrument must never be
        # the reason a runtime fails to come up.
        try:
            ready_frame["boot_timeline"] = timeline.stamps()
        except Exception:
            pass
        # Read-model warmup starts BEFORE ``ready`` is announced, unlike the
        # provider warmup below. The launcher's first request lands within
        # milliseconds of this frame, and only the build that STARTED FIRST can
        # be shared: if the request wins the race it leads its own build and
        # the warmup then queues a second, redundant one behind it. Starting a
        # daemon thread costs microseconds, so ``ready`` is not delayed.
        #
        # ONE thread, and the provider warmup runs on it AFTER the build (EG-3.2,
        # two independent investigations reaching the same fix: HY-H2 = HC-H3).
        # It used to be a second daemon thread started just after ``ready``, and
        # under the GIL its ~5-8s of CPU — OpenAI SDK import, SSL context, and
        # since BW-H3 the ``model_tools`` import plus the discovery/check_fn storm
        # — was subtracted from the build the launcher's canvas is waiting on.
        # Nothing it warms is consumable before that canvas is authoritative: its
        # purpose is the FIRST CHAT TURN's latency, which is after.
        #
        # The brief's one-line version of this fix — reorder the two
        # ``Thread.start()`` calls — was REFUSED as a no-op by both sources
        # independently: starts issued microseconds apart schedule nothing, and
        # the provider prewarm reached ``model_tools`` ~5s in either way.
        #
        # Named cost, carried rather than hidden: a chat turn sent inside the (now
        # shorter) boot window pays the cold SDK import inline, exactly as every
        # turn did before the prewarm existed — best effort by the prewarm's own
        # contract. If receipts show first-turn misses, the refinement is
        # "provider prewarm starts at first-request-enqueue OR build-completion,
        # whichever is first", not a revert.
        # Since 2026-08-23 a THIRD step rides the same thread, last: the
        # persona-chat actor prewarm (Stage 2 of `planned/chat-turn-prep-cost`).
        # Last on purpose — it queues agent constructions, and a construction
        # that runs after the provider warmup does not pay the SDK import it
        # would otherwise pay itself. It only QUEUES here; the constructions run
        # on that module's own worker, which stands down for any live turn.
        if (
            snapshot_prewarm is not None
            or provider_prewarm is not None
            or actor_prewarm is not None
        ):

            def _prewarm_worker() -> None:
                # Sequential, and each step isolated: a build that raised must
                # still leave the providers warm (HY-H2), and an injected fake
                # that raises must not silently cancel the step after it.
                for step in (snapshot_prewarm, provider_prewarm, actor_prewarm):
                    if step is None:
                        continue
                    try:
                        step()
                    except Exception:
                        try:
                            import logging as _logging

                            _logging.getLogger(__name__).debug(
                                "serve prewarm step did not complete", exc_info=True
                            )
                        except Exception:
                            pass

            threading.Thread(
                target=_prewarm_worker,
                name="harness-serve-prewarm",
                daemon=True,
            ).start()
        frames.emit(ready_frame)
        # RL-16's test seam, and the ONLY line it costs the production path.
        # AFTER ``ready`` because every arm that uses it needs a booted runtime
        # with its recorder armed and its registry row on disk — the state a
        # real death happens in. Inert without ``HERMES_SERVE_BOOT_FAULT``; see
        # :func:`_maybe_inject_boot_fault` for the three endings it buys.
        _maybe_inject_boot_fault()
        try:
            import logging as _logging

            _logging.getLogger(__name__).info(
                timeline.log_line("harness serve boot timeline:")
            )
        except Exception:
            pass
        # (Both warmups run on the single thread started just before the ready
        # frame above — the read-model build first, then the chat turn's one-time
        # costs. The invariant the two-thread arrangement was written to protect
        # is now provable rather than raced: the build cannot queue behind the
        # ~3s SDK import, because that import has not started yet.)
        # A busy serve must never look dead. The launcher's stream watchdog
        # keys on "no frames for N seconds", and when pool workers are deep in
        # chat-turn work the infinite `stream` request's generator can starve
        # past that budget — Mission Control then raised the loud "Runtime
        # offline" banner DURING healthy turns (live incident 2026-07-23,
        # two flaps inside one 4-minute Neko turn). This dedicated thread
        # emits the same typed `busy` frame the `ping` op returns whenever
        # requests are in flight: pure liveness telemetry on the shared
        # stdout, independent of every pool worker, so the launcher can
        # distinguish "busy running your turn" from "gone".
        liveness_stop = threading.Event()

        def _liveness_pump() -> None:
            while not liveness_stop.wait(liveness_pump_interval_seconds):
                with inflight_lock:
                    pending = list(inflight.values())
                if not pending:
                    continue
                busy_frame = _busy_frame()
                # STANDING SUBSCRIPTIONS ARE NOT WORK. `harness stream` never
                # ends by design, so an attached launcher keeps two of them in
                # `inflight` for the life of the attachment — and this pump,
                # which only ever asked "is anything pending?", therefore
                # announced `busy` every 5s to a runtime that was doing
                # NOTHING (measured 2026-09-05: `chat_turns: 0, long_runs: 0,
                # pending: 2`, forever). `_report_quiet_requests` had already
                # learned to exclude them, and says why; this is the same
                # exclusion applied to the frame the launcher actually reads.
                # `ping` is untouched — a supervisor that ASKS still gets every
                # count, because silence is the pump's rule, not the frame's.
                if busy_frame["work"] > 0:
                    try:
                        frames.emit(busy_frame)
                    except Exception:
                        # Writer gone — the main loop is on its way down too.
                        return
                    # And to every SOCKET client, for the identical reason the
                    # comment above gives for stdout. This lane was left behind
                    # when the drain path learned the same lesson: "the socket
                    # client IS such a watchdog: it reads with a finite timeout
                    # and reports `transport_failed` on silence" (see the
                    # drain's `_broadcast_lanes(progress)`). Measured
                    # 2026-08-27: an authenticated socket connection waiting on
                    # a `characters list` read ZERO frames for >120s while this
                    # pump was emitting `busy` the whole time — to stdout,
                    # where that client could not see it.
                    #
                    # Best-effort and never fatal: `_broadcast_lanes` is a later
                    # local of this loop, so an early tick can find it unbound,
                    # and a broadcast failing must not stop the liveness the
                    # launcher keys on.
                    try:
                        _broadcast_lanes(busy_frame)
                    except Exception:
                        pass
                # The per-request half: `busy` is a count, and a client waiting
                # on ONE id needs to know whether that id has started. It gets
                # the FULL pending list — it does its own stream exclusion, and
                # a subscription-only lap can still be the lap on which an
                # argv request crosses the silence budget.
                _report_quiet_requests(pending)

        threading.Thread(
            target=_liveness_pump,
            name="harness-serve-liveness",
            daemon=True,
        ).start()
        # Detached-dispatch delivery. This is the half that makes
        # `agent_chat_send(wait=false)` honest: the target's turn ran in the
        # background, its answer is durable, and this thread forges it back into
        # the SENDER's thread once that thread is idle. It lives HERE, and only
        # here, because serve is the one long-lived process that hosts persona
        # turns — a one-shot CLI exits long before a 30-minute dispatch lands.
        #
        # Started after `ready` (so a cold boot is never delayed by a delivery)
        # and stopped with the liveness pump before `shutdown` (so it cannot
        # forge a turn into a process that is on its way down). Best effort by
        # contract: a runtime that cannot start the drain still serves, and the
        # completions stay pending for the next boot rather than being lost.
        try:
            from agent_runtime.dispatch_delivery import start_delivery_drain

            # Rehydrate durable delegation completions BEFORE the drain that
            # will deliver them starts — explicit at serve boot, never as an
            # import side effect (same #16856 class as module-scope MCP
            # discovery; see
            # docs/agent-runtime-harness/archive/2026-08-22-pre-consolidation/eager-tool-discovery-audit-2026-08-09.md).
            from tools.process_registry import process_registry

            process_registry.restore_durable_completions()
            start_delivery_drain(stop_event=liveness_stop)
        except Exception:
            # Function-local: parts files are exec'd into harness.py's globals,
            # which carry no module logger.
            #
            # WARNING, not debug: a drain that fails to start disables the
            # entire `agent_chat_send(wait=false)` lane for the life of this
            # serve — every dispatch is refused with
            # `async_delivery_unavailable` — and at debug level that
            # feature-killing fact was invisible in every live log
            # (2026-08-09 dispatch-lane investigation).
            import logging as _logging

            _logging.getLogger(__name__).warning(
                "dispatch delivery drain did not start; "
                "agent_chat_send(wait=false) will be refused for this serve",
                exc_info=True,
            )
        # Independent lifecycle: failure in another delivery consumer does
        # not disable room execution. Capabilities report accepting=False if
        # this worker itself could not start.
        if discussion_owner is not None:
            try:
                discussion_owner.start()
            except Exception:
                import logging as _discussion_logging
                _discussion_logging.getLogger(__name__).warning(
                    "discussion worker did not start", exc_info=True,
                )

        def _unregister_instance(reason: str = "shutdown") -> None:
            """Drop this serve's registry entry. Idempotent, never raises.

            ``reason`` is the exit path that called it — the same three words
            the teardown already uses on ``_close_socket_lane`` beside it — and
            it exists so the receipt below names WHICH ending removed the row.
            """

            if store_root_path is None:
                return
            try:
                from agent_runtime.serve_registry import (
                    serve_instance_path,
                    unregister_serve_instance,
                )

                row_path = serve_instance_path(store_root_path, os.getpid())
                if unregister_serve_instance(store_root_path):
                    # RS-3. The one line that marks the INSTANT this runtime
                    # stopped advertising itself. The drain's terminal frame is
                    # published before the teardown it accounts for, so until
                    # this existed nothing on the wire dated the row's removal —
                    # and that instant is what a contender's ``lock_held_by``
                    # has to be read against.
                    _service_log(
                        {
                            "event": "serve_instance_unregistered",
                            "boot_id": boot_id,
                            "pid": os.getpid(),
                            "reason": reason,
                            "path": str(row_path),
                        }
                    )
                else:
                    # Reported, not swallowed. A clean exit that leaves its
                    # entry behind makes the registry claim a serve that is on
                    # its way out, and the next client's discovery would try to
                    # connect to it. The read-time classification eventually
                    # calls it dead — "eventually" is the part an operator has
                    # to be able to see coming.
                    if row_path.exists():
                        _service_log(
                            {
                                "event": "serve_instance_unregister_failed",
                                "boot_id": boot_id,
                                "pid": os.getpid(),
                                "reason": reason,
                                "path": str(row_path),
                            }
                        )
            except Exception:
                pass

        # ── socket lane plumbing ────────────────────────────────────────────
        #
        # Everything below is inert on a stdio-only serve: ``socket_server`` is
        # None, no connection ever exists, and the stdio path never reaches a
        # branch that touches it.

        connection_sinks: dict[str, _SafeSink] = {}
        connection_sinks_lock = threading.Lock()

        def _emit_safely(sink: Any, frame: dict[str, Any]) -> None:
            try:
                sink.emit(frame)
            except Exception:
                pass

        def _sink_for(connection: Any) -> Any:
            """The STABLE per-connection request sink.

            Stable matters twice: the partial-line buffers in
            ``_LineFrameProxy`` are keyed on the sink's identity, and a sink
            rebuilt per line would split one handler's output across two
            buffers mid-line.
            """

            if connection is None:
                return frames
            with connection_sinks_lock:
                sink = connection_sinks.get(connection.key)
                if sink is None:
                    sink = _SafeSink(connection)
                    connection_sinks[connection.key] = sink
                return sink

        def _owner_of(connection: Any) -> str:
            return "stdio" if connection is None else str(connection.key)

        def _deny_subscribe(
            sink: Any,
            connection: Any,
            lane: Any,
            reason: str,
            **extra: Any,
        ) -> None:
            """Refuse a subscribe: the LINE the operator reads and the FRAME the
            client reads, in that order, from one place.

            Six branches refuse a subscribe and every one of them used to emit
            the frame inline and log nothing. On 2026-09-04 the Windows cockpit's
            stream to the Mac died 7 ms after its subscribe and neither machine
            could say which refusal it was: the reason lived only in the
            launcher's memory and went out with the connection
            (dialable-addresses §8, R-D26). Single-homing both halves is what
            stops a seventh branch from growing the frame and forgetting the
            line — the failure this helper exists to make impossible rather than
            merely unlikely.

            The log goes FIRST, deliberately. The refusals worth reconstructing
            are the ones on a connection that is already going away, and a client
            that never reads its frame is exactly the case the operator has only
            this serve's own log for.

            The frame is unchanged, key for key and in order: the launcher's
            connector switches on ``event``/``reason``, and the stream-lane
            parity and socket-lane tests pin the shape.
            """

            from agent_runtime.stream import log_stream_denied

            log_stream_denied(
                reason=reason,
                lane=lane,
                connection=_owner_of(connection),
                # The attach line's own additive field, and for its reason: a
                # census of who attached is a census of names, not keys.
                client=getattr(connection, "client", None),
                # WHICH DOOR the refusal came through — the question the field
                # gap was actually about, because a denial on the gateway lane is
                # another machine's cockpit and a denial on the loopback lane is
                # this one's. The tier rides beside it because a paired device
                # has one and nothing else does. Neither names the device: the
                # connection key identifies the connection to a reader of THIS
                # process's log and to nobody else, which is the whole of what
                # this line needs.
                transport=(
                    "stdio"
                    if connection is None
                    else getattr(connection, "transport", None)
                ),
                tier=getattr(connection, "device_tier", None),
                **extra,
            )
            sink.emit(
                {
                    "event": "subscribe_denied",
                    "lane": lane,
                    "reason": reason,
                }
            )

        def _accepted_fold_entities() -> Any:
            """What the SHARED producer may promote: the intersection of every
            attached subscriber's declaration.

            One producer feeds N subscribers (``serve_stream_hub``), so a patch
            frame promoted for a client that declared ``office_actor`` would ALSO
            be fanned out to whoever sits next to it, and a subscriber that
            cannot fold that entity answers with a full re-hydrate. Intersection
            is the only rule under which a promotion is safe for everyone in the
            room; a client that declared nothing contributes the historical set,
            so a room of only today's clients accepts exactly today's set.

            The room is BOTH LANES. ``stream_fold_entities`` holds the socket
            stream lane's declarations, but an RPC office subscriber
            (``serve_office_subscriptions``) registers against this same hub and
            is fanned exactly the same frames — it is an attached subscriber in
            every sense that matters here. Reading only the stream table is how
            ``office_actor`` was never once promoted in production: an
            office-only room resolved to the historical default, every office
            write demoted to a full core, and the push lane could emit nothing
            but resync. Both tables are read, so the intersection is taken over
            everyone actually attached.

            **Read LIVE, once per drain pass, not once per producer.** It used to
            be producer-build-time, and the note here said a LEAVE deliberately
            does not re-widen the running producer because re-widening would mean
            RESTARTING it — charging every remaining subscriber a fresh full core
            to buy back a promotion they were living without. That trade is gone:
            ``stream_frames`` takes this derivation as ``fold_room`` and re-reads
            it between drains, so a leave re-widens for free and a JOIN is
            noticed by a producer nobody restarted.

            The second half is what makes a restart-free join safe at all. A
            joiner that folds LESS than the frozen floor would otherwise be
            handed bare patches inside that floor and answer them with
            re-hydrates — the promotion regression this negotiation exists to
            prevent, arriving through the door built to avoid a restart. Read
            live, the next pass sees the narrowed floor and splits instead.

            The window that remains is one drain pass wide: a batch already
            GATED when a declaration lands can still go out bare. It costs the
            joiner one resync and cannot lose an event — the client's
            ``base_offset`` gate refuses a patch it cannot chain — and it is
            named here rather than left for a reader to find.
            """

            from agent_runtime.patch_coverage import accepted_fold_entities

            return accepted_fold_entities(_room_fold_declarations())

        def _room_fold_declarations() -> list[Any]:
            """Every attached subscriber's declaration, both lanes, once.

            Was inline in ``_accepted_fold_entities``; lifted out when a SECOND
            operator over the same room arrived (``_promoted_fold_entities``'s
            union). Two readers assembling the same list from the same two tables
            is how one of them quietly stops reading the office registry, which is
            the bug the intersection already shipped once.
            """

            from agent_runtime.serve_office_subscriptions import OFFICE_SUBSCRIPTIONS

            with lane_lock:
                declarations = list(stream_fold_entities.values())
            # Taken OUTSIDE ``lane_lock``: the registry holds a lock of its own,
            # and the two are never nested in the opposite order anywhere.
            declarations.extend(OFFICE_SUBSCRIPTIONS.declarations())
            return declarations

        def _promoted_fold_entities() -> Any:
            """What the shared producer may promote for SOMEBODY: the UNION.

            R10's assigned consequence, closed here. The intersection above is
            the only safe rule while a fan-out can deliver exactly one shape of a
            frame, and it has a cost the drop-latency tables did not price: a
            Stage 5 phone declaring a narrow chat-first fold DEMOTES the desktop
            beside it to a full ~1 MB core on every office write. Correct, and
            paid by the client that did nothing.

            Now a batch can go out as a ``fold_variants`` envelope — the promoted
            patch and the demoted core together — and each subscriber's pump
            resolves it against its own declaration
            (:func:`agent_runtime.stream.resolve_fold_variant`). So the producer
            promotes whenever ANYBODY can fold, and the demotion is per
            subscriber. The intersection is still derived and still shipped, as
            the ROOM'S FLOOR on the hydrate's echo — a value true for every
            recipient of a frame that is fanned to all of them.

            **With one subscriber these two functions return the same set**, the
            envelope is never built, and the wire does not move by a byte. That
            is not a convention: ``_batch_frames_with_liveness`` takes the
            promoted branch only when the floor REFUSED a batch the union
            accepts, which an equal pair cannot produce.
            """

            from agent_runtime.patch_coverage import union_fold_entities

            return union_fold_entities(_room_fold_declarations())

        def _room_wants_stale_first() -> bool:
            """Does anybody attached to the shared producer PAINT a whole core?

            Same room as ``_accepted_fold_entities`` above — both lanes, read at
            producer-build time — and deliberately the OPPOSITE operator, which
            is the sentence worth keeping. Intersection is right there because a
            PROMOTION must be safe for everyone fanned the frame: one subscriber
            that cannot fold ``office_actor`` makes the promotion wrong for the
            room. Union is right here because the stale-first hydrate is an EXTRA
            frame that a non-painting subscriber merely ignores: the office sink
            discards every row that is not an ``office_actor`` under its own
            workspace, so a stale core costs it a discard and costs the painting
            subscriber beside it the whole point of EG-3.1. One painter is enough;
            a room of office-only sinks answers False, and the boot's single
            stale core stays available for the argv lane the launcher is actually
            on (measured 2026-08-18: the office subscribe attaches 0.1–0.2s
            first, and under the old process-global one-shot it won two boots in
            three and threw the paint away).

            The predicate is membership in ``stream_fold_entities``, not its
            values: that table is the socket STREAM lane's, one entry per
            subscribed connection, and a stream subscriber is by construction a
            consumer of whole hydrate/delta frames. The office registry's
            subscribers contribute False — the union over an empty set of
            painters is False — which is why they are not read here at all.
            """

            with lane_lock:
                return bool(stream_fold_entities)

        #: Does an INJECTED source factory want the negotiated fold set? Answered
        #: once, by signature — never by calling it and catching ``TypeError``,
        #: which would swallow a TypeError raised INSIDE a zero-arg factory and
        #: retry it at a different arity (the reasoning ``serve_stream_hub``
        #: records for its own stop-event probe, one seam up).
        stream_factory_takes_fold_entities = False
        if stream_source_factory is not None:
            try:
                inspect.signature(stream_source_factory).bind(frozenset())
                stream_factory_takes_fold_entities = True
            except (TypeError, ValueError):
                stream_factory_takes_fold_entities = False

        def _stream_source(stop: Any = None) -> Any:
            """The shared subscription producer. One per serve, never per client.

            Takes the hub's per-GENERATION stop event (the hub probes for it by
            signature — ``serve_stream_hub._accepts_stop_argument``) and hands it
            to the runtime's own cancellation seam, which is what makes an
            abandoned generation stop before its next frame instead of after it.

            WHY THE SEAM AND NOT A CHECK BETWEEN FRAMES. Checking ``stop`` around
            the ``yield`` here buys NOTHING, and measuring it is the only way to
            know that: ``StreamHub._produce`` already tests ``_should_stop``
            immediately after every ``next()``, so a wrapper that tested the same
            flag at the same moment would be a second copy of a check that had
            already been made. Measured on the real producer at production
            cadences, both spellings left the producer thread alive for 3.08s past
            ``hub.stop(join_timeout=2.0)`` — identical to no fix at all. A fence
            that changes nothing while looking staffed is worse than an absent
            one.

            The park is INSIDE ``next()``: ``stream_frames`` polls its event tail
            every 250ms and only YIELDS on a frame, so a quiet lane surfaces once
            per 5s heartbeat and nothing outside can interrupt the gap. The one
            thing that can is ``request_control``, the seam that module exists for
            — "the read-only ``harness stream`` handler is infinite and must
            release its worker when its consumer disconnects", which is this
            situation exactly, one caller over. Bound to the stop event, every
            ``request_cancelled()`` probe inside the tail loop (its bounded sleep
            slices at 100ms, and the snapshot-build wait beside it) becomes a
            probe of THIS generation's liveness, and the generator returns
            cooperatively at its own next safe point. Same measurement,
            afterwards: ``hub.stop()`` returns with zero producers alive.

            The ``stop`` default keeps the factory callable with no argument (a
            direct caller, and the hub itself if the probe ever stops matching),
            in which case the scope is bound to an event nobody sets and the
            behaviour is exactly what it was.

            An INJECTED ``stream_source_factory`` is deliberately not handed the
            event: its arity contract is the fold-set one negotiated above, and a
            test fake owns its own lifecycle by construction.
            """

            fold_entities = _accepted_fold_entities()
            # The union, derived beside the floor and with the same lifetime, so
            # a join that widens the room re-derives both together. An INJECTED
            # factory is deliberately not handed it: its arity contract is the
            # one-set one negotiated above, and a test fake that wanted the split
            # lane would be testing the hub rather than itself.
            promote_entities = _promoted_fold_entities()
            # Derived HERE, beside the fold set, for the same reason and with the
            # same lifetime: ``StreamHub.subscribe`` restarts the producer, so
            # every join re-derives it. That restart is what makes the boot work
            # under the office-first ordering — the first generation is built for
            # an office-only room and takes nothing, and the painting subscriber's
            # own join builds the generation that does take it.
            wants_stale_first = _room_wants_stale_first()
            if stream_source_factory is not None:
                return (
                    stream_source_factory(fold_entities)
                    if stream_factory_takes_fold_entities
                    else stream_source_factory()
                )
            from agent_runtime.request_control import request_cancel_scope
            from agent_runtime.serde import to_jsonable
            from agent_runtime.stream import stream_frames

            # Never-set stand-in for the no-argument call, so the body below has
            # ONE shape rather than a scoped and an unscoped variant to keep in
            # step.
            generation_stop = stop if stop is not None else threading.Event()

            def _generate():
                # The scope is entered on the PRODUCER thread — this body runs
                # there, and a fresh thread starts with an empty context, so
                # nothing of serve's own dispatch is being overwritten and the
                # reset on close lands in the same context that set it.
                with request_cancel_scope(generation_stop):
                    # ``caller="hub"``: every build this producer pays for is
                    # attributed to the SHARED lane rather than to whichever
                    # subscriber happened to trigger the restart — the serve hub
                    # is one producer for N subscribers by construction, and a
                    # build line naming a subscriber would be a lie about who
                    # pays.
                    for frame in stream_frames(
                        fold_entities=fold_entities,
                        promote_fold_entities=promote_entities,
                        # The LIVE room, re-read by the producer once per drain
                        # pass. The two sets above still seed the hydrate's echo
                        # (resolved once, so a client's ack and its baseline
                        # cannot disagree); this is what a batch is promoted
                        # against, and it is what lets a restart-free join —
                        # the office lane's, and a watermark resume's — be
                        # noticed by a producer nobody restarted.
                        fold_room=lambda: (
                            _accepted_fold_entities(),
                            _promoted_fold_entities(),
                        ),
                        caller="hub",
                        wants_stale_first=wants_stale_first,
                    ):
                        # Byte-for-byte the frames ``harness stream`` writes: a
                        # subscriber folds the same hydrate/delta/patch/heartbeat
                        # shapes it already folds, so the socket lane introduces
                        # no second stream contract to keep in sync.
                        yield to_jsonable(frame)

            return _generate()

        def _ensure_stream_hub() -> Any:
            nonlocal stream_hub
            with lane_lock:
                if stream_hub is None:
                    from agent_runtime.serve_stream_hub import (
                        DEFAULT_BUFFER_LIMIT,
                        DEFAULT_BYTE_LIMIT,
                        StreamHub,
                    )

                    stream_hub = StreamHub(
                        _stream_source,
                        buffer_limit=int(stream_buffer_limit or DEFAULT_BUFFER_LIMIT),
                        byte_limit=int(stream_byte_limit or DEFAULT_BYTE_LIMIT),
                        log=_service_log,
                    )
                return stream_hub

        # The office push lane reaches the hub through a FACTORY, not a handle:
        # `_ensure_stream_hub` builds lazily and `_close_socket_lane` can swap
        # the hub out across a drain, so a captured instance would go stale at
        # exactly the moment a client reconnects. Binding the factory also means
        # an RPC subscriber COUNTS as a hub subscriber — load-bearing, because
        # the hub stops producing when its room empties, and the whole point of
        # the ruling is that the launcher stops joining the legacy stream.
        from agent_runtime.serve_office_subscriptions import OFFICE_SUBSCRIPTIONS

        # `log` is where a RE-BASELINE is billed. A second subscribe on one
        # connection replaces the first rather than being refused, which cures a
        # client stuck holding a baseline it refused — but `StreamHub.subscribe`
        # restarts the producer, so a re-baseline makes every OTHER subscriber
        # on this hub pay a fresh full core. The client sees `replaced` on its
        # own reply; without this line the operator would see a retry loop only
        # as an unexplained climb in the hub's generation counter.
        #
        # `_accepted_fold_entities` rides along because a restart-free rejoin is
        # only safe when the joiner is not NARROWING what the room may promote,
        # and the room is BOTH LANES — the stream lane's declaration table is
        # this closure's, unreachable from a process-global registry. Lending
        # the derivation keeps one authority for what the room accepts; reading
        # only one of the two tables is the mistake this lane already made once.
        OFFICE_SUBSCRIPTIONS.bind(
            _ensure_stream_hub,
            log=_service_log,
            accepted_fold_entities=_accepted_fold_entities,
        )

        def _release_subscription(connection: Any) -> None:
            """A client left. Unsubscribe it, and do NOTHING else.

            Not a cancellation, not a shutdown, not a state change: the runtime
            outliving its clients is the entire point of the durable service,
            and a disconnect that touched backend state would reintroduce the
            per-client lifecycle ownership this workstream exists to retire.
            """

            key = _owner_of(connection)
            with lane_lock:
                hub = stream_hub
                # A departed client's fold declaration must not keep narrowing
                # the lane for the clients that remain — the next subscribe
                # re-derives the accepted set from whoever is actually here.
                stream_fold_entities.pop(key, None)
            if hub is not None:
                try:
                    hub.unsubscribe(key)
                except Exception:
                    pass
            # The office lane's keys are NAMESPACED away from `key` (which the
            # stream lane owns), so the unsubscribe above cannot reach them and
            # a departing connection would otherwise leak a subscriber — which
            # would in turn keep a producer alive for nobody.
            from agent_runtime.serve_office_subscriptions import (
                OFFICE_SUBSCRIPTIONS as _office_subs,
            )

            _office_subs.release(key)
            # S2d's lane is namespaced away from both of the above for the same
            # reason the office lane is, so a departing connection would
            # otherwise leave a sink the fan-out keeps writing to — which is how
            # a push registry starts holding a dead socket open.
            from agent_runtime.serve_gateway_peers_rpc import (
                PEER_DIRECTORY_SUBSCRIPTIONS as _peer_dir_subs,
            )

            _peer_dir_subs.release(key)
            if connection is not None:
                connection.subscribed = False
                with connection_sinks_lock:
                    connection_sinks.pop(connection.key, None)

        def _reclaim_abandoned_streams(connection: Any) -> int:
            """Cancel the departed connection's infinite ``harness stream``.

            THE POOL IS FOUR WORKERS WIDE and ``harness stream`` is an argv
            request that never returns, so every abandoned one is a worker
            permanently gone. The ``cancel`` op's own comment says what that
            costs — "otherwise four watchdog cycles exhaust the entire serve
            pool with abandoned streams" — and until now the ONLY thing that
            set the event was that op, sent by a launcher that came BACK. A
            client that simply died, or a socket session that closed, left its
            stream running forever, and the next argv request queued behind a
            pool with no free worker and emitted nothing at all. That is the
            measured 2026-08-27 shape: >120s of zero frames for a ``characters
            list``, the identical argv answered in ~6s on a later connection.
            ``agent_runtime.request_control`` already states this as the
            contract — the stream handler "must release its worker when its
            consumer disconnects" — and nothing implemented the disconnect half.

            Deliberately narrower than ``_release_subscription``'s "do NOTHING
            else", and not a softening of it: that rule is about BACKEND state
            surviving its clients, which is the whole durable-service premise.
            This touches no backend state. It reclaims a worker that is
            producing frames for a socket nobody is reading, and it reclaims it
            for exactly the one request shape the cancel path already calls the
            sole safe cooperative exception — read-only, infinite, with a
            polled seam. Chat turns and every mutation are untouched: they stay
            uninterruptible, because a half-applied mutation is worse than a
            held worker and a killed turn is lost recording.
            """

            if connection is None:
                return 0
            owner = _owner_of(connection)
            with inflight_lock:
                abandoned = [
                    request
                    for request in inflight.values()
                    if request.is_runtime_stream and request.owner == owner
                ]
            for request in abandoned:
                request.cancel_event.set()
            if abandoned:
                _service_log(
                    {
                        "event": "serve_stream_worker_reclaimed",
                        "boot_id": boot_id,
                        "connection": owner,
                        "client": getattr(connection, "client", None),
                        "request_ids": sorted(item.rid for item in abandoned),
                    }
                )
            return len(abandoned)

        def _on_connection_closed(connection: Any) -> None:
            """The ONE disconnect path: unsubscribe, then reclaim the worker.

            Both doors call this rather than ``_release_subscription`` on its
            own, so a lane added later cannot get one half and not the other —
            the same reasoning ``_broadcast_lanes`` is written down with.
            """

            _release_subscription(connection)
            _reclaim_abandoned_streams(connection)

        def _broadcast_lanes(frame: dict[str, Any]) -> None:
            """Tell every attached client, on whichever door it came through.

            One call site per announcement rather than two, because the failure
            mode of two is silent and asymmetric: a drain that reached the
            loopback launcher and not the paired phone leaves the phone waiting
            on a runtime that has gone, and nothing anywhere says so. Every
            broadcast in this loop goes through here, so a lane added later is
            added once.
            """

            for server in (socket_server, gateway_server):
                if server is None:
                    continue
                try:
                    server.broadcast(frame)
                except Exception:
                    pass

        def _close_socket_lane(reason: str) -> None:
            """Stop the hub, close every connection, release the ownership lock.

            Idempotent and never raises: it runs on the drain path, the
            shutdown path, and the EOF path, and any of them may be second.
            """

            nonlocal socket_server, socket_lock, stream_hub, gateway_server
            # Unbound FIRST, so a subscribe racing the drain is refused with a
            # typed `push_lane_unavailable` instead of registering against a hub
            # that is about to be stopped. The registry is process-global and
            # outlives this loop, so leaving it bound would also hand the next
            # serve_loop in the same process a factory closed over a dead lane —
            # which is a test-suite failure mode, not only a production one.
            from agent_runtime.serve_office_subscriptions import (
                OFFICE_SUBSCRIPTIONS as _office_subs,
            )

            _office_subs.bind(None)
            # The three swaps happen together, under the lock, and NOTHING
            # slow happens while it is held: whoever takes a handle owns
            # closing it, and a second caller gets None and does nothing.
            with lane_lock:
                hub, stream_hub = stream_hub, None
                server, socket_server = socket_server, None
                # The gateway listener is swapped under the SAME lock and by the
                # same closer. It has no lock and no registry entry of its own —
                # it is the loopback lane's dispatcher answering on a second
                # door — so a teardown that closed one and not the other would
                # leave a runtime that has drained still accepting devices.
                gateway, gateway_server = gateway_server, None
                lock, socket_lock = socket_lock, None
                stream_fold_entities.clear()
            if gateway is not None:
                try:
                    gateway.close(reason=reason)
                except Exception:
                    pass
            if hub is not None:
                try:
                    # One TOTAL budget for the hub, not one per subscriber
                    # join: the drain's exit watchdog is already armed, and a
                    # teardown that can outlast it is how a drained runtime
                    # kept running.
                    hub.stop()
                except Exception:
                    pass
            if server is not None:
                try:
                    server.close(reason=reason)
                except Exception:
                    pass
            if lock is not None:
                try:
                    lock.release()
                except Exception:
                    pass

        def _build_mismatch(client_build: Any) -> bool | None:
            """Does the client's build disagree with the code answering it?

            None means NOT COMPARABLE — the client named no build, or this
            runtime could not measure its own. A fabricated ``false`` there
            would answer "you are current" for a runtime that does not know,
            which is exactly the false-all-clear the build stamp exists to
            retire. Prefix comparison so a short hash and a full one agree.
            """

            serve_commit = build_block.get("commit")
            if not isinstance(serve_commit, str) or not serve_commit:
                return None
            if not isinstance(client_build, str) or len(client_build.strip()) < 7:
                return None
            claimed = client_build.strip().lower()
            actual = serve_commit.lower()
            return not (
                actual.startswith(claimed) or claimed.startswith(actual)
            )

        def _hello_ok_frame(message: dict[str, Any], connection: Any) -> dict[str, Any]:
            """The version handshake, enforced end to end at the door."""

            from agent_runtime.serve_socket import HELLO_CONTRACT_VERSION

            return {
                "event": "hello_ok",
                "pid": os.getpid(),
                "boot_id": boot_id,
                # L-h item 3. The socket greeting is the ONLY frame an
                # attach-first client reads, so this is where it learns that
                # what it just attached to is a durable service rather than
                # somebody else's stdio child.
                "service": service,
                "starter_pid": starter_pid,
                # The frame-protocol contract this service speaks. A client that
                # does not recognise it must not proceed on hope.
                "contract": SERVE_SCHEMA_VERSION,
                # Restated from ``server_hello`` so a client that reconnects and
                # reads only the reply still learns which handshake it just
                # completed.
                "hello_contract": HELLO_CONTRACT_VERSION,
                "schema_version": SERVE_SCHEMA_VERSION,
                # Which DOOR this client came through, read off the connection
                # rather than written as a constant. It was "socket" when there
                # was one listener; a device reading "socket" here would be told
                # it is on the local lane, and `ops` below would then advertise
                # a verb this connection is refused.
                "transport": connection.transport,
                "connection": connection.key,
                # D12 — the address this client actually REACHED, read off the
                # accepting socket's own ``getsockname()`` rather than off any
                # candidate list. Every other address this install offers is an
                # inference; this one is a measurement, and it is the only one
                # that already proved a packet got through. Absent when the
                # socket could not answer or the bind is not a dialable
                # address — never a fabricated `0.0.0.0`, which is the thing
                # R-D1 spent a wave removing from every payload.
                **(
                    {"reached_at": dict(connection.reached_at)}
                    if isinstance(getattr(connection, "reached_at", None), dict)
                    else {}
                ),
                "runtime_root": runtime_root,
                "build": build_block,
                # The socket greeting's half of the install identity. A socket
                # client never reads ``ready``, and from Stage 1 a REMOTE client
                # reads nothing else — which install it just reached has to be
                # answerable from the handshake it already performs, not from a
                # ``runtime_root`` path that means nothing on another machine.
                "install": install_block,
                # Visible, never fatal: a client on other code still gets to
                # work, and now KNOWS it is talking to a different build.
                "build_mismatch": _build_mismatch(connection.client_build),
                "draining": drain_state is not None,
                # The socket's half of the method-lane advertisement. A socket
                # client never reads ``ready`` (that frame goes to the stdio
                # owner), so without this it could only learn the method set by
                # asking ``version`` — one extra round trip on every connect,
                # for something the handshake it already performs can carry.
                "rpc": serve_rpc.manifest(),
                # Same argument, the OP lane's half — and the place the
                # advertisements differ per door: ``shutdown`` is refused on
                # both sockets, and ``drain`` additionally on the gateway one.
                # A device learns what it may ask by MEMBERSHIP rather than by
                # trying and reading an error.
                "ops": ops_manifest(
                    transport=connection.transport, service=service
                ),
                # What the SECOND door is doing, on the greeting a client
                # already reads. For a device this is the lane it is standing
                # on; for the local launcher it is the answer to "is this
                # install reachable from my phone", which nothing else on this
                # frame can give it.
                "gateway": gateway_block,
                # The ONE frame in this lane that ever carries a secret, and it
                # carries it exactly once: the credential a pairing code was
                # just redeemed for. Read-and-CLEAR, so the value is gone from
                # the connection before this function returns and cannot reach
                # `payload()`, a log line, or a second reply. Absent on every
                # other handshake, which is every handshake after the first.
                **_pairing_block(connection),
            }

        def _connections_frame() -> dict[str, Any]:
            # S2c (R-S2-8). One stat on a read this frame was making anyway.
            # The serve is the process that NOTICES an external write because it
            # is the one that reads repeatedly; a fresh CLI process seeds on its
            # first read and emits nothing, having no baseline to claim a change
            # against.
            if store_root_path is not None:
                try:
                    from agent_runtime.gateway_peers import note_peer_store_read

                    note_peer_store_read(store_root_path)
                except Exception:
                    pass
            payload: dict[str, Any] = {"event": "socket_connections", "boot_id": boot_id}
            with lane_lock:
                server = socket_server
            if server is None:
                payload["enabled"] = False
                payload["socket"] = socket_block
                payload["count"] = 0
                payload["connections"] = []
            else:
                payload["enabled"] = True
                payload.update(server.connections_payload())
            with lane_lock:
                gateway = gateway_server
            # The gateway lane gets its OWN sub-block rather than having its
            # rows merged into the list above, and the reason is that the
            # top-level keys are per-listener facts: `port`, `host`, `count`,
            # `max_connections`, `rejected_by_reason`. Merged, every one of them
            # would answer for two listeners at once and none of them would say
            # which. Additive and absent-when-off, so every existing consumer of
            # this frame reads exactly the shape it was written against.
            if gateway is not None:
                payload["gateway"] = {
                    "enabled": True,
                    **gateway.connections_payload(),
                }
            else:
                payload["gateway"] = {"enabled": False, "outcome": gateway_block.get("outcome")}
            with lane_lock:
                hub = stream_hub
            payload["subscriptions"] = (
                hub.stats() if hub is not None else {"subscribers": 0}
            )
            return payload

        def _handle_socket_line(line: str, connection: Any) -> None:
            """Every authenticated socket line enters the SHARED dispatcher."""

            _handle_line(line, _sink_for(connection), connection=connection)

        def _finish_drain(code: int, frame: dict[str, Any]) -> None:
            """Emit the drain's terminal frame, then get the process out.

            Order is the contract: the frame is written and flushed BEFORE any
            exit path, because a drain that took the process down without
            accounting for what it refused and what it completed is
            indistinguishable from the crash the drain exists to replace.
            """

            nonlocal drain_exit_code, pool_shutdown_wait

            # A drain has ONE terminal frame. The latch is taken before
            # anything is published, so a mid-drain EOF racing a completing
            # drain cannot follow ``drain_complete`` with ``drain_abandoned``.
            with drain_terminal_lock:
                if drain_terminal_published.is_set():
                    return
                drain_terminal_published.set()
            drain_exit_code = code
            if code != 0:
                # Stuck workers: do NOT let the pool's context manager join
                # them (it would hang exactly as long as "forever"), and do not
                # trust a plain return either — concurrent.futures' atexit hook
                # joins worker threads on the way out of the interpreter.
                pool_shutdown_wait = False
            # THE WATCHDOG IS THE FIRST ACT, before the frame, the broadcast,
            # and the teardown — because every one of those can block. It used
            # to be armed after them, so the very steps most likely to hang ran
            # unwatched: broadcasting to a wedged reader parks a ``sendall``
            # for IO_TIMEOUT, and the hub's joins were a per-subscriber budget
            # that SUMMED. And the wakeup itself can block: observed live on
            # Windows (2026-08-13), closing the protocol descriptor a reader is
            # parked on does not return until that read does, and the child
            # outlived its own completed drain. From here to process exit
            # everything is inside one deadline.
            if hard_exit is not None:
                threading.Thread(
                    target=_force_exit_after_drain,
                    args=(code,),
                    name="harness-serve-drain-exit",
                    daemon=True,
                ).start()
            frames.emit(frame)
            # Socket clients are owed the SAME terminal frame: a client that
            # asked for the drain over the socket, and every client that was
            # merely attached, learns how it ended on the transport it is on.
            # Broadcast before teardown — after ``_close_socket_lane`` there is
            # nobody left to tell.
            _broadcast_lanes(frame)
            _close_socket_lane(reason="drain")
            _unregister_instance(reason="drain")
            # RL-16, and it has to be HERE rather than in an ``atexit`` hook:
            # the clean-drain tail can end in ``hard_exit``, which is
            # ``os._exit``, and the timeout tail always does — neither runs an
            # interpreter shutdown, so the fallback hook never fires on the one
            # path the launcher's restart verb actually takes.
            #
            # One word for all three drain outcomes (complete, timeout,
            # abandoned) on purpose: the sidecar answers *why did this runtime
            # end*, and the answer is "somebody drained it". HOW the drain went
            # is already on the wire, in the terminal frame this function just
            # published, with the counters that make it meaningful.
            _note_end("drained")
            _write_end()
            drain_finished.set()
            # The service park's wakeup, set at the SAME instant and for the
            # same reason as the reader's below: in service mode the main thread
            # is parked on this event rather than blocked on a pipe, so THIS is
            # what ``{"op":"drain","force":true}`` over the socket actually
            # pulls. Untouched and unread on every non-service boot.
            service_stop.set()
            if drain_wakeup is not None:
                try:
                    drain_wakeup()
                except Exception:
                    pass
            if hard_exit is None:
                # Unit-test path: the loop returns ``drain_exit_code`` and the
                # caller observes the frames. No process-level lever is pulled.
                return
            if code != 0:
                hard_exit(code)
                return
            # Clean drain: the reader gets its chance to unwind normally
            # (closed sockets, flushed writer, restored stdio) and the watchdog
            # above forces the exit if it does not. Nothing is waited on here.

        def _force_exit_after_drain(code: int) -> None:
            """Force the process down if the drain does not finish getting out.

            Armed at the START of ``_finish_drain``, so its deadline covers the
            WHOLE tail: publishing the terminal frame, broadcasting it, closing
            the socket lane (hub joins, connection closes, lock release),
            unregistering, waking the reader, and the reader unwinding. The
            normal case returns in milliseconds; anything else is a drained
            runtime that is still running, which is the state this exists to
            make impossible.

            Read from the module at call time on purpose — a test lowers it.
            """

            deadline = time.monotonic() + _DRAIN_EXIT_DEADLINE_SECONDS
            while time.monotonic() < deadline:
                if drain_finished.is_set() and reader_unwound.is_set():
                    return
                time.sleep(0.02)
            if hard_exit is not None:
                hard_exit(code)

        def _drain_monitor(state: _DrainState) -> None:
            deadline = state.started_monotonic + state.deadline_seconds
            last_progress = state.started_monotonic
            while True:
                with inflight_lock:
                    remaining = sorted(inflight)
                    # Read in the SAME critical section as the pending set: a
                    # timeout that decided "no chat turns" from a second,
                    # later read could kill the turn that started in between.
                    chat_turn_ids = sorted(
                        key for key, item in inflight.items() if item.is_chat_turn
                    )
                    # Read in the SAME critical section for the same reason,
                    # one line later: a generation that started between two
                    # reads would be killed by a timeout that had already
                    # decided nothing was holding.
                    long_run_ids = sorted(
                        key for key, item in inflight.items() if item.is_long_run
                    )
                if not remaining:
                    _finish_drain(
                        0,
                        {
                            "event": "drain_complete",
                            "pid": os.getpid(),
                            "boot_id": boot_id,
                            **state.counters(),
                            "drain_ms": state.elapsed_ms(),
                        },
                    )
                    return
                now = time.monotonic()
                if now >= deadline:
                    expiry = {
                        "event": "drain_timeout",
                        "pid": os.getpid(),
                        "boot_id": boot_id,
                        **state.counters(),
                        "drain_ms": state.elapsed_ms(),
                        "deadline_seconds": state.deadline_seconds,
                        # WHICH requests are stuck, by id — a timeout that
                        # only reported a count would leave the operator
                        # with nothing to correlate against the stack dump.
                        "stuck_request_ids": remaining,
                        # And WHY it is allowed to be stuck. A chat turn in
                        # flight is recording-safety work: this file's own
                        # contract says a supervisor must never recycle serve
                        # while ``chat_turns`` > 0, and a drain deadline firing
                        # `hard_exit` (which is `os._exit`) over one is that
                        # recycle by another name.
                        "held_by_chat_turns": len(chat_turn_ids),
                        "chat_turn_request_ids": chat_turn_ids,
                        # ADDITIVE, beside the two above rather than folded into
                        # them. `held_by_chat_turns` keeps its name and its
                        # meaning — a reader that only knows that key still
                        # reads a true number about chat turns, it just is not
                        # the whole reason the drain is being held any more.
                        # And the split is what the frame is FOR: "held by 1
                        # chat turn" and "held by 1 `characters rows`" are the
                        # same terminal:false with very different waits behind
                        # them, and an operator watching a restart deserves to
                        # know which.
                        "held_by_long_runs": len(long_run_ids),
                        "long_run_request_ids": long_run_ids,
                        "terminal": not (chat_turn_ids or long_run_ids),
                    }
                    if chat_turn_ids or long_run_ids:
                        # NOT terminal: say so, keep serving, re-arm. The frame
                        # is emitted every time the deadline lapses, so a
                        # supervisor watching a drain that is being held open
                        # sees each hold rather than silence.
                        state.note_deadline_held()
                        expiry.update(state.counters())
                        frames.emit(expiry)
                        _broadcast_lanes(expiry)
                        deadline = now + state.deadline_seconds
                        last_progress = now
                        time.sleep(max(0.0, drain_poll_interval_seconds))
                        continue
                    _finish_drain(DRAIN_TIMEOUT_EXIT_CODE, expiry)
                    return
                if now - last_progress >= _DRAIN_PROGRESS_INTERVAL_SECONDS:
                    progress = {
                        "event": "drain_progress",
                        "pending": len(remaining),
                        "request_ids": remaining,
                        "drain_ms": state.elapsed_ms(),
                    }
                    frames.emit(progress)
                    # The ONE drain frame that reached stdio and nothing else.
                    # Its entire purpose is that "a draining service never looks
                    # dead to a watchdog" — and the socket client IS such a
                    # watchdog: it reads with a finite timeout and reports
                    # `transport_failed` on silence. With the socket lane's
                    # minimum deadline, a drain holding a chat turn open puts
                    # the first socket-visible frame 30s out, so a healthy,
                    # completing drain reported a transport failure and exit 6.
                    _broadcast_lanes(progress)
                    last_progress = now
                time.sleep(max(0.0, min(drain_poll_interval_seconds, deadline - now)))

        # ── the shared dispatcher ───────────────────────────────────────────
        #
        # ONE op table, N transports. ``sink`` is where this message's answers
        # go (stdout for stdio, the originating connection for a socket client)
        # and ``connection`` is None on stdio. Every branch below was previously
        # inline in the stdio reader loop and is unchanged in behaviour: on
        # stdio, ``sink is frames`` and ``connection is None``, so the frames,
        # their order, and the exit codes are byte-identical.

        def _handle_line(line: str, sink: Any, *, connection: Any = None) -> str | None:
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                sink.emit(
                    {
                        "id": None,
                        "event": "error",
                        "error": "invalid_request",
                        "detail": "request line is not valid JSON",
                    }
                )
                return None
            if not isinstance(message, dict):
                sink.emit(
                    {
                        "id": None,
                        "event": "error",
                        "error": "invalid_request",
                        "detail": "request must be a JSON object",
                    }
                )
                return None
            return _handle_message(message, sink, connection=connection)

        def _handle_message(
            message: dict[str, Any], sink: Any, *, connection: Any = None
        ) -> str | None:
            """Answer one op. Returns ``"shutdown"`` to stop the stdio reader."""

            nonlocal drain_state

            op = message.get("op")
            if op == "ping":
                sink.emit(_busy_frame())
                return None
            if op == "hello":
                # The socket lane authenticates BEFORE this dispatcher ever
                # sees a line, so a hello arriving here is a second one (or a
                # stdio client speaking the socket handshake at a pipe that
                # needs no handshake). Typed, and never a second auth path.
                sink.emit(
                    {
                        "event": "error",
                        "error": "unexpected_hello",
                        "detail": (
                            "this connection is already established; hello is the "
                            "first line of a SOCKET connection only"
                        ),
                    }
                )
                return None
            if op == "version":
                # Re-askable at any time, and deliberately NOT re-measured:
                # the answer is what code THIS interpreter loaded, which
                # cannot change while it lives. A client comparing against
                # its own install is how "the service is stale" becomes a
                # measurement instead of a theory.
                try:
                    from agent_runtime.build_stamp import build_stamp

                    version_build = build_stamp().payload()
                except Exception as exc:
                    version_build = {
                        "commit": None,
                        "dirty": None,
                        "source": "unknown",
                        "reason": f"stamp_failed:{type(exc).__name__}",
                        "code_tree": None,
                        "code_tree_rule": None,
                        "code_tree_reason": f"stamp_failed:{type(exc).__name__}",
                    }
                sink.emit(
                    {
                        "event": "version",
                        "schema_version": SERVE_SCHEMA_VERSION,
                        "pid": os.getpid(),
                        "boot_id": boot_id,
                        # The transport THIS reply came over — honest per
                        # connection, and unchanged for every stdio consumer.
                        "transport": (
                            "stdio" if connection is None else connection.transport
                        ),
                        "runtime_root": runtime_root,
                        # L-h item 3, re-askable like everything else on this
                        # reply: a client that attached hours ago must be able
                        # to re-read what it is attached to without a restart it
                        # cannot cause.
                        "service": service,
                        "starter_pid": starter_pid,
                        "build": version_build,
                        "auth": auth_block,
                        # Re-askable like the two blocks above it. Resolved ONCE
                        # at boot and echoed, not re-read: an operator rename
                        # (``harness gateway id --set-name``) writes the file,
                        # but the identity this SESSION greeted with is the one
                        # its clients correlate against, and re-reading here
                        # would let a frame disagree with the greeting that
                        # opened the connection.
                        "install": install_block,
                        "draining": drain_state is not None,
                        # Additive: what else is attached to this runtime, on
                        # the reply a client already asks for.
                        "socket": socket_block,
                        # Re-askable like the socket block above it: a client
                        # that reconnects after an operator turned the lane on
                        # (or after it failed to come up) must be able to learn
                        # that without a restart it cannot cause.
                        "gateway": gateway_block,
                        "connections": _connections_frame(),
                        # Re-askable, like the build stamp beside it and for the
                        # same reason: a durable service outlives the install it
                        # was started from, so "which methods does the thing I
                        # am attached to actually have" must be answerable at
                        # any time, not only at the greeting a client may have
                        # read hours ago.
                        "rpc": serve_rpc.manifest(),
                        # Re-askable for the same reason, and honest about the
                        # transport it just came over: ``shutdown`` is in the
                        # stdio answer and out of the socket one.
                        "ops": ops_manifest(
                            transport=(
                                "stdio" if connection is None else connection.transport
                            ),
                            service=service,
                        ),
                    }
                )
                return None
            if op == "connections":
                sink.emit(_connections_frame())
                return None
            if op == "subscribe":
                lane = message.get("lane", "stream")
                if lane != "stream":
                    _deny_subscribe(sink, connection, lane, "unsupported_lane")
                    return None
                if drain_state is not None:
                    _deny_subscribe(sink, connection, "stream", "draining")
                    return None
                # Optional patch-fold capability declaration. ABSENT means the
                # client said nothing — the historical {persona_instance,
                # incident} — which is what every client in the field sends and
                # is exactly today's wire. Present-but-malformed is REFUSED
                # rather than quietly read as absent: a client that meant to
                # narrow the set and was silently widened back to the historical
                # one would get patches it cannot fold, which is the precise
                # failure this negotiation exists to prevent.
                declared_raw = message.get("fold_entities")
                if declared_raw is None:
                    declared_fold_entities: Any = None
                elif isinstance(declared_raw, list) and all(
                    isinstance(name, str) and name.strip() for name in declared_raw
                ):
                    declared_fold_entities = frozenset(
                        name.strip() for name in declared_raw
                    )
                else:
                    _deny_subscribe(sink, connection, "stream", "invalid_fold_entities")
                    return None
                # Optional watermark RESUME. Same discipline as the declaration
                # above: absent means the client asked for nothing (and gets the
                # hydrate it always got, with no `resume` key anywhere on the
                # ack, so a subscribe that predates this parameter is answered
                # byte-identically); present-but-malformed is REFUSED rather
                # than read as absent, because a client that meant to resume and
                # was silently re-baselined would pay the megabyte it asked not
                # to and have nothing to grep for.
                resume_raw = message.get("resume")
                resume_requested = resume_raw is not None
                resume_offset: Any = None
                if resume_requested:
                    if isinstance(resume_raw, dict):
                        resume_offset = resume_raw.get("event_offset")
                    else:
                        _deny_subscribe(sink, connection, "stream", "invalid_resume")
                        return None
                key = _owner_of(connection)
                hub = _ensure_stream_hub()
                if hub.has(key):
                    # ``at`` separates the two branches that share this reason,
                    # and they are different diagnoses: HERE the key was already
                    # attached before this frame arrived (a resubscribe, or a
                    # subscription the last generation never released), while the
                    # ``hub_join`` one below lost a race to a concurrent
                    # subscribe. The frame cannot tell them apart — the launcher
                    # switches on ``reason`` and that contract is fixed — so the
                    # log is the only place the difference can live.
                    _deny_subscribe(
                        sink, connection, "stream", "already_subscribed", at="precheck"
                    )
                    return None
                # Recorded BEFORE ``hub.subscribe``: that call starts the new
                # producer generation, which reads this table to decide what it
                # may promote. Recorded after, this subscriber's declaration
                # would not reach the very producer its own subscribe created.
                with lane_lock:
                    stream_fold_entities[key] = declared_fold_entities
                # THIS subscriber's own answer, not the room's. Per-subscriber
                # promotion made the room's intersection the wrong thing to echo
                # on a PER-CONNECTION ack: what this client will actually be
                # handed a patch for is its own declaration, because the fan-out
                # resolves each envelope against it. The room's floor is still
                # echoed — on the hydrate, which is one frame fanned to everyone
                # and can only honestly carry a value true for all of them.
                #
                # For a single subscriber the two are the same set, which is why
                # the byte-pinned `subscribed.json` capture does not move.
                from agent_runtime.patch_coverage import normalize_fold_entities

                accepted_entities = sorted(
                    normalize_fold_entities(declared_fold_entities)
                )
                raw_sink = connection.emit if connection is not None else frames.emit

                # The resume decision, taken AFTER this connection's declaration
                # is recorded and BEFORE the hub join, which is the only window
                # where both facts are true: the span is judged against what this
                # client says it folds, and the producer that will feed it can
                # already see the narrowed room (`stream_frames` re-reads the
                # room per drain pass — see `_room` there, which is what makes a
                # restart-free join safe at all).
                resume = None
                if resume_requested:
                    from agent_runtime.stream_resume import resolve_stream_resume

                    try:
                        resume = resolve_stream_resume(
                            resume_offset, fold_entities=declared_fold_entities
                        )
                    except Exception as exc:  # noqa: BLE001 - never fatal
                        # A resume that cannot be COMPUTED must still leave the
                        # client subscribed. The hydrate is the answer to every
                        # question this path could have answered more cheaply, so
                        # a failure here costs bytes and never a lane.
                        from agent_runtime.stream_resume import StreamResume

                        resume = StreamResume(
                            honored=False,
                            reason=f"resume_failed:{type(exc).__name__}",
                        )

                def _on_drop(reason: str, stats: dict[str, Any]) -> None:
                    # Typed, never silent: an unsubscribed client that was told
                    # nothing would keep folding a stream that stopped arriving
                    # and believe itself current.
                    #
                    # The buffer is bounded TWICE — by frame count and by bytes
                    # — so the drop has to say WHICH bound tripped and carry
                    # both sets of numbers. The hub measures all of this and
                    # this frame used to throw it away, reporting a count
                    # against a `buffer_limit` read from the CONFIG rather than
                    # from the hub (None whenever it was left at the default).
                    # A client told only `backpressure` cannot tell one that
                    # fell 256 heartbeats behind from one that pinned 32 MiB,
                    # which is the difference between resubscribing and fixing
                    # its reader.
                    _emit_safely(
                        sink,
                        {
                            "event": "subscription_dropped",
                            "lane": "stream",
                            "reason": reason,
                            "bound": stats.get("drop_bound"),
                            "frames_delivered": stats.get("frames_delivered"),
                            "frames_discarded": stats.get("frames_discarded"),
                            "bytes_discarded": stats.get("bytes_discarded"),
                            "buffer_limit": stats.get("frame_limit"),
                            "byte_limit": stats.get("byte_limit"),
                        },
                    )
                    _release_subscription(connection)
                    _service_log(
                        {
                            "event": "serve_stream_subscription_dropped",
                            "boot_id": boot_id,
                            "connection": key,
                            "client": getattr(connection, "client", None),
                            "reason": reason,
                            "bound": stats.get("drop_bound"),
                            "frames_discarded": stats.get("frames_discarded"),
                            "bytes_discarded": stats.get("bytes_discarded"),
                        }
                    )

                # ONE line per attachment, in the serve child's OWN log. The
                # subscriber census of the 2026-08-17 boot had to be
                # reconstructed from timestamps and still left one rider
                # unidentified, because nothing on any attach path said so —
                # every line in the window described a BUILD, and the builds
                # were what the census was trying to explain (plan EG-2.1).
                from agent_runtime.stream import log_stream_attach

                log_stream_attach(
                    op="subscribe",
                    purpose="stream_lane",
                    connection=key,
                    client=getattr(connection, "client", None),
                    fold_entities=",".join(accepted_entities) or "-",
                )
                # The ACK precedes the subscription, deliberately. The producer
                # starts pushing the moment ``subscribe`` returns, so acking
                # afterwards would let the hydrate overtake the ack — and a
                # client reading "everything up to my ack is a reply to
                # something else" would discard its own baseline.
                if connection is not None:
                    connection.subscribed = True
                ack: dict[str, Any] = {
                    "event": "subscribed",
                    "lane": "stream",
                    "connection": key,
                    "buffer_limit": hub.stats().get("buffer_limit"),
                        # What the producer will actually promote FOR THIS
                        # CLIENT. It used to be able to come back narrower than
                        # asked because another subscriber folded less; per
                        # subscriber promotion retired that — a room that
                        # disagrees now ships both halves and each pump takes
                        # its own. So this is the client's own declaration,
                        # normalized (an absent one resolving to the historical
                    # set, which is the answer it always got).
                    "fold_entities": accepted_entities,
                }
                # Present ONLY when a resume was asked for, so the ack a client
                # that asked for nothing receives is byte-for-byte the one it
                # received before this lane existed — which is what keeps the
                # launcher's `subscribed.json` capture from moving.
                if resume is not None:
                    ack["resume"] = resume.payload()
                sink.emit(ack)

                # The catch-up span, on THIS connection's own sink, between the
                # ack and the join. Both edges matter: after the ack, because a
                # client reads everything before its ack as a reply to something
                # else; before the join, because the hub's first frame has to be
                # able to CHAIN onto the last of these.
                #
                # A honoured resume with zero frames is the whole feature working
                # — the client was already current and is sent nothing at all,
                # where it used to be sent the core.
                if resume is not None and resume.honored:
                    for frame in resume.frames:
                        _emit_safely(sink, frame)

                if not hub.subscribe(
                    key,
                    sink=raw_sink,
                    on_drop=_on_drop,
                    # A honoured resume attaches to the RUNNING producer instead
                    # of restarting it, and that is the half that actually saves
                    # the megabyte: a restart re-baselines the room, so a resume
                    # that restarted would hand this client the very hydrate it
                    # just proved it did not need — and charge every other
                    # subscriber a fresh full core for the privilege.
                    #
                    # Safe because `stream_frames` re-reads the room per drain
                    # pass: a producer that has not been restarted still NOTICES
                    # this subscriber's declaration and splits for it. The hub's
                    # own floor still starts a producer when none is running, so
                    # a resume into an empty room is not a subscription attached
                    # to nothing.
                    restart_producer=not (resume is not None and resume.honored),
                    # What this pump resolves a split frame against. Passing the
                    # RAW declaration rather than the normalized one keeps
                    # "said nothing" distinguishable all the way down, exactly
                    # as `parse_fold_entities_option` argues at the other end.
                    declared=declared_fold_entities,
                ):
                    # Lost a race with another subscribe for the same key. Say
                    # so rather than leave a client believing it is attached.
                    if connection is not None:
                        connection.subscribed = False
                    # The declaration is deliberately LEFT in place. This branch
                    # means another subscribe for the same key won the race, so
                    # that key IS attached — dropping its declaration here could
                    # only WIDEN the lane under a subscriber that never asked
                    # for the wider set, which is the failure direction. A stale
                    # entry can only ever narrow, and ``_release_subscription``
                    # (or the lane close) clears it.
                    _deny_subscribe(
                        sink, connection, "stream", "already_subscribed", at="hub_join"
                    )
                return None
            if op == "unsubscribe":
                key = _owner_of(connection)
                with lane_lock:
                    hub = stream_hub
                was_subscribed = hub is not None and hub.has(key)
                _release_subscription(connection)
                sink.emit(
                    {
                        "event": "unsubscribed",
                        "lane": "stream",
                        "connection": key,
                        "was_subscribed": was_subscribed,
                    }
                )
                return None
            if op == "drain":
                if _is_gateway(connection):
                    # A paired device does not get to end a runtime other
                    # clients are using — not even at `console` tier, because
                    # `drain` is not a level mutation the tier speaks about: it
                    # is the lifecycle verb, and its effect is that this process
                    # stops and every other attached client is disconnected. A
                    # phone deciding that for the desktop it is a guest on is
                    # the wrong default, and "restart the runtime from my phone"
                    # is a verb somebody can add on purpose later. The refusal
                    # mirrors `shutdown`'s rather than inventing a shape, and
                    # `ops_manifest(transport="gateway")` already said so, so a
                    # well-behaved client never reaches this line.
                    sink.emit(
                        {
                            "event": "error",
                            "error": "op_not_available_on_gateway",
                            "detail": (
                                "drain ends this runtime for every attached "
                                "client; it is the local console's verb"
                            ),
                        }
                    )
                    return None
                if connection is not None and message.get("force") is not True:
                    # The socket lane's second key. `shutdown` is refused there
                    # outright because a client does not get to kill a service
                    # other clients are using; `drain` is the safe replacement
                    # verb, but it still ENDS this process, and any local
                    # process holding the root's secret can ask. One explicit
                    # field is a trivial cost for an operator and a real
                    # barrier against an automated or accidental restart.
                    sink.emit(
                        {
                            "event": "error",
                            "error": "drain_requires_force",
                            "transport": "socket",
                            "detail": (
                                "drain over the socket ends the service for every "
                                'attached client; resend as {"op":"drain","force":true}'
                            ),
                        }
                    )
                    return None
                # The EFFECTIVE deadline is decided here, server-side, from the
                # client's ask floored by the minimum for the TRANSPORT it came
                # in on. Over stdio the asker owns this process outright and the
                # ask stands as given (the pre-socket contract, untouched); over
                # the socket it is floored, because that asker is any local
                # process holding the root's secret and it is shortening a
                # promise made to work it cannot see.
                effective_minimum = (
                    drain_socket_minimum_deadline_seconds
                    if connection is not None
                    else _DRAIN_DEADLINE_FLOOR_SECONDS
                )
                effective_deadline = _drain_deadline_seconds(
                    message.get("deadline_seconds"),
                    drain_deadline_seconds,
                    minimum=effective_minimum,
                )
                # ONE critical section for the whole transition. The guard and
                # the install used to be a bare read-modify-write on a closure
                # variable, which was harmless while the only caller was the
                # single stdio reader and became a genuine race the moment N
                # connection threads could ask: two of them could both observe
                # ``None``, both install a ``_DrainState``, and the process
                # would then run two monitors, publish two terminal frames, and
                # split its counters across two objects. The "already draining"
                # answer is decided INSIDE the section that would have
                # installed it, so it cannot be decided against a state a
                # sibling thread is mid-way through replacing.
                with inflight_lock:
                    existing = drain_state
                    if existing is None:
                        drain_state = _DrainState(effective_deadline)
                        started = drain_state
                        pending_at_start = sorted(inflight)
                if existing is not None:
                    sink.emit(
                        {
                            "event": "drain_in_progress",
                            "drain_ms": existing.elapsed_ms(),
                            **existing.counters(),
                        }
                    )
                    return None
                # Stop the delivery drain (and with it the busy pump) the
                # moment we stop accepting work: it forges completed
                # dispatches back into a sender's thread, and doing that to
                # a process on its way down is exactly what the shutdown
                # path already refuses to allow. `drain_progress` frames
                # take over the liveness duty for the rest of the wait.
                liveness_stop.set()
                draining_frame = {
                    "event": "draining",
                    "id": None,
                    "pid": os.getpid(),
                    "boot_id": boot_id,
                    "pending": len(pending_at_start),
                    "request_ids": pending_at_start,
                    "deadline_seconds": started.deadline_seconds,
                    # What was ASKED for, beside what was granted: a client
                    # that requested 0.05s and got 30 must be able to see that
                    # its ask was floored rather than honoured.
                    "requested_deadline_seconds": message.get("deadline_seconds"),
                    "minimum_deadline_seconds": effective_minimum,
                }
                frames.emit(draining_frame)
                # RS-3, and it has to be BEFORE the listeners close: from the
                # next line on this lane refuses new connections, and a
                # contender that read the sidecar in that window used to see a
                # live pid and a port and conclude "serving". The stamp is what
                # lets it conclude "leaving" instead and wait the drain out
                # (``SocketOwnerLock.acquire``) rather than degrade to stdio for
                # the rest of the session — the operator's 2026-09-07 restart.
                if socket_lock is not None:
                    try:
                        socket_lock.mark_draining()
                    except Exception:
                        pass
                # New connections are refused from here on BOTH doors (existing
                # ones stay up to be told how it ends), and every attached
                # client hears it at the same moment the stdio supervisor does.
                for _lane in (socket_server, gateway_server):
                    if _lane is None:
                        continue
                    try:
                        _lane.begin_drain()
                    except Exception:
                        pass
                _broadcast_lanes(draining_frame)
                threading.Thread(
                    target=_drain_monitor,
                    args=(started,),
                    name="harness-serve-drain",
                    daemon=True,
                ).start()
                return None
            if op == "stacks":
                # Operator diagnostic: dump every thread's stack as
                # stderr frames (hung-request forensics without py-spy).
                import traceback

                for thread_id, frame in sys._current_frames().items():
                    sink.emit(
                        {
                            "id": None,
                            "event": "stderr",
                            "line": f"--- thread {thread_id} ---",
                        }
                    )
                    for entry in traceback.format_stack(frame):
                        for line in entry.rstrip().splitlines():
                            sink.emit(
                                {"id": None, "event": "stderr", "line": line}
                            )
                sink.emit({"event": "stacks_dumped"})
                return None
            if op == "shutdown":
                if connection is not None:
                    # A socket client does NOT get to kill a service other
                    # clients are using. `drain` is the multi-client lifecycle
                    # verb — it refuses new work, lets in-flight work land, and
                    # accounts for both — and `shutdown` stays what it has
                    # always been: the verb of the process that owns the pipe.
                    sink.emit(
                        {
                            "event": "error",
                            "error": "op_not_available_on_socket",
                            "detail": (
                                "shutdown is the stdio owner's verb; use "
                                '{"op":"drain"} to replace the service safely'
                            ),
                        }
                    )
                    return None
                return "shutdown"
            if op == "cancel":
                cancel_id = message.get("id")
                cancel_id = cancel_id.strip() if isinstance(cancel_id, str) else ""
                if not cancel_id:
                    sink.emit(
                        {
                            "id": None,
                            "event": "error",
                            "error": "invalid_request",
                            "detail": 'cancel needs {"op": "cancel", "id": "<request id>"}',
                        }
                    )
                    return None
                # Scoped to the asker's OWN work: the inflight table is keyed
                # per owner, so one client can neither cancel nor even observe
                # another's request id.
                owner = _owner_of(connection)
                cancel_key = (
                    cancel_id if owner == "stdio" else f"{owner}:{cancel_id}"
                )
                with inflight_lock:
                    future = inflight_futures.get(cancel_key)
                    running_request = inflight.get(cancel_key)
                    known = running_request is not None
                if future is not None and future.cancel():
                    with inflight_lock:
                        inflight.pop(cancel_key, None)
                        inflight_futures.pop(cancel_key, None)
                    sink.emit(
                        {
                            "id": cancel_id,
                            "event": "exit",
                            "code": 130,
                            "cancelled": True,
                        }
                    )
                elif running_request is not None and running_request.is_runtime_stream:
                    # The state stream is read-only and infinite. Unlike a
                    # mutation, it has a cooperative cancellation seam and
                    # MUST release its worker when the Launcher reconnects;
                    # otherwise four watchdog cycles exhaust the entire
                    # serve pool with abandoned streams.
                    running_request.cancel_event.set()
                    sink.emit(
                        {
                            "id": cancel_id,
                            "event": "cancel_accepted",
                            "state": "running",
                        }
                    )
                else:
                    # Already running (uninterruptible) or unknown — the
                    # side effect may still land; mutation verbs' own
                    # --issued-at replay guard is what makes that safe.
                    sink.emit(
                        {
                            "id": cancel_id,
                            "event": "cancel_denied",
                            "state": "running" if known else "unknown",
                        }
                    )
                return None
            # ── the METHOD lane ─────────────────────────────────────────────
            #
            # Named JSON-RPC 2.0 methods, BESIDE the argv lane rather than
            # instead of it (decision doc §3 / launcher `fa2226750`). The argv
            # lane below is unchanged and stays the fallback: it has never sent
            # `jsonrpc` or `method`, so nothing that used to reach it can be
            # captured here, and nothing about its frames or exit codes moves.
            #
            # Answered INLINE, like `ping` / `version` / `connections` and
            # unlike an argv request. The pool exists for handlers that block —
            # chat turns, streams — and these methods touch a handful of small
            # JSON files under the office lock and are done in microseconds.
            #
            # It is also why the lane is not refused while draining, and the
            # test that matters here is NOT "is it a read": `runtime.office.
            # upsert` mutates and is still answered. A drain refuses new WORK so
            # in-flight work can land, and the work it is protecting is the kind
            # that can be CUT OFF HALF-DONE — a chat turn whose frames stop
            # mid-stream when the process exits. An inline handler cannot be:
            # `OfficeStore` has written the actor file atomically and released
            # the lock before the ack is emitted, and the replacement runtime
            # reads that same file. Refusing it would fail an operator's drag
            # during a restart to protect against a loss that cannot occur.
            # `version` and `ping` are answered throughout for the same reason.
            # (Pinned by `test_a_write_during_a_drain_lands_because_it_cannot_be
            # _cut_off_half_done` in tests/agent_runtime/test_serve_rpc_office_
            # upsert.py — this is a decision, not an oversight.)
            #
            # The handler is told WHO asked, not just what. All of it comes
            # from this frame's own dispatch — ``sink`` is the stable
            # per-connection writer ``_sink_for`` hands out, and ``connection``
            # is None exactly on stdio. Nothing here is office-specific: it is
            # the argument a method needs before it can push to its caller
            # LATER, which request/response methods simply ignore.
            #
            # ``caller`` is the AUTHORIZATION half (chokepoint plan, Stage A2),
            # and this is the ONE place a live connection becomes one. It is
            # derived from the connection object the transport handed us — never
            # from ``message`` — so no field a client can type reaches the front
            # door's predicate. ``caller_for_connection`` reads the connection's
            # own ``authenticated`` flag, which is set only after
            # ``verify_hello_proof``, so the socket lane's identity is proven
            # here rather than assumed, and stdio's is the process owner's.
            #
            # ``spawn_chat_turn`` is the ONE exception to "answered inline", and
            # it proves the rule rather than breaking it: the chat methods do not
            # run their turn on this loop, they put it on the pool through this
            # seam and ack. Everything the argv lane does for a chat turn happens
            # here too — the same ``_ArgvRequest``, so ``is_chat_turn`` is
            # derived from the same ``_CHAT_TURN_COMMANDS`` shapes and the drain
            # ledger counts an RPC turn exactly as it counts a local one; the
            # same inflight table, so ``connections`` and cancel see it; the same
            # ``_run``, so the frames, the exit code and the completion
            # accounting are one implementation. A serve that recycled mid-turn
            # because the turn arrived on the other lane is the exact defect
            # ``held_by_chat_turns`` exists to prevent.
            def _spawn_chat_turn(
                request_id: str, argv: list[str], turn_request_id: str
            ) -> None:
                from agent_runtime.chat_turn import ChatTurnSpawnRefused

                if drain_state is not None:
                    # And ACCOUNTED, exactly as an argv refusal is: a drain that
                    # turned a remote turn away is a number on the terminal
                    # frame rather than an inference. The method lane keeps
                    # answering during a drain for handlers that cannot be cut
                    # off half-done; a chat turn is the work that CAN be, which
                    # is what the drain is for.
                    drain_state.note_refused()
                    raise ChatTurnSpawnRefused(
                        "draining",
                        "serve is draining and is not accepting new chat turns; "
                        "reconnect to the replacement runtime and retry with the "
                        "same turn_request_id",
                    )
                chat_request = _ArgvRequest(
                    request_id,
                    [str(item) for item in argv],
                    owner=_owner_of(connection),
                    sink=None if connection is None else sink,
                    turn_request_id=turn_request_id,
                )
                with inflight_lock:
                    # The id is server-minted and random, so a collision here is
                    # not a client behaviour — it is a bug, and it refuses
                    # rather than silently replacing a live request's entry.
                    if chat_request.key in inflight:
                        raise ChatTurnSpawnRefused(
                            "request_id_collision",
                            "a request with this server-minted id is already in flight",
                        )
                    inflight[chat_request.key] = chat_request
                chat_future = pool.submit(_run, chat_request)
                with inflight_lock:
                    if chat_request.key in inflight:
                        inflight_futures[chat_request.key] = chat_future

            # The SECOND seam onto the pool, and the general one. A chat turn is
            # a whole request handed over and acked; this is the TAIL of one
            # request handed over — a callable that returns the very frame the
            # handler would have returned — so the method lane keeps its
            # request/response shape and only the thread that finishes the work
            # moves. ``runtime.media.get``'s proxy arm is the first caller: it
            # dials another machine, and a machine that is switched off parked
            # this loop for the dial's whole timeout with every other request
            # from that client queued behind it.
            #
            # Refused while DRAINING, which puts the deferral on the same side
            # of the drain as the pool it uses: a drain is waiting for the pool
            # to empty, and handing it new work is the opposite of that. The
            # handler answers inline instead — the pre-existing behaviour, for
            # the seconds a drain lasts.
            def _spawn_reply(build: Any) -> bool:
                if drain_state is not None:
                    return False
                try:
                    pool.submit(_emit_deferred_reply, build, sink)
                except RuntimeError:
                    # The pool is already shutting down. False, so the handler
                    # answers on this thread rather than a client waiting for a
                    # frame no worker will ever write.
                    return False
                return True

            if serve_rpc.is_rpc_frame(message):
                rpc_frame = serve_rpc.handle_request(
                    message,
                    serve_rpc.RpcContext(
                        connection_key=getattr(connection, "key", None),
                        transport=getattr(connection, "transport", "stdio"),
                        emit=sink.emit,
                        caller=caller_for_connection(connection),
                        spawn_chat_turn=_spawn_chat_turn,
                        spawn_reply=_spawn_reply,
                    ),
                )
                # The ONE frame this lane does not write: the handler took the
                # deferral and the worker owns the reply now. Compared by
                # identity, so no result a handler builds can land here.
                if not serve_rpc.is_deferred(rpc_frame):
                    sink.emit(rpc_frame)
                return None
            if _is_gateway(connection):
                # THE ARGV LANE IS NOT REACHABLE FROM A DEVICE, and this is the
                # load-bearing refusal of the whole stage. The front-door tier
                # gate (`authorize_call`) sits on the METHOD lane; the argv lane
                # runs `harness <anything>` through the CLI dispatcher, where a
                # tier declaration does not exist and every verb is the local
                # operator's. Without this line a `read`-tier device refused
                # `runtime.agent.retire` on the method lane could simply send
                # `{"argv": ["harness", "agent", "retire", ...]}` and be obeyed —
                # the gate would be real and bypassable in one frame.
                #
                # This is a refusal rather than a second gate on purpose. Gating
                # argv would mean deciding a tier for every CLI verb this repo
                # has and keeping that map correct forever, which is the
                # duplicated-authority shape this stack keeps retiring. A device
                # has the method lane, whose tiers ride the manifest it already
                # reads.
                sink.emit(
                    {
                        "id": message.get("id") if isinstance(message.get("id"), str) else None,
                        "event": "error",
                        "error": "argv_lane_unavailable",
                        "detail": (
                            "the argv lane is the local console's; a paired "
                            "device calls JSON-RPC methods, whose tiers ride "
                            "the rpc manifest on hello_ok"
                        ),
                    }
                )
                return None
            rid = message.get("id")
            argv = message.get("argv")
            if (
                not isinstance(rid, str)
                or not rid.strip()
                or not isinstance(argv, list)
                or not argv
                or not all(isinstance(item, str) for item in argv)
            ):
                sink.emit(
                    {
                        "id": rid if isinstance(rid, str) else None,
                        "event": "error",
                        "error": "invalid_request",
                        "detail": 'request needs {"id": "<non-empty>", "argv": ["harness", …]}',
                    }
                )
                return None
            if drain_state is not None:
                # Refused, and ACCOUNTED: the count lands on the terminal
                # drain frame, so "the restart dropped work" is a number an
                # operator can read rather than an inference.
                drain_state.note_refused()
                sink.emit(
                    {
                        "id": rid.strip(),
                        "event": "draining",
                        "detail": (
                            "serve is draining and is not accepting new requests; "
                            "reconnect to the replacement runtime"
                        ),
                        "drain_ms": drain_state.elapsed_ms(),
                    }
                )
                # Terminal frame too: a client that predates the `draining`
                # event is waiting for an `exit` and would otherwise hang
                # for the life of its request.
                sink.emit(
                    {
                        "id": rid.strip(),
                        "event": "exit",
                        "code": DRAINING_EXIT_CODE,
                        "draining": True,
                    }
                )
                return None
            request = _ArgvRequest(
                rid.strip(),
                [str(item) for item in argv],
                owner=_owner_of(connection),
                sink=None if connection is None else sink,
            )
            with inflight_lock:
                if request.key in inflight:
                    sink.emit(
                        {
                            "id": request.rid,
                            "event": "error",
                            "error": "duplicate_request_id",
                            "detail": "a request with this id is still in flight",
                        }
                    )
                    return None
                inflight[request.key] = request
            future = pool.submit(_run, request)
            with inflight_lock:
                # _run may already have finished and popped the request;
                # only track the future while the request is in flight so
                # the registry cannot leak completed entries.
                if request.key in inflight:
                    inflight_futures[request.key] = future
            return None

        pool = ThreadPoolExecutor(
            max_workers=max(1, pool_size), thread_name_prefix="harness-serve"
        )
        # The socket starts ACCEPTING only now: the listener has been bound
        # since before the ready frame (so the port could be published), but a
        # connection whose first request landed before this pool existed would
        # have nowhere to dispatch. The backlog holds them for the microseconds
        # in between.
        if socket_server is not None:
            try:
                socket_server.start_accepting()
            except Exception as exc:
                _service_log(
                    {
                        "event": "serve_socket_accept_start_failed",
                        "boot_id": boot_id,
                        "reason": type(exc).__name__,
                    }
                )
                _close_socket_lane(reason="accept_start_failed")
        if gateway_server is not None:
            # Same two-phase start, same reason: the port was bound before the
            # ready frame so it could be published, and accepting waits for the
            # pool. A gateway lane that cannot start accepting closes BOTH doors
            # through the shared closer, because a half-open runtime — loopback
            # serving, gateway bound but deaf — is a state nothing downstream
            # can describe.
            try:
                gateway_server.start_accepting()
            except Exception as exc:
                _service_log(
                    {
                        "event": "serve_gateway_accept_start_failed",
                        "boot_id": boot_id,
                        "reason": type(exc).__name__,
                    }
                )
                _close_socket_lane(reason="gateway_accept_start_failed")
        # Explicit construction + shutdown rather than ``with``: the drain's
        # timeout path must be able to stop waiting on work that has proven it
        # will not finish, and a context manager always joins.
        def _detach_stdio_owner() -> None:
            """The starter has gone; stop writing to its pipe and say so once.

            Order matters and is the whole function: the receipt is published
            BEFORE the sink is swapped, so a starter that is merely slow to
            close (or a socket client attached right now) actually sees it, and
            a starter that has already gone costs one swallowed
            ``BrokenPipeError`` instead of taking the runtime down with it.
            """

            detached = {
                "event": "stdio_owner_detached",
                "pid": os.getpid(),
                "boot_id": boot_id,
                "starter_pid": starter_pid,
            }
            _service_log(detached)
            # Attached socket clients are owed this too: from here the runtime
            # answers only them, and "the launcher that started this closed" is
            # a fact a client showing a runtime sheet wants without asking.
            _broadcast_lanes(detached)
            frames.detach()

        def _park_until_service_stop() -> None:
            """Hold the main thread open until something asks the service to stop.

            This is the ENTIRE lifetime change. The reader is gone, the pool and
            both socket lanes are untouched and still serving, and the thread
            that used to be blocked on ``os.read`` is blocked here instead —
            so when it is released, the finalization below it runs exactly as
            it does for a stdio EOF. Nothing is skipped, nothing is duplicated.

            The event is the mechanism; the poll is a bound. See
            ``_SERVICE_PARK_POLL_SECONDS``.
            """

            saved = _install_service_stop_signal(service_stop, note=_note_end)
            try:
                while not service_stop.wait(_SERVICE_PARK_POLL_SECONDS):
                    if drain_terminal_published.is_set():
                        break
            finally:
                _restore_service_stop_signal(saved)

        try:
            stdio_shutdown = False
            for raw in reader:
                line = raw.strip()
                if not line:
                    continue
                if _handle_line(line, frames) == "shutdown":
                    stdio_shutdown = True
                    break
            # A stdio ``shutdown`` is an ORDER and EOF is an OBSERVATION, and
            # until service mode existed the loop could not tell them apart —
            # both simply ended the reader. They part here, and only here: an
            # order still ends the runtime exactly as it always has (which is
            # what makes ``--service`` safe for Update/Repair to keep using),
            # while EOF on a service means the starter closed its end and
            # walked away.
            if service and not stdio_shutdown:
                _detach_stdio_owner()
                _park_until_service_stop()
        finally:
            # The reader is done; from here the process is unwinding normally,
            # which is what the drain monitor's grace window is waiting to see.
            reader_unwound.set()
            # ``wait`` is True everywhere except after a drain TIMEOUT, where
            # the whole point is that the remaining work has already outlived
            # its deadline and joining it would restore the hang.
            pool.shutdown(wait=pool_shutdown_wait)
        liveness_stop.set()
        if drain_state is not None:
            # The drain owns the terminal frame (``drain_complete`` /
            # ``drain_timeout``); emitting ``shutdown`` as well would tell a
            # consumer that a TIMED-OUT drain ended cleanly — the one thing it
            # must not conclude.
            #
            # But the reader can get here BEFORE the monitor has published
            # anything: a `shutdown` op, or the pipe reaching EOF, while a drain
            # is still in progress. That path used to fall straight to
            # ``return drain_exit_code`` — no terminal frame at all, the registry
            # entry left on disk, and code 0 even when the drain had TIMED OUT.
            # A drain that exits silently is exactly the crash it exists to
            # replace, so wait a bounded moment for the monitor (the pool is
            # already joined above, so it is normally one poll away) and, if it
            # never publishes, say so in a typed frame of its own.
            if not drain_finished.wait(_DRAIN_ABANDON_GRACE_SECONDS):
                if drain_terminal_published.is_set():
                    # A drain that already DECIDED how it ended owns the
                    # terminal frame; this path is only for a drain that never
                    # got one. Publishing ``drain_abandoned`` on top of a
                    # completed drain told a supervisor that a successful
                    # restart gave up, and exited 3 on it — the frame and the
                    # code both wrong, about work that had actually landed. The
                    # exit watchdog covers the case where the publisher is the
                    # thing that hung.
                    return drain_exit_code
                abandoned = {
                    "event": "drain_abandoned",
                    "pid": os.getpid(),
                    "boot_id": boot_id,
                    **drain_state.counters(),
                    "drain_ms": drain_state.elapsed_ms(),
                    "detail": (
                        "the transport closed while a drain was still in "
                        "progress; the drain published no terminal frame"
                    ),
                }
                frames.emit(abandoned)
                _broadcast_lanes(abandoned)
                _close_socket_lane(reason="drain_abandoned")
                _unregister_instance(reason="drain_abandoned")
                _note_end("drained")
                _write_end()
                # Nonzero on purpose, and the SAME code a timeout uses: a
                # supervisor must be able to tell "drained" from "gave up".
                return DRAIN_TIMEOUT_EXIT_CODE
            # ``_finish_drain`` published the frame, closed the socket lane, and
            # unregistered; ``drain_exit_code`` is its verdict, not this path's.
            return drain_exit_code
        # RL-16. The two events that reach this line are the two service mode
        # taught the loop to tell apart, and the sidecar keeps them apart too: a
        # stdio ``{"op":"shutdown"}`` is an ORDER somebody gave, while EOF is an
        # OBSERVATION that the pipe closed. ``stdin_eof`` is unreachable under
        # ``--service`` by construction — there EOF parks instead of exiting —
        # so it is a word only a launcher's stdio child can ever write.
        _note_end("shutdown_op" if stdio_shutdown else "stdin_eof")
        shutdown_frame = {"event": "shutdown", "pid": os.getpid()}
        # Socket clients hear it BEFORE the transport closes under them: an
        # attached client whose socket simply died could not tell a clean
        # service shutdown from a crash, which is the distinction the durable
        # service exists to make legible.
        _broadcast_lanes(shutdown_frame)
        _close_socket_lane(reason="shutdown")
        _unregister_instance(reason="shutdown")
        _write_end()
        frames.emit(shutdown_frame)
        return 0
    except KeyboardInterrupt:
        # POSIX's Ctrl-C, and Windows' too once the console handler has declined
        # to handle it. Named rather than folded into ``uncaught:`` below
        # because it is not a fault: somebody interrupted this runtime, which is
        # the same fact the console table spells ``ctrl_c``. The latch is
        # first-wins, so on Windows the handler's word is already in place and
        # this is a no-op.
        _note_end("ctrl_c")
        raise
    except Exception as exc:
        # The class of death that used to be indistinguishable from a hard kill:
        # a stale row, a gone pid, and no way to tell a bug in this process from
        # a ``taskkill`` outside it. The type name is the whole value of the
        # word — it is what turns "it crashed" into a grep.
        #
        # ``SystemExit`` and ``GeneratorExit`` are deliberately NOT caught here:
        # they are BaseExceptions, an orderly exit runs ``atexit``, and an
        # orderly exit that set no reason is exactly what ``unknown_exit`` is
        # for. Re-raised unchanged: this arm records, it never handles.
        _note_end(f"uncaught:{type(exc).__name__}")
        # RL-19, and the one thing the redirect alone cannot deliver. MEASURED
        # 2026-09-06 on this branch: an uncaught exception out of a serve child
        # produces no traceback on ANY channel, service or not — the harness
        # dispatch converts it into an error envelope and the ``--ndjson`` serve
        # emits nothing for it, so all three frames on stdout are ``booting``,
        # ``root_anchor``, ``ready`` and the process exits 1 having said nothing
        # about why. The interpreter never gets the exception, so restoring
        # ``sys.stderr`` restores a channel nobody writes the traceback to.
        # This line is therefore the traceback's only author.
        if service_stderr_log is not None:
            try:
                import traceback as _traceback

                rendered = _traceback.format_exc()
                service_stderr_log.write(
                    rendered if rendered else f"{type(exc).__name__}: {exc}\n"
                )
            except Exception:  # pragma: no cover - a dying process, best effort
                pass
        raise
    finally:
        sys.stdout, sys.stderr = original_stdout, original_stderr
        if discussion_owner is not None:
            from agent_runtime.discussions.service import shutdown as shutdown_discussions
            shutdown_discussions(root=discussion_owner.context.root)
        from agent_runtime.local_llama_adapter.rpc import shutdown as shutdown_local_llama
        if local_llama_bound_root is not None:
            shutdown_local_llama(root=local_llama_bound_root)
