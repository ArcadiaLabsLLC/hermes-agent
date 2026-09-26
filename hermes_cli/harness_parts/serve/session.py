"""``ServeSession`` — one serve process's state and its boot order.

The fields are what ``serve_loop``'s closures used to capture; the methods are
those closures, on six modules by what they do: this one (boot order, the end
reason, liveness, the registry row, the stdio owner), ``boot_phases`` (the boot
steps between the stdio swap and ``ready``), ``handle_message`` (the op table
and the dispatcher), ``lanes`` (the pool), ``subscriptions`` (the stream hub and
the socket lanes' plumbing) and ``drain``. ``serve_loop`` builds one and
runs it; nothing else constructs one.

``serve_loop`` — the entry point every caller and test drives — lives here,
at the end of the module: it builds one session and runs it, and the loop's
contract (transports, drain, service mode, the stdout discipline) is the
class docstring.
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

from hermes_cli.harness_parts.serve.argv_lane import _ArgvRequest, dispatch_argv
from hermes_cli.harness_parts.serve.boot_phases import BootPhases
from hermes_cli.harness_parts.serve.boot import _annotate_import_tax, _runtime_state_fingerprint
from hermes_cli.harness_parts.serve.constants import (
    _DRAIN_ABANDON_GRACE_SECONDS,
    _DRAIN_POLL_INTERVAL_SECONDS,
    _DRAIN_SOCKET_MINIMUM_DEADLINE_SECONDS,
    _READ_CACHE_MAX_AGE_SECONDS,
    _REQUEST_SILENCE_SECONDS,
    _SERVICE_PARK_POLL_SECONDS,
    DEFAULT_DRAIN_DEADLINE_SECONDS,
    DEFAULT_POOL_SIZE,
    DRAIN_TIMEOUT_EXIT_CODE,
    FINGERPRINT_HOME_BOOT_SITE,
    READER_STOP,
    SERVE_SCHEMA_VERSION,
)
from hermes_cli.harness_parts.serve.drain import DrainLane, _DrainState
from hermes_cli.harness_parts.serve.end_reason import (
    EndReason,
    _install_service_stop_signal,
    _restore_service_stop_signal,
)
from hermes_cli.harness_parts.serve.frames import (
    _FrameWriter,
    _LineFrameProxy,
    _PollResponseCache,
    _SafeSink,
)
from hermes_cli.harness_parts.serve.handle_message import MessageHandling
from hermes_cli.harness_parts.serve.lanes import ArgvLanes
from hermes_cli.harness_parts.serve.subscriptions import SubscriptionLanes

__layer__ = "lanes"

__all__ = ["ServeSession", "serve_loop"]


class ServeSession(BootPhases, MessageHandling, SubscriptionLanes, ArgvLanes, DrainLane):
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
    def __init__(
        self,
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
    ) -> None:
        self.reader = reader
        self.writer = writer
        self.pool_size = pool_size
        self.dispatch = dispatch
        self.fingerprint = fingerprint
        self.read_cache_max_age = read_cache_max_age
        self.liveness_pump_interval_seconds = liveness_pump_interval_seconds
        self.boot_timeline = boot_timeline
        self.snapshot_prewarm = snapshot_prewarm
        self.provider_prewarm = provider_prewarm
        self.actor_prewarm = actor_prewarm
        self.root_anchor = root_anchor
        self.skill_install = skill_install
        self.drain_deadline_seconds = drain_deadline_seconds
        self.drain_socket_minimum_deadline_seconds = drain_socket_minimum_deadline_seconds
        self.drain_poll_interval_seconds = drain_poll_interval_seconds
        self.drain_wakeup = drain_wakeup
        self.hard_exit = hard_exit
        self.socket_lane = socket_lane
        self.service = service
        self.record_end_reason = record_end_reason
        self.stream_source_factory = stream_source_factory
        self.stream_buffer_limit = stream_buffer_limit
        self.stream_byte_limit = stream_byte_limit

    def run(self) -> int:
        """Boot, serve until the reader ends, unwind. The process's exit code."""

        self._boot_prelude()
        self._boot_anchor_and_skills()
        self._init_request_state()
        self._swap_stdio()
        try:
            return self._boot_and_serve()
        except KeyboardInterrupt:
            # POSIX's Ctrl-C, and Windows' too once the console handler has declined
            # to handle it. Named rather than folded into ``uncaught:`` below
            # because it is not a fault: somebody interrupted this runtime, which is
            # the same fact the console table spells ``ctrl_c``. The latch is
            # first-wins, so on Windows the handler's word is already in place and
            # this is a no-op.
            self._note_end(EndReason.CTRL_C)
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
            self._note_end(f"uncaught:{type(exc).__name__}")
            # RL-19, and the one thing the redirect alone cannot deliver. MEASURED
            # 2026-09-06 on this branch: an uncaught exception out of a serve child
            # produces no traceback on ANY channel, service or not — the harness
            # dispatch converts it into an error envelope and the ``--ndjson`` serve
            # emits nothing for it, so all three frames on stdout are ``booting``,
            # ``root_anchor``, ``ready`` and the process exits 1 having said nothing
            # about why. The interpreter never gets the exception, so restoring
            # ``sys.stderr`` restores a channel nobody writes the traceback to.
            # This line is therefore the traceback's only author.
            if self.service_stderr_log is not None:
                try:
                    import traceback as _traceback

                    rendered = _traceback.format_exc()
                    self.service_stderr_log.write(
                        rendered if rendered else f"{type(exc).__name__}: {exc}\n"
                    )
                except Exception:  # pragma: no cover - a dying process, best effort
                    pass
            raise
        finally:
            sys.stdout, sys.stderr = self.original_stdout, self.original_stderr
            if self.conversation_owner is not None:
                from agent_runtime.conversations.binding import shutdown as shutdown_conversations
                shutdown_conversations(root=self.conversation_owner.root)
            if self.discussion_owner is not None:
                from agent_runtime.discussions.service import shutdown as shutdown_discussions
                shutdown_discussions(root=self.discussion_owner.context.root)
            from agent_runtime.local_llama_adapter.binding import shutdown as shutdown_local_llama
            if self.local_llama_bound_root is not None:
                shutdown_local_llama(root=self.local_llama_bound_root)

    def _boot_and_serve(self) -> int:
        """Everything between the stdio swap and the unwind, in boot order."""
        from hermes_cli.harness_parts.mission_chat_door_binding import bind_mission_chat_door

        bind_mission_chat_door()  # ruling Q10: bound before any request can run a turn
        self._boot_store_and_identity()
        exit_code = self._boot_socket_lane()
        if exit_code is not None:
            return exit_code
        self._boot_gateway_lane()
        self._boot_register_instance()
        self._arm_service_stderr_log()
        self._prune_stale_records()
        self._arm_end_reason()
        self._boot_sweeps_and_ready_frame()
        self._announce_ready()
        self._start_background_workers()
        self._bind_subscription_lanes()
        self._start_pool_and_accepting()
        return self._serve_until_eof()

    def _boot_prelude(self) -> None:
        from agent_runtime.boot_timeline import BootTimeline

        self.timeline = self.boot_timeline if self.boot_timeline is not None else BootTimeline()
        _annotate_import_tax(self.timeline)
        self.frames = _FrameWriter(self.writer, detachable=self.service)
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
        self.frames.emit(
            {
                "event": "booting",
                "pid": os.getpid(),
                "schema_version": SERVE_SCHEMA_VERSION,
                "boot": self.timeline.stamps(),
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
        from agent_runtime.core_cache import home as _core_cache

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

        self.serve_request_home = _get_hermes_home()
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
        self.timeline.mark("chat_registry_ms")
        # Publish this process's EXPLICIT chat head home into the shared runtime
        # store root — the ONE writer of that pointer. The Launcher always starts
        # serve with HERMES_HEAD_HOME; a plain CLI turn started later names no head
        # and, without the pointer, degrades to its own profile database, minting
        # the transcript where the cockpit never looks while writing the binding
        # into the shared store (the 2026-07-27 read-lane gap). No-op when this
        # process named no head of its own, and best effort by contract.
        from agent_runtime.chat_session_scope import publish_chat_head_home

        publish_chat_head_home()
        self.timeline.mark("head_publish_ms")

    def _boot_anchor_and_skills(self) -> None:
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
        if self.root_anchor is not None:
            try:
                anchor_report = self.root_anchor()
                anchor_frame = {"event": "root_anchor", **anchor_report.payload()}
            except Exception as exc:  # must never take the boot down
                anchor_frame = {
                    "event": "root_anchor",
                    "outcome": "unwritable",
                    "detail": type(exc).__name__,
                }
            self.frames.emit(anchor_frame)
        self.timeline.mark("root_anchor_ms")
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
        if self.skill_install is not None:
            try:
                print(self.skill_install(), file=sys.stderr, flush=True)
            except Exception as exc:
                print(
                    f"harness serve: skill install FAILED — {type(exc).__name__}: {exc}"
                    " (booting anyway; the installed packages may be stale)",
                    file=sys.stderr,
                    flush=True,
                )
        self.timeline.mark("skill_install_ms")

    def _init_request_state(self) -> None:
        self.stdout_proxy = _LineFrameProxy(self.frames, "line")
        self.stderr_proxy = _LineFrameProxy(self.frames, "stderr")
        self.read_cache = _PollResponseCache(self.read_cache_max_age)
        from agent_runtime.snapshot.context import SnapshotBuildContext

        self.read_build_context = SnapshotBuildContext()

        self.inflight: dict[str, _ArgvRequest] = {}
        # Futures by request id so ``{"op":"cancel"}`` can drop work that is
        # still queued behind the pool. A running request is uninterruptible —
        # cancel() then returns False and the client is told the side effect may
        # still land.
        self.inflight_futures: dict[str, Future] = {}
        self.inflight_lock = threading.Lock()

        # Drain state. ``None`` until a `drain` op arrives; from then on it is the
        # single answer to "are we still accepting work", read by the request path
        # and written once by the op.
        self.drain_state: _DrainState | None = None
        self.drain_exit_code = 0
        self.drain_finished = threading.Event()
        #: Latched the instant a drain DECIDES how it ended, before it publishes
        #: anything. A drain has exactly one terminal frame: without this latch a
        #: mid-drain EOF could publish ``drain_abandoned`` after a completed drain
        #: had already published ``drain_complete``, telling a supervisor that a
        #: successful restart gave up — and exiting 3 on it.
        self.drain_terminal_published = threading.Event()
        self.drain_terminal_lock = threading.Lock()
        self.reader_unwound = threading.Event()
        self.pool_shutdown_wait = True
        self.boot_id = uuid.uuid4().hex
        #: WHO started this runtime, read NOW and never again. In service mode the
        #: whole point is that the starter goes away, and a parent read after that
        #: names the reaper/init that adopted us — a different process, and on
        #: Windows often no process at all. Published on the greeting frames and the
        #: registry row so an attaching client can tell "the launcher I am running
        #: in started this" from "this was already here", which is the difference
        #: between RL-4's ``started by this launcher`` and ``attached``.
        self.starter_pid: int | None
        try:
            self.starter_pid = int(os.getppid())
        except Exception:  # pragma: no cover - os.getppid exists everywhere we run
            self.starter_pid = None
        #: The service park's only wakeup. Set by the drain's terminal path, by
        #: SIGTERM where the platform delivers one, and by nothing else.
        self.service_stop = threading.Event()
        #: RL-16's recorder, armed below once the store root is known AND the caller
        #: asked for it. ``None`` until then — and forever, in every ``serve_loop``
        #: unit test — which is why every use goes through the two shims beside it
        #: rather than through the attribute.
        self.end_reason: Any = None
        #: RL-19's file handle, opened below for the ``--service`` arm only and
        #: ``None`` in every other serve and every unit test. Held as a name because
        #: the uncaught arm at the bottom of this function writes the one thing the
        #: rest of the wiring cannot deliver — see there.
        self.service_stderr_log: Any = None

        # ── socket lane state (all None unless ``socket_lane`` is on AND this
        # serve wins the per-root ownership lock) ────────────────────────────────
        self.socket_server: Any = None
        self.socket_lock: Any = None
        #: The SECOND listener (remote-gateway Stage 1). ``None`` unless
        #: ``remote_gateway.listen`` names an interface AND this serve owns the
        #: loopback lane — the gateway lane is not a separate ownership question, it
        #: is the same dispatcher answering on a second door, so a serve that lost
        #: the per-root lock must not open one either. It shares the loopback lane's
        #: lock, its pool, its stream hub and its drain; what it does not share is
        #: the credential (per device, not per root) and the encryption (TLS).
        self.gateway_server: Any = None
        #: The ONE stream producer, built on the first ``subscribe`` and stopped
        #: when the last subscriber leaves. Never per client: a delta batch rebuilds
        #: a full snapshot core, so N generators would cost N of them.
        self.stream_hub: Any = None
        #: ONE lock over all three lane handles above. They used to be swapped by
        #: bare ``nonlocal`` assignment from the drain path, the shutdown path, and
        #: the EOF path — three threads racing an unsynchronised read-modify-write
        #: on the objects whose whole job is to be released exactly once. Held for
        #: the SWAP only, never across a join: the point is that two closers cannot
        #: both take the same handle, not that teardown is serialised.
        self.lane_lock = threading.Lock()
        #: Per-subscriber patch-fold declarations: connection key → the entity
        #: classes that client said it can fold, or None when it said nothing (which
        #: is NOT the empty set — see ``patch_coverage.HISTORICAL_FOLD_ENTITIES``).
        #: Guarded by ``lane_lock`` because the producer thread reads it while a
        #: request thread is writing it. The producer is SHARED, so what it may
        #: promote is the INTERSECTION over this table, not any one client's answer.
        self.stream_fold_entities: dict[str, Any] = {}

    def _swap_stdio(self) -> None:
        self.original_stdout, self.original_stderr = sys.stdout, sys.stderr
        self.local_llama_bound_root = None
        self.discussion_owner = None
        self.conversation_owner = None
        sys.stdout, sys.stderr = self.stdout_proxy, self.stderr_proxy

    def _start_background_workers(self) -> None:
        self.liveness_stop = threading.Event()

        threading.Thread(
            target=self._liveness_pump,
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
            start_delivery_drain(stop_event=self.liveness_stop)
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
        if self.discussion_owner is not None:
            try:
                self.discussion_owner.start()
            except Exception:
                import logging as _discussion_logging
                _discussion_logging.getLogger(__name__).warning(
                    "discussion worker did not start", exc_info=True,
                )

    def _bind_subscription_lanes(self) -> None:

        # ── socket lane plumbing ────────────────────────────────────────────
        #
        # Everything below is inert on a stdio-only serve: ``socket_server`` is
        # None, no connection ever exists, and the stdio path never reaches a
        # branch that touches it.

        self.connection_sinks: dict[str, _SafeSink] = {}
        self.connection_sinks_lock = threading.Lock()

        #: Does an INJECTED source factory want the negotiated fold set? Answered
        #: once, by signature — never by calling it and catching ``TypeError``,
        #: which would swallow a TypeError raised INSIDE a zero-arg factory and
        #: retry it at a different arity (the reasoning ``serve_stream_hub``
        #: records for its own stop-event probe, one seam up).
        self.stream_factory_takes_fold_entities = False
        if self.stream_source_factory is not None:
            try:
                inspect.signature(self.stream_source_factory).bind(frozenset())
                self.stream_factory_takes_fold_entities = True
            except (TypeError, ValueError):
                self.stream_factory_takes_fold_entities = False

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
            self._ensure_stream_hub,
            log=self._service_log,
            accepted_fold_entities=self._accepted_fold_entities,
        )

    def _start_pool_and_accepting(self) -> None:

        self.pool = ThreadPoolExecutor(
            max_workers=max(1, self.pool_size), thread_name_prefix="harness-serve"
        )
        # The socket starts ACCEPTING only now: the listener has been bound
        # since before the ready frame (so the port could be published), but a
        # connection whose first request landed before this pool existed would
        # have nowhere to dispatch. The backlog holds them for the microseconds
        # in between.
        if self.socket_server is not None:
            try:
                self.socket_server.start_accepting()
            except Exception as exc:
                self._service_log(
                    {
                        "event": "serve_socket_accept_start_failed",
                        "boot_id": self.boot_id,
                        "reason": type(exc).__name__,
                    }
                )
                self._close_socket_lane(reason="accept_start_failed")
        if self.gateway_server is not None:
            # Same two-phase start, same reason: the port was bound before the
            # ready frame so it could be published, and accepting waits for the
            # pool. A gateway lane that cannot start accepting closes BOTH doors
            # through the shared closer, because a half-open runtime — loopback
            # serving, gateway bound but deaf — is a state nothing downstream
            # can describe.
            try:
                self.gateway_server.start_accepting()
            except Exception as exc:
                self._service_log(
                    {
                        "event": "serve_gateway_accept_start_failed",
                        "boot_id": self.boot_id,
                        "reason": type(exc).__name__,
                    }
                )
                self._close_socket_lane(reason="gateway_accept_start_failed")
        # Explicit construction + shutdown rather than ``with``: the drain's
        # timeout path must be able to stop waiting on work that has proven it
        # will not finish, and a context manager always joins.

    def _serve_until_eof(self) -> int:

        try:
            stdio_shutdown = False
            for raw in self.reader:
                line = raw.strip()
                if not line:
                    continue
                if self._handle_line(line, self.frames) == READER_STOP:
                    stdio_shutdown = True
                    break
            # A stdio ``shutdown`` is an ORDER and EOF is an OBSERVATION, and
            # until service mode existed the loop could not tell them apart —
            # both simply ended the reader. They part here, and only here: an
            # order still ends the runtime exactly as it always has (which is
            # what makes ``--service`` safe for Update/Repair to keep using),
            # while EOF on a service means the starter closed its end and
            # walked away.
            if self.service and not stdio_shutdown:
                self._detach_stdio_owner()
                self._park_until_service_stop()
        finally:
            # The reader is done; from here the process is unwinding normally,
            # which is what the drain monitor's grace window is waiting to see.
            self.reader_unwound.set()
            # ``wait`` is True everywhere except after a drain TIMEOUT, where
            # the whole point is that the remaining work has already outlived
            # its deadline and joining it would restore the hang.
            self.pool.shutdown(wait=self.pool_shutdown_wait)
        self.liveness_stop.set()
        if self.drain_state is not None:
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
            if not self.drain_finished.wait(_DRAIN_ABANDON_GRACE_SECONDS):
                if self.drain_terminal_published.is_set():
                    # A drain that already DECIDED how it ended owns the
                    # terminal frame; this path is only for a drain that never
                    # got one. Publishing ``drain_abandoned`` on top of a
                    # completed drain told a supervisor that a successful
                    # restart gave up, and exited 3 on it — the frame and the
                    # code both wrong, about work that had actually landed. The
                    # exit watchdog covers the case where the publisher is the
                    # thing that hung.
                    return self.drain_exit_code
                abandoned = {
                    "event": "drain_abandoned",
                    "pid": os.getpid(),
                    "boot_id": self.boot_id,
                    **self.drain_state.counters(),
                    "drain_ms": self.drain_state.elapsed_ms(),
                    "detail": (
                        "the transport closed while a drain was still in "
                        "progress; the drain published no terminal frame"
                    ),
                }
                self.frames.emit(abandoned)
                self._broadcast_lanes(abandoned)
                self._close_socket_lane(reason="drain_abandoned")
                self._unregister_instance(reason="drain_abandoned")
                self._note_end(EndReason.DRAINED)
                self._write_end()
                # Nonzero on purpose, and the SAME code a timeout uses: a
                # supervisor must be able to tell "drained" from "gave up".
                return DRAIN_TIMEOUT_EXIT_CODE
            # ``_finish_drain`` published the frame, closed the socket lane, and
            # unregistered; ``drain_exit_code`` is its verdict, not this path's.
            return self.drain_exit_code
        # RL-16. The two events that reach this line are the two service mode
        # taught the loop to tell apart, and the sidecar keeps them apart too: a
        # stdio ``{"op":"shutdown"}`` is an ORDER somebody gave, while EOF is an
        # OBSERVATION that the pipe closed. ``stdin_eof`` is unreachable under
        # ``--service`` by construction — there EOF parks instead of exiting —
        # so it is a word only a launcher's stdio child can ever write.
        self._note_end(EndReason.SHUTDOWN_OP if stdio_shutdown else EndReason.STDIN_EOF)
        shutdown_frame = {"event": "shutdown", "pid": os.getpid()}
        # Socket clients hear it BEFORE the transport closes under them: an
        # attached client whose socket simply died could not tell a clean
        # service shutdown from a crash, which is the distinction the durable
        # service exists to make legible.
        self._broadcast_lanes(shutdown_frame)
        self._close_socket_lane(reason="shutdown")
        self._unregister_instance(reason="shutdown")
        self._write_end()
        self.frames.emit(shutdown_frame)
        return 0

    def _note_end(self, reason: str) -> None:
        """Latch WHY this runtime is ending. Inert when unarmed; never raises."""

        if self.end_reason is not None:
            self.end_reason.note(reason)

    def _write_end(self, reason: str | None = None) -> None:
        """Put the record on disk NOW, for a path that will not reach ``atexit``.

        The drain's exit is ``os._exit``; a signal handler's is the OS. Both run
        no interpreter shutdown at all, so the fallback hook is not a fallback
        for them.
        """

        if self.end_reason is not None:
            self.end_reason.write(reason)

    def _busy_frame(self) -> dict[str, Any]:
        with self.inflight_lock:
            pending = len(self.inflight)
            chat_turns = sum(1 for item in self.inflight.values() if item.is_chat_turn)
            long_runs = sum(1 for item in self.inflight.values() if item.is_long_run)
            subscriptions = sum(
                1 for item in self.inflight.values() if item.is_runtime_stream
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

    def _report_quiet_requests(self, pending: list[_ArgvRequest]) -> None:
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
                "pool_size": self.pool_size,
            }
            target = request.sink if request.sink is not None else self.frames
            try:
                target.emit(frame)
            except Exception:
                # Same contract as the pump that calls this: telemetry must
                # never take down the loop it describes.
                pass

    def _service_log(self, payload: dict[str, Any]) -> None:
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

    def _liveness_pump(self) -> None:
        while not self.liveness_stop.wait(self.liveness_pump_interval_seconds):
            with self.inflight_lock:
                pending = list(self.inflight.values())
            if not pending:
                continue
            busy_frame = self._busy_frame()
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
                    self.frames.emit(busy_frame)
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
                    self._broadcast_lanes(busy_frame)
                except Exception:
                    pass
            # The per-request half: `busy` is a count, and a client waiting
            # on ONE id needs to know whether that id has started. It gets
            # the FULL pending list — it does its own stream exclusion, and
            # a subscription-only lap can still be the lap on which an
            # argv request crosses the silence budget.
            self._report_quiet_requests(pending)

    def _unregister_instance(self, reason: str = "shutdown") -> None:
        """Drop this serve's registry entry. Idempotent, never raises.

        ``reason`` is the exit path that called it — the same three words
        the teardown already uses on ``_close_socket_lane`` beside it — and
        it exists so the receipt below names WHICH ending removed the row.
        """

        if self.store_root_path is None:
            return
        try:
            from agent_runtime.serve_registry import (
                serve_instance_path,
                unregister_serve_instance,
            )

            row_path = serve_instance_path(self.store_root_path, os.getpid())
            if unregister_serve_instance(self.store_root_path):
                # RS-3. The one line that marks the INSTANT this runtime
                # stopped advertising itself. The drain's terminal frame is
                # published before the teardown it accounts for, so until
                # this existed nothing on the wire dated the row's removal —
                # and that instant is what a contender's ``lock_held_by``
                # has to be read against.
                self._service_log(
                    {
                        "event": "serve_instance_unregistered",
                        "boot_id": self.boot_id,
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
                    self._service_log(
                        {
                            "event": "serve_instance_unregister_failed",
                            "boot_id": self.boot_id,
                            "pid": os.getpid(),
                            "reason": reason,
                            "path": str(row_path),
                        }
                    )
        except Exception:
            pass

    def _detach_stdio_owner(self) -> None:
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
            "boot_id": self.boot_id,
            "starter_pid": self.starter_pid,
        }
        self._service_log(detached)
        # Attached socket clients are owed this too: from here the runtime
        # answers only them, and "the launcher that started this closed" is
        # a fact a client showing a runtime sheet wants without asking.
        self._broadcast_lanes(detached)
        self.frames.detach()

    def _park_until_service_stop(self) -> None:
        """Hold the main thread open until something asks the service to stop.

        This is the ENTIRE lifetime change. The reader is gone, the pool and
        both socket lanes are untouched and still serving, and the thread
        that used to be blocked on ``os.read`` is blocked here instead —
        so when it is released, the finalization below it runs exactly as
        it does for a stdio EOF. Nothing is skipped, nothing is duplicated.

        The event is the mechanism; the poll is a bound. See
        ``_SERVICE_PARK_POLL_SECONDS``.
        """

        saved = _install_service_stop_signal(self.service_stop, note=self._note_end)
        try:
            while not self.service_stop.wait(_SERVICE_PARK_POLL_SECONDS):
                if self.drain_terminal_published.is_set():
                    break
        finally:
            _restore_service_stop_signal(saved)


def serve_loop(reader: TextIO, writer: TextIO, **options: Any) -> int:
    """Serve NDJSON frames from *reader* to *writer* until EOF, shutdown or drain.

    *options* are :class:`ServeSession`'s keyword arguments (pool size, the
    injected seams, ``socket_lane``, ``service``, …) with the same defaults.
    """

    return ServeSession(reader, writer, **options).run()
