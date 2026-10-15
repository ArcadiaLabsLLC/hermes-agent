"""Fork: the one builder of a child interpreter's leading argv.

The Launcher starts a bundled runtime that must never write beside its source
(a sealed macOS ``.app`` breaks its signature; an AppImage is read-only) with
``-X pycache_prefix=<per-user dir>`` and ``PYTHONPYCACHEPREFIX``. A child
started with ``-I`` ignores every ``PYTHON*`` variable, so it would compile the
standard library (not precompiled on those formats) into the bundle. Every
``-I`` spawn of an interpreter that imports modules goes through
:func:`child_python_argv`, which forwards this process's ``sys.pycache_prefix``
as the explicit ``-X`` option the child cannot ignore.

Sites that need no forwarding, measured 2026-10-15: ``venv_sync`` and
``source_completion`` pass ``-B`` (no bytecode written); ``update_custody``'s
``-I -S`` launchers and ``update_cmd_commit``'s ``compileall`` run only for a
source checkout's self-update, never inside a bundle.
"""

from __future__ import annotations

import os
import sys


def bytecode_cache_flags() -> list[str]:
    """``["-X", "pycache_prefix=<dir>"]`` when this interpreter has a cache prefix, else ``[]``."""
    prefix = getattr(sys, "pycache_prefix", None)
    return ["-X", f"pycache_prefix={prefix}"] if prefix else []


def child_python_argv(python: str | os.PathLike[str], *options: str) -> list[str]:
    """``[python, <cache prefix flags>, *options]`` for a child interpreter."""
    return [os.fspath(python), *bytecode_cache_flags(), *options]
