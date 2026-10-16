"""Fork scripts never hard-code one machine's paths (fork-hygiene row after 39dc323f491).

A NEGATIVE guarantee, so a source walk is the right tool: over-approximating
("any spelling of the owner's drive root or user home") is the safe direction.
Scope: the fork-owned Python under scripts/ and pm/ (files absent from the upstream
manifest). Comments in other trees that cite a measurement on this machine are not
in scope; code that ASSERTS a machine path is filed separately.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
MACHINE_PATH = re.compile(r"[A-Za-z]:[\/]+Eternia\b|[A-Za-z]:[\/]+Users[\/]+beast\b", re.IGNORECASE)


def _fork_scripts() -> list[str]:
    inherited = set((REPO / "tests" / "fixtures" / "upstream_manifest.txt").read_text(encoding="utf-8").splitlines())
    tracked = subprocess.run(["git", "-C", str(REPO), "ls-files", "scripts/*.py", "pm/*.py"],
                             capture_output=True, text=True, check=True).stdout.split()
    return [rel for rel in tracked if rel not in inherited]


def offenders(paths: list[str]) -> list[str]:
    return [f"{rel}:{n}" for rel in paths
            for n, line in enumerate((REPO / rel).read_text(encoding="utf-8").splitlines(), 1)
            if MACHINE_PATH.search(line)]


def test_no_fork_script_names_one_machines_paths():
    found = offenders(_fork_scripts())
    assert not found, f"resolve the root (HERMES_HOME / get_default_hermes_root) or write a placeholder: {found}"


def test_the_scan_sees_a_planted_path(tmp_path, monkeypatch):
    monkeypatch.setattr(__import__(__name__), "REPO", tmp_path)
    (tmp_path / "x.py").write_text('root = r"X:/Eternia/.hermes"\n', encoding="utf-8")
    assert offenders(["x.py"]) == ["x.py:1"]
