"""Why a serve process ended: the service-stop signal, the console-ctrl and signal
reason handlers, and the ``_ServeEndReason`` holder the loop writes into its sidecar.
"""

from __future__ import annotations

import os
import sys
import threading
from typing import Any, Callable


__layer__ = "stores"

__all__ = [
    "CONSOLE_CTRL_END_REASONS",
    "END_REASON_UNCAUGHT_PREFIX",
    "END_REASON_UNKNOWN",
    "END_REASON_VOCABULARY",
    "SIGNAL_END_REASONS",
    "_CONSOLE_CTRL_HANDLER_KEEPALIVE",
    "_ServeEndReason",
    "_UNCAUGHT_TYPE_MAX_LENGTH",
    "_console_ctrl_reason_callback",
    "_end_reason_is_known",
    "_install_console_ctrl_reason_handler",
    "_install_service_stop_signal",
    "_install_signal_reason_handlers",
    "_restore_service_stop_signal",
]


def _install_service_stop_signal(
    stop: threading.Event, *, note: Callable[[str], None] | None = None
) -> Any:
    """Make ``SIGTERM`` set *stop*; return what to restore, or ``None``.

    Installed only for the ``--service`` park and removed when it ends, so the
    only signal disposition a non-service serve carries is the recorder's own
    (RL-16), which re-raises the default and changes no behaviour.

    *note* is the end-reason recorder's latch. It is passed here rather than
    left to the boot-time handler because this handler REPLACES that one for the
    duration of the park — a SIGTERM arriving while parked would otherwise wake
    the service, run the ordinary shutdown tail, and record the ordinary
    shutdown word for a death the operator caused with a signal.

    Honest about the platform, because this is the half that cannot be proven
    here. On POSIX this is the ordinary stop verb: ``kill <pid>`` sets the event
    and the finalization below runs unchanged. **On Windows it is very nearly
    decoration** — a handler can be registered, but nothing in the OS delivers
    SIGTERM to another process: ``os.kill(pid, SIGTERM)`` is ``TerminateProcess``
    and the handler never runs. The Windows stop verbs are therefore the socket
    ones (``harness serve connect --drain``), which is what the launcher will
    use, and what the e2e proof exercises.

    Never raises: ``signal.signal`` refuses to run off the main thread, which is
    exactly where every ``serve_loop`` unit test calls this from. That case
    degrades to "no handler", which is today's behaviour.
    """

    def _stop(*_args: Any) -> None:
        if note is not None:
            note("sigterm")
        stop.set()

    try:
        import signal as _signal

        previous = _signal.getsignal(_signal.SIGTERM)
        _signal.signal(_signal.SIGTERM, _stop)
        return (_signal.SIGTERM, previous)
    except Exception:  # pragma: no cover - platform/thread dependent
        return None


def _restore_service_stop_signal(saved: Any) -> None:
    """Undo :func:`_install_service_stop_signal`. Never raises."""

    if not saved:
        return
    try:
        import signal as _signal

        _signal.signal(saved[0], saved[1])
    except Exception:  # pragma: no cover - platform/thread dependent
        pass


# ── RL-16: the runtime says why it ended ────────────────────────────────────
#
# The measurement this exists for: on 2026-09-05 a runtime (pid 33680) died
# between two observations with its registry row left on disk, and NOTHING on
# the machine could say what killed it. A closed console window, a logoff, an
# uncaught fault, and a hygiene sweep's ``taskkill /F`` all leave the identical
# evidence — a stale row — so the cause had to be GUESSED from a chain of
# circumstantial process facts. It was guessed wrong twice (see the plan's
# §8.8b, which struck its own §3).
#
# So the runtime now names its own cause on the way out, into
# ``serve_instances/<pid>.ended.json``. Every mechanism below exists to catch
# one more class of ending; the union is deliberately not complete, and the
# hole is the point: a ``TerminateProcess`` runs no code in this process at all,
# writes nothing, and THAT SILENCE IS THE READING — the launcher words a stale
# row with no sidecar ``ended=absent``, which is a fact, not an absence of one.
#
#: Windows console control events → the word. ``wincon.h``'s numbers, matched
#: rather than imported because ``signal.CTRL_*`` covers only two of the five.
#:
#: CTRL_BREAK shares ``ctrl_c``'s word on purpose: both are "the operator
#: interrupted it from the console", and Break exists in this table mainly
#: because it is the only one of the five that ``GenerateConsoleCtrlEvent`` can
#: aim at a single process group — which is what makes the handler testable at
#: all. LOGOFF and SHUTDOWN share ``logoff`` for the same reason RL-16 gave them
#: one word: the distinction a reader needs is "the session/machine went away",
#: not which of the two notifications the OS chose.
CONSOLE_CTRL_END_REASONS: dict[int, str] = {
    0: "ctrl_c",  # CTRL_C_EVENT
    1: "ctrl_c",  # CTRL_BREAK_EVENT
    2: "ctrl_close",  # CTRL_CLOSE_EVENT — the console window's X
    5: "logoff",  # CTRL_LOGOFF_EVENT
    6: "logoff",  # CTRL_SHUTDOWN_EVENT
}

#: POSIX signals → the word, by NAME because ``SIGHUP`` does not exist on
#: Windows. ``SIGHUP`` maps to ``logoff`` rather than to a word of its own: a
#: hangup is the session going away, which is what ``logoff`` means on the other
#: platform, and one vocabulary that reads the same on both is worth more than a
#: sixth word that only ever appears on one.
SIGNAL_END_REASONS: dict[str, str] = {"SIGTERM": "sigterm", "SIGHUP": "logoff"}

#: What nothing-set-a-reason writes. Not a failure: a route this recorder was
#: never taught, said plainly instead of guessed at.
END_REASON_UNKNOWN = "unknown_exit"

#: ``uncaught:`` is the one open-ended word — the exception's type name is the
#: whole value of it — and it is a PREFIX rather than a member below.
END_REASON_UNCAUGHT_PREFIX = "uncaught:"

#: The closed set. Closed because the launcher's runtime sheet switches on it,
#: and a word it has never seen renders as a shrug. A caller that hands over
#: anything else gets ``unknown_exit`` — the record says "I do not know", which
#: is true, rather than passing an unvetted string through to an operator's UI.
END_REASON_VOCABULARY: frozenset[str] = frozenset(
    {
        # the ordinary ends, one per code path
        "drained",  # a drain op completed; _finish_drain owns it
        "shutdown_op",  # {"op":"shutdown"} — an ORDER from the stdio owner
        "stdin_eof",  # the pipe closed on a NON-service serve (see below)
        # the operator and the OS
        "ctrl_close",
        "ctrl_c",
        "sigterm",
        "logoff",
        # the fallback
        END_REASON_UNKNOWN,
    }
)

#: A type name arrives from ``type(exc).__name__`` and is therefore an
#: identifier — but it reaches an operator's screen, so it is validated rather
#: than trusted.
_UNCAUGHT_TYPE_MAX_LENGTH = 64


def _end_reason_is_known(reason: str) -> bool:
    if reason in END_REASON_VOCABULARY:
        return True
    if not reason.startswith(END_REASON_UNCAUGHT_PREFIX):
        return False
    name = reason[len(END_REASON_UNCAUGHT_PREFIX) :]
    return bool(name) and len(name) <= _UNCAUGHT_TYPE_MAX_LENGTH and name.isidentifier()


class _ServeEndReason:
    """One runtime's last word, written once, from wherever the end arrives.

    Latch-then-write, and both halves matter. The LATCH is first-wins because
    several of these mechanisms fire at once on a real ending — a CTRL_CLOSE
    lands while the drain that was already running finishes, and the cause is
    whichever got there first, not whichever finished last. The WRITE is
    once-only because ``atexit`` runs after the drain path has already written
    and a second write would restamp ``at`` with a time this process was already
    dead at.

    Every method is called from somewhere hostile — an ``atexit`` hook, an
    OS-owned console-control thread, a signal handler, a drain that is holding
    a watchdog open — so nothing here raises, allocates a logger, or waits.
    """

    __slots__ = ("_boot_id", "_lock", "_pid", "_reason", "_store_root", "_written")

    def __init__(
        self, store_root: Any, *, boot_id: str, pid: int | None = None
    ) -> None:
        self._store_root = store_root
        self._boot_id = str(boot_id)
        self._pid = int(pid if pid is not None else os.getpid())
        self._reason: str | None = None
        self._written = False
        self._lock = threading.Lock()

    def note(self, reason: str) -> None:
        """Latch a cause. First one wins; never raises."""

        try:
            with self._lock:
                if self._reason is None:
                    self._reason = str(reason)
        except Exception:  # pragma: no cover - defensive
            pass

    def write(self, reason: str | None = None) -> bool:
        """Put the record on disk. True the one time it lands."""

        try:
            with self._lock:
                if self._written:
                    return False
                if reason is not None and self._reason is None:
                    self._reason = str(reason)
                word = self._reason or END_REASON_UNKNOWN
                if not _end_reason_is_known(word):
                    word = END_REASON_UNKNOWN
                self._written = True
        except Exception:  # pragma: no cover - defensive
            return False
        try:
            from agent_runtime.serve_registry import write_serve_ended

            return write_serve_ended(
                self._store_root,
                reason=word,
                boot_id=self._boot_id,
                pid=self._pid,
            )
        except Exception:
            return False


def _console_ctrl_reason_callback(recorder: _ServeEndReason) -> Callable[[int], int]:
    """The console control handler's body, as a plain function so it is testable.

    Returns 0 — FALSE, "not handled" — for every event including the ones it
    recorded. That is the contract, not laziness: TRUE would mean this process
    has taken responsibility for the event, and Ctrl-C would stop raising
    ``KeyboardInterrupt``, a close would stop closing. The handler's only job is
    to leave a record in the few seconds Windows gives it before the OS kills
    the process anyway.
    """

    def _handle(event: int) -> int:
        try:
            reason = CONSOLE_CTRL_END_REASONS.get(int(event))
            if reason is not None:
                recorder.note(reason)
                recorder.write()
        except Exception:  # pragma: no cover - defensive
            pass
        return 0

    return _handle


#: The ctypes callback must outlive the call that registers it — Windows keeps
#: only the function pointer, and a garbage-collected trampoline is an access
#: violation the next time the operator presses Ctrl-C. Module-level, because
#: there is exactly one serve per process.
_CONSOLE_CTRL_HANDLER_KEEPALIVE: Any = None


def _install_console_ctrl_reason_handler(recorder: _ServeEndReason) -> Any:
    """``SetConsoleCtrlHandler`` for the five events. Never raises.

    Returns the registered callback (kept alive at module scope) or ``None``
    where there is nothing to install onto.

    **It must install cleanly with NO CONSOLE**, which is the case RL-17 is
    about to make normal: once the launcher starts the runtime with
    ``CREATE_NO_WINDOW`` there is no window for anyone to close, so
    ``CTRL_CLOSE_EVENT`` will rarely arrive again. Today's chain still has a
    visible ``cmd /K`` console and closing it is one of the two live candidate
    explanations for the 2026-09-05 death, so the handler matters NOW and must
    cost nothing later.
    """

    global _CONSOLE_CTRL_HANDLER_KEEPALIVE
    if sys.platform != "win32":
        return None
    try:
        import ctypes

        prototype = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_uint)
        callback = prototype(_console_ctrl_reason_callback(recorder))
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        if not kernel32.SetConsoleCtrlHandler(callback, 1):
            return None
        _CONSOLE_CTRL_HANDLER_KEEPALIVE = callback
        return callback
    except Exception:
        return None


def _install_signal_reason_handlers(recorder: _ServeEndReason) -> None:
    """Latch-and-die handlers for ``SIGTERM``/``SIGHUP``. Never raises.

    Deliberately NOT a stop mechanism. Each handler records the word, restores
    the default disposition, and re-raises the same signal at itself, so the
    process dies exactly as it did before this existed — same exit status, same
    timing. A handler that merely latched would silently make a serve immune to
    ``kill``, which is a lifetime change nobody asked for.

    ``signal.signal`` refuses to run off the main thread; that lands in the
    ``except`` and degrades to today's behaviour.
    """

    try:
        import signal as _signal
    except Exception:  # pragma: no cover - signal is always importable
        return

    def _make(signum: int, reason: str) -> Callable[..., None]:
        def _handler(*_args: Any) -> None:
            recorder.note(reason)
            recorder.write()
            try:
                _signal.signal(signum, _signal.SIG_DFL)
                os.kill(os.getpid(), signum)
            except Exception:  # pragma: no cover - defensive
                pass

        return _handler

    for name, reason in SIGNAL_END_REASONS.items():
        signum = getattr(_signal, name, None)
        if signum is None:
            continue
        try:
            _signal.signal(signum, _make(int(signum), reason))
        except Exception:  # pragma: no cover - platform/thread dependent
            continue
