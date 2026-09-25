"""Everything about ONE child process: its argv and environment, the bounded tails and pumps that read it, its identity and kill, the payload parser, the lane-specific error rewrite.

Map: ``tools/agent_chat_dispatch/__init__.py``.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import threading
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

__layer__ = "policy"


#: How long a child gets to honour its own ``--max-seconds`` before the parent
#: stops asking. The child enforces the budget itself and settles the turn
#: gracefully (``budget_exhausted``); this is the backstop for a child that
#: cannot — wedged in a syscall, stuck inside an unkillable tool — and it is
#: generous on purpose, because killing a turn that was about to write its
#: result loses the result.
KILL_GRACE_SECONDS = 120.0


#: The ``event`` a serve request's STDOUT lines carry
#: (``serve.py:1784``: ``_LineFrameProxy(frames, "line")``). Not ``"stdout"`` —
#: only the error stream is named after itself — and named here because a
#: reader that guesses collects nothing and sees an empty payload rather than an
#: error. Fenced by ``test_gateway_peer_cross_install_chat_e2e``, which is the
#: thing that caught the guess.
SERVE_STDOUT_EVENT = "line"


#: Bound on the child's captured streams. Stdout only has to carry one JSON
#: payload; stderr is diagnostics. Neither may grow without limit inside a
#: long-lived parent.
#:
#: The bound keeps the TAIL and drops the head — see :class:`_BoundedTail`. The
#: first implementation did the opposite and it was a data-loss bug, not a
#: tuning choice: the payload is the LAST thing the child prints, so a chatty
#: turn that crossed the cap had its own answer discarded and every successful
#: 30-minute dispatch was reported ``unknown``.
_MAX_STREAM_CHARS = 512_000
#: How much stderr rides into a failure record. Enough to name the failure,
#: nowhere near the 8KB reply bound.
_STDERR_EXCERPT = 800

#: The key every mission-chat payload carries, on every exit path — success,
#: refusal, blocker, replay. It is what tells the handler's payload apart from
#: any other JSON object a child happens to print.
_PAYLOAD_MARKER = "capability_id"


# --------------------------------------------------------------------------
# building the child invocation
# --------------------------------------------------------------------------


def build_dispatch_argv(spec: dict[str, Any], *, deadline_epoch: float) -> list[str]:
    """The child's argv — a plain ``harness mission-chat message`` turn.

    The relay deadline is minted by the caller of this function AT SPAWN TIME,
    not when the dispatch was enqueued. That distinction fixes a real erosion:
    a dispatch waiting behind the concurrency cap used to burn its wall budget
    sitting in a queue, so the budget the sender was told about and the budget
    the turn actually got drifted apart silently. The clock now starts when the
    turn does.

    ``--defer-thread-policy`` carries the tri-state ``new_session`` argparse
    cannot otherwise express (absent means False, not unset), so the child
    threads exactly as the in-process lane did.
    """

    argv = [
        sys.executable,
        "-m",
        "hermes_cli.main",
        "harness",
        "mission-chat",
        "message",
        "--persona",
        str(spec["persona_id"]),
        "--message",
        str(spec["message"]),
        "--json",
        "--intent-hint",
        str(spec.get("intent_hint") or "chat"),
        "--requested-by",
        str(spec.get("requested_by") or "agent-chat-relay"),
        "--max-seconds",
        f"{float(spec['max_seconds']):.3f}",
        "--relay-deadline-epoch",
        f"{float(deadline_epoch):.3f}",
    ]
    if spec.get("client_message_id"):
        argv += ["--client-message-id", str(spec["client_message_id"])]
    if spec.get("persona_instance_id"):
        argv += ["--persona-instance-id", str(spec["persona_instance_id"])]
    if spec.get("session_id"):
        argv += ["--session-id", str(spec["session_id"])]
    if spec.get("clarify_token"):
        argv += ["--clarify-token", str(spec["clarify_token"])]
    if spec.get("title"):
        argv += ["--title", str(spec["title"])]
    if spec.get("requested_by_session"):
        argv += ["--requested-by-session", str(spec["requested_by_session"])]
    # The chain travels WHOLE, so depth and cycle detection still run at the
    # handler's chokepoint inside the child. Only the CLOCK is fresh (the
    # operator ruling); the reach is not.
    chain = [str(item) for item in (spec.get("relay_chain") or []) if str(item).strip()]
    if chain:
        argv += ["--relay-chain", ",".join(chain)]
    new_session = spec.get("new_session")
    if new_session is True:
        argv.append("--new-session")
    elif new_session is None:
        argv.append("--defer-thread-policy")
    # new_session is False → omit both: argparse's absent default IS False.
    return argv


def child_environment(spec: dict[str, Any]) -> dict[str, str]:
    """The child's environment: writers and readers made to converge, explicitly.

    Both homes are STATED rather than inherited. ``HERMES_HOME`` is the
    operator/ambient home the dispatch was made from, captured through the
    existing authority before this supervisor's own environment could drift.
    ``HERMES_HEAD_HOME`` is the resolved background-work home, so the child's own
    background writers (its ``processes.json``, its delegations) land where the
    Activity projection and this parent read them. Nothing is re-derived here.

    ``PYTHONPATH`` is pinned to the tree THIS process runs from, so a serve
    booted out of a worktree spawns children from the same worktree instead of
    whatever the interpreter would otherwise import.
    """

    env = dict(os.environ)
    if spec.get("hermes_home"):
        env["HERMES_HOME"] = str(spec["hermes_home"])
    if spec.get("head_home"):
        env["HERMES_HEAD_HOME"] = str(spec["head_home"])
    try:
        import hermes_cli

        root = str(Path(hermes_cli.__file__).resolve().parents[1])
        existing = env.get("PYTHONPATH") or ""
        if root not in existing.split(os.pathsep):
            env["PYTHONPATH"] = root + (os.pathsep + existing if existing else "")
    except Exception:  # pragma: no cover - defensive
        pass
    return env


def parse_child_payload(text: str) -> dict[str, Any] | None:
    """The LAST complete JSON object in the child's stdout, or None.

    ``emit_json`` writes indented multi-line JSON, so this cannot be a line
    scan, and the child's stdout legitimately carries other lines (a SQLite WAL
    advisory, provider warnings) both before and after the payload. Decoding
    with ``raw_decode`` from every ``{`` and keeping the last success is the only
    shape that survives noise on both sides.
    """

    if not text:
        return None
    decoder = json.JSONDecoder()
    marked: dict[str, Any] | None = None
    fallback: dict[str, Any] | None = None
    index = text.find("{")
    while index != -1:
        try:
            value, end = decoder.raw_decode(text, index)
        except ValueError:
            index = text.find("{", index + 1)
            continue
        if isinstance(value, dict):
            # PREFER the handler's own payload. "last object wins" was wrong in
            # both directions and neither was theoretical: a shutdown notice
            # (``{"event":"mcp_shutdown","ok":false}``) printed after a
            # successful turn made it an error, and a trailing ``{}`` made it a
            # success with an EMPTY reply — which reads as "they had nothing to
            # report". Every mission-chat payload carries ``capability_id`` on
            # every exit path, so the discriminator is the producer's own, not a
            # guess about ordering.
            if _PAYLOAD_MARKER in value:
                marked = value
            elif marked is None:
                fallback = value
        index = text.find("{", max(end, index + 1))
    # The fallback keeps a pre-marker or hand-stubbed payload readable rather
    # than reporting a turn that did answer as having produced nothing.
    #
    # It is NOT an inversion of the old "last object wins", though it reads like
    # one: `fallback` is overwritten by every unmarked object while `marked` is
    # still None, so when NO marked payload exists at all — the only case where
    # `fallback` is ever returned — it holds the last object, exactly as before.
    # The `elif` only stops it tracking objects printed AFTER a marked payload,
    # and in that case `marked` wins regardless. Stated here because the shape
    # invites the wrong reading twice over.
    return marked if marked is not None else fallback


# --------------------------------------------------------------------------
# running one dispatch
# --------------------------------------------------------------------------


class _BoundedTail:
    """A capture that keeps the LAST ``limit`` characters and drops the head.

    WHICH END IS KEPT IS THE WHOLE POINT. The child prints its JSON payload
    LAST, after everything else it has to say, so a head-keeping bound throws
    away exactly the thing the parent came for: a chatty turn that crossed the
    cap had its own answer discarded, ``parse_child_payload`` returned None, and
    a successful thirty-minute dispatch was recorded ``unknown`` — with an empty
    stderr excerpt, because the noise was all on stdout. Reproduced at 583,070
    characters in, 512,033 captured, payload gone.

    The running total is not a micro-optimisation either. Re-summing the sink on
    every line is O(n²), so a child that printed past the cap pinned a pump
    thread to a core for the rest of a half-hour run, inside a long-lived serve.

    WHAT ``limit`` ACTUALLY BOUNDS, stated because it is not quite what it
    looks like: the eviction loop stops at one remaining chunk, so a SINGLE
    chunk larger than the limit is kept whole. That is deliberate — a chunk is
    one line, the payload is a single line of JSON, and truncating it produces
    something ``parse_child_payload`` cannot read, which is precisely the
    data-loss this class exists to prevent. The effective ceiling is therefore
    ``max(limit, longest single line)``, not ``limit``, and this runs inside a
    long-lived serve process. Bounding it for real would have to happen at the
    producer (a child that bounds its own payload line), never here, where the
    only available tool is the truncation that breaks it.
    """

    __slots__ = ("_chunks", "_limit", "_total", "dropped_chars")

    def __init__(self, limit: int):
        from collections import deque

        self._chunks: Any = deque()
        self._limit = int(limit)
        self._total = 0
        self.dropped_chars = 0

    def append(self, text: str) -> None:
        if not text:
            return
        self._chunks.append(text)
        self._total += len(text)
        while self._total > self._limit and len(self._chunks) > 1:
            oldest = self._chunks.popleft()
            self._total -= len(oldest)
            self.dropped_chars += len(oldest)

    def text(self) -> str:
        return "".join(self._chunks)


def _drain(stream, sink: _BoundedTail) -> threading.Thread:
    """Consume a child pipe for its WHOLE lifetime on a daemon thread.

    Both pipes get one of these, always. A stderr pipe nobody reads fills its OS
    buffer and wedges the child mid-write — a hang that looks exactly like a slow
    turn, and the standing reason this repo requires draining both streams
    rather than only the one being parsed.
    """

    def _pump() -> None:
        try:
            for line in iter(stream.readline, ""):
                if not line:
                    break
                sink.append(line)
        except Exception:  # pragma: no cover - pipe torn down under us
            pass
        finally:
            try:
                stream.close()
            except Exception:
                pass

    thread = threading.Thread(target=_pump, daemon=True)
    thread.start()
    return thread


def _release_pumps(proc, threads) -> None:
    """Join the pumps, then force them loose if a survivor still holds the pipe.

    ``readline`` blocks until EOF, and EOF only arrives when every writer has
    closed. A grandchild that inherited the pipe — which is exactly what "go run
    the suite" spawns — or a tree member that survived the kill keeps it open,
    so a plain join leaks two daemon threads PER DISPATCH, permanently, inside a
    process that is meant to run for days.

    Closing the parent's handle unblocks the reader (it raises, and the pump
    swallows it), which bounds the thread even when the pipe does not close on
    its own. Best effort by contract: a thread that still will not budge is one
    leak, not a growing one, and never a failed dispatch.
    """

    for thread in threads:
        thread.join(timeout=10)
    if not any(thread.is_alive() for thread in threads):
        return
    for stream in (getattr(proc, "stdout", None), getattr(proc, "stderr", None)):
        try:
            if stream is not None and not stream.closed:
                stream.close()
        except Exception:
            pass
    for thread in threads:
        thread.join(timeout=2)


def _child_identity(pid: int) -> int | None:
    try:
        from gateway.status import get_process_start_time

        return get_process_start_time(int(pid))
    except Exception:  # pragma: no cover - defensive
        return None


def _kill_child(pid: int, started_at: int | None) -> None:
    """Identity-verified tree-kill through the repo's ONE implementation.

    ``ProcessRegistry._terminate_host_pid`` re-validates the recorded start time
    before it signals anything, which is what stops a recycled PID from turning
    a budget timeout into a killed stranger. A second tree-kill here would be a
    second place for that guard to be forgotten.
    """

    try:
        from tools.process_registry import ProcessRegistry

        ProcessRegistry._terminate_host_pid(int(pid), started_at)
    except Exception:  # pragma: no cover - best effort by contract
        logger.debug("dispatch child %s tree-kill failed", pid, exc_info=True)


def _detached_error_text(payload: dict[str, Any]) -> str:
    """The refusal text, rewritten for the lane it will actually be READ on.

    Typed refusals from the handler are written for a caller who is BLOCKED on
    the reply — ``relay_budget_exhausted`` ends "Answer your caller with what you
    have", which is sound advice mid-turn and nonsense inside a delivered error
    turn that arrives minutes later, addressed to an agent who has already moved
    on and has no caller waiting.

    Only the ones whose guidance is lane-specific are rewritten; everything else
    passes through verbatim, because a refusal an agent can act on is worth more
    than a uniformly-phrased one it cannot.
    """

    kind = str(payload.get("error_kind") or "")
    raw = str(payload.get("error") or payload.get("blocker") or "the dispatched turn failed")
    if kind == "relay_budget_exhausted":
        return (
            "The dispatch was refused before it ran: the relay chain it belongs to had no wall "
            "budget left. Nothing was executed and there is no partial result. Re-dispatch it as "
            "a fresh request if you still need it."
        )
    if kind in {"relay_cycle", "relay_depth_limit"}:
        return (
            f"The dispatch was refused before it ran ({kind}): this request would have looped back "
            "through an agent already on the relay chain, or gone deeper than the chain allows. "
            "Nothing was executed. Ask the agent directly, or do it yourself."
        )
    return raw[:600]
