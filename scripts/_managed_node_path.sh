# shellcheck shell=bash
# Sourced, never executed: pm's managed Node and pnpm on PATH for a test run that skips activation.
#
# Owner ruling 2026-11-21 ("Node and pnpm on PATH for every hermes test run, not just the daily
# run"). Activation (`scripts/run-in-hermes-env`) composes every installed pm package onto PATH;
# the fork's workstation runs take the shared test venv (or an explicit HERMES_PYTHON) instead
# and never activate, so a box whose only node/pnpm is pm's reds the suite's Node tests
# (tests/scripts/test_bundle_pnpm.py, tests/scripts/test_webapp_renderer_freshness.py,
# tests/plugins/platforms/photon/test_url_send_path.py) on the box, never in the code.
#
# The ONE copy: scripts/_fork_test_env.sh (every scripts/run_tests.sh and, through it,
# run_tests_bundled.sh run) and scripts/daily_full_run.sh both call it.
#
#   fork_managed_node_on_path REPO
#
# The dirs come from pm's own resolver (`pm.install.env_for`, what `pm env node pnpm` prints),
# run under the bootstrap interpreter activation itself composes with (`hermes_bootstrap_python`)
# — no version is named here. A checkout whose pins the store does not hold resolves nothing:
# PATH stays as it was and one notice line says so. HERMES_TEST_PM_PYTHON replaces that
# interpreter (the scripts' own tests drive it).
#
# Cheap: one python start (~0.2 s) per invocation, and the answer is exported as
# __HERMES_MANAGED_NODE_PATH, so a nested run (daily_full_run.sh's steps, run_tests_bundled.sh's
# re-entry) reuses it and starts nothing; a dir already on PATH is not added twice.

_fork_resolve_managed_node_path() {
  local repo="$1" python pythonpath="$1"
  if [ -n "${HERMES_TEST_PM_PYTHON:-}" ]; then
    python="$HERMES_TEST_PM_PYTHON"
  else
    [ -f "$repo/scripts/_activation.sh" ] || return 1
    # shellcheck source=scripts/_activation.sh
    python="$(. "$repo/scripts/_activation.sh" && hermes_bootstrap_python "$repo")" || return 1
  fi
  # A native Windows python cannot open Git Bash's /c/... spelling.
  if command -v cygpath >/dev/null 2>&1; then pythonpath="$(cygpath -m "$repo")"; fi
  PYTHONHOME= PYTHONPATH="$pythonpath" "$python" -c \
    'from pm.install import env_for; print(env_for("node", "pnpm", base_env={}).get("PATH", ""))' 2>/dev/null
}

fork_managed_node_on_path() {
  local managed
  if [ -n "${__HERMES_MANAGED_NODE_PATH+set}" ]; then
    managed="$__HERMES_MANAGED_NODE_PATH"
  else
    managed="$(_fork_resolve_managed_node_path "$1")" || managed=""
    # A native Windows python prints `C:\a;C:\b`; bash splits PATH on ':'.
    if [ -n "$managed" ] && command -v cygpath >/dev/null 2>&1; then managed="$(cygpath -u -p "$managed")"; fi
    export __HERMES_MANAGED_NODE_PATH="$managed"
  fi
  if [ -z "$managed" ]; then
    echo "▶ no managed node/pnpm recorded for this checkout's pins — PATH unchanged"
    return 0
  fi
  case ":$PATH:" in
    *":$managed:"*) ;;
    *) PATH="$managed:$PATH"; export PATH ;;
  esac
  echo "▶ managed node/pnpm on PATH: $managed"
}
