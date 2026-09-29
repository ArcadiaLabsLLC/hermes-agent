"""Fork-owned half of ``tests/cron/test_restart_safe_worker.py``.

The external cron worker refuses a PM dependency generation built for another
Python (``hermes_cli.interpreter_abi``, fork seam in ``cron/worker_bootstrap.py``).
Moved out of the upstream file so its bytes stay upstream's; upstream's
generation and worker helpers are imported by name.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from tests.cron.test_restart_safe_worker import _commit_generation, _marked_worker


def test_marked_worker_refuses_a_generation_built_for_another_python():
    """2026-09-29 (alice): a 3.12 interpreter that activates a 3.14 generation imports every
    pure-Python package and none of the compiled ones -- openai died on pydantic_core for
    seven hours. The worker must exit before cron.jobs instead of running on that tree; the
    spawn site reports the pre-ack exit with this stderr. The positive control is
    ``test_marked_worker_keeps_its_generation_through_a_rotation``: same generation shape,
    this interpreter's version, and it boots."""
    import cron.worker_bootstrap as worker_bootstrap
    import pm.environments

    repo_root = Path(worker_bootstrap.__file__).resolve().parent.parent
    venv = _commit_generation(repo_root, "foreign", with_site_packages=True)
    foreign = f"{sys.version_info[0]}.{sys.version_info[1] + 1}"
    (venv / "pyvenv.cfg").write_text(f"uv = 0.12.3\nversion_info = {foreign}.0\n", encoding="utf-8")
    # Present, so the refusal under test answers -- not the missing-interpreter one.
    interpreter = pm.environments.venv_python(venv)
    interpreter.parent.mkdir(parents=True, exist_ok=True)
    interpreter.write_bytes(b"")
    child = _marked_worker(repo_root, subprocess.PIPE)
    out, err = child.communicate(timeout=60)
    assert child.returncode == 3, err
    result = json.loads(out.strip().splitlines()[-1])
    assert f"built for Python {foreign}" in result["error"]
    assert f"start it with {interpreter}" in result["error"]
    assert result["jobs"] is False
