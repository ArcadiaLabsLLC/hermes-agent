"""An unbundled-list line never lands in the commit that adds its test file.

``scripts/test_bundles_unbundled.txt`` takes a file only on an OBSERVED isolation leak; a
file written and listed in one change skipped the bisect (two 2026-10-15 entries from
``c360f7ae60d`` waited a wave for theirs). ``git blame`` names the commit that wrote each
line; that commit must not be the one that added the file. A line not yet committed is
judged against ``HEAD``: its file must already exist there.

Killing mutation: list a file in the same commit that adds it (or, uncommitted, list a
file ``HEAD`` does not have) -> ``test_no_unbundled_line_lands_with_its_file`` reds.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
LIST = "scripts/test_bundles_unbundled.txt"
_UNCOMMITTED = "0" * 40


def _git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(REPO), *args], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=120, check=False)


def _blamed_entries() -> list[tuple[str, str]]:
    """``(commit, path)`` for every entry line of the list."""
    porcelain = _git("blame", "--line-porcelain", "--", LIST)
    if porcelain.returncode != 0:
        pytest.skip(f"git blame unavailable: {porcelain.stderr.strip()[:200]}")
    entries, commit = [], None
    for line in porcelain.stdout.splitlines():
        if line[:40].strip("0123456789abcdef") == "" and len(line.split(" ")[0]) == 40:
            commit = line.split(" ")[0]
        elif line.startswith("\t"):
            path = line[1:].split("#", 1)[0].strip()
            if path:
                entries.append((commit, path))
    return entries


def _added_in(commit: str) -> set[str]:
    shown = _git("show", "--diff-filter=A", "--name-only", "--format=", commit)
    return {p.strip() for p in shown.stdout.splitlines() if p.strip()}


def test_no_unbundled_line_lands_with_its_file():
    if _git("rev-parse", "--is-shallow-repository").stdout.strip() == "true":
        pytest.skip("shallow clone: the commit that added a file may be absent")
    added: dict[str, set[str]] = {}
    offenders = []
    for commit, path in _blamed_entries():
        if commit == _UNCOMMITTED:
            if _git("cat-file", "-e", f"HEAD:{path}").returncode != 0:
                offenders.append(f"{path} (uncommitted line, file not in HEAD)")
            continue
        if path in added.setdefault(commit, _added_in(commit)):
            offenders.append(f"{path} (added and listed in {commit[:11]})")
    assert not offenders, "listed in the change that wrote the file, before any bisect: " + "; ".join(offenders)
