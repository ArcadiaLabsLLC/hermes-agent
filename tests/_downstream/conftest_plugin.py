"""Fork-owned root test plugin (seam Stage 5), imported by the fork-only root
``conftest.py`` right after pytest registers ``tests/conftest.py`` (lane CARRY3;
that upstream file's ``pytest_plugins`` line is gone).

Every fixture, hook and constant here was fork-added to ``tests/conftest.py``;
moving them leaves that upstream file carrying none of them (only
the in-place edits of upstream names that the Stage 3 PR series owns). A plugin
imported by name registers its fixtures session-wide (node id
``""``), one level above the root conftest's ``tests`` scope, so the autouse
fixtures here set up before the conftest's and tear down after them. The two
that import production modules request ``_hermetic_environment`` so they still
run inside the sandbox, as they did when alphabetical order put them after it.
"""

from __future__ import annotations

import itertools
import os
import re
import shutil
import sys
import tempfile

import pytest

from tests._downstream.id_markers import (  # noqa: F401 — hook re-exports
    NO_LIVE_GATEWAY_MARK,
    pytest_collection_modifyitems,
    pytest_make_collect_report,
    pytest_runtest_setup,
)


# ── Opt-in test-temp root (suite-perf Stage 7, ruled 2026-09-01) ─────────────
# Defender real-time scanning taxes every test file-op 2.3–2.9× on
# non-excluded paths, and %TEMP% — where every tmp_path and hermetic
# HERMES_HOME otherwise lands — is not excluded on the operator's machine
# (the plan's §5 churn table). `HERMES_TEST_TMP_ROOT` names a DEDICATED,
# scan-excluded, throwaway directory (the operator's is `X:\Eternia\test-tmp`,
# inside their existing `X:\Eternia\` exclusion). When it names a real
# directory, the whole session's temp — this process AND every spawned child,
# which inherits the env — moves under a fresh per-run subdir there. Absent or
# missing, NOTHING changes: the opt-in degrades to today's behavior, never to
# an error. `tempfile.tempdir` is set as well as the env because the module
# caches its answer on first use, and pytest has usually asked before conftest
# imports. Each process removes its OWN run-dir when its session ends green
# (kept on a red session, for debugging); whatever is left — red sessions,
# killed processes — is pruned once it is a day old. The keep was 7 days until
# 2026-09-24, when every process also KEPT its dir: ~1,840 dirs per gate run,
# 14,901 in the operator's root that day (lane SUITE2).
#
# The prune runs at most once per `_PRUNE_INTERVAL_SECONDS` per root, not once
# per process. This function runs at IMPORT in every per-file pytest process
# (~1,840 per validated-scope run), and the unthrottled sweep was the fork's
# largest suite cost: measured 2026-09-24 (lane SPEED, the note
# `docs/agent-runtime-harness/planned/suite-cost-centres-2026-09-24.md`) the
# operator's root held 14,901 run-dirs, 322 of them aged dirs that
# `rmtree(ignore_errors=True)` could NOT remove — git writes its objects
# read-only, and on Windows a read-only file refuses deletion — so every
# process re-scanned the whole root and re-failed the same 322 trees. The
# stamp makes the sweep a session-of-runs cost; the chmod-and-retry makes it
# actually finish, so the same trees are not retried forever.
_PRUNE_INTERVAL_SECONDS = 3600
_PRUNE_STAMP = ".prune-stamp"
_RUN_DIR_KEEP_SECONDS = 24 * 3600


def _rmtree_readonly_too(path: str) -> None:
    def _retry_writable(func, target, _exc):
        try:
            os.chmod(target, 0o700)
            func(target)
        except OSError:
            pass

    if sys.version_info >= (3, 12):
        shutil.rmtree(path, onexc=_retry_writable)
    else:  # pragma: no cover - 3.11 floor
        shutil.rmtree(path, onerror=lambda f, p, e: _retry_writable(f, p, e[1]))


def _maybe_redirect_test_tmp(environ: dict = os.environ) -> str | None:
    root = (environ.get("HERMES_TEST_TMP_ROOT") or "").strip()
    if not root or not os.path.isdir(root):
        return None
    import time

    now = time.time()
    stamp = os.path.join(root, _PRUNE_STAMP)
    try:
        due = now - os.stat(stamp).st_mtime >= _PRUNE_INTERVAL_SECONDS
    except OSError:
        due = True
    if due:
        # Stamp BEFORE sweeping so the processes starting alongside this one
        # skip instead of racing it through the same trees.
        try:
            with open(stamp, "a", encoding="utf-8"):
                pass
            os.utime(stamp, (now, now))
        except OSError:
            pass
        cutoff = now - _RUN_DIR_KEEP_SECONDS
        for entry in os.scandir(root):
            try:
                if entry.is_dir() and entry.stat().st_mtime < cutoff:
                    _rmtree_readonly_too(entry.path)
            except OSError:
                pass
    run_dir = tempfile.mkdtemp(prefix="run-", dir=root)
    for key in ("TMP", "TEMP", "TMPDIR"):
        environ[key] = run_dir
    if environ is os.environ:
        tempfile.tempdir = run_dir
    return run_dir


_TEST_TMP_RUN_DIR = _maybe_redirect_test_tmp()


def _release_test_tmp_run_dir(run_dir: str | None, exitstatus: int | None) -> bool:
    """Remove this process's run-dir if its session ended green (exit 0, or 5 =
    nothing collected). A red or unfinished session keeps it for debugging; the
    day-old prune above reclaims it. Returns whether it removed the dir."""

    if not run_dir or exitstatus not in (0, 5):
        return False
    _rmtree_readonly_too(run_dir)
    return not os.path.exists(run_dir)


_SESSION_EXIT: dict[str, int] = {}


def pytest_sessionfinish(session, exitstatus):  # noqa: D401 — pytest hook
    """Record the exit status for the at-exit release below."""
    _SESSION_EXIT["status"] = int(exitstatus)


if _TEST_TMP_RUN_DIR is not None:
    import atexit

    # At EXIT, not at sessionfinish: ``tempfile.tempdir`` points into the
    # run-dir, and pytest's own teardown after sessionfinish may still ask for
    # a temp file. Registered at import, so atexit's LIFO order runs it after
    # every handler registered later in the session.
    atexit.register(
        lambda: _release_test_tmp_run_dir(_TEST_TMP_RUN_DIR, _SESSION_EXIT.get("status"))
    )


# HERMES_* vars the FORK blanks before every test, in addition to upstream's
# ``tests/conftest.py::_HERMES_BEHAVIORAL_VARS`` (which ``_hermetic_environment``
# deletes). Kept here so that upstream tuple stays upstream's bytes; the
# autouse fixture below deletes these the same way.
_DOWNSTREAM_BEHAVIORAL_VARS = frozenset({
    # HERMES_HOME is sandboxed below (step 3), but HERMES_HEAD_HOME OUTRANKS it:
    # get_hermes_head_home() (agent_runtime/profile_home.py:91-107) returns HERMES_HEAD_HOME
    # verbatim and only falls back to get_hermes_home() when it is unset. The
    # Launcher's serve exports HERMES_HEAD_HOME=<root>/profiles/base, so a suite
    # run from a Launcher-shaped shell inherited the operator's LIVE head home
    # while HERMES_HOME was hermetic — and that home is not read-only config: it
    # selects the SessionDB the Mission Control transcript store WRITES to, and
    # it flips hermes_head_home_is_authoritative() True, which changes which
    # branch the fail-closed guards in persona_chat_history take. Deleting (not
    # re-pinning) is the fix: unset is what CI has, and unset degrades to the
    # already-sandboxed HERMES_HOME. Tests of head-home behavior set it
    # explicitly in their own fixtures, which run after this one.
    "HERMES_HEAD_HOME",
    # The detached-service marker, and it SHORT-CIRCUITS a fallback rather than
    # merely tinting one. ``_windows_gateway_should_absorb_console_controls``
    # (``hermes_cli/gateway.py:1737``) returns True the moment this reads as a
    # truthy word and never reaches the ``sys.stdin.isatty()`` branch below it;
    # ``gateway.py:4924`` then installs ``SIG_IGN`` for SIGINT/SIGBREAK and calls
    # ``SetConsoleCtrlHandler(NULL, TRUE)``. So the suite exercised a DIFFERENT
    # branch of a signal-handling decision depending on whose shell launched it.
    # The Windows service wrappers export it verbatim (``gateway_windows.py:413``,
    # ``:498``, ``:816``, ``:883``), and an operator shell descended from one
    # inherits it — which is exactly how it came to be set live on the machine
    # that found this. Deleted rather than re-pinned, per HERMES_HEAD_HOME above:
    # unset is what CI has, and unset degrades to the isatty() fallback, which
    # under pytest's captured stdin answers the sandboxed way. Both branches are
    # covered by tests that set it explicitly (``tests/hermes_cli/test_gateway.py``
    # :259 deletes it, :289 sets it), and those run after this fixture.
    "HERMES_GATEWAY_DETACHED",
    # The charsheet draftsman seam (RL-26). Set to "fake" it rebinds the ONE
    # charsheet provider door to a local Pillow drawing — which is exactly the
    # right thing for a sandboxed child and exactly the wrong thing to inherit
    # from an operator shell mid-suite: every charsheet test that patches
    # ``pipeline._generate_image`` would keep passing while the test that pins
    # the DEFAULT door read the operator's environment instead of the default.
    # Unset is what CI has; the tests that exercise it set it themselves, after
    # this fixture.
    "HERMES_CHARSHEET_DRAFTSMAN",
    # ── Path-shaped discovery overrides ──────────────────────────────────────
    # Every one of these REDIRECTS a lookup at a filesystem path the operator
    # controls: which profile name the kanban/author defaults resolve to
    # (``agent_runtime/profile_context.py:129``, ``hermes_cli/kanban_db.py:9450``),
    # which auth home and shared-secret dir the credential resolver reads, which
    # skill / MCP / plugin trees discovery walks, which ``hermes`` binary, TUI
    # bundle and web dist a launcher shells out to, and which home the ACP child
    # inherits. That is the same hazard class as HERMES_HEAD_HOME — not "a flag
    # tints a default" but "a path outside the sandbox wins" — and unlike
    # HERMES_HEAD_HOME it is not one variable but the whole discovery surface.
    #
    # These are blanked as a SET rather than one at a time on purpose. "Not
    # currently set on this machine" is a fact about one operator's shell on one
    # day, not a property of the code: HERMES_HEAD_HOME was also unset until the
    # Launcher's serve started exporting it, and it took a live incident to
    # notice. Four test files already hand-roll a private defence against exactly
    # these names leaking in — ``tests/agent_runtime/test_realm_sync_skill_inbox.py:56``
    # and ``test_skill_promotion.py:35`` pop HERMES_SHARED_SKILLS with the comment
    # "a stray ... from the ambient env would break isolation",
    # ``tests/agent/test_external_skills.py:88`` pops the same one, and
    # ``tests/agent/test_copilot_acp_client.py:200`` names an "ambient
    # HERMES_REAL_HOME". Four independent workarounds for one missing central
    # blank is the argument for blanking centrally.
    #
    # Unset is what CI has for all of them: the HERMES_* names
    # ``scripts/run_tests.sh`` forwards into the per-file subprocesses are
    # HERMES_RUN_SLOW_PET_TESTS, HERMES_E2E_BROWSER, HERMES_TEST_TMP_ROOT and
    # HERMES_TEST_REAL_ROOT — none of which is on this list, all four
    # test-only — and ``.github/workflows/tests.yml`` sets none of these.
    # Tests that need one set it explicitly with monkeypatch, after this.
    #
    # HERMES_TEST_REAL_ROOT is worth naming here because it looks like the
    # opposite of this fixture's job: it carries the operator's REAL store root
    # into the hermetic env. It is not a redirect — nothing production reads it.
    # It is the FORBIDDEN path, handed to ``tests/hermes_cli/_gateway_fence.py``
    # so that fence can refuse a spawn aimed at it. HERMES_HOME stays unset and
    # step 3 below still installs the per-test temp home.
    "HERMES_PROFILE",
    "HERMES_AUTH_HOME",
    "HERMES_SHARED_AUTH_DIR",
    "HERMES_OPTIONAL_SKILLS",
    "HERMES_OPTIONAL_MCPS",
    "HERMES_BUNDLED_SKILLS",
    "HERMES_SHARED_SKILLS",
    "HERMES_BUNDLED_PLUGINS",
    "HERMES_BIN",
    "HERMES_TUI_DIR",
    "HERMES_WEB_DIST",
    "HERMES_REAL_HOME",
})


@pytest.fixture(autouse=True)
def _downstream_behavioral_vars_scrubbed(monkeypatch):
    """Delete the fork's behavioural HERMES_* vars (see the set above)."""
    for name in _DOWNSTREAM_BEHAVIORAL_VARS:
        monkeypatch.delenv(name, raising=False)


# ── The tree-wide no-undo tripwire (ML-14 / C21, EG-0.1) ───────────────────
#
# Every autouse guard in this file installs itself through ``monkeypatch`` —
# ONE MonkeyPatch instance per test function, shared by every fixture that
# requests it AND by the test body. Its ``undo()`` takes no argument and
# unwinds the ENTIRE stack; it cannot drop "the patch I made". So a body that
# calls ``monkeypatch.undo()`` to drop its own stub also takes down
# ``_hermetic_environment`` (HERMES_HOME redirected to a tempdir, every
# credential-shaped env var blanked), ``_kanban_write_guard``,
# ``_live_system_guard``, ``_audio_playback_guard``,
# ``_neutralize_webbrowser`` and ``_neutralize_macos_keychain_creds`` — plus,
# under ``tests/agent_runtime``, that package's ``HERMES_AGENT_RUNTIME_ROOT``
# and worktree-base pins. Everything the test does after that line runs
# against the OPERATOR's live root with their real credentials.
#
# Not hypothetical. On 2026-08-17 (EG-0.1 / HC-H1) five sites did it and the
# damage was found in the live tree: the leaked actor ``ws_office_patch_test``
# sat at revision 67 in X:/Eternia/.hermes and climbed once per suite run, and
# a persona-chat root lease file was taken out there.
#
# TWO WITNESSES, DIFFERENT MECHANISMS. This fixture is the BEHAVIOURAL one:
#
#   1. structural — ``tests/agent_runtime/test_no_midtest_monkeypatch_undo.py``
#      AST-walks the whole tree and reddens in review, naming file and line. It
#      sees only the spellings a walker can resolve.
#   2. behavioural — this fixture. It watches a sentinel minted per test and
#      never handed to the body, so an unwind reddens the exact test that
#      performed it, whatever spelling it used: an alias, a callback, a
#      ``getattr``.
#
# Witness 2 used to live in ``tests/agent_runtime/conftest.py`` and covered
# that package alone while witness 1 covered the tree — a gap that file stated
# rather than closed (ML-4). It is closed here, by hoisting the tripwire to
# where the pins it protects actually live. The package-local copy is RETIRED
# rather than kept alongside: it watched the same event through the same
# mechanism, so two copies produce two teardown errors for one defect, not two
# facts.
#
# WHY A SENTINEL AND NOT A PROBE OF THE PINS THEMSELVES. Comparing
# ``os.environ["HERMES_HOME"]`` against the tempdir at teardown — the obvious
# probe — reddens legitimate tests: re-pointing or dropping a pinned variable
# inside a body is a supported pattern (a test whose SUBJECT is the fallback
# rung must ``delenv`` it; ``test_profile_runner.py`` sets
# ``HERMES_AGENT_RUNTIME_ROOT`` to a literal to prove the runner restores the
# caller's value). Every one of those is a test being explicit about what it
# needs, and a fence that punished them would be re-litigated and then
# weakened. The sentinel is untouchable by all of them and is unwound by
# exactly one thing: an ``undo()`` on the shared instance, which is the defect.


class _SharedMonkeypatchWitness:
    """Holder for the tree-wide teardown tripwire's witness token.

    A module-scope object in this conftest rather than an attribute on a
    production module: nothing under ``agent_runtime``/``hermes_cli`` should
    have to grow a field so the test suite can watch itself.
    """

    token: object | None = None


#: The one instance the fixture below pins. Module-scope so the pin is a real
#: ``monkeypatch.setattr`` on a real attribute — which is what makes
#: ``monkeypatch.undo()`` restore it to ``None`` and redden the tripwire.
_SHARED_MONKEYPATCH_WITNESS = _SharedMonkeypatchWitness()

#: The typed head of the tripwire's failure. Named so the gate
#: (``tests/test_conftest_pin_tripwire.py``) can match on it instead of on
#: prose that is free to be rewritten.
SHARED_MONKEYPATCH_UNWOUND_MESSAGE = (
    "THE SHARED MONKEYPATCH WAS UNWOUND FROM INSIDE THIS TEST"
)


@pytest.fixture(autouse=True)
def _shared_monkeypatch_pin_tripwire(monkeypatch):
    """PROVE, after every test body in the tree, that the autouse pins held.

    Declared FIRST among this file's autouse fixtures on purpose: setup order
    is declaration order, teardown is its reverse, so this assertion runs after
    every other guard's teardown and therefore covers the widest window. It
    still runs before ``monkeypatch``'s own unwind, because this fixture
    requests ``monkeypatch`` and a fixture is torn down before what it depends
    on.

    See the block comment above for the incident and for why the witness is a
    sentinel rather than a probe of the pins themselves.
    """

    # Minted per test and never handed to the body, so a body that unwound the
    # stack cannot restore it: the token is a fresh object this fixture owns,
    # and re-setting it would BE un-doing the unwind.
    token = object()
    monkeypatch.setattr(_SHARED_MONKEYPATCH_WITNESS, "token", token)

    yield

    assert _SHARED_MONKEYPATCH_WITNESS.token is token, (
        f"{SHARED_MONKEYPATCH_UNWOUND_MESSAGE}. `monkeypatch` is ONE instance "
        "shared by every fixture and the test body, and `undo()` takes no "
        "argument — it drops EVERYTHING. So this test also unwound the autouse "
        "guards in tests/conftest.py: HERMES_HOME is no longer the per-test "
        "tempdir, every credential-shaped env var this suite blanks is back, "
        "the kanban write guard, the live-system guard and the audio guard are "
        "all off — and under tests/agent_runtime the HERMES_AGENT_RUNTIME_ROOT "
        "and worktree-base pins are down too. Everything the body did after "
        "that point ran against the OPERATOR's live root with their real "
        "credentials: that is the 2026-08-17 leak (EG-0.1) that left "
        "`ws_office_patch_test` at revision 67 in X:/Eternia/.hermes and took a "
        "persona-chat root lease out there.\n\n"
        "FIX: wrap the one patch you meant to drop in a scoped context instead "
        "of unwinding the shared stack —\n"
        "    with pytest.MonkeyPatch.context() as patched:\n"
        "        patched.setattr(...)\n"
        "        ...  # the patched half of the test\n"
        "    ...            # the unpatched half; ONLY your patch is gone\n\n"
        "HERMES_HOME is now "
        f"{os.environ.get('HERMES_HOME')!r}."
    )


@pytest.fixture(autouse=True)
def _reset_snapshot_catalog_memos():
    """The snapshot core's TTL memos (installed-skill catalog, profile
    templates) must never leak rows across tests — tests monkeypatch the
    underlying fetchers (`skills_tool._find_all_skills`,
    `snapshot.available_profile_templates`) and a warm memo would mask the
    patch. Start every test cold."""
    for module_name, attr in (
        ("agent_runtime.prompt_observability", "_skill_catalog_memo"),
        ("agent_runtime.snapshot", "_profile_template_memo"),
    ):
        module = sys.modules.get(module_name)
        memo = getattr(module, attr, None) if module else None
        if isinstance(memo, dict):
            memo["rows"] = None
            memo["at"] = 0.0
    # Same rule, different shape: the chat-lane visibility bundle
    # (``agent_runtime.chat_lane_bundle``) is keyed on persona/permission/config
    # identity, and a test's hermetic HERMES_HOME normally makes that key unique
    # per test anyway. "Normally" is not a guarantee, and a bundle surviving into
    # the next test would serve it another test's toolset answer. Start cold.
    #
    # This does NOT cover a single test that monkeypatches a resolver BETWEEN two
    # turn-path calls — the memo cannot see a function patch. Such a test calls
    # ``invalidate_chat_lane_bundles()`` itself, which is real API.
    bundle_module = sys.modules.get("agent_runtime.chat_lane_bundle")
    if bundle_module is not None:
        bundle_module.invalidate_chat_lane_bundles()
    yield


@pytest.fixture(autouse=True)
def _isolate_hermes_shim_dir(tmp_path, monkeypatch, _hermetic_environment):
    """Keep `hermes postinstall`'s PATH shim out of the developer's real home.

    ``_hermetic_environment`` redirects ``HERMES_HOME`` and, by an explicit
    ruling recorded there, does NOT redirect ``HOME``. So the one directory
    ``register_hermes_command`` writes into — ``~/.local/bin`` on POSIX,
    ``%LOCALAPPDATA%\\hermes\\bin`` on Windows — stayed REAL for every test in
    this tree. A test that reached postinstall wrote a genuine shim onto the
    developer's PATH with the TEST's temp ``HERMES_HOME`` baked in as its
    default state root; that shim then outlives the run and hands every later
    hand-run ``hermes`` a state root that was deleted when the test finished.
    Measured on an operator's Mac, whose `~/.local/bin/hermes` defaulted
    ``HERMES_HOME`` to a macOS temp path from an E2E run.

    Redirecting the seam is the fix rather than redirecting ``HOME``, which
    that ruling forbids, and rather than asking each test to remember: the
    tests that DID remember are not the population this protects.

    **In-process only.** A test that spawns `hermes postinstall` as a
    SUBPROCESS is not covered by a monkeypatch and must isolate the directory
    itself (``LOCALAPPDATA``/``HOME`` in the child's env).
    """
    try:
        from hermes_cli import path_setup
    except Exception:
        return None

    shim_dir = tmp_path / "shim-bin"
    monkeypatch.setattr(path_setup, "_shim_install_dir", lambda: str(shim_dir))
    return shim_dir


_ALLOW_CLAUDE_CODE_CREDENTIALS_FILE_MARK = "allow_claude_code_credentials_file"


@pytest.fixture(autouse=True)
def _neutralize_claude_code_credentials_file(request, monkeypatch, _hermetic_environment):
    """Keep the suite off Claude Code's real ``~/.claude/.credentials.json``.

    The twin of ``_neutralize_macos_keychain_creds`` for the OTHER source
    ``read_claude_code_credentials()`` consults — and, unlike the keychain,
    this one is a READ **and a WRITE**.

    Invariant 2 at the top of this file deliberately does not redirect
    ``HOME`` ("that broke subprocesses in CI"), so ``HERMES_HOME`` never
    covered this path: ``Path.home()`` in any test resolves to the operator's
    real profile. ``~/.claude/.credentials.json`` is Claude Code's file,
    deliberately outside Hermes home (``credential_sources.py`` refuses to
    delete it for exactly that reason), so relocating it under
    ``HERMES_HOME`` was never an option either.

    Two routes reach it from the credential pool, gated differently:

    * ``_seed_from_singletons`` -> ``read_claude_code_credentials()``
      (``credential_pool.py``) sits behind
      ``is_provider_explicitly_configured("anthropic")``, which reads files
      ``HERMES_HOME`` *does* sandbox. Blocked — but only until a fixture
      writes ``active_provider: anthropic`` into its own hermetic
      ``auth.json``, which is one line and which the suite already does.
    * ``_available_entries`` -> ``_sync_anthropic_entry_from_credentials_file``
      has **no gate at all** and fires whenever a hermetic pool holds an
      anthropic entry with ``source="claude_code"`` and an exhausted/dead
      ``last_status``.

    The write side is the worse half: a test that reaches the token-refresh
    path calls ``_write_claude_code_credentials`` (from the adapter's own
    ``_refresh_oauth_token`` and from two pool refresh sites), which
    rewrites the operator's live Claude Code login with whatever the test's
    mocked refresh endpoint returned.

    Both module attributes are replaced here. A test that legitimately needs
    the real code path declares ``@pytest.mark.allow_claude_code_credentials_file``
    **and** points ``Path.home()`` at its own tmpdir — the gate in
    ``tests/test_claude_code_credentials_file_gate.py`` enforces the second
    half, because the marker alone would hand the host file straight back.

    Returns a call-count dict (never argument values — those are
    credentials) so the proof tests can assert the routes actually land here.
    """
    counts = {"read": 0, "write": 0}

    if request.node.get_closest_marker(_ALLOW_CLAUDE_CODE_CREDENTIALS_FILE_MARK):
        return counts

    try:
        import agent.anthropic_credentials as _anthropic_adapter
    except Exception:
        return counts

    def _blocked_read(*_args, **_kwargs):
        counts["read"] += 1
        return None

    def _blocked_write(*_args, **_kwargs):
        counts["write"] += 1
        return None

    _blocked_read._hermes_neutralized = True  # type: ignore[attr-defined]
    _blocked_write._hermes_neutralized = True  # type: ignore[attr-defined]

    monkeypatch.setattr(
        _anthropic_adapter,
        "_read_claude_code_credentials_from_file",
        _blocked_read,
        raising=False,
    )
    monkeypatch.setattr(
        _anthropic_adapter,
        "_write_claude_code_credentials",
        _blocked_write,
        raising=False,
    )
    return counts


# ── O(1) tmp_path (the aging-floor fix) ─────────────────────────────────────
#
# pytest's stock ``tmp_path`` allocates through ``make_numbered_dir``, which
# scans EVERY entry of the session basetemp to find the next free suffix — an
# O(entries) scan per test that makes the per-test floor GROW as a
# single-process run ages. Measured 2026-09-01 on this codebase's own scale:
# a fresh process pays ~2.7 ms/call, the 11,000th call pays ~24 ms, 150.8 s
# cumulative — and a 200-no-op-test probe's setup went 28 ms/test fresh →
# 77 ms/test at the end of a 4.7k-test run, with this scan the largest
# attributed component. (docs/agent-runtime-harness/planned/
# hermes-suite-perf-field-notes-2026-09-01.md §6b-i.)
#
# This override keeps the stock fixture's contract — a unique, empty,
# test-named directory under the session basetemp, kept for the life of the
# session exactly like the default ``tmp_path_retention_policy = "all"`` — and
# replaces only the ALLOCATOR: a process-local counter, so creation is O(1)
# regardless of how many tests have run. Uniqueness is the counter's, not the
# scan's: two tests with the same sanitized name get different suffixes, and
# concurrent pytest processes never share a basetemp in the first place
# (pytest allocates basetemp per process; the HERMES_TEST_TMP_ROOT wiring
# above keeps that per-PID too).
#
# ``tmp_path_factory`` is deliberately NOT overridden — direct
# ``mktemp()`` callers still get stock behavior; they are rare enough not to
# age the floor.

_TMP_COUNTER = itertools.count()
_TMP_NAME_RE = re.compile(r"[\W]")


@pytest.fixture()
def tmp_path(request, tmp_path_factory):
    """O(1) drop-in for pytest's ``tmp_path`` — see block comment above."""
    name = _TMP_NAME_RE.sub("_", request.node.name)[:30]
    path = tmp_path_factory.getbasetemp() / f"{name}-{next(_TMP_COUNTER)}"
    path.mkdir(mode=0o700)
    return path


_CLAUDE_HOME_IS_TMP_PATH_MARK = "claude_home_is_tmp_path"


@pytest.fixture(autouse=True)
def _claude_home_is_tmp_path(request, monkeypatch):
    """Point ``Path.home()`` at the test's own ``tmp_path``, by id.

    The redirect ``allow_claude_code_credentials_file`` REQUIRES
    (``tests/test_claude_code_credentials_file_gate.py``), for an upstream file
    that exercises the real ``~/.claude/.credentials.json`` reader/writer and
    carries no redirect of its own. ``tests/_downstream/id_markers.py`` applies
    both marks together; the gate accepts a table scope carrying this mark as
    redirected. ``tmp_path`` is resolved only for marked tests.
    """
    if request.node.get_closest_marker(_CLAUDE_HOME_IS_TMP_PATH_MARK) is None:
        return
    from pathlib import Path

    home = request.getfixturevalue("tmp_path")
    monkeypatch.setattr(Path, "home", lambda: home)


_CONFIG_READS_THROUGH_LOAD_CONFIG_MARK = "config_reads_through_load_config"


@pytest.fixture(autouse=True)
def _config_reads_through_load_config(request, monkeypatch):
    """Route ``load_config_readonly`` through whatever ``load_config`` is NOW.

    The fork moved several readers (``tools.vision_tools``,
    ``tools.image_generation_tool``, ``plugins/dashboard_auth/_shared.py``) from
    ``hermes_cli.config.load_config`` to ``load_config_readonly`` so an import
    cannot scaffold the home. Upstream's tests patch ``load_config``; for the
    ids ``tests/_downstream/id_markers.py`` marks, the readonly loader defers to
    it at call time, so upstream's patch reaches the reader and the upstream
    file carries no edit.
    """
    if request.node.get_closest_marker(_CONFIG_READS_THROUGH_LOAD_CONFIG_MARK) is None:
        return
    import hermes_cli.config as _config

    monkeypatch.setattr(_config, "load_config_readonly", lambda: _config.load_config())


_NO_REAL_ORPHAN_REAP_MARK = "no_real_orphan_reap"


@pytest.fixture(autouse=True)
def _no_real_orphan_reap(request, monkeypatch):
    """Keep an upstream web-server test off the machine's real process table.

    ``hermes_cli.web_server._spawn_gateway_restart`` (and the desktop backend's
    startup) call ``hermes_cli.gateway._reap_unsupervised_gateway_orphans``,
    which scans the REAL process table and then waits up to
    ``_ORPHAN_EXIT_GRACE_SECONDS`` (30 s) for every unsupervised gateway it
    found. Any such process on the box — an operator's, or a test-leaked
    ``gateway run --replace`` — turns the wait into the fork's 30 s per-test
    timeout. For the ids ``tests/_downstream/id_markers.py`` marks, the reap
    finds nothing; the behaviour under test (the restart report, the ticker)
    is unchanged.
    """
    if request.node.get_closest_marker(_NO_REAL_ORPHAN_REAP_MARK) is None:
        return
    import hermes_cli.gateway as _gateway

    monkeypatch.setattr(_gateway, "_reap_unsupervised_gateway_orphans", lambda *_a, **_k: False)


_BACKGROUND_AGENT_TURNS_MARK = "background_agent_turns"


@pytest.fixture(autouse=True)
def _background_agent_turns(request, _hermetic_environment, monkeypatch):
    """Turn on the agent-turn lane for an upstream test that exercises it.

    The fork delivers background-process completions as status text unless
    ``HERMES_BACKGROUND_AGENT_TURNS`` is set (``gateway.downstream_extensions``
    and ``tui_gateway.session_notifications``); upstream's delivery is an agent
    turn. For the ids ``tests/_downstream/id_markers.py`` marks, the opt-in is
    set, so the upstream test runs the lane it was written against, unedited.
    The one authority for this mark, tree-wide (it replaced a tests/hermes_cli
    copy that covered that directory alone).
    """
    if request.node.get_closest_marker(_BACKGROUND_AGENT_TURNS_MARK) is None:
        return
    monkeypatch.setenv("HERMES_BACKGROUND_AGENT_TURNS", "1")


#: The fork's per-test cap (seconds) and how it fires. ``thread`` dumps every
#: stack and KILLS the process, which is the only method Windows has (no
#: SIGALRM). Applied below as defaults, so an explicit ``--timeout`` /
#: ``--timeout-method`` on the command line still wins, exactly as it did when
#: these rode pyproject's ``addopts``.
FORK_TEST_TIMEOUT_SECONDS = 30.0
FORK_TEST_TIMEOUT_METHOD = "thread"


_SCOPED_MONKEYPATCH_UNDO_MARK = "scoped_monkeypatch_undo"


@pytest.hookimpl(wrapper=True)
def pytest_pyfunc_call(pyfuncitem):
    """Run an upstream test's mid-body ``monkeypatch.undo()`` against its OWN patches.

    Upstream tests that drop a stub with ``monkeypatch.undo()`` unwind the shared
    per-test instance, fixtures' hermetic pins included, and redden
    ``_shared_monkeypatch_pin_tripwire``. For a test carrying the mark (applied by
    id from ``tests/_downstream/id_markers.py``) ``undo`` is narrowed, for the call
    only, to the entries the BODY pushed: the stack length is taken once every
    fixture has set up, and an undo replays only the tail above it. Upstream's
    bytes run unchanged; what they drop is exactly what they patched.
    """
    monkeypatch = None
    if pyfuncitem.get_closest_marker(_SCOPED_MONKEYPATCH_UNDO_MARK) is not None:
        monkeypatch = getattr(pyfuncitem, "funcargs", {}).get("monkeypatch")
    if monkeypatch is None:
        return (yield)
    base_attr, base_item = len(monkeypatch._setattr), len(monkeypatch._setitem)
    base_cwd, base_path = monkeypatch._cwd, monkeypatch._savesyspath

    def body_undo() -> None:
        # A private instance takes the body's tail; leaving the context unwinds it alone.
        with pytest.MonkeyPatch.context() as body:
            body._setattr = monkeypatch._setattr[base_attr:]
            del monkeypatch._setattr[base_attr:]
            body._setitem = monkeypatch._setitem[base_item:]
            del monkeypatch._setitem[base_item:]
            if base_cwd is None:
                body._cwd, monkeypatch._cwd = monkeypatch._cwd, None
            if base_path is None:
                body._savesyspath, monkeypatch._savesyspath = monkeypatch._savesyspath, None

    monkeypatch.undo = body_undo
    try:
        return (yield)
    finally:
        del monkeypatch.undo


@pytest.hookimpl(tryfirst=True)
def pytest_configure(config):  # noqa: D401 — pytest hook
    """Register the fork's markers and default the per-test timeout.

    ``tryfirst`` because pytest-timeout reads ``config.option.timeout`` in its
    own ``pytest_configure``; a default set after it would be ignored. Without
    pytest-timeout installed (``requirements-fork-dev.txt``) the options do not
    exist and nothing is set.
    """
    if config.pluginmanager.hasplugin("timeout"):
        if getattr(config.option, "timeout", None) is None:
            config.option.timeout = FORK_TEST_TIMEOUT_SECONDS
        if getattr(config.option, "timeout_method", None) is None:
            config.option.timeout_method = FORK_TEST_TIMEOUT_METHOD
    config.addinivalue_line(
        "markers",
        "real_venv_pip: opt out of the autouse stub that replaces "
        "lazy_deps._venv_pip_install (for the one test that probes that function itself)",
    )
    config.addinivalue_line(
        "markers",
        "real_agent_browser_probe: opt out of the autouse stub that stops "
        "hermes_constants.agent_browser_runnable from EXECUTING an agent-browser off the operator PATH",
    )
    config.addinivalue_line(
        "markers",
        f"{_ALLOW_CLAUDE_CODE_CREDENTIALS_FILE_MARK}: allow a test to "
        "exercise the real ~/.claude/.credentials.json reader/writer. The "
        "test MUST also point Path.home() at its own tmpdir — the marker "
        "alone hands back the operator's live Claude Code login.",
    )
    config.addinivalue_line(
        "markers",
        "tirith_config_value_under_test: the test pins tirith's config.yaml value, so "
        "the fork's tools conftest drops the suite-wide TIRITH_* env for it "
        "(applied by id from tests/_downstream/id_markers.py).",
    )
    config.addinivalue_line(
        "markers",
        f"{_CONFIG_READS_THROUGH_LOAD_CONFIG_MARK}: the test patches "
        "hermes_cli.config.load_config for a reader the fork moved to "
        "load_config_readonly; the readonly loader defers to it (applied by id "
        "from tests/_downstream/id_markers.py).",
    )
    config.addinivalue_line(
        "markers",
        f"{_BACKGROUND_AGENT_TURNS_MARK}: the upstream test exercises agent-turn "
        "completion delivery, which the fork gates behind "
        "HERMES_BACKGROUND_AGENT_TURNS; the fixture sets it (applied by id from "
        "tests/_downstream/id_markers.py).",
    )
    config.addinivalue_line(
        "markers",
        f"{_CLAUDE_HOME_IS_TMP_PATH_MARK}: Path.home() is the test's tmp_path "
        "(applied by id from tests/_downstream/id_markers.py, together with "
        "allow_claude_code_credentials_file).",
    )
    config.addinivalue_line(
        "markers",
        f"{NO_LIVE_GATEWAY_MARK}: the test's premise is that no hermes gateway runs "
        "on this machine (it reads the real fleet process table); it skips, naming "
        "the live pids, where one does (applied by id from "
        "tests/_downstream/id_markers.py).",
    )
    config.addinivalue_line(
        "markers",
        f"{_NO_REAL_ORPHAN_REAP_MARK}: the gateway orphan reap finds nothing, so the "
        "test never waits on this machine's real unsupervised gateways (applied by "
        "id from tests/_downstream/id_markers.py).",
    )
    config.addinivalue_line(
        "markers",
        f"{_SCOPED_MONKEYPATCH_UNDO_MARK}: the upstream test calls monkeypatch.undo() "
        "mid-body; undo is narrowed to the body's own patches so the fixtures' hermetic "
        "pins hold (applied by id from tests/_downstream/id_markers.py).",
    )
