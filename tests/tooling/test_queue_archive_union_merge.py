"""Two branches that each closed a queue row merge and rebase without a conflict on the archive file.

FH-QUEUE-ARCHIVE-APPENDS-MERGE-CLEAN. ``scripts/work_row.py close`` appends one line at the end of
``Harness_Brain/80 — Archive/Queues/<queue>-<month>.md``; two branches doing so both change the file's last
line, and git's default merge conflicts there (wave w1112b: two lanes each redid a close by hand).
``Harness_Brain/.gitattributes`` gives those files the union merge, which keeps both sides' lines.

KILLING MUTATION: delete the ``merge=union`` line from ``Harness_Brain/.gitattributes`` -> ``git merge`` and
``git rebase`` both stop on a conflict, red.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.gate

ROOT = Path(__file__).resolve().parents[2]
ATTRIBUTES = "Harness_Brain/.gitattributes"
ARCHIVE = "Harness_Brain/80 — Archive/Queues/q-2026-11.md"
HEAD = "---\ntype: queue-archive\nqueue: q.md\nmonth: 2026-11\n---\n\n- **`RT-0` — earlier** · DONE 2026-11-01 0000000\n"


def git(*args: str, cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-c", "core.quotePath=false", *args], cwd=cwd, capture_output=True, text=True,
                          encoding="utf-8", stdin=subprocess.DEVNULL, check=False)


@pytest.fixture
def two_closes(tmp_path: Path, monkeypatch) -> Path:
    """A scratch repository carrying this repo's attributes file, with branches ``a`` and ``b`` that each
    appended one closed row to the same archive month file."""

    for key in ("GIT_AUTHOR", "GIT_COMMITTER"):
        monkeypatch.setenv(f"{key}_NAME", "Lane")
        monkeypatch.setenv(f"{key}_EMAIL", "lane@test.invalid")
    repo = tmp_path / "repo"
    (repo / ARCHIVE).parent.mkdir(parents=True)
    assert git("init", "-q", "-b", "main", str(repo), cwd=tmp_path).returncode == 0
    (repo / ATTRIBUTES).write_bytes((ROOT / ATTRIBUTES).read_bytes())
    (repo / ARCHIVE).write_text(HEAD, encoding="utf-8", newline="\n")
    git("add", "-A", cwd=repo)
    assert git("commit", "-q", "-m", "seed", cwd=repo).returncode == 0
    for branch in ("a", "b"):
        assert git("checkout", "-q", "-b", branch, "main", cwd=repo).returncode == 0
        with (repo / ARCHIVE).open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(f"- **`RT-{branch.upper()}` — closed on {branch}** · DONE 2026-11-12 1111111\n")
        assert git("commit", "-q", "-am", f"close on {branch}", cwd=repo).returncode == 0
    return repo


def _rows(repo: Path) -> list[str]:
    text = (repo / ARCHIVE).read_text(encoding="utf-8")
    assert "<<<<<<<" not in text and ">>>>>>>" not in text
    return [line.split("`")[1] for line in text.split("\n") if line.startswith("- **`")]


def test_a_merge_of_two_closes_keeps_both_rows(two_closes):
    merged = git("merge", "-q", "--no-edit", "a", cwd=two_closes)
    assert merged.returncode == 0, merged.stdout + merged.stderr
    assert sorted(_rows(two_closes)) == ["RT-0", "RT-A", "RT-B"]


def test_a_rebase_over_another_lanes_close_keeps_both_rows(two_closes):
    rebased = git("rebase", "-q", "a", cwd=two_closes)
    assert rebased.returncode == 0, rebased.stdout + rebased.stderr
    assert _rows(two_closes) == ["RT-0", "RT-A", "RT-B"]


def test_only_the_archive_month_files_take_the_union_merge():
    """The live queues keep git's default merge: a row is one line edited in place, and union would keep both
    versions of an edited row."""

    def merge_of(path: str) -> str:
        return git("check-attr", "merge", "--", path, cwd=ROOT).stdout.strip().rsplit(": ", 1)[-1]

    assert merge_of("Harness_Brain/80 — Archive/Queues/runtime-queue-2026-11.md") == "union"
    assert merge_of("Harness_Brain/20 — Active Initiatives/runtime-queue.md") == "unspecified"
    assert merge_of("Harness_Brain/80 — Archive/notes.md") == "unspecified"
