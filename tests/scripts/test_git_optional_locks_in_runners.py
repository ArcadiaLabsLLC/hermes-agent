"""Every test process, and the bundled runner's own git, run with ``GIT_OPTIONAL_LOCKS=0`` (design sweep D3.16).

Plan: ``docs/agent-runtime-harness/planned/design-sweep-d3-2026-10-10.md`` § D3.16.
A gate run left a zero-byte ``index.lock`` in its worktree: git's opportunistic
index refresh takes the lock, and a process killed mid-refresh leaves it. The
fork's root ``conftest.py`` sets the variable for the whole session; the probe
runs one throwaway test in a pytest process whose environment does NOT carry it
(as under the runners' ``env -i``, which never forwards it) and reads what that
test saw. Through ``scripts/run_tests.sh`` itself the probe cost 257 s on the
operator's box (activation + byte-compiling the tree) for the same answer.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

from scripts import run_tests_bundled as bundled

_REPO_ROOT = Path(__file__).resolve().parents[2]


def test_a_test_process_without_the_variable_sees_git_optional_locks_off():
    # Under the checkout (so its root conftest loads), in a git-ignored directory
    # no discovery walks.
    probe_dir = _REPO_ROOT / ".pytest_cache" / f"git_optional_locks_probe_{uuid.uuid4().hex}"
    probe_dir.mkdir(parents=True)
    seen = probe_dir / "seen.txt"
    (probe_dir / "test_probe.py").write_text(
        "import os\nfrom pathlib import Path\n\n"
        "def test_probe():\n"
        f"    Path({str(seen)!r}).write_text(os.environ.get('GIT_OPTIONAL_LOCKS', '<unset>'), encoding='utf-8')\n",
        encoding="utf-8",
    )
    env = {k: v for k, v in os.environ.items() if k != "GIT_OPTIONAL_LOCKS"}
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", str(probe_dir / "test_probe.py")],
            cwd=_REPO_ROOT, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120,
        )
        got = seen.read_text(encoding="utf-8") if seen.exists() else "<the probe did not run>"
    finally:
        shutil.rmtree(probe_dir, ignore_errors=True)
    assert got == "0", proc.stdout[-3000:] + proc.stderr[-2000:]


def test_the_bundled_runners_own_git_runs_with_optional_locks_off(monkeypatch, tmp_path):
    seen: list[dict] = []

    def fake_run(argv, **kwargs):
        seen.append(kwargs.get("env") or {})
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    monkeypatch.delenv("GIT_OPTIONAL_LOCKS", raising=False)
    monkeypatch.setattr(subprocess, "run", fake_run)
    bundled.changed_paths(tmp_path, "origin/main")

    assert seen and all(env.get("GIT_OPTIONAL_LOCKS") == "0" for env in seen)
