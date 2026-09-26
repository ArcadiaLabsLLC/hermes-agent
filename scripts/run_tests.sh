#!/usr/bin/env bash
# Canonical test runner for hermes-agent. Run this instead of calling
# `pytest` directly to guarantee your local run matches CI behavior.
#
# What this script enforces:
#   * Per-file isolation via scripts/run_tests_parallel.py — each test
#     file runs in its own freshly-spawned `python -m pytest <file>`
#     subprocess. No xdist, no shared workers, no module-level leakage
#     between files.
#   * TZ=UTC, LANG=C.UTF-8, PYTHONHASHSEED=0 (deterministic)
#   * Env vars blanked (conftest.py also does this, but this
#     is belt-and-suspenders for anyone running pytest outside our
#     conftest path — e.g. on a single file)
#   * The activated checkout's test environment (activates when needed)
#
# Usage:
#   scripts/run_tests.sh                            # full suite
#   scripts/run_tests.sh -j 4                       # cap parallelism
#   scripts/run_tests.sh tests/agent/               # discover only here
#   scripts/run_tests.sh tests/agent/ tests/acp_adapter/    # multiple roots
#   scripts/run_tests.sh tests/foo.py               # single file
#   scripts/run_tests.sh tests/foo.py -q            # path + bare pytest flag
#   scripts/run_tests.sh tests/foo.py -v --tb=long  # bare flags "just work"
#   scripts/run_tests.sh -k 'pattern'               # value flags pass through too
#   scripts/run_tests.sh tests/foo.py -- --tb=long  # explicit '--' still works
#
# Bare pytest flags (anything starting with '-' that isn't one of this
# runner's own options: -j/--jobs, --paths, --slice, --file-timeout, etc.)
# are forwarded to each per-file pytest invocation automatically — no '--'
# separator required. The explicit '--' form still works and stacks with
# bare flags. Positional path arguments override the default discovery
# root (tests/).
#
# ── Running tests/hermes_cli (and why through here) ─────────────────────────
#
#   scripts/run_tests.sh tests/hermes_cli -j 6
#
# This script is THE checkpoint runner for that directory, and a red is
# defined as "any FILE red under it". Running `pytest tests/hermes_cli`
# directly asks a different question: 568 files then share one interpreter,
# and ~41 failures appear in test_web_server_* / test_web_ui_build.py that are
# green when each file is run alone (ledger row F3). That is module-level
# state leaking across files — the exact thing per-file spawning exists to
# prevent — so it is a fact about the interpreter, not a defect in those
# tests, and it is not being chased (ML-7 / operator ruling R-e, 2026-08-18).
#
# The fork's shared-venv probe (``$HERMES_TEST_VENV``, ``~/.venvs/hermes-test``)
# retired at the 2026-09-25 upstream merge in favour of upstream's door: an
# explicit ``HERMES_PYTHON`` that has pytest wins when nothing is activated.
# On the workstation that is the shared canonical test venv:
#
#   HERMES_PYTHON=C:/Users/beast/.venvs/hermes-test/Scripts/python.exe #     scripts/run_tests.sh tests/hermes_cli
#
# Without it the runner activates the checkout (upstream's supported path).

set -euo pipefail

# ── Locate repo root ────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# ── Locate python ───────────────────────────────────────────────────────────
# The suite runs under the activated checkout's isolated test environment
# (pm.testenv: `activate` builds it beside the checkout's install state, and CI
# activates the same way). An inherited activation is re-checked against its
# inputs (scripts/_activation.sh) and re-sourced when stale, so a branch switch
# or lock edit never runs the suite against the previous dependency set.
#
# Without an activation, an explicit HERMES_PYTHON that has pytest is honored:
# the Nix devShell's editable venv and CI's minimal installer lanes provide
# one on purpose. The import check matters: a wrapped `hermes` binary exports
# HERMES_PYTHON pointing at a release venv without pytest.
_has_pytest() { [ -n "$1" ] && [ -x "$1" ] && "$1" -c 'import pytest' 2>/dev/null; }
# shellcheck source=scripts/_activation.sh
. "$SCRIPT_DIR/_activation.sh"
if [ -z "${__HERMES_ACTIVATED:-}" ] && _has_pytest "${HERMES_PYTHON:-}"; then
  PYTHON="$HERMES_PYTHON"
  echo "▶ not activated — using HERMES_PYTHON: $PYTHON"
else
  test_stamp="${__HERMES_ACTIVATED:-}"
  test_stamp="${test_stamp//\\//}"
  if ! hermes_activation_current "$REPO_ROOT" ||
     [ ! -f "${test_stamp%/*}/inputs/.test-environment" ] ||
     ! _has_pytest "${__HERMES_TEST_PYTHON:-}"; then
    echo "▶ activating $REPO_ROOT (environment missing or stale)" >&2
    # activate is written for interactive shells, not errexit/nounset.
    set +euo pipefail
    # shellcheck source=/dev/null
    . "$REPO_ROOT/activate" --
    activated=$?
    set -euo pipefail
    if [ "$activated" != 0 ]; then
      echo "error: activation failed (see above)" >&2
      exit 1
    fi
  fi
  PYTHON="${__HERMES_TEST_PYTHON:-}"
  if ! _has_pytest "$PYTHON"; then
    echo "error: activation provided no test interpreter with pytest (__HERMES_TEST_PYTHON=${PYTHON:-unset})" >&2
    exit 1
  fi
fi

# Fork-only test deps (requirements-fork-dev.txt): the one place they install.
"$PYTHON" "$REPO_ROOT/scripts/ensure_fork_dev_deps.py" || exit 1


# ── Live-gateway plugin (computed before we drop env) ───────────────────────
EXTRA_PYTHONPATH=""
EXTRA_PYTEST_PLUGINS=""
if [ -f "$HOME/.hermes/pytest_live_guard.py" ]; then
  EXTRA_PYTHONPATH="$HOME/.hermes"
  EXTRA_PYTEST_PLUGINS="pytest_live_guard"
fi


# ── Windows location variables (computed before we drop env) ───────────────
# `env -i` forwards HOME, which is enough on POSIX. Native Windows CPython
# resolves Path.home() from USERPROFILE (or HOMEDRIVE+HOMEPATH), stdlib
# platform paths come from LOCALAPPDATA/APPDATA, ssl/sockets need SYSTEMROOT,
# and tempfile needs TEMP/TMP. Dropping them breaks collection on native
# Windows (issues #67385, #70813). PATHEXT is also required: without .EXE,
# PowerShell opens a native child as a document without waiting for its exit.
# These are location variables, not
# credentials, so forwarding them keeps the isolation intent intact. Each is
# only forwarded when actually set, so POSIX runs are byte-for-byte unchanged.
WIN_ENV=()
for _win_var in USERPROFILE HOMEDRIVE HOMEPATH LOCALAPPDATA APPDATA SYSTEMROOT TEMP TMP \
    ComSpec PATHEXT PROGRAMFILES ProgramFiles PROGRAMDATA ProgramData; do
  if [ -n "${!_win_var:-}" ]; then
    WIN_ENV+=("$_win_var=${!_win_var}")
  fi
done
# Native build toolchain (Windows arm64 has no wheels for every pinned C extension, so
# `uv sync` inside a PM test compiles ruamel-yaml-clib and friends). The MSVC developer
# environment is exported by scripts/build/windows-deps.ps1 into the job env; without
# INCLUDE/LIB/VSINSTALLDIR the build backend reports "Visual C++ 14.0 or greater is
# required". These describe compiler locations, not credentials.
for _tool_var in INCLUDE LIB LIBPATH VSINSTALLDIR VCINSTALLDIR VCToolsInstallDir VCToolsVersion \
    VCToolsRedistDir WindowsSdkDir WindowsSDKVersion WindowsSdkBinPath WindowsSdkVerBinPath \
    WindowsLibPath UCRTVersion UniversalCRTSdkDir VSCMD_ARG_HOST_ARCH VSCMD_ARG_TGT_ARCH VSCMD_VER \
    DevEnvDir ExtensionSdkDir Platform CARGO_HOME RUSTUP_HOME RUSTUP_TOOLCHAIN \
    CARGO_TARGET_AARCH64_PC_WINDOWS_MSVC_LINKER CC_aarch64_pc_windows_msvc CC CXX AR \
    VCPKG_ROOT OPENSSL_DIR OPENSSL_STATIC OPENSSL_LIB_DIR OPENSSL_INCLUDE_DIR; do
  if [ -n "${!_tool_var:-}" ]; then
    WIN_ENV+=("$_tool_var=${!_tool_var}")
  fi
done
# setuptools locates the compiler through vswhere under "%ProgramFiles(x86)%\Microsoft Visual
# Studio\Installer"; without that variable a primed INCLUDE/LIB still reads as "Visual C++ 14.0
# or greater is required". The parenthesised name cannot be read with ${!var}.
_pf86="$(env | sed -n 's/^ProgramFiles(x86)=//p' | head -n1)"
[ -z "$_pf86" ] || WIN_ENV+=("ProgramFiles(x86)=$_pf86")

# ── Test-runner knobs (computed before we drop env) ────────────────────────
# The runner's own documented environment knobs must survive the hermetic
# `env -i` below, or they are silent no-ops for anyone invoking this script:
#
#   * HERMES_TEST_WORKERS / PATHS / FILE_TIMEOUT / FILE_RETRIES / SLICE are
#     read by run_tests_parallel.py at argparse-default time — inside the
#     stripped environment.
#   * HERMES_TEST_IMAGE is read by tests/docker/conftest.py to skip its
#     session-scoped `docker build`. CI's docker.yml sets it to the image
#     the build step just loaded; stripping it made every per-file pytest
#     subprocess rebuild the 5GB image from a cold builder cache instead
#     (~4 min per worker per run, and the rebuilt image lacked the
#     HERMES_GIT_SHA build-arg the workflow bakes in).
#   * HERMES_E2E_REQUIRE_TUI turns a missing Ink TUI build into a failure in
#     tests/e2e/core/terminal instead of a skip (set by the e2e CI job).
#   * CI / GITHUB_ACTIONS tell suites they run on a disposable runner (e.g.
#     tests/e2e/core/upgrade runs the real updater unsandboxed only there).
#
# These are test-infrastructure knobs, not credentials — same class as the
# HERMES_RUN_SLOW_PET_TESTS / HERMES_E2E_BROWSER / HERMES_RUN_E2E opt-ins
# forwarded below.
# SSL_CERT_FILE/DIR are trust-store locations: the pinned interpreter's
# OpenSSL has no compiled-in bundle path on NixOS, so network tests (PM
# downloads, channel reads) need the host's pointer to verify TLS.
# Keep this an explicit allowlist (no HERMES_TEST_* glob) so the "no
# credential can leak" property stays auditable at a glance.
TEST_ENV=()
for _test_var in HERMES_TEST_IMAGE HERMES_TEST_WORKERS HERMES_TEST_PATHS \
  HERMES_TEST_FILE_TIMEOUT HERMES_TEST_FILE_RETRIES HERMES_TEST_SLICE \
  SSL_CERT_FILE SSL_CERT_DIR HERMES_GATEWAY_LOCK_DIR HERMES_E2E_REQUIRE_TUI CI GITHUB_ACTIONS; do
  if [ -n "${!_test_var:-}" ]; then
    TEST_ENV+=("$_test_var=${!_test_var}")
  fi
done

# ── Run in hermetic env ──────────────────────────────────────────────────────
# env -i: start with empty environment, opt-in only what we need.
# No credential var can leak — you'd have to explicitly add it here.
#
# The Windows platform vars below are opt-in for the same reason PATH/HOME are:
# they are not credentials, they are how the OS answers "where is the user, and
# where is scratch space". Without USERPROFILE/LOCALAPPDATA/APPDATA, CPython's
# ``Path.home()`` has nothing to resolve against and every import that touches
# it dies at COLLECTION time — a baseline run on Windows reported ~56 files
# failing for reasons no source change caused, which makes the failure-set diff
# (the only honest "is this mine?" signal) unreadable. SYSTEMROOT is required by
# the socket/ssl/subprocess machinery on Windows, and TEMP/TMP keep tempfile off
# a fabricated path. All six are absent-safe: `${VAR:+VAR="$VAR"}` expands to
# nothing on POSIX, so Linux/macOS/CI runs are byte-for-byte unchanged.
#
# SYSTEMROOT is read UPPERCASE on purpose. Windows treats env var names as
# case-insensitive; the shell reading them here does not. git-bash exports the
# variable as `SYSTEMROOT`, so the mixed-case `${SystemRoot:+…}` this line used
# to carry expanded to NOTHING and the var was silently dropped from the
# hermetic env — the exact class of dead guard it was written to prevent. The
# child is still handed it under the spelling Windows itself uses.
echo "▶ running per-file parallel test suite via run_tests_parallel.py"
echo "  (TZ=UTC LANG=C.UTF-8 PYTHONHASHSEED=0; clean env)"

cd "$REPO_ROOT"

# ── The operator's REAL store root, named for the fence ─────────────────────
#
# ``tests/hermes_cli/_gateway_fence.py`` has a "would run hermes against the
# operator's REAL store" arm. It learns that root by calling the production
# resolver, ``hermes_constants.get_default_hermes_root()`` — which reads
# ``HERMES_HOME``. Under BARE pytest, launched from an operator shell where
# HERMES_HOME names the live store, that answers correctly and the arm works.
#
# Under THIS script it did not, and the reason is the `env -i` two lines below:
# HERMES_HOME is deliberately not forwarded, so ``tests/conftest.py`` mints a
# throwaway session home, the fence imports AFTER that, and the resolver hands
# it the TEMPDIR. Measured on this workstation 2026-09-03, before this block:
#
#   _REAL_ROOT under run_tests.sh = C:\...\Temp\hermes-test-home-g_quyxlh
#   _REAL_ROOT under bare pytest  = X:\Eternia\.hermes
#
# and a `hermes config get` argv aimed at X:\Eternia\.hermes\profiles\alice
# classified ALLOWED in the first case, REFUSED in the second.
#
# So the whole arm — and the three tests in test_gateway_spawn_fence.py that
# drive it — was measuring a directory that had existed for a few milliseconds
# and would never appear in any argv. The defence existed only on the path
# nobody is told to use.
#
# Forwarding HERMES_HOME itself is NOT the fix: conftest must keep installing
# its own hermetic home, and handing the child the real one would put the live
# store back in front of every test — the hazard, not the guard. Instead the
# root travels under a dedicated TEST-ONLY name the fence reads first.
# HERMES_REAL_HOME was NOT reused: that is a production variable
# (``hermes_constants.py:1004`` ``_iter_real_home_candidates``, whose first
# candidate it is — the OS-user home an ACP child inherits, not a
# store root) and ``tests/conftest.py`` blanks it per test on purpose.
#
# Computed with the probed venv python and the production resolver rather than
# re-derived in shell, so the "which profile dir belongs to which root"
# unwrapping has exactly one implementation. Fail-soft: if the probe prints
# nothing the variable is not forwarded and the fence falls back to today's
# behavior.
REAL_HERMES_ROOT="$(
  "$PYTHON" -c 'import sys; sys.path.insert(0, "."); from hermes_constants import get_default_hermes_root; print(get_default_hermes_root())' \
    2>/dev/null || true
)"
if [ -n "$REAL_HERMES_ROOT" ]; then
  echo "▶ real store root handed to the gateway fence: $REAL_HERMES_ROOT"
fi

# Fork (Git Bash / MSYS / WSL): a native-Windows "$PYTHON" (…/Scripts/python.exe)
# cannot open a POSIX-style /x/... or /mnt/x/... script path, so translate the
# runner path to the spelling Windows itself uses before exec'ing.
RUNNER_PATH="$SCRIPT_DIR/run_tests_parallel.py"
if command -v cygpath >/dev/null 2>&1 && [[ "$PYTHON" == *.exe ]]; then
  RUNNER_PATH="$(cygpath -w "$RUNNER_PATH")"
elif [[ "$PYTHON" == *.exe && "$RUNNER_PATH" =~ ^/mnt/([A-Za-z])/(.*)$ ]]; then
  drive="${BASH_REMATCH[1]^^}"
  rest="${BASH_REMATCH[2]//\//\\}"
  RUNNER_PATH="${drive}:\\${rest}"
fi

# ── Pre-compile .pyc bytecode cache ─────────────────────────────────────────
# Each test file runs in its own subprocess via run_tests_parallel.py.
# Pre-building the bytecode cache once here (instead of each subprocess
# compiling on first import) avoids redundant work across ~2000 processes.
# Uses git to list tracked .py files (skips venv, node_modules, etc).
echo "▶ pre-compiling bytecode cache"
"$PYTHON" -m compileall -q -j 0 -- $(git ls-files '*.py') >/dev/null 2>&1 || true

# ── The branch measurement's one variable ───────────────────────────────────
#
# HERMES_TEST_COVERAGE_RC names a coverage config file. When it is set, every
# per-file subprocess becomes `coverage run --rcfile=<it> -m pytest <file>`
# (``run_tests_parallel.py::_pytest_argv``); when it is not, the argv is
# byte-identical to what it has always been, so an ordinary run pays nothing.
# Its only caller is ``scripts/unreachable_branch_report.py``, which measures
# THROUGH this runner rather than re-spelling the hermetic env below — a second
# spelling of that env would report branches taken under pins and variables no
# suite actually runs with. Nothing consumes the report's exit code: it is a
# report, not a gate.
echo "▶ launching test runner"
exec env -i \
  PATH="$PATH" \
  HOME="$HOME" \
  ${WIN_ENV[@]+"${WIN_ENV[@]}"} \
  ${TEST_ENV[@]+"${TEST_ENV[@]}"} \
  TZ=UTC \
  LANG=C.UTF-8 \
  LC_ALL=C.UTF-8 \
  PYTHONHASHSEED=0 \
  PYTHONUTF8=1 \
  ${HERMES_RUN_SLOW_PET_TESTS:+HERMES_RUN_SLOW_PET_TESTS="$HERMES_RUN_SLOW_PET_TESTS"} \
  ${HERMES_E2E_BROWSER:+HERMES_E2E_BROWSER="$HERMES_E2E_BROWSER"} \
  ${HERMES_TEST_TMP_ROOT:+HERMES_TEST_TMP_ROOT="$HERMES_TEST_TMP_ROOT"} \
  ${HERMES_TEST_COVERAGE_RC:+HERMES_TEST_COVERAGE_RC="$HERMES_TEST_COVERAGE_RC"} \
  ${REAL_HERMES_ROOT:+HERMES_TEST_REAL_ROOT="$REAL_HERMES_ROOT"} \
  ${HERMES_RUN_E2E:+HERMES_RUN_E2E="$HERMES_RUN_E2E"} \
  ${EXTRA_PYTHONPATH:+PYTHONPATH="$EXTRA_PYTHONPATH"} \
  ${EXTRA_PYTEST_PLUGINS:+PYTEST_PLUGINS="$EXTRA_PYTEST_PLUGINS"} \
  "$PYTHON" "$RUNNER_PATH" "$@"
