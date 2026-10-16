"""Process-global state a fork module owns, declared beside the global with its reset.

Plan ``docs/agent-runtime-harness/planned/process-global-state-reset-2026-10-15.md``.
A module that keeps state for the whole Python process -- a memo, a registry, an
on/off switch, a keeper's windows -- registers the function that puts that state
back the way a fresh import left it, at import, next to the global:

    _ENABLED = False
    register_process_state("agent_runtime.builds.detect", _reset, holds=("_ENABLED",))

:func:`reset_all_process_state` runs every declared reset. One test fixture calls
it before each test, so a leak is retired by a declaration in the owning module,
never by one more line in a fixture somewhere else. ``holds`` names the module
globals the reset covers; the census gate
(``tests/tooling/test_process_globals_declared.py``) reads it at runtime to
tell a declared global from one nobody owns.

``models`` layer, no imports: every layer may declare.
"""

from __future__ import annotations

from typing import Callable

__layer__ = "models"

#: name -> (reset, the module globals it covers). This registry is itself
#: process-global and is never reset: it is the declaration, not the state.
_RESETS: dict[str, tuple[Callable[[], None], tuple[str, ...]]] = {}


class ProcessStateResetError(RuntimeError):
    """One or more declared resets raised; every other reset still ran."""


def register_process_state(name: str, reset: Callable[[], None], *, holds: tuple[str, ...] = ()) -> None:
    """Declare ``reset`` for the process state ``name`` owns. ``name`` is the
    owning module's dotted name; ``holds`` the module globals ``reset`` puts
    back. Re-registering a name (a module re-imported) replaces it."""

    if not name or not callable(reset):
        raise ValueError("register_process_state needs a name and a callable reset")
    _RESETS[name] = (reset, tuple(holds))


def registered_process_state() -> tuple[str, ...]:
    """Every declared name, sorted."""

    return tuple(sorted(_RESETS))


def declared_globals() -> frozenset[str]:
    """``module:global`` for every global a declared reset covers."""

    return frozenset(f"{name}:{held}" for name, (_reset, holds) in _RESETS.items() for held in holds)


def reset_all_process_state() -> tuple[str, ...]:
    """Run every declared reset, in name order, and return the names reset.

    A reset that raises does not stop the others; after all have run, a
    :class:`ProcessStateResetError` names every one that failed (the first
    failure is its cause), so a broken reset is loud rather than a silent leak.
    """

    failed: list[str] = []
    first: BaseException | None = None
    for name in sorted(_RESETS):
        reset, _holds = _RESETS[name]
        try:
            reset()
        except Exception as exc:  # collected; re-raised below
            failed.append(name)
            first = first or exc
    if failed:
        raise ProcessStateResetError(f"process-state reset failed: {', '.join(failed)}") from first
    return registered_process_state()


__all__ = [
    "ProcessStateResetError",
    "declared_globals",
    "register_process_state",
    "registered_process_state",
    "reset_all_process_state",
]
