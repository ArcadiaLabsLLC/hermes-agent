"""The measured time limits on inherited real-gateway e2e files follow upstream's copy of each file.

``tests/_downstream/id_markers/fork_marks.py::_MEASURED_E2E_WALLS`` gives 99 upstream-owned test
files a ``pytest.mark.timeout`` of three times their measured slowest-test wall. Each row carries
the file's upstream blob the wall was measured against. Upstream owns these files, so a release
merge can bring a slower (or faster) version and the limit would silently describe a file that no
longer exists (owner 2026-11-21: "a don't forget to track upstream code").

The fork's record of which upstream version ``main`` holds is the upstream manifest's ``# base``
(``tests/fixtures/upstream_manifest.txt``), re-based by every release merge
(``scripts/upstream_footprint.py --refresh-manifest``, Merging upstream.md step 4a). This gate reds
when a row's recorded blob is not the file's blob at that base, or not the file in the tree (a fork
edit), and names the new blob. The fix is Merging upstream.md step 5e: re-measure the named files,
then write the new wall and blob on their rows. Never move a blob without re-measuring.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Callable

import pytest

from scripts.upstream_footprint import read_manifest
from tests._downstream.id_markers import fork_marks

pytestmark = pytest.mark.gate

_REPO = Path(__file__).resolve().parents[2]


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", "--no-optional-locks", "-C", str(_REPO), *args],
        capture_output=True, text=True, encoding="utf-8", check=False,
    ).stdout.strip()


def stale_rows(table: dict[str, tuple[int, str]], blob_of: Callable[[str], str], where: str) -> list[str]:
    """Rows whose recorded blob is not ``blob_of(path)``; one readable line each."""
    lines = []
    for path, (wall, recorded) in sorted(table.items()):
        actual = blob_of(path)
        if not actual:
            lines.append(f"{path}: absent at {where} (upstream deleted or renamed it) -- drop its row")
        elif not actual.startswith(recorded):
            lines.append(f"{path}: measured {wall} s against blob {recorded}, {where} has {actual[:12]} -- re-measure")
    return lines


def test_stale_rows_names_a_moved_and_a_missing_file():
    table = {"tests/a.py": (40, "aaaaaaaaaaaa"), "tests/b.py": (20, "bbbbbbbbbbbb"), "tests/c.py": (12, "cccccccccccc")}
    blobs = {"tests/a.py": "aaaaaaaaaaaa1111", "tests/b.py": "dddddddddddd2222"}
    assert stale_rows(table, lambda p: blobs.get(p, ""), "base X") == [
        "tests/b.py: measured 20 s against blob bbbbbbbbbbbb, base X has dddddddddddd -- re-measure",
        "tests/c.py: absent at base X (upstream deleted or renamed it) -- drop its row",
    ]


def test_every_measured_file_is_upstream_owned():
    _base, paths = read_manifest()
    fork_files = sorted(set(fork_marks._MEASURED_E2E_WALLS) - set(paths))
    assert not fork_files, f"rows for files not in the upstream manifest (fork files get no limit row): {fork_files}"


def test_every_limit_was_measured_on_the_upstream_copy_main_now_holds():
    base, _paths = read_manifest()
    assert base, "tests/fixtures/upstream_manifest.txt carries no '# base <sha>' header"
    assert _git("cat-file", "-t", base) == "commit", f"manifest base {base} is not in this clone (shallow?)"
    stale = stale_rows(fork_marks._MEASURED_E2E_WALLS, lambda p: _git("rev-parse", "-q", "--verify", f"{base}:{p}"),
                       f"upstream base {base}")
    assert not stale, (
        "upstream changed an e2e file whose time limit was measured on an older copy; re-measure each "
        "(Merging upstream.md step 5e) and write its new wall and blob in fork_marks._MEASURED_E2E_WALLS:\n"
        + "\n".join(stale)
    )


def test_every_limit_was_measured_on_the_file_in_the_tree():
    def tree_blob(path: str) -> str:
        return _git("hash-object", "--", path) if (_REPO / path).is_file() else ""

    stale = stale_rows(fork_marks._MEASURED_E2E_WALLS, tree_blob, "the tree")
    assert not stale, (
        "an e2e file whose time limit was measured on another copy changed in the tree; re-measure each "
        "(Merging upstream.md step 5e) and write its new wall and blob in fork_marks._MEASURED_E2E_WALLS:\n"
        + "\n".join(stale)
    )
