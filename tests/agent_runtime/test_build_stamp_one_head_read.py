"""RT-FU-A-COLD-HARNESS-SERVE-REGISTERS-SECONDS-SOONER: the boot's build stamp reads HEAD once.

``status`` and ``ls-tree`` both read HEAD's tree objects, and on a clone with thousands of packs
every object-reading git costs ~2 s just to open them. The stamp now reads the code tree from the
INDEX (``ls-files``, no object reads) whenever the status proves the index is HEAD, and asks HEAD
(``ls-tree``) only when it is not. The digest must be the one ``ls-tree`` gives, in every arm.
These drive real git in a throwaway repo.
"""

from __future__ import annotations

import subprocess
from types import SimpleNamespace

import pytest

from agent_runtime import build_identity
from agent_runtime import build_stamp as build_stamp_module
from agent_runtime.build_identity import code_tree_for, code_tree_from_index, parse_ls_files_stage_z
from agent_runtime.build_stamp import (
    _index_is_head,
    build_stamp,
    prefetch_build_stamp,
    reset_build_stamp_cache,
)


@pytest.fixture(autouse=True)
def _fresh_stamp():
    reset_build_stamp_cache()
    yield
    reset_build_stamp_cache()


def _git(root, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=str(root), capture_output=True, text=True, timeout=30, check=True
    ).stdout


@pytest.fixture
def repo(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "stamp@test")
    _git(root, "config", "user.name", "stamp")
    _git(root, "config", "core.autocrlf", "false")
    (root / "agent_runtime").mkdir()
    (root / "agent_runtime" / "a.py").write_bytes(b"one\n")
    (root / "b.py").write_bytes(b"two\n")
    (root / "docs").mkdir()
    (root / "docs" / "note.md").write_bytes(b"prose\n")
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "one")
    monkeypatch.setattr(build_stamp_module, "repo_root_for", lambda *a, **k: root)
    monkeypatch.setattr(build_stamp_module, "checkout_bound_enabled", lambda: True)
    return root


def _count_ls_tree(monkeypatch) -> list:
    calls: list = []
    real = build_stamp_module.code_tree_for

    def counted(root, *a, **k):
        calls.append(root)
        return real(root, *a, **k)

    monkeypatch.setattr(build_stamp_module, "code_tree_for", counted)
    return calls


def test_the_index_digest_of_a_clean_checkout_is_heads_digest(repo):
    from_index = code_tree_from_index(repo)

    assert from_index is not None
    assert from_index == code_tree_for(repo)


def test_a_clean_checkout_never_reads_head_for_its_code_tree(repo, monkeypatch):
    calls = _count_ls_tree(monkeypatch)

    stamp = build_stamp(refresh=True)

    assert calls == []
    assert stamp.dirty is False
    assert stamp.code_tree == code_tree_for(repo).code_tree


def test_an_unstaged_edit_is_dirty_and_still_reads_the_code_tree_from_the_index(repo, monkeypatch):
    # The first porcelain line is " M agent_runtime/a.py": its leading space is the
    # proof the index is HEAD, so the probe's output must keep its columns.
    (repo / "agent_runtime" / "a.py").write_bytes(b"edited\n")
    calls = _count_ls_tree(monkeypatch)

    stamp = build_stamp(refresh=True)

    assert calls == []
    assert stamp.dirty is True
    assert stamp.code_tree == code_tree_for(repo).code_tree


def test_a_staged_edit_reads_head_so_the_digest_stays_heads(repo, monkeypatch):
    (repo / "b.py").write_bytes(b"staged\n")
    _git(repo, "add", "b.py")
    calls = _count_ls_tree(monkeypatch)

    stamp = build_stamp(refresh=True)

    assert calls == [repo]
    assert stamp.dirty is True
    assert stamp.code_tree == code_tree_for(repo).code_tree
    assert stamp.code_tree != code_tree_from_index(repo).code_tree


def test_an_intent_to_add_entry_reads_head(repo, monkeypatch):
    (repo / "new.py").write_bytes(b"new\n")
    _git(repo, "add", "-N", "new.py")
    calls = _count_ls_tree(monkeypatch)

    stamp = build_stamp(refresh=True)

    assert calls == [repo]
    assert stamp.code_tree == code_tree_for(repo).code_tree


@pytest.mark.parametrize(
    ("porcelain", "is_head"),
    [
        ("", True),
        (" M a.py\n D b.py\n", True),
        ("M  a.py\n", False),
        ("R  a.py -> c.py\n", False),
        ("UU a.py\n", False),
        (" A new.py\n", False),
    ],
)
def test_only_a_status_with_no_index_side_change_proves_the_index_is_head(porcelain, is_head):
    assert _index_is_head(porcelain) is is_head


def test_an_index_with_a_conflict_stage_or_sparse_directory_cannot_stand_for_head():
    blob = "e69de29bb2d1d6434b8b29ae775ad8c2e48c5391"
    assert parse_ls_files_stage_z(f"100644 {blob} 0\ta.py\0") == [("a.py", blob)]
    assert parse_ls_files_stage_z(f"100644 {blob} 2\ta.py\0") is None
    assert parse_ls_files_stage_z(f"040000 {blob} 0\tsparse/\0") is None


def test_the_status_probe_has_the_code_trees_bound_not_the_two_second_one(repo, monkeypatch):
    seen: list = []
    real = build_identity.run_git

    def recording(args, **kwargs):
        seen.append((tuple(args), kwargs.get("timeout")))
        return real(args, **kwargs)

    monkeypatch.setattr(build_stamp_module, "run_git", recording)

    build_stamp(refresh=True)

    status_timeouts = [t for a, t in seen if "status" in a]
    assert status_timeouts == [build_identity.CODE_TREE_TIMEOUT_SECONDS]


def test_a_second_prefetch_while_one_is_in_flight_starts_nothing(monkeypatch):
    import threading

    gate = threading.Event()
    monkeypatch.setattr(build_stamp_module, "_resolve", lambda: (gate.wait(10), SimpleNamespace())[1])

    first = prefetch_build_stamp()
    second = prefetch_build_stamp()
    gate.set()
    assert first is not None
    first.join(10)

    assert second is None
