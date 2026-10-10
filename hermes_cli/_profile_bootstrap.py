"""The gate that says who may run the CLI's pre-argparse profile bootstrap.

The pre-parse itself is upstream's ``hermes_cli.main._apply_profile_override``
(it has to run before any hermes module is importable: many modules cache
``HERMES_HOME`` at import time, so ``--profile``/``-p`` is intercepted out of
``sys.argv`` and turned into an env var, and the flag is stripped so argparse
never sees it). It lives in ``main.py`` in upstream's bytes plus the fork's
three in-place deltas; only this gate is fork-owned.

``is_hermes_cli_entrypoint()`` exists because the pre-parse used to run from
``main.py``'s MODULE SCOPE, which made two facts true that nobody chose:

* **it parsed whatever argv the process happened to have.** Under pytest that
  argv is pytest's, so ``pytest … -p markdump`` was read as ``--profile
  markdump``, resolved nothing, and ``sys.exit(1)`` out of a collection import —
  reported as a bare ``INTERNALERROR> SystemExit: 1`` with no line naming the
  cause. Reproduced three times before it was understood.
* **it mutated the whole process's env.** No fixture is active during
  collection, so a collection-time import of ``hermes_cli.main`` read the
  OPERATOR's live ``<root>/active_profile`` and pointed ``HERMES_HOME`` at their
  live profile for the rest of the session. Every hermetic fixture in the tree
  runs one layer BELOW that window and cannot close it.

So importing a module must not do either, and the gate is what makes that
structural: the pre-parse now runs only when this process was STARTED as a
hermes CLI entrypoint. The gate is deliberately **entrypoint-based, not
env-var-based** — an env toggle would be a silent fallback that any process
could set, including the ones this exists to keep out, and "the tests set the
opt-out" is exactly how the window would grow back.

``is_hermes_cli_entrypoint`` answers POSITIVELY or not at all: it names the
console scripts hermes installs (pinned against ``pyproject.toml``'s
``[project.scripts]`` by ``tests/hermes_cli/test_cli_entrypoint_gate.py``, so a
new script cannot be added silently) and it recognises ``python -m
hermes_cli.main`` through the caller's own ``__name__``. Nothing else answers
true, and pytest can satisfy neither arm: its argv[0] is pytest's and it imports
``main`` under its real dotted name.

Import-safe and stdlib-only by contract: ``main.py`` imports it before any
hermes module is importable.
"""

from __future__ import annotations

import sys

#: The console scripts ``pyproject.toml`` installs. Every one of them reaches
#: ``hermes_cli.main`` (``hermes`` IS it; ``hermes-acp`` and ``hermes-agent``
#: import it), so all three keep the pre-parse they have always had — this gate
#: was built to change nothing about a real invocation.
#:
#: Typed here rather than read from ``pyproject.toml`` because a wheel install
#: does not ship one; the equality against that table is asserted in the test
#: named in the module docstring, which is where a fourth script gets noticed.
HERMES_CONSOLE_SCRIPTS = frozenset({"hermes", "hermes-agent", "hermes-acp"})

#: Suffixes a launcher may hang on the script name. ``.exe`` is pip on Windows;
#: ``-script.py`` is older pip's Windows shim; ``.hermes-wrapped`` is what
#: ``makeWrapper`` leaves behind in a nix store, and the nix path is a shipped
#: deployment here (see ``pyproject.toml``'s uv2nix note), so dropping it is not
#: hypothetical tidiness.
#: The attribute hermes' OWN published launcher sets on ``sys`` before it imports
#: anything from the checkout (``hermes_cli._launchers.PIN_DEFAULT_HOME_FLAG``;
#: spelled here because this module is stdlib-only, pinned equal by
#: ``tests/hermes_cli/test_cli_entrypoint_gate.py``). That launcher runs
#: ``python -I -c <script>``, so ``argv[0]`` is ``"-c"`` when ``hermes_cli.main``
#: is imported, and neither arm above could recognise it: ``hermes.cmd -p alice
#: mcp list`` answered "'alice' is not a `hermes` command" (2026-10-02). ``-c``
#: plus the mark is the positive answer — pytest sets neither.
LAUNCHER_MARK = "_hermes_pin_default_home"

_EXECUTABLE_SUFFIXES = (".exe", ".cmd", ".bat", ".pyw", ".pyc", ".py")


def _argv0_basename(text: str) -> str:
    """The last path component of ``argv0`` under EITHER separator.

    ``argv[0]`` is a path in the syntax of the launcher that produced it, and
    the Windows launcher shapes this module exists to recognise
    (``C:\\venv\\Scripts\\hermes.exe``, ``…\\hermes-script.py``) are
    backslash-separated. ``os.path.basename`` only knows the RUNNING host's
    separator: on POSIX it hands the whole Windows path back, so
    :func:`entrypoint_name` returned ``c:\\venv\\scripts\\hermes`` and the gate
    compared THAT against the console-script names. Splitting on both is right
    on both hosts — a POSIX console script's path never carries a backslash,
    and a Windows one may carry either — and it is what lets the Windows
    shapes be asserted from the Linux CI runners instead of only on a
    developer's box.
    """

    tail = str(text or "").strip().strip('"')
    for separator in ("\\", "/"):
        tail = tail.rpartition(separator)[2]
    # A drive-relative argv[0] ("C:hermes.exe") has no separator at all;
    # ntpath.basename drops the drive, so this keeps parity with it.
    if len(tail) > 1 and tail[1] == ":" and tail[0].isalpha():
        tail = tail[2:]
    return tail


def entrypoint_name(argv0: str) -> str:
    """The bare program name behind ``argv[0]``, launcher decoration removed."""

    name = _argv0_basename(argv0)
    lowered = name.lower()
    for suffix in _EXECUTABLE_SUFFIXES:
        if lowered.endswith(suffix):
            name = name[: -len(suffix)]
            break
    if name.startswith("."):
        name = name[1:]
    for shim in ("-script", "-wrapped"):
        if name.lower().endswith(shim):
            name = name[: -len(shim)]
    return name.lower()


def is_hermes_cli_entrypoint(
    caller_module_name: str,
    *,
    argv0: str | None = None,
) -> bool:
    """Was THIS process started as a hermes CLI entrypoint?

    ``caller_module_name`` is the importing module's ``__name__``. It is the
    whole of the ``python -m hermes_cli.main`` / ``python path/to/main.py`` arm:
    runpy executes the module AS ``__main__`` in that case, and only in that
    case, so the caller reporting ``"__main__"`` is the process saying it IS the
    program being run. A test importing the module gets its real dotted name and
    cannot reach this arm even by accident.

    Otherwise the process entrypoint has to BE one of hermes' console scripts.
    ``argv[0]`` is what carries that: pip/uv/nix all put the script's own path
    there. Under pytest it is pytest's own path, which is not in the set and
    cannot be made to be by anything a test does short of rewriting argv[0] —
    at which point the process is lying about what it is, not accidentally
    tripping a check.
    """

    if caller_module_name == "__main__":
        return True
    if argv0 is None:
        argv0 = sys.argv[0] if sys.argv else ""
    if argv0 == "-c" and getattr(sys, LAUNCHER_MARK, False):
        return True
    return entrypoint_name(argv0) in HERMES_CONSOLE_SCRIPTS

