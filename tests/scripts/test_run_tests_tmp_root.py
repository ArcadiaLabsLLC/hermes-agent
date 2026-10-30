"""The per-file runner puts its OWN scratch and its child's temp under the named root (D3.08).

``HERMES_TEST_TMP_ROOT`` used to move only the pytest children (the fork's
conftest plugin redirects them); the runner process kept ``%TEMP%``, so its
``hermes-pytest`` scratch root — every child's basetemp lives under it — and
upstream's import-time ``hermes-test-home-*`` landed in the system temp dir.
``scripts/run_tests.sh`` now exports the root as TEMP/TMP for the runner too, and on POSIX —
where upstream hard-codes ``/var/tmp/hermes-pytest-<uid>`` — the fork seam
``scripts/_fork_runner.py::scratch_root`` puts the scratch under the root as well.

The probe file sits outside the repository, so no repo conftest touches the
child's temp: what it reports is what the runner handed it.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]

_PROBE = '''
import json
import os
import tempfile


def test_probe():
    with open({out!r}, "w", encoding="utf-8") as handle:
        json.dump({{"temproot": os.environ.get("PYTEST_DEBUG_TEMPROOT"), "gettempdir": tempfile.gettempdir()}}, handle)
'''


def _inside(path: str, root: Path) -> bool:
    resolved, base = Path(path).resolve(), root.resolve()
    return resolved == base or base in resolved.parents


@pytest.mark.timeout(300)
def test_the_runner_scratch_and_the_child_temp_land_under_the_named_root(tmp_path, real_bash):
    root = tmp_path / ("root-" + "x" * 40)  # over the 40-byte AF_UNIX budget on every host
    root.mkdir()
    out = tmp_path / "seen.json"
    case = tmp_path / "case" / "test_tmp_probe.py"
    case.parent.mkdir()
    case.write_text(_PROBE.format(out=str(out)), encoding="utf-8")
    env = {
        **os.environ,
        "HERMES_PYTHON": sys.executable,
        "HERMES_TEST_TMP_ROOT": str(root),
        "HERMES_TEST_FILE_RETRIES": "0",
    }

    result = subprocess.run(
        [real_bash, str(_REPO / "scripts" / "run_tests.sh"), "-j", "1", str(case)],
        cwd=str(tmp_path), capture_output=True, text=True, encoding="utf-8", errors="replace",
        env=env, timeout=280,
        check=False,
    )

    assert result.returncode == 0, result.stdout[-3000:] + result.stderr[-3000:]
    assert "test temp root (runner and children): " in result.stdout
    if sys.platform != "win32":  # FH-TEST-TMP-ROOT-SUN-PATH-BUDGET: warned, and still followed
        assert f"⚠ test temp root is {len(os.fsencode(str(root)))} bytes; over the 40-byte AF_UNIX budget" in result.stdout
    seen = json.loads(out.read_text(encoding="utf-8"))
    # Every platform: the runner's scratch follows the named root (``_fork_runner.scratch_root``,
    # FH-RUNNER-SCRATCH-FOLLOWS-TEST-TMP-ROOT); on POSIX it used to stay on /var/tmp.
    scratch = root
    assert seen["temproot"] and _inside(seen["temproot"], scratch), seen
    assert _inside(seen["gettempdir"], scratch), seen


# FH-TEST-TMP-ROOT-SUN-PATH-BUDGET. Mutation: compare against 400 instead of 40 -> the long root
# prints no warning. Positive control: the same call with a short root prints none.
@pytest.mark.skipif(sys.platform == "win32", reason="the AF_UNIX budget is POSIX-only; Windows uses named pipes")
@pytest.mark.parametrize(("name", "warned"), [("r", False), ("r" * 41, True)])
def test_a_root_over_the_af_unix_budget_is_warned_and_still_followed(tmp_path, real_bash, name, warned):
    (tmp_path / name).mkdir()
    script = (f'REPO_ROOT={str(_REPO)!r}; . {str(_REPO / "scripts" / "_fork_test_env.sh")!r}; '
              f'HERMES_TEST_TMP_ROOT={name}; fork_test_tmp_root; echo "TMPDIR=$TMPDIR"')
    result = subprocess.run([real_bash, "-c", script], cwd=str(tmp_path), capture_output=True, text=True,
                            encoding="utf-8", errors="replace", timeout=60, check=False,
                            env={**os.environ, "ETERNIA_HEAVY_SLOT_DIR": str(tmp_path)})
    assert result.returncode == 0, result.stderr
    assert f"TMPDIR={name}" in result.stdout  # followed either way
    assert ("over the 40-byte AF_UNIX budget" in result.stdout) is warned, result.stdout
