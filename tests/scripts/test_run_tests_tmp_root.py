"""The per-file runner puts its OWN scratch and its child's temp under the named root (D3.08).

``HERMES_TEST_TMP_ROOT`` used to move only the pytest children (the fork's
conftest plugin redirects them); the runner process kept ``%TEMP%``, so its
``hermes-pytest`` scratch root — every child's basetemp lives under it — and
upstream's import-time ``hermes-test-home-*`` landed in the system temp dir.
``scripts/run_tests.sh`` now exports the root as TEMP/TMP for the runner too.

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
    root = tmp_path / "root"
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
    )

    assert result.returncode == 0, result.stdout[-3000:] + result.stderr[-3000:]
    assert "test temp root (runner and children): " in result.stdout
    seen = json.loads(out.read_text(encoding="utf-8"))
    assert seen["temproot"] and _inside(seen["temproot"], root), seen
    assert _inside(seen["gettempdir"], root), seen
