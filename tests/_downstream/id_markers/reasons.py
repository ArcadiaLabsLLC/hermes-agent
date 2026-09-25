"""The VOCABULARY of the id table: every reason string, the mark constructors, the shared marks.

A vocabulary module (floor-exempt). Each constructor IS a retiring class --
``_posix_only`` / ``_posix_xfail`` (a POSIX premise), ``_up_red`` / ``_up_red_skip``
(upstream's own Windows red), ``_fork_replaces`` (fork behaviour) -- and the prefix is
what a reader greps for in the report. The map is
``tests/_downstream/id_markers/__init__.py``.
"""

from __future__ import annotations

import importlib.util
import sys

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
CLAUDE_HOME_IS_TMP_PATH_MARK = "claude_home_is_tmp_path"
CONFIG_READS_THROUGH_LOAD_CONFIG_MARK = "config_reads_through_load_config"
NO_OLLAMA_SHOW_PROBE_MARK = "no_ollama_show_probe"
NO_REAL_ORPHAN_REAP_MARK = "no_real_orphan_reap"
SCOPED_MONKEYPATCH_UNDO_MARK = "scoped_monkeypatch_undo"
TIRITH_CONFIG_VALUE_UNDER_TEST_MARK = "tirith_config_value_under_test"
#: Upstream's own mark (read by ``tests/conftest.py``'s live-system guard, used by
#: upstream tests); nobody registers it -- see tests/test_id_markers_downstream.py.
SPAWNS_GATEWAY_LOOKALIKE_MARK = "spawns_gateway_lookalike"
#: A live-machine premise, not a platform one: the test reads the REAL fleet
#: process table and needs it to hold no hermes gateway (``pytest_runtest_setup``).
NO_LIVE_GATEWAY_MARK = "requires_no_live_gateway"

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
_FORK_PERSONA_CONFIG_SYNC = (
    "the fork's agent_runtime/persona_config_sync.py reads a pulled realm "
    "subtree's config.yaml raw (not this machine's user config); the fork-scope "
    "guard is tests/hermes_cli/test_config_read_guard_downstream.py"
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

#: Single source: the banner in ``hermes_cli_conftest._KNOWN_DEFECTS`` and the
#: strict xfail below carry this one string (ML-16).
TELEGRAM_PARITY_DEFECT_REASON = (
    "KNOWN DEFECT (owner call, not an environment gap): Slack's 50-slash app "
    "cap drops '/platform', a canonical gateway command with no native Slack "
    "slot, so Telegram/Slack parity cannot hold until an owner either pins it "
    "a slot (something else loses one) or declares it _SLACK_VIA_HERMES_ONLY. "
    "strict=True: the day parity holds, this XPASSes and reds — delete the "
    "mark and this row. Full account: _KNOWN_DEFECTS in "
    "tests/_downstream/hermes_cli_conftest/registry.py."
)

_CREDENTIALS_FILE = getattr(pytest.mark, ALLOW_CLAUDE_CODE_CREDENTIALS_FILE_MARK)
_REAL_PAUSE = getattr(pytest.mark, REAL_PAUSE_MARK)
_TIRITH_CONFIG_VALUE = getattr(pytest.mark, TIRITH_CONFIG_VALUE_UNDER_TEST_MARK)
_NO_LIVE_GATEWAY = getattr(pytest.mark, NO_LIVE_GATEWAY_MARK)
_NO_OLLAMA_SHOW_PROBE = getattr(pytest.mark, NO_OLLAMA_SHOW_PROBE_MARK)
_NO_REAL_ORPHAN_REAP = getattr(pytest.mark, NO_REAL_ORPHAN_REAP_MARK)

#: Prefix of every row that skips an upstream test because it is POSIX-only
#: (not because of fork behaviour); the tests-PR lane turns these rows into
#: upstream platform marks.
_POSIX_ONLY = "POSIX-only; upstream fix = @pytest.mark.platforms('linux')"


def _posix_only(detail: str) -> pytest.MarkDecorator:
    return pytest.mark.skip(reason=f"{_POSIX_ONLY} ({detail})")


_CONFIG_READ_THROUGH = getattr(pytest.mark, CONFIG_READS_THROUGH_LOAD_CONFIG_MARK)
_LOOKALIKE = getattr(pytest.mark, SPAWNS_GATEWAY_LOOKALIKE_MARK)
_TIRITH_NO_BUILD = _posix_only(
    "tirith ships no Windows build: _detect_target() is None and every entry "
    "point short-circuits to allow before the behaviour under test"
)

# Upstream tests that call monkeypatch.undo() mid-body run upstream's bytes with
# undo narrowed to their own patches (conftest_plugin.pytest_pyfunc_call, lane
# CARRY3); no sibling copy.
_SCOPED_UNDO = getattr(pytest.mark, SCOPED_MONKEYPATCH_UNDO_MARK)

_CLAUDE_HOME_TMP = getattr(pytest.mark, CLAUDE_HOME_IS_TMP_PATH_MARK)

def _fork_replaces(symbol: str, sibling: str) -> pytest.MarkDecorator:
    return pytest.mark.xfail(strict=True, reason=(
        f"the fork's {symbol} makes this upstream assertion false; fork half: {sibling}"
    ))

# Upstream test files back at upstream's bytes: upstream's own Windows reds at
# the tag (X:/wt/_holds/upstream-reds-v2026.9.24.md). No open fork PR covers any.
_UP_RED = "upstream-red on Windows at v2026.9.24; no fix yet"


def _up_red(detail: str) -> pytest.MarkDecorator:
    return pytest.mark.xfail(strict=True, reason=f"{_UP_RED} ({detail})")


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

_NEEDS_ACP = pytest.mark.skipif(
    importlib.util.find_spec("acp") is None,
    reason="imports `acp` inside the test (agent-client-protocol, extra [acp]), "
    "which the canonical test venv does not carry; runs once it is installed",
)
