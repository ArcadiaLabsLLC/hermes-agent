"""Two members publish at once: the phone's git settles it exactly as the git program does (plan
phone-realm-sync-dulwich-2026-11-16 S5, §4.1).

Each scenario builds ONE starting state — a bare remote, a member who committed, a teammate who pushed
first — copies the member's clone twice, and runs ``merge_remote_theirs`` on each copy: the git program's
``git pull --no-rebase --no-edit -X theirs`` (``git_binary.BinarySyncGit``) and the stdlib diff3 merge
(``git_dulwich.DulwichSyncGit`` over ``merge_theirs.FavouringMerger``). Equal result trees by id, or
equal conflict sets — a file/directory clash by path prefix, never by git's ``p~HEAD`` spelling.

Killing mutation (recorded in the S5 commit): take theirs WHOLE in ``merge_theirs.merge_lines`` (return
``theirs``) -> "far hunks" and "overlap plus a far hunk of ours" red.
"""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

from agent_runtime.realm_sync.git_binary import BinarySyncGit
from agent_runtime.realm_sync.git_dulwich import DulwichSyncGit

_LINES = "".join(f"line {n}\n" for n in range(1, 21))


def _sh(cwd: Path, *args: str) -> str:
    proc = subprocess.run(["git", "-c", "user.name=Mate", "-c", "user.email=mate@example.invalid",
                           "-c", "init.defaultBranch=main", *args], cwd=cwd, capture_output=True, text=True, check=True)
    return proc.stdout.strip()


def _write(root: Path, files: dict[str, str | None]) -> None:
    for rel, text in files.items():
        path = root / rel
        if text is None:
            if path.is_dir():
                shutil.rmtree(path)
            elif path.exists():
                path.unlink()
            continue
        if path.is_file() and text.endswith("/"):
            path.unlink()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


def _edit(line: int, text: str) -> str:
    lines = _LINES.splitlines(keepends=True)
    lines[line - 1] = text + "\n"
    return "".join(lines)


def _edits(**changes: str) -> str:
    lines = _LINES.splitlines(keepends=True)
    for key, text in changes.items():
        lines[int(key[1:]) - 1] = text + "\n"
    return "".join(lines)


# name -> (base files, the teammate's change, the member's change)
_SCENARIOS: dict[str, tuple[dict[str, str | None], dict[str, str | None], dict[str, str | None]]] = {
    "disjoint files": ({"r/a.txt": _LINES}, {"r/b.txt": "b\n"}, {"r/c.txt": "c\n"}),
    "same line, both sides": ({"r/a.txt": _LINES}, {"r/a.txt": _edit(5, "THEIRS")}, {"r/a.txt": _edit(5, "OURS")}),
    "far hunks, one file": ({"r/a.txt": _LINES}, {"r/a.txt": _edit(2, "THEIRS")}, {"r/a.txt": _edit(18, "OURS")}),
    "overlap plus a far hunk of ours": ({"r/a.txt": _LINES}, {"r/a.txt": _edit(5, "THEIRS")},
                                        {"r/a.txt": _edits(l5="OURS", l17="OURS FAR")}),
    "manifest.json both rewrite": ({"r/manifest.json": '{\n  "generated_at": "1",\n  "n": 1\n}\n'},
                                   {"r/manifest.json": '{\n  "generated_at": "3",\n  "n": 3\n}\n'},
                                   {"r/manifest.json": '{\n  "generated_at": "2",\n  "n": 2\n}\n'}),
    "add/add, different bytes": ({"r/a.txt": _LINES}, {"r/new.txt": "theirs\nshared\n"}, {"r/new.txt": "ours\nshared\n"}),
    "modify/delete": ({"r/a.txt": _LINES, "r/keep.txt": "k\n"}, {"r/a.txt": None}, {"r/a.txt": _edit(3, "OURS")}),
    "delete/modify": ({"r/a.txt": _LINES, "r/keep.txt": "k\n"}, {"r/a.txt": _edit(3, "THEIRS")}, {"r/a.txt": None}),
    "both delete": ({"r/a.txt": _LINES, "r/keep.txt": "k\n"}, {"r/a.txt": None, "r/t.txt": "t\n"},
                    {"r/a.txt": None, "r/o.txt": "o\n"}),
    "file vs directory": ({"r/a.txt": _LINES}, {"r/p": "a file\n"}, {"r/p/inside.txt": "a directory\n"}),
}


def _start(tmp_path: Path, base: dict, theirs: dict, ours: dict) -> Path:
    bare = tmp_path / "remote.git"
    _sh(tmp_path, "init", "-q", "--bare", str(bare))
    seed = tmp_path / "seed"
    _sh(tmp_path, "clone", "-q", str(bare), str(seed))
    _write(seed, base)
    _sh(seed, "add", "-A")
    _sh(seed, "commit", "-q", "-m", "base")
    _sh(seed, "push", "-q", "origin", "HEAD:main")
    member = tmp_path / "member"
    _sh(tmp_path, "clone", "-q", str(bare), str(member))
    _write(seed, theirs)
    _sh(seed, "add", "-A")
    _sh(seed, "commit", "-q", "-m", "teammate")
    _sh(seed, "push", "-q", "origin", "HEAD:main")
    _write(member, ours)
    _sh(member, "add", "-A")
    _sh(member, "commit", "-q", "-m", "member")
    return member


def _settle(member: Path, copy: Path, backend: Callable[[Path], object]) -> tuple[str | None, frozenset[str]]:
    shutil.copytree(member, copy, symlinks=True)
    outcome = backend(copy).merge_remote_theirs(None)  # type: ignore[attr-defined]
    if outcome.conflicts:
        return None, frozenset(path.split("~", 1)[0] for path in outcome.conflicts)
    return _sh(copy, "rev-parse", "HEAD^{tree}"), frozenset()


@pytest.mark.parametrize("name", list(_SCENARIOS))
def test_the_phone_settles_a_race_as_the_git_program_does(tmp_path, name):
    base, theirs, ours = _SCENARIOS[name]
    member = _start(tmp_path, base, theirs, ours)
    want = _settle(member, tmp_path / "binary", BinarySyncGit)
    got = _settle(member, tmp_path / "dulwich", DulwichSyncGit)
    assert got == want
    expect_conflict = name in {"modify/delete", "delete/modify", "file vs directory"}
    assert bool(want[1]) is expect_conflict  # positive control: the scenario is the case it names


def test_a_settled_race_is_a_two_parent_commit_on_the_phone(tmp_path):
    base, theirs, ours = _SCENARIOS["far hunks, one file"]
    member = _start(tmp_path, base, theirs, ours)
    head = _sh(member, "rev-parse", "HEAD")
    _sh(member, "fetch", "-q")
    upstream = _sh(member, "rev-parse", "origin/main")
    assert DulwichSyncGit(member).merge_remote_theirs(None).conflicts == ()
    assert _sh(member, "rev-list", "--parents", "-n1", "HEAD").split()[1:] == [head, upstream]
    assert _sh(member, "log", "-1", "--format=%an") == "Hermes Realm Sync"
    assert _sh(member, "status", "--porcelain") == ""


def test_the_gpl_only_merge3_is_not_installed_here():
    """dulwich's own merger needs ``merge3`` (GPL-2.0-or-later only, never shippable): an environment that
    grows it would let a call to it pass unseen, so this one must not have it."""

    assert importlib.util.find_spec("merge3") is None
