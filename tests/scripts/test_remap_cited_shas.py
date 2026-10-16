"""A cited wave-branch SHA is rewritten to its landed equivalent; an unlanded one is reported HELD."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

from scripts import remap_cited_shas as remap


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True).stdout.strip()


def _commit(repo: Path, name: str, body: str, date: str = "") -> str:
    (repo / name).write_text(body, encoding="utf-8")
    _git(repo, "add", name)
    env = {**os.environ, "GIT_AUTHOR_DATE": date} if date else None
    subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", name],
                   capture_output=True, check=True, env=env)
    return _git(repo, "rev-parse", "HEAD")


def _repo(tmp_path: Path) -> tuple[Path, str, str, str]:
    repo = tmp_path / "r"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    base = _commit(repo, "a.txt", "a\n")
    _git(repo, "checkout", "-q", "-b", "wave")
    landed_on_branch = _commit(repo, "b.txt", "b\n", date="1700000000 +0000")
    held = _commit(repo, "c.txt", "c\n")
    _git(repo, "checkout", "-q", "main")
    _commit(repo, "d.txt", "d\n")  # main moved: the landing rebases, so the SHA changes
    _commit(repo, "b.txt", "b\n", date="1700000000 +0000")  # the rebase: same author, date, subject
    return repo, base, landed_on_branch, held


def test_a_rebased_citation_is_rewritten_and_an_unlanded_one_is_held(tmp_path):
    repo, base, branch_sha, held = _repo(tmp_path)
    landed = _git(repo, "rev-parse", "HEAD")
    assert landed != branch_sha
    text = f"- row closed in `{branch_sha[:11]}`; HELD `{held[:11]}`; base `{base[:11]}`\n"
    mapping = remap.plan(repo, "main", [text])
    assert mapping.remapped == {branch_sha[:11]: landed[:11]}
    assert list(mapping.held) == [held[:11]]
    out = remap.rewrite(text, mapping.remapped)
    assert landed[:11] in out and branch_sha[:11] not in out
    assert base[:11] in out and held[:11] in out  # a commit on main, and HELD work, are left as cited


def test_check_mode_reports_and_leaves_the_file(tmp_path, capsys):
    repo, _base, branch_sha, _held = _repo(tmp_path)
    queue = tmp_path / "queue.md"
    queue.write_text(f"closed in `{branch_sha[:11]}`\n", encoding="utf-8")
    assert remap.main(["--repo", str(repo), "--onto", "main", "--check", str(queue)]) == 1
    assert "REMAP" in capsys.readouterr().out
    assert branch_sha[:11] in queue.read_text(encoding="utf-8")
    assert remap.main(["--repo", str(repo), "--onto", "main", str(queue)]) == 0
    assert branch_sha[:11] not in queue.read_text(encoding="utf-8")
