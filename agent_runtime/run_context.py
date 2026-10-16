"""The run's context-local process facts: what a turn used to publish through ``os.environ``.

Plan: ``docs/agent-runtime-harness/planned/run-serialization-retirement-2026-10-15.md``.
``persona_profile_context`` writes ``HERMES_AGENT_RUNTIME_ROOT`` and ``HERMES_AUTH_HOME``
into the process env for the width of a turn, and that write is sound only while one turn
runs at a time (``profile_runner.workdir._WORKDIR_LOCK``). This module is the per-context
channel that replaces it:

* :func:`run_runtime_root_scope` binds the turn's runtime root in a ContextVar and, for
  in-process store reads, a matching ``resolution.runtime_resolution_scope``.
* :func:`runtime_root_signal` is what the terminal envelope and the harness safety block
  read instead of the raw env var: the bound root first, the process env second.
* :func:`apply_run_context_child_env` is the ONE spawn seam: upstream
  ``tools/environments/local.py::_apply_profile_home`` calls it for every factory-built
  child env, so a child carries this run's root and auth home even when nobody wrote them
  into ``os.environ``.

With nothing bound every function is a no-op and the process env answers as before.
"""

from __future__ import annotations

import os
from collections.abc import Iterator, MutableMapping
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path

__layer__ = "models"

__all__ = [
    "RUNTIME_ROOT_ENV",
    "apply_run_context_child_env",
    "bound_runtime_root",
    "run_runtime_root_scope",
    "runtime_root_signal",
]

RUNTIME_ROOT_ENV = "HERMES_AGENT_RUNTIME_ROOT"
AUTH_HOME_ENV = "HERMES_AUTH_HOME"

_RUN_RUNTIME_ROOT: ContextVar[str] = ContextVar("hermes_run_runtime_root", default="")


def bound_runtime_root() -> str:
    """The runtime root this context's run bound, or ``""``."""

    return _RUN_RUNTIME_ROOT.get()


def runtime_root_signal() -> str:
    """The run's runtime root for a reader that used to key on the raw env var.

    The bound root wins; the process env answers only for a context with none bound (a
    plain CLI process, or a serve pinned by its launcher).
    """

    return bound_runtime_root() or str(os.environ.get(RUNTIME_ROOT_ENV, "") or "").strip()


@contextmanager
def run_runtime_root_scope(root: Path | str | None) -> Iterator[None]:
    """Bind *root* as this context's runtime root. ``None``/empty binds nothing."""

    text = str(root or "").strip()
    if not text:
        yield
        return
    token = _RUN_RUNTIME_ROOT.set(text)
    try:
        yield
    finally:
        _RUN_RUNTIME_ROOT.reset(token)


def apply_run_context_child_env(env: MutableMapping[str, str]) -> None:
    """Write this context's runtime root and auth home into a child env, in place.

    Only values a run BOUND are written; with none bound the child keeps whatever its base
    env carried, exactly as before this seam existed.
    """

    root = bound_runtime_root()
    if root:
        env[RUNTIME_ROOT_ENV] = root
    from agent_runtime.profile_home import get_hermes_auth_home_override

    auth_home = get_hermes_auth_home_override()
    if auth_home:
        env[AUTH_HOME_ENV] = auth_home
