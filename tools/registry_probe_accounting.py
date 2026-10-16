"""Availability-probe accounting for ``tools.registry`` (fork-owned).

The registry's ``check_fn`` probes and availability rounds are counted here so
the upstream file carries only the call sites: ``_note_check_fn_probe()`` where a
probe actually executes, ``with _probe_round():`` around an availability pass,
and ``bump_check_fn_epoch()`` inside ``invalidate_check_fn_cache``. Stdlib-only
and import-free of the registry, so it is cycle-safe at the registry's import.
"""

from contextlib import contextmanager
import threading

_check_fn_epoch = 0
_probe_state = threading.local()


def _note_check_fn_probe() -> None:
    _probe_state.probes = int(getattr(_probe_state, "probes", 0)) + 1


@contextmanager
def _probe_round():
    before = int(getattr(_probe_state, "probes", 0))
    try:
        yield
    finally:
        if int(getattr(_probe_state, "probes", 0)) > before:
            _probe_state.rounds = int(getattr(_probe_state, "rounds", 0)) + 1


def probe_rounds_this_thread() -> int:
    """Rounds this THREAD has run since the process started.

    A cumulative counter, never reset by the runtime: callers take the
    difference across the window they care about. Resetting it here would make
    two overlapping observers destroy each other's measurement.
    """

    return int(getattr(_probe_state, "rounds", 0))


def bump_check_fn_epoch() -> None:
    """Advance the availability counter. ``invalidate_check_fn_cache`` calls it under its lock."""

    global _check_fn_epoch
    _check_fn_epoch += 1


def check_fn_epoch() -> int:
    """The registry's availability counter (fork addition).

    Moves on every :func:`tools.registry.invalidate_check_fn_cache` and on
    nothing else. A memo that keys on registry CONTENT
    (``agent_runtime.chat_lane_bundle``) pairs this with that content instead of
    with ``registry.generation``, which also counts a register/deregister pair
    that left the content as it was. Compare for equality only.
    """

    return _check_fn_epoch
