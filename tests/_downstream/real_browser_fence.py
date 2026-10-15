"""No test spawns the REAL agent-browser or a real Chromium (fork-hygiene, lane h13-test 2026-09-29).

Upstream's browser tests resolve ``agent-browser`` the way production does: pm's install,
then the operator PATH. On a developer box that is a live profile's
``node_modules\\agent-browser`` (measured: ``X:\\Eternia\\.hermes\\profiles\\alice\\node\\...``),
so a test that forgot one patch — ``test_browser_real_profile``'s
``test_snapshot_failure_fails_closed`` asks it for a session's ``cdp-url`` — starts a real
daemon, the daemon launches a headless Chrome on a test-tmp user-data-dir, and both
outlive the run (lane h12-fix ``e4763d4b2a``); a daemon still holding the pipe hangs the
next run of the same test.

The fence sits on ``subprocess.Popen._execute_child`` — the one door every ``Popen``
(and ``subprocess.run``, and asyncio's Windows ``Popen`` subclass) walks through, below
any test's own ``patch.object(subprocess, "Popen", fake)``, which still wins. A spawn
whose program is an agent-browser or a Chromium binary resolved OUTSIDE this run's temp
roots never happens: the test SKIPS, naming the binary it reached. A fake of the same
name a test writes under ``tmp_path`` is not the real thing and runs. Off the test's
own thread a skip cannot land, so there the spawn fails as ``FileNotFoundError`` —
the "not installed" answer production already fails closed on.
"""

from __future__ import annotations

import errno
import os
import shlex
import shutil
import subprocess
import tempfile
import threading

import pytest

_AGENT_BROWSER = "agent-browser"
_CHROMIUM = frozenset({
    "chrome", "chromium", "chromium-browser", "google-chrome", "google-chrome-stable",
    "chrome-headless-shell", "msedge", "brave", "brave-browser",
})
# A launcher whose NEXT argument is the program that really runs (``npx agent-browser``).
_LAUNCHERS = frozenset({"node", "npx", "pnpm", "bunx", "bun", "cmd"})
_SUFFIXES = (".exe", ".cmd", ".bat", ".ps1", ".js", ".mjs", ".cjs")


def _stem(token: str) -> str:
    name = os.path.basename(token.replace("\\", "/")).lower()
    for suffix in _SUFFIXES:
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return name


def _is_browser(stem: str) -> bool:
    return stem == _AGENT_BROWSER or stem.startswith(_AGENT_BROWSER + "-") or stem in _CHROMIUM


def _tokens(args) -> list[str]:
    if isinstance(args, (str, bytes)):
        text = os.fsdecode(args)
        try:
            return shlex.split(text, posix=os.name != "nt")
        except ValueError:
            return text.split()
    return [os.fsdecode(a) if isinstance(a, (bytes, os.PathLike)) else str(a) for a in args]


def _search_path(env) -> str | None:
    source = env if env is not None else os.environ
    for key, value in source.items():
        if os.fsdecode(key).upper() == "PATH":
            return os.fsdecode(value)
    return None


def _under(path: str, roots) -> bool:
    real = os.path.normcase(os.path.realpath(path))
    for root in roots:
        base = os.path.normcase(os.path.realpath(root))
        if real == base or real.startswith(base.rstrip("\\/") + os.sep):
            return True
    return False


def real_browser_spawn(args, executable, env, allowed_roots) -> str | None:
    """The fence's verdict for one spawn: a skip reason, or None when it may run."""

    tokens = [t.strip('"') for t in _tokens(args)]
    if executable:
        tokens = [os.fsdecode(executable), *tokens[1:]]
    if not tokens:
        return None
    candidates = [tokens[0]]
    if _stem(tokens[0]) in _LAUNCHERS:
        candidates += [t for t in tokens[1:4] if not t.startswith("-") and not (t.startswith("/") and len(t) <= 3)]
    for token in candidates:
        stem = _stem(token)
        if not _is_browser(stem):
            continue
        is_path = os.path.dirname(token.replace("\\", "/")) != ""
        resolved = token if is_path else shutil.which(token, path=_search_path(env))
        if resolved is None and token is tokens[0]:
            continue  # nothing to spawn — the OS answers "not found" on its own
        if resolved is not None and _under(resolved, allowed_roots):
            continue  # a fake the test wrote into its own temp
        where = resolved or f"{token} (fetched by {_stem(tokens[0])})"
        return (f"real-browser fence: this test reaches the real {stem} at {where}; a real "
                "daemon and headless Chrome would outlive the run "
                "(tests/_downstream/real_browser_fence.py)")
    return None


@pytest.fixture(autouse=True, scope="session")
def _no_real_browser_spawn(tmp_path_factory):
    """Session-wide: the temp roots are read at spawn time, after the run's temp redirect."""

    basetemp = str(tmp_path_factory.getbasetemp())
    original = subprocess.Popen._execute_child
    main = threading.main_thread()

    def _fenced_execute_child(self, args, executable, *rest, **kwargs):
        env = rest[4] if len(rest) > 4 else kwargs.get("env")  # (preexec_fn, close_fds, pass_fds, cwd, env, ...)
        reason = real_browser_spawn(args, executable, env, (basetemp, tempfile.gettempdir()))
        if reason is not None:
            if threading.current_thread() is main:
                pytest.skip(reason)
            raise FileNotFoundError(errno.ENOENT, reason)
        return original(self, args, executable, *rest, **kwargs)

    with pytest.MonkeyPatch.context() as patcher:
        patcher.setattr(subprocess.Popen, "_execute_child", _fenced_execute_child)
        yield
