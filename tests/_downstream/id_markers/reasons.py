"""The VOCABULARY of the id table: every reason string, the mark constructors, the shared marks.

A vocabulary module (floor-exempt). Each constructor IS a retiring class --
``_posix_only`` / ``_posix_xfail`` (a POSIX premise), ``_up_red`` / ``_up_red_skip``
(upstream's own Windows red), ``_fork_replaces`` (fork behaviour) -- and the prefix is
what a reader greps for in the report. The map is
``tests/_downstream/id_markers/__init__.py``.
"""

from __future__ import annotations

import importlib.util
import os
import shutil
import sys
from pathlib import Path

import pytest

from tests.hermes_cli._gateway_fence import REAL_PAUSE_MARK

__layer__ = "models"

_WIN = sys.platform == "win32"

# ── The marker VOCABULARY the table applies, spelled ONCE ─────────────────────
# ``tests/_downstream/conftest_plugin.py`` imports these names to register them
# (``addinivalue_line``) and to find them (its consumer fixtures); the table
# below builds its mark objects from them with ``getattr(pytest.mark, NAME)``.
# The suite runs without ``--strict-markers``, so a second spelling of any of
# these is a mark nothing reads -- which is why there is only one.
# ``real_windows_gateway_pause`` is ``tests/hermes_cli/_gateway_fence.REAL_PAUSE_MARK``.
ALLOW_CLAUDE_CODE_CREDENTIALS_FILE_MARK = "allow_claude_code_credentials_file"
CHILDREN_DIE_WITH_THE_TEST_MARK = "children_die_with_the_test"
CLAUDE_HOME_IS_TMP_PATH_MARK = "claude_home_is_tmp_path"
HOST_DISK_HAS_ROOM_MARK = "host_disk_has_room"
NO_REAL_ORPHAN_REAP_MARK = "no_real_orphan_reap"
#: Opts out of ``tests/hermes_cli``'s ``_no_live_process_table`` (an empty
#: ``psutil.process_iter``) for a test that scans for a child it spawned itself.
REAL_PROCESS_TABLE_MARK = "real_process_table"
SCOPED_MONKEYPATCH_UNDO_MARK = "scoped_monkeypatch_undo"
STRIP_REAL_HOME_PATH_MARK = "strip_real_home_path"
STATE_DB_RESOLVES_THROUGH_SCOPE_MARK = "state_db_resolves_through_scope"
UPSTREAM_WIRE_UNBRIEFED_MARK = "upstream_wire_unbriefed"
#: Pins ``make_restart_runner``'s ``_cron_drain_timeout`` to 0.01 s for a shutdown test
#: whose API work shares the 30 s cron drain floor (FH-FOOTPRINT-FORK-TEST-HUNKS-OUT).
SHUTDOWN_CRON_DRAIN_PINNED_MARK = "shutdown_cron_drain_pinned"
#: Upstream's own mark (read by ``tests/conftest.py``'s live-system guard, used by
#: upstream tests); nobody registers it -- see tests/test_id_markers_downstream.py.
SPAWNS_GATEWAY_LOOKALIKE_MARK = "spawns_gateway_lookalike"
#: A live-machine premise, not a platform one: the test reads the REAL fleet
#: process table and needs it to hold no hermes gateway (``pytest_runtest_setup``).
NO_LIVE_GATEWAY_MARK = "requires_no_live_gateway"
#: A file the gate directory (``docs/agent-runtime-harness/11-gate-directory.md``) lists;
#: spelled in ``scripts/gate_mark.py``, the one reader of it (the gate directory's
#: enumeration and the bundled scope's chain sample both ask it), and re-exported here.
from scripts.gate_mark import GATE_MARK

_PATH_SPELLING = (
    "upstream interpolates a Windows tmp_path into a JSON string literal "
    "(backslash-U and backslash-b are invalid escapes); fixed by the open PR "
    "up/win-path-spelling"
)
_WSL_FAKE = (
    "patches is_wsl but not platform.system/shutil.which, so a native-Windows "
    "host takes the Windows branch; the premise is a Linux (WSL) host"
)
_SEPARATOR_SPELLING = (
    "the tool under test (git worktree --porcelain, find via the POSIX shell) "
    "echoes forward slashes, upstream compares against str(Path) backslashes; "
    "a test-side spelling fix, PR candidate class win-path-spelling"
)
_CONTAINER_SPELLING = (
    "upstream spells a container path as str(tmp_path) and a warning's path via "
    "{!r}; on Windows tmp_path is drive-anchored (not POSIX-absolute) and repr "
    "doubles backslashes. Test-side spelling, PR candidate class win-path-spelling"
)
_TMP_LITERAL = (
    "upstream mocks gettempdir() as the literal \"/tmp\" and spells the operand "
    "unquoted; on Windows realpath(\"/tmp\") lands on the current drive and "
    "shlex eats the separators. Test-side spelling, PR candidate class "
    "win-path-spelling"
)
_FORK_SYSTEM_PATH = (
    "the fork's tools/environments/local.py _augment_windows_system_path appends "
    "the System32 dirs, so upstream's verbatim equality cannot hold on Windows; "
    "the fork's assertion is tests/tools/test_local_env_blocklist_downstream.py; "
    "retires with the G2 Windows-paths PR"
)

_FORK_LIVE_SYSTEM_GUARD = (
    "the fork's live-system guard (tests/conftest.py) refuses the spawn of a real "
    "`hermes dashboard` backend; the fork's in-process twin is the test's "
    "*_downstream.py sibling"
)
_FORK_LIVE_GUARD_ENSURE = (
    "the fork's live-system guard (tests/conftest.py) refuses `hermes gateway ensure`: "
    "ensure STARTS a gateway when none answers, and this child keeps the developer's HOME, "
    "so only the live update claim the test plants keeps it from starting one"
)
_FORK_MANAGED_PYTHON = (
    "the fork's hermes_cli.gateway.resolve_managed_python replaces get_python_path "
    "in _build_gateway_argv, so upstream's patch no longer steers it; the fork twin "
    "is tests/hermes_cli/test_gateway_windows_downstream.py"
)
_FORK_SPAWN_DETACHED = (
    "the fork's hermes_cli.gateway_windows._spawn_detached(script_path) replaces "
    "upstream's breakaway retry; covered by tests/gateway/test_windows_gateway_spawn.py"
)

_CREDENTIALS_FILE = getattr(pytest.mark, ALLOW_CLAUDE_CODE_CREDENTIALS_FILE_MARK)
_REAL_PAUSE = getattr(pytest.mark, REAL_PAUSE_MARK)
_NO_LIVE_GATEWAY = getattr(pytest.mark, NO_LIVE_GATEWAY_MARK)
_NO_REAL_ORPHAN_REAP = getattr(pytest.mark, NO_REAL_ORPHAN_REAP_MARK)
_CHILDREN_DIE_WITH_THE_TEST = getattr(pytest.mark, CHILDREN_DIE_WITH_THE_TEST_MARK)

#: Prefix of every row that skips an upstream test because it is POSIX-only
#: (not because of fork behaviour); the tests-PR lane turns these rows into
#: upstream platform marks.
_POSIX_ONLY = "POSIX-only; upstream fix = @pytest.mark.platforms('linux')"


def _posix_only(detail: str) -> pytest.MarkDecorator:
    return pytest.mark.skip(reason=f"{_POSIX_ONLY} ({detail})")


_LOOKALIKE = getattr(pytest.mark, SPAWNS_GATEWAY_LOOKALIKE_MARK)
_REAL_PROCESS_TABLE = getattr(pytest.mark, REAL_PROCESS_TABLE_MARK)
#: Upstream's own opt-out of the whole live-system guard (``tests/_fixtures/live_system_guard.py``,
#: which registers it); applied by id only where the fork's backend-spawn arm is the only refusal
#: and the "backend" is a test-owned stand-in script.
_LIVE_GUARD_BYPASS = pytest.mark.live_system_guard_bypass

# Upstream tests that call monkeypatch.undo() mid-body run upstream's bytes with
# undo narrowed to their own patches (conftest_plugin.pytest_pyfunc_call, lane
# CARRY3); no sibling copy. Applied by hooks.body_calls_monkeypatch_undo at
# collection, never by an id row.
_SCOPED_UNDO = getattr(pytest.mark, SCOPED_MONKEYPATCH_UNDO_MARK)
_STRIP_REAL_HOME_PATH = getattr(pytest.mark, STRIP_REAL_HOME_PATH_MARK)
_STATE_DB_THROUGH_SCOPE = getattr(pytest.mark, STATE_DB_RESOLVES_THROUGH_SCOPE_MARK)
_HOST_DISK_HAS_ROOM = getattr(pytest.mark, HOST_DISK_HAS_ROOM_MARK)
_UPSTREAM_WIRE_UNBRIEFED = getattr(pytest.mark, UPSTREAM_WIRE_UNBRIEFED_MARK)
_CRON_DRAIN_PINNED = getattr(pytest.mark, SHUTDOWN_CRON_DRAIN_PINNED_MARK)

_CLAUDE_HOME_TMP = getattr(pytest.mark, CLAUDE_HOME_IS_TMP_PATH_MARK)
_GATE = getattr(pytest.mark, GATE_MARK)

def _fork_replaces(symbol: str, sibling: str) -> pytest.MarkDecorator:
    return pytest.mark.xfail(strict=True, reason=(
        f"the fork's {symbol} makes this upstream assertion false; fork half: {sibling}"
    ))

# Upstream test files back at upstream's bytes: upstream's own Windows reds at
# the tag (X:/wt/_holds/upstream-reds-v2026.9.24.md). No open fork PR covers any.
_UP_RED = "upstream-red on Windows at v2026.9.24; no fix yet"


def _up_red(detail: str, *, qualified: str = "") -> pytest.MarkDecorator:
    """``qualified`` names the interpreter / SQLite pair (and date) the row was last seen
    red on, so the next re-qualification reads the row's age off its reason (D3.13)."""
    seen = f"; last seen red on {qualified}" if qualified else ""
    return pytest.mark.xfail(strict=True, reason=f"{_UP_RED} ({detail}{seen})")


def _up_red_when(condition: bool, detail: str) -> pytest.MarkDecorator:
    """``_up_red`` for a red that belongs to the HOST, not to Windows as a whole.

    The condition names what makes it red (an interpreter, its bundled SQLite, a
    directory on the checkout's drive), so a host without it runs the test
    unmarked instead of reporting a strict XPASS.
    """
    return pytest.mark.xfail(condition, strict=True, reason=f"{_UP_RED} ({detail})")


def _up_red_skip(detail: str) -> pytest.MarkDecorator:
    """For a red that kills the process (a thread-method timeout), not an assertion."""
    return pytest.mark.skip(reason=f"{_UP_RED} ({detail})")


def _posix_xfail(detail: str) -> pytest.MarkDecorator:
    return pytest.mark.xfail(strict=True, reason=f"{_POSIX_ONLY} ({detail})")


_LIFECYCLE_SCAN = _up_red(
    "the lifecycle guard reads a referenced script through a POSIX command "
    "string; a Windows path in it loses its separators (class c-E)"
)

_TCC_POSIX_VENV = _posix_xfail(
    "the fixture builds a POSIX venv (bin/, symlinked interpreters) and patches only "
    "platform.system; venv_python_path follows sys.platform to Scripts/python.exe"
)

#: A system TOOL the test drives, absent from the box: ``tmux`` (the live classic-CLI tests type
#: into a real terminal through it). Runs again the day it is on PATH
#: (FH-HERMES-CLI-GATEWAY-UPDATE-REDS-REMAINDER, 2026-11-02).
_NEEDS_TMUX = pytest.mark.skipif(
    shutil.which("tmux") is None,
    reason="drives a real terminal through `tmux`, which is not on PATH; runs once it is installed",
)

#: ``node`` (Node.js), absent from the Linux box's test PATH: upstream's desktop/web build tests
#: ``assert shutil.which("node")`` (or spawn it), so they red for the host, not the code. Runs
#: again the day Node is on PATH (FH-LINUX-BOX-SCRIPTS-NEED-NODE, 2026-11-08).
_NEEDS_NODE = pytest.mark.skipif(
    shutil.which("node") is None,
    reason="REQUIRES node: drives Node.js (`node`/`npm`), which is not on PATH; runs once it is",
)

#: ``node`` AND ``pnpm``: upstream's source-launch and web-build tests prepare a real workspace
#: with pnpm under the host's Node, so either one missing reds them at fixture setup
#: (``os.symlink(None, …)``, ``assert node and pnpm``). Runs again the day both are on PATH
#: (FH-LINUX-BOX-NO-NODE-UPSTREAM-REDS, 2026-11-11).
_NEEDS_NODE_AND_PNPM = pytest.mark.skipif(
    shutil.which("node") is None or shutil.which("pnpm") is None,
    reason="REQUIRES node and pnpm: prepares a real pnpm workspace under Node, and one of them is not on PATH; "
    "runs once both are",
)

#: ``rg`` (ripgrep) on PATH: with none, the search tool falls back to grep, which cannot match
#: across lines and gives no zero-match hint, and the doctor's executable parity test pins the
#: host's own rg. Runs again the day rg is on PATH (FH-LINUX-BOX-NO-RIPGREP-SEARCH-REDS, 2026-11-11).
_NEEDS_RIPGREP = pytest.mark.skipif(
    shutil.which("rg") is None,
    reason="REQUIRES ripgrep: needs `rg` on PATH (grep, the fallback, cannot do this); runs once it is installed",
)


def _chrome_desktop_entry_installed() -> bool:
    data_dirs = [os.environ.get("XDG_DATA_HOME", ""),
                 *(os.environ.get("XDG_DATA_DIRS") or "/usr/local/share:/usr/share").split(os.pathsep)]
    return any(d and (Path(d) / "applications" / "google-chrome.desktop").is_file() for d in data_dirs)


#: The desktop-update shim renders its UI only when ``xdg-settings get default-web-browser``
#: names a Chromium-family browser. The test points ``mimeapps.list`` at
#: ``google-chrome.desktop`` and puts a stub ``google-chrome`` on PATH, but both ``xdg-mime``
#: and GNOME's ``gio`` honour a default only for an INSTALLED desktop entry: on a box with no
#: ``google-chrome.desktop`` they answer the host's real default (Firefox, Brave), the shim
#: skips its UI and the stub never writes ``launched-profile``. Measured 2026-11-08 on the Linux
#: box: no entry -> ``firefox_firefox.desktop``; an entry under a prepended ``XDG_DATA_DIRS`` ->
#: ``google-chrome.desktop`` (FH-LINUX-BOX-SCRIPTS-NEED-NODE).
_NEEDS_CHROME_DESKTOP_ENTRY = pytest.mark.skipif(
    shutil.which("xdg-settings") is not None and not _chrome_desktop_entry_installed(),
    reason="REQUIRES google-chrome.desktop: xdg-settings honours the test's mimeapps.list default only for "
    "an installed google-chrome.desktop, and this host has none, so it names the host's own browser",
)

_NEEDS_ACP = pytest.mark.skipif(
    importlib.util.find_spec("acp") is None,
    reason="imports `acp` inside the test (agent-client-protocol, extra [acp]), "
    "which the canonical test venv does not carry; runs once it is installed",
)
