from pathlib import Path


def _code_lines(script: str) -> list[str]:
    """The script's executable lines: comments and blanks dropped."""
    return [
        line for line in script.splitlines() if line.strip() and not line.lstrip().startswith("#")
    ]


def test_run_tests_supports_windows_git_bash_venv_layout():
    """A native-Windows interpreter is handed a Windows spelling of the runner.

    The interpreter comes from an activation or ``HERMES_PYTHON`` (often
    ``…/Scripts/python.exe``); under Git Bash / MSYS / WSL it cannot open a
    POSIX ``/x/...`` script path, so the runner path is translated first.
    """
    script = Path("scripts/run_tests.sh").read_text(encoding="utf-8")
    assert 'if command -v cygpath >/dev/null 2>&1 && [[ "$PYTHON" == *.exe ]]; then' in script
    assert 'RUNNER_PATH="$(cygpath -w "$RUNNER_PATH")"' in script
    assert '[[ "$PYTHON" == *.exe && "$RUNNER_PATH" =~ ^/mnt/([A-Za-z])/(.*)$ ]]' in script


def test_run_tests_does_not_use_global_python_after_venv_detection():
    script = Path("scripts/run_tests.sh").read_text(encoding="utf-8")
    # The runner invocation spends the selected interpreter, never a global one,
    # and the runner path travels through $RUNNER_PATH so the Windows arms can
    # rewrite it for a native interpreter. The interpreter is one of exactly
    # two doors: an explicit HERMES_PYTHON, or the activation's test python.
    assert '"$PYTHON" "$RUNNER_PATH" "$@"' in script
    assert 'RUNNER_PATH="$SCRIPT_DIR/run_tests_parallel.py"' in script
    assignments = sorted(
        {line.strip() for line in _code_lines(script) if line.strip().startswith("PYTHON=")}
    )
    assert assignments == ['PYTHON="$HERMES_PYTHON"', 'PYTHON="${__HERMES_TEST_PYTHON:-}"']


def test_the_local_venv_still_outranks_the_shared_canonical_one():
    """The checkout's activation outranks an inherited ``HERMES_PYTHON``.

    The fork's shared-venv probe (``VENV_CANDIDATES``) retired at the
    2026-09-25 upstream merge in favour of upstream's door. ``HERMES_PYTHON``
    is honoured only when nothing is activated AND it has pytest, so a wrapped
    ``hermes`` binary's release venv never silently replaces the checkout's
    own environment. The probe list must not come back beside it.
    """
    script = Path("scripts/run_tests.sh").read_text(encoding="utf-8")
    assert (
        'if [ -z "${__HERMES_ACTIVATED:-}" ] && _has_pytest "${HERMES_PYTHON:-}"; then' in script
    )
    assert "\"$1\" -c 'import pytest'" in script
    assert not [line for line in _code_lines(script) if "VENV_CANDIDATES" in line]


def test_no_machine_specific_venv_path_is_committed_in_the_runner():
    """Every interpreter selection must be PORTABLE.

    A site-local absolute path in a shared script is a fact about one machine
    that everyone else has to read past, and it rots silently when that
    machine changes. The workstation's shared venv is reached through
    ``HERMES_PYTHON`` set in the caller's environment, never spelled here.

    Drive letters in COMMENTS are fine and deliberate. Only executable lines
    are constrained.
    """
    script = Path("scripts/run_tests.sh").read_text(encoding="utf-8")
    selection = [line for line in _code_lines(script) if "PYTHON" in line]
    assert selection, "the interpreter selection moved — re-point this test"
    for line in selection:
        assert ":/" not in line and ":\\" not in line, (
            f"machine-specific path in the interpreter selection: {line.strip()}. "
            "Set HERMES_PYTHON in the caller's environment instead."
        )


def test_run_tests_hands_the_gateway_fence_the_real_store_root():
    """The runner must forward the real store root, and NOT ``HERMES_HOME``.

    ``tests/hermes_cli/_gateway_fence.py``'s real-store arm learns the root it
    must refuse from ``HERMES_TEST_REAL_ROOT``. Without this forwarding the
    fence resolved the root from ``HERMES_HOME``, which this script drops on
    purpose — so under the canonical runner it computed the throwaway session
    tempdir and the arm could never fire (measured 2026-09-03: a
    ``hermes config get`` argv aimed at ``X:\\Eternia\\.hermes`` classified
    ALLOWED under the runner, REFUSED under bare pytest).

    Forwarding ``HERMES_HOME`` itself would be the wrong fix and is asserted
    against: ``tests/conftest.py`` must keep installing the hermetic home.
    """
    script = Path("scripts/run_tests.sh").read_text(encoding="utf-8")
    assert '${REAL_HERMES_ROOT:+HERMES_TEST_REAL_ROOT="$REAL_HERMES_ROOT"}' in script
    assert "get_default_hermes_root" in script
    # The hermetic env must not carry HERMES_HOME through.
    exec_block = script[script.index("exec env -i") :]
    assert 'HERMES_HOME="$HERMES_HOME"' not in exec_block
    assert "HERMES_HOME=" not in exec_block


def test_run_tests_forwards_the_branch_measurement_config_var():
    """``HERMES_TEST_COVERAGE_RC`` reaches the hermetic child, absent-safe.

    ``scripts/unreachable_branch_report.py`` measures THROUGH this runner rather
    than re-spelling its ``env -i`` block, so the one variable that switches
    tracing on has to survive the drop. It is forwarded with the same
    ``${VAR:+…}`` guard every other opt-in uses, so a run without it is
    byte-for-byte the run it always was — asserted here, because a plain
    ``VAR="$VAR"`` would hand the child an empty value and make every run a
    traced one.
    """
    script = Path("scripts/run_tests.sh").read_text(encoding="utf-8")
    exec_block = script[script.index("exec env -i") :]
    assert (
        '${HERMES_TEST_COVERAGE_RC:+HERMES_TEST_COVERAGE_RC="$HERMES_TEST_COVERAGE_RC"}'
        in exec_block
    )
    assert 'HERMES_TEST_COVERAGE_RC="$HERMES_TEST_COVERAGE_RC"' not in exec_block.replace(
        '${HERMES_TEST_COVERAGE_RC:+HERMES_TEST_COVERAGE_RC="$HERMES_TEST_COVERAGE_RC"}', ""
    )
