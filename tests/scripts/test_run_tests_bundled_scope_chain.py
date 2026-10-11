"""Fast-gate §5 — a change to the session chain reaches every inherited test file.

Plan: ``docs/agent-runtime-harness/planned/fast-gate-2026-10-10.md`` §5 (owner
ruling Q3: a plugin-chain edit reaches the whole tree). The old rule read only
``rel.endswith("/conftest.py")``: the fork's root ``conftest.py``, the conftest
plugin under ``tests/_downstream/`` and ``pyproject.toml`` reached no upstream
file although every test process loads them.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts import run_tests_bundled as bundled

scope = bundled.scope

_INHERITED = ["tests/pkg/test_up.py", "tests/other/deep/test_up2.py"]


def _tree(root: Path) -> list[Path]:
    files = []
    for rel in ["tests/pkg/test_fork.py", *_INHERITED]:
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text("def test_ok():\n    pass\n", encoding="utf-8")
        files.append(root / rel)
    return files


def _rels(root: Path, paths) -> list[str]:
    return sorted(p.resolve().relative_to(root.resolve()).as_posix() for p in paths)


@pytest.mark.parametrize(
    "changed",
    [
        "conftest.py",
        "tests/_downstream/conftest_plugin.py",
        "tests/_downstream/id_markers/upstream_reds_v0216.py",
        "tests/_fixtures/gateway_lock_dirs.py",
        "scripts/_bundle_plugin/hermes_bundle_report.py",
        "pyproject.toml",
        "requirements-fork-dev.txt",
    ],
)
def test_a_session_chain_change_reaches_every_inherited_file(tmp_path, changed):
    files = _tree(tmp_path)

    sel = bundled.select_scope(files, tmp_path, set(_INHERITED), {changed})

    assert _rels(tmp_path, sel.chain) == sorted(_INHERITED)
    assert _rels(tmp_path, sel.selected) == sorted(["tests/pkg/test_fork.py", *_INHERITED])
    assert sel.excluded == []


def test_a_doc_under_a_chain_prefix_reaches_nothing(tmp_path):
    files = _tree(tmp_path)

    sel = bundled.select_scope(files, tmp_path, set(_INHERITED), {"tests/_downstream/README.md"})

    assert sel.chain == [] and _rels(tmp_path, sel.excluded) == sorted(_INHERITED)


def test_a_nested_conftest_keeps_its_directory_rule_and_is_not_the_chain(tmp_path):
    files = _tree(tmp_path)

    sel = bundled.select_scope(files, tmp_path, set(_INHERITED), {"tests/other/conftest.py"})

    assert _rels(tmp_path, sel.conftest) == ["tests/other/deep/test_up2.py"]
    assert sel.chain == [] and _rels(tmp_path, sel.excluded) == ["tests/pkg/test_up.py"]


def test_the_skip_list_still_wins_over_the_chain(tmp_path):
    files = _tree(tmp_path)

    sel = bundled.select_scope(files, tmp_path, set(_INHERITED), {"conftest.py"}, skipped={"tests/pkg/test_up.py"})

    assert _rels(tmp_path, sel.skipped_red) == ["tests/pkg/test_up.py"]
    assert _rels(tmp_path, sel.chain) == ["tests/other/deep/test_up2.py"]


def test_the_printed_reason_names_the_chain_paths():
    assert scope.chain.chain_changed({"pkg/a.py", "pyproject.toml", "conftest.py", "tests/_downstream/x.md"}) == [
        "conftest.py",
        "pyproject.toml",
    ]


# ── --since-merge: a chain path whose fork hunk the merge left unchanged ────


def _merged_pyproject(repo: Path, *, after_edit: bool) -> str:
    """A fork with a pyproject hunk merges an upstream release that edits the
    file elsewhere; returns the merge sha."""

    from tests.scripts import test_run_tests_bundled_merge_scope as ms

    base = [f"key{i} = {i}" for i in range(1, 21)]
    repo.mkdir()
    ms._git(repo, "init", "-q", "-b", "main")
    ms._write(repo, "pyproject.toml", base)
    ms._write(repo, "tests/pkg/test_a.py", ["def test_a():", "    pass"])
    ms._commit(repo, "upstream v1")
    ms._git(repo, "branch", "upstream")
    ms._write(repo, "pyproject.toml", base[:10] + ["fork = true"] + base[10:])
    ms._commit(repo, "fork hunk")
    ms._git(repo, "checkout", "-q", "upstream")
    ms._write(repo, "pyproject.toml", ["key1 = 'v2'"] + base[1:])
    ms._commit(repo, "upstream v2")
    ms._git(repo, "checkout", "-q", "main")
    ms._git(repo, "merge", "-q", "--no-ff", "-m", "merge: upstream v2", "upstream")
    merge = ms._git(repo, "rev-parse", "HEAD")
    if after_edit:
        ms._write(repo, "pyproject.toml", (repo / "pyproject.toml").read_text(encoding="utf-8").splitlines() + ["later = 1"])
    return merge


def test_a_chain_path_whose_fork_hunk_the_merge_left_unchanged_does_not_reach(tmp_path):
    repo = tmp_path / "repo"
    merge = _merged_pyproject(repo, after_edit=False)

    change = scope.merge_change(repo, merge)

    assert change.standing == ["pyproject.toml"]
    sel = bundled.select_scope([repo / "tests/pkg/test_a.py"], repo, {"tests/pkg/test_a.py"}, change.paths)
    assert sel.chain == [] and len(sel.excluded) == 1


def test_a_chain_path_edited_after_the_merge_still_reaches(tmp_path):
    repo = tmp_path / "repo"
    merge = _merged_pyproject(repo, after_edit=True)

    change = scope.merge_change(repo, merge)

    assert change.standing == [] and "pyproject.toml" in change.paths
    sel = bundled.select_scope([repo / "tests/pkg/test_a.py"], repo, {"tests/pkg/test_a.py"}, change.paths)
    assert _rels(repo, sel.chain) == ["tests/pkg/test_a.py"]
