"""Fork-owned half of ``tests/hermes_cli/conftest.py`` (seam Stage 5).

Every name here was fork-added to that conftest. The root ``conftest.py``
registers this module when pytest registers ``tests/hermes_cli/conftest.py``, under a
``tests/hermes_cli/_downstream_conftest.py`` name, so its fixtures keep that
directory's scope and its hooks run; the upstream conftest carries no fork line
(lane CARRY3).

**The map** (lane B5, 2026-09-25; the layout sheet is
``docs/agent-runtime-harness/planned/god-file-layout-sheets/hermes_cli_conftest.md``).
This package IS the object the root ``conftest.py`` registers (by the module name
``tests._downstream.hermes_cli_conftest``), so it BINDS every autouse fixture and every
``pytest_*`` hook by name below. Imports are ABSOLUTE: ``tests/test_env_gap_registry.py``
execs this file under a synthetic module name, where a relative import has no parent::

    tests/_downstream/hermes_cli_conftest/
      __init__.py     wiring   this map; ``import dotenv`` FIRST; binds the fixtures and every pinned name;
                               DEFINES the five pytest hooks, _OWNER_DIR and the KNOWN DEFECTS tracker
      fences.py       lanes    "no test reaches this machine": the gateway fence, the pause token, psutil, agent-browser
      isolation.py    lanes    "no test's state outlives it": kanban workers, web_server.app, PAIRING_DIR, sys.modules
      probes.py       stores   every host probe, each answering once per process
      registry.py     stores   TABLES: _ENV_GAP_SKIPS, _WEB_BUILD_PREREQ_FILES, _KNOWN_DEFECTS

Following an entry point: the root registration -> here (1); "why was this test
skipped?" -> here -> ``registry`` -> ``probes`` (3); "why is psutil / the pause
token / agent-browser patched under me?" -> ``fences`` (1); "why did my sys.modules swap
not stick?" -> ``isolation`` (1); the KNOWN DEFECTS banner -> here -> ``registry`` (2).
Layers go DOWN: here -> ``registry`` -> ``probes``; ``fences`` and
``isolation`` import neither. A conftest that runs for UPSTREAM tests never imports
``agent_runtime``.
"""

from __future__ import annotations

# The REAL python-dotenv, loaded before any tests/hermes_cli module is imported.
# Upstream's test_gmi_provider / test_fireworks_provider / test_upstage_provider
# install a fake `dotenv` (no `dotenv.main`) at import when none is loaded yet,
# and a bundle imports every member before it runs any, so the fake reached
# every co-member (lane REDS2's two observed pairs). With the real module in
# sys.modules their own guard is a no-op; upstream bytes untouched.
import dotenv  # noqa: F401

import pathlib  # noqa: E402

import pytest  # noqa: E402

from tests._env_gap_fence import KnownDefectTracker, apply_skips, is_owned  # noqa: E402
from tests._downstream.hermes_cli_conftest.fences import (  # noqa: E402, F401
    _gateway_fence_is_armed_for_this_test,
    _AGENT_BROWSER_PROBE_BINDINGS,
    _agent_browser_probe_never_spawns,
    _no_windows_gateway_pause_token,
    _empty_process_iter,
    _no_live_process_table,
)
from tests._downstream.hermes_cli_conftest.isolation import (  # noqa: E402, F401
    _APP_BASELINE,
    _web_server_app_is_pristine,
    _pairing_dir_follows_the_test_home,
    _sys_modules_identity_is_restored,
    _kanban_live_worker_registry_is_per_test,
)
from tests._downstream.hermes_cli_conftest.probes import (  # noqa: E402, F401
    _VITE8_NODE_FLOOR,
    _node_version,
    _web_build_prereq_failure,
    _web_build_prereq_reason,
    _no_module,
    _no_posix_mode_bits,
    _no_os_chown,
    _no_posix_wait_status,
    _no_posix_privilege_api,
    _posix_only_branch,
    _no_shebang_script_execution,
)
from tests.hermes_cli import _gateway_fence  # noqa: E402
from tests._downstream.hermes_cli_conftest.registry import (  # noqa: E402, F401
    _WEB_BUILD_PREREQ_FILES,
    _ENV_GAP_SKIPS,
    TELEGRAM_PARITY_DEFECT_REASON,
    _KNOWN_DEFECTS,
)

__layer__ = "wiring"

#: The directory this conftest's registries own. The hooks below are GLOBAL and
#: every registry is keyed by file BASENAME, so without it a combined run lets
#: one directory's rows skip a same-named file in another (the tracker scopes the
#: report half by its own owner prefix). tests/_env_gap_fence.py carries the
#: measurement and the shared half of this scoping.
_OWNER_DIR = pathlib.Path(__file__).resolve().parents[2] / "hermes_cli"

#: The KNOWN DEFECTS banner (tests/_env_gap_fence.KnownDefectTracker): a known
#: defect's FAILED or xfailed call, under tests/hermes_cli/ only.
_KNOWN_DEFECT_TRACKER = KnownDefectTracker(_KNOWN_DEFECTS, "tests/hermes_cli/conftest.py")


def pytest_configure(config):  # noqa: D401 — pytest hook
    """Register the one mark this directory owns (the real-pause opt-out)."""
    config.addinivalue_line(
        "markers",
        f"{_gateway_fence.REAL_PAUSE_MARK}: let this test drive the REAL "
        "_pause_windows_gateways_for_update (it reads this machine's live "
        "gateway table and Scheduled Task). The test must mock the spawn "
        "itself; the process-wide gateway fence still stands behind it.",
    )


def pytest_collection_modifyitems(items):  # noqa: D401 — pytest hook
    """Apply the prerequisite guards, then the probe-backed env-gap skips.

    Items OUTSIDE this directory are skipped first. This is a global pytest
    hook — once this conftest is loaded, pytest hands it every item in the
    session — and every registry it reads is keyed by file BASENAME, so in a
    combined run (``pytest tests/hermes_cli tests/cli``) a row here would reach
    a same-named file one directory over and skip it. See the ownership block in
    tests/_env_gap_fence.py for the measurement.
    """
    for item in items:
        if not is_owned(item.path, _OWNER_DIR):
            continue
        # The web-UI build prerequisite (registry._WEB_BUILD_PREREQ_FILES):
        # probed lazily, only for an item of a file that needs it. NOT an
        # _ENV_GAP_SKIPS row — a prerequisite goes INERT on a host that meets
        # the floor, which the registry gate would read as a rotted row.
        if item.path.name in _WEB_BUILD_PREREQ_FILES and (reason := _web_build_prereq_reason()) is not None:
            item.add_marker(pytest.mark.skip(reason=reason))
    apply_skips(items, _ENV_GAP_SKIPS, owner_dir=_OWNER_DIR)


def pytest_runtest_logreport(report):  # noqa: D401 — pytest hook
    """Record the known-defect tests' outcomes.

    The known-defect test is ``xfail(strict=True)``, so its ordinary outcome is
    ``skipped`` with ``wasxfail`` set — NOT ``failed``; the tracker takes both,
    and a strict XPASS (``failed``, no ``wasxfail``) is the day someone must read
    the row and delete it.
    """
    _KNOWN_DEFECT_TRACKER.record(report)


def pytest_sessionfinish(session, exitstatus):  # noqa: D401 — pytest hook
    """Latch the gateway fence on for whatever the process does next.

    Every fixture has torn down by now and every monkeypatch is undone, which
    is precisely the state the measured escape ran in: ``_cmd_update_impl``
    parks ``_resume_windows_gateways_after_update`` on ``atexit`` mid-test, and
    it fires at interpreter exit against the operator's real profile. Arming is
    a flag the already-installed wrappers read at spawn time, so it does not
    have to beat that handler in atexit's LIFO order — it only has to be down
    before the handler runs, and session finish always is.

    Nothing is disarmed after this point, on purpose. The run is over; no
    legitimate test spawn can still be owed.
    """
    _gateway_fence.arm_permanently()


def pytest_terminal_summary(terminalreporter):  # noqa: D401 — pytest hook
    """Explain the deliberate reds."""
    _KNOWN_DEFECT_TRACKER.report(terminalreporter, "KNOWN DEFECTS — fenced xfail(strict), still open")


# ── History (relocated from the flat file's comment blocks by lane B5, 2026-09-25) ──
# Dated audit narratives: still the only record of the 07-30 fence, the 07-31
# upstream-sync sweep, the 08-10 audit's fifty stale rows and the known-defects
# banner's provenance. Comments, so the code counter does not read them as code.
#
# ── Pre-existing environment-gap fence (2026-07-30) ─────────────────────────
#
# `python -m pytest tests/hermes_cli` on this Windows 10 workstation reports
# 234 failures across 57 files. Every one of them was triaged against the
# mission-lane removal (commits f47e6d278..25e2651ac) and **none is caused by
# it** — the removal touched `hermes_cli/harness*.py`,
# `hermes_cli/harness_parts/`, `hermes_cli/profiles.py`,
# `hermes_cli/web_server.py` and `tools/`, and the tests covering those are
# green (`test_harness_cli.py`, `test_web_server_blueprints.py`, the
# `test_mission_chat_*` set, `test_flow_commands.py`, `test_persona_chat_session.py`).
#
# SUPERSEDED 2026-08-10 — read the audited block further down before this one.
# The claim above ("234 failures ... pre-existing gaps between this host and
# the Linux CI") did not survive being checked: of the 82 rows that reached
# this audit, fifty were stale tests or defects in our own code. The no-skip
# design that left them failing is retired; genuine rows now carry a live probe
# and become real skips (`_ENV_GAP_SKIPS`), and `tests/test_env_gap_registry.py`
# fails when a probe stops describing anything. The paragraphs below are kept
# because their toolchain/hang notes are still accurate and still load-bearing.
#
# Two marks, by cause:
#
#   windows_env_gap      The assertion encodes POSIX-only semantics that
#                        Windows cannot satisfy — 0o600 file modes (NTFS
#                        reports 0o666), `os.chown` / `os.getpgid` /
#                        `signal.SIGKILL` / `signal.pause` / `_curses`,
#                        `/usr/bin/...` literals, POSIX path separators,
#                        `bash -n <C:\...>`, cp1252 console decoding, and
#                        the `git -c windows.appendAtomically=false` prefix
#                        that `cmd_update` adds only on win32.
#
#   host_dependency_gap  A host package or capability is absent rather than a
#                        platform property: `croniter`, `pywinpty`, `pathspec`
#                        are not installed (all three are declared project
#                        dependencies, so this is an install gap on THIS box,
#                        not an optional extra); the installed `rich` does not
#                        emit OSC-8 panel-title hyperlinks; upstream has since
#                        added a standalone `tool_describe` bridge tool to the
#                        minimal toolset; and the host's git 2.31.1 does not
#                        honour `--ignore-cr-at-eol` for `--name-only` output.
#
#                        `fire` and `psutil` USED to be in that list. They were
#                        installed on the ambient interpreter on 2026-08-01
#                        (ledger item 7, RULED EXECUTE) and every row naming
#                        them retired — three groups here, and more in the
#                        gateway/tools registries.
#
# ── 2026-07-31 upstream-sync sweep ─────────────────────────────────────────
#
# The `upstream/main` merge (b9721809e) replayed this registry against a suite
# that upstream had pruned hard (prune waves 1-2: 46,820 -> 19,757 test
# functions). Two things were done in one pass:
#
#   * every registry row whose node id no longer exists was DELETED (163 rows
#     across 40 files, plus the whole `test_uv_tool_update.py` file, which
#     upstream removed). An orphaned row marks nothing, so it silently stops
#     being a fence while still reading like one;
#   * four rows the stale detector reported as PASSING were deleted too
#     (test_dashboard_unified_launch, test_gateway_wsl, test_install_cua_driver,
#     test_kanban_db).
#
# The rows ADDED in that same pass are all merge-delta failures that were
# triaged individually to a real host/platform cause — never to hide a
# regression. The one genuine merge-resolution defect found in this area
# (`hermes_cli/dep_ensure.py` lost `import os` when the merge took upstream's
# import block over the fork's `ensure_git_bash` body) was FIXED in the code,
# not fenced.
#
# Two failure modes cannot be handled by a mark, because they HANG instead of
# failing and a hang kills the whole pytest process before any deselection can
# matter. Those get real prerequisite probes further down (`node --version`
# against the Vite 8 engine floor, and a TCP probe of 127.0.0.1:11434). Both
# are inert on a host that satisfies the prerequisite, so nothing is masked.
#
# Toolchain floor worth stating explicitly, because it is the one gap with a
# concrete version number: `hermes_cli.main._build_web_ui` runs
# `npm run build -w web`, and `web/package.json` pins `vite ^8`, which requires
# Node `^20.19.0 || >=22.12.0`. This box has Node v20.17.0, so that build
# cannot succeed here. `test_web_ui_build.py` fails on it, and
# `test_cmd_update.py` *executes* it for real — it stubs `subprocess.run` but
# not the `subprocess.Popen` that `_run_with_idle_timeout` uses, so a plain run
# of that file performs a real npm install/build (and a real bundled-skill
# sync) against the checkout. Treat that file as side-effecting until the
# upstream mocking is tightened.
#
# Keeping the registry honest: any registered node id that PASSES is printed in
# a "stale environment-gap registry entries" section at the end of the run (see
# pytest_terminal_summary below), so a fixed environment — or a fixed test —
# forces the row to be deleted rather than quietly masking a regression.

#
# ── Environment-gap registry (audited 2026-08-10) ──────────────────────────
#
# 82 node ids across 44 files were registered here as pre-existing Windows/host
# gaps. Every one was reproduced individually. FIFTY were not gaps:
#
#   * three were REAL DEFECTS in our own code, which rule 3 of the fence
#     contract forbids registering at all:
#       - utils.atomic_replace only retried EXDEV/EBUSY, so concurrent
#         os.replace onto one target lost ~3 writes in 10 on Windows. It now
#         retries Win32 rename contention (fixed).
#       - hermes_cli/uninstall.py compared os.readlink()'s extended-length
#         (\\?\) target against an unprefixed root, so uninstall silently left
#         its own node/npm/npx symlinks behind — via a bare `continue`, with no
#         log. The candidate dirs include ~/.local/bin on EVERY platform
#         (fixed).
#       - hermes_cli/main.py swallowed the web-UI stamp failure at DEBUG, so a
#         missing pathspec meant a full npm install + Vite build on every boot
#         with nothing above DEBUG to say why; and the READER called the same
#         hash unguarded, so `hermes web` would have died on an unhandled
#         ModuleNotFoundError the moment a stamp existed. It never crashed only
#         because the swallowing writer guaranteed no stamp ever existed. Both
#         halves fixed, and pinned by portable tests that mock the import
#         failure so they run with or without pathspec.
#   * the rest were stale TESTS: a dozen read a UTF-8 file with no encoding=;
#     several asserted a POSIX path SPELLING that os.path.abspath
#     drive-qualifies; several pinned a sys.platform-selected POSIX branch
#     without pinning the branch, where a sibling test in the SAME FILE already
#     showed the convention; two leaked an open sqlite handle (test_kanban_boards
#     used `with kb.connect(...)`, which commits but never closes, though
#     kb.connect_closing exists for exactly this); one asserted a hardcoded
#     toolset list that upstream had since extended.
#
#   * THREE VACUOUS GREENS were caught in passing — tests that passed while
#     proving nothing. The worst: test_setup_matrix_e2ee's guard used
#     ast.walk(), which descends into function bodies, so it matched a DEFERRED
#     `import shutil`. Deleting the module-level import left it GREEN, which is
#     precisely the NameError it exists to prevent. It now walks tree.body.
#
# What is left below is genuine and probe-backed.
#
# ── 2026-08-10: the dependency rows were never environment gaps ────────────
#
# 17 of the surviving rows were DEPENDENCY-bound rather than platform-bound.
# croniter==6.0.0, pathspec==1.1.1 and pywinpty>=2.0.0 are all DECLARED in
# pyproject.toml, and all three were already present in the managed runtime
# venv (X:\Eternia\.hermes\venvs\hermes-agent) — they were missing only from
# the ambient C:\Python312 the tests run under. That is a BROKEN LOCAL INSTALL,
# not a property of this host, and the fence should never have described it as
# one. Installing them on the ambient interpreter retired 12 rows outright
# (croniter 2, pathspec 3, pywinpty 7), matching the fire/psutil precedent.
#
# The 13th pywinpty row did NOT pass, and what it was hiding is the reason this
# distinction matters. test_win_pty_bridge's test_cwd_is_respected matched the
# PTY's RAW bytes for a tmp_path longer than the terminal's 80-column width, so
# the ConPTY's hard line wrap split the path mid-token and the test pinned
# terminal geometry rather than the cwd. Fixed with a wrap-aware unwrap.
#
# Under that row, in tests/tools, sat a REAL DEFECT — see the commit message.
# tools/process_registry.py's Windows PTY stdin path was entirely non-functional
# while reporting {"status": "ok"}, and the ONLY test that would have caught it
# was gated on the pywinpty that was never installed.
#
# windows-curses is the one that stays: it is deliberately NOT declared, and
# curses_ui.py falls back to a numbered text menu, so it is a real optional
# extra rather than a broken install.
#
# NOT registered, deliberately, and therefore still RED — these are defects,
# and rule 3 says a defect gets fixed, not fenced:
#
#   * test_hooks_cli.py (3 nodes) — FIXED 2026-08-10, owner ruled. The cause
#     was agent/shell_hooks.py running shlex.split(spec.command) in POSIX mode
#     at :452/:817/:904, which ate every backslash in a Windows hook path, so
#     script_mtime_iso returned None and the "script modified since approval"
#     TAMPER CHECK at hermes_cli/hooks.py:369-376 could never fire. All three
#     sites now route through shell_hooks._split_command; the tamper-check node
#     is green. The other two nodes had a SECOND cause underneath, unrelated to
#     tokenization — a bare shebang script cannot be exec'd by this loader —
#     and are now probe-registered in _ENV_GAP_SKIPS below.
#   * test_commands.py::TestSlackNativeSlashes::test_telegram_parity —
#     slack_native_slashes() drops entries at _SLACK_MAX_SLASH_COMMANDS
#     (commands.py:1335) in registration order with NO accounting, so which
#     commands survive is a function of how many plugins are installed. The old
#     row also named the wrong casualty ('version', which is in
#     _SLACK_VIA_HERMES_ONLY); the command actually clamped off is 'platform'.
#     Which commands get pinned is product curation: owner call.
#
# ── Known defects that are deliberately NOT fenced ─────────────────────────
#
# The 2026-08-10 registry audit left these RED on purpose. Rule 3 of the fence
# contract says a failure caused by a defect in our own code gets FIXED, not
# registered — and both of these need an owner decision, so neither could be
# fixed inside that audit. Without this banner the next person to run the suite
# sees a red on Windows and files it back into the registry as an environment
# gap, which is precisely how the tamper-check hole below stayed invisible.
# The test_hooks_cli.py entry was REMOVED on 2026-08-10: the defect it named is
# fixed. agent/shell_hooks.py no longer parses hook commands with POSIX-mode
# shlex — _split_command keeps the backslashes, script_mtime_iso resolves, and
# the "script modified since approval" tamper check fires again (pinned by
# TestHooksDoctor::test_flags_mtime_drift, which is green). A banner announcing
# a defect that no longer exists is the same stale claim in the other
# direction, so it does not outlive the fix. The two remaining reds in that
# file have a different, independent cause and are registered in
# _ENV_GAP_SKIPS above with a live probe.
