"""Fast-gate §5 — a change to the session chain runs the chain's contract plus a sample.

Plan: ``docs/agent-runtime-harness/planned/fast-gate-2026-10-10.md`` §5. Every
test process loads the chain (the fork's root ``conftest.py``, the conftest
plugin under ``tests/_downstream/``, ``pyproject.toml``), so a chain edit is
proved by the chain's contract and one file per folder nothing else reached —
at an ordinary landing (owner ruling 2026-10-16) and at a release merge
(``--since-merge``) alike: ADR 0016, no whole-tree run, ever.
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
def test_a_session_chain_change_runs_a_sample_never_every_file(tmp_path, changed):
    files = _tree(tmp_path)

    sel = bundled.select_scope(files, tmp_path, set(_INHERITED), {changed})

    assert _rels(tmp_path, sel.chain) == ["tests/other/deep/test_up2.py", "tests/pkg/test_fork.py"], (
        "one file per folder (the smallest, ties by path), not the whole tree")
    assert _rels(tmp_path, sel.excluded) == ["tests/pkg/test_up.py"]


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
    assert _rels(tmp_path, sel.chain) == ["tests/other/deep/test_up2.py", "tests/pkg/test_fork.py"]


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


def test_a_chain_path_edited_after_the_merge_runs_the_sample(tmp_path):
    repo = tmp_path / "repo"
    merge = _merged_pyproject(repo, after_edit=True)

    change = scope.merge_change(repo, merge)

    assert change.standing == [] and "pyproject.toml" in change.paths
    sel = bundled.select_scope([repo / "tests/pkg/test_a.py"], repo, {"tests/pkg/test_a.py"}, change.paths)
    assert _rels(repo, sel.chain) == ["tests/pkg/test_a.py"]


# ── an ordinary landing: the chain's contract plus a sample (owner ruling 2026-10-16) ──


def _sample_tree(root: Path) -> list[Path]:
    texts = {
        "tests/pkg/test_fork.py": "x\n",
        "tests/pkg/test_up.py": "x\n",
        "tests/other/deep/test_up2.py": "xxxxxxxx\n",
        "tests/other/deep/test_a_small.py": "x\n",
        "tests/third/test_reached.py": "import pkg.mod\n",
        "tests/third/test_sibling.py": "x\n",
        "tests/third/test_fork_unreached.py": "x\n",
        "tests/tooling/test_session_chain_contract.py": "x\n",
    }
    for rel, text in texts.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text, encoding="utf-8")
    return [root / rel for rel in texts]


_SAMPLE_INHERITED = {
    "tests/pkg/test_up.py", "tests/other/deep/test_up2.py", "tests/other/deep/test_a_small.py",
    "tests/third/test_reached.py", "tests/third/test_sibling.py",
}


@pytest.mark.parametrize("changed", ["conftest.py", "tests/conftest.py", "tests/_downstream/conftest_plugin.py"])
def test_an_ordinary_landing_runs_the_contract_and_one_sample_per_empty_folder(tmp_path, changed):
    files = _sample_tree(tmp_path)

    sel = bundled.select_scope(files, tmp_path, _SAMPLE_INHERITED, {changed, "pkg/mod.py"})

    assert _rels(tmp_path, sel.chain) == ["tests/other/deep/test_a_small.py", "tests/pkg/test_fork.py"], (
        "the smallest of every empty folder, fork files included")
    assert _rels(tmp_path, sel.importer) == ["tests/third/test_reached.py"]
    assert _rels(tmp_path, sel.fork_only) == ["tests/tooling/test_session_chain_contract.py"], "never every fork file"
    assert _rels(tmp_path, sel.excluded) == ["tests/other/deep/test_up2.py", "tests/pkg/test_up.py",
                                             "tests/third/test_fork_unreached.py", "tests/third/test_sibling.py"]


def test_without_a_chain_change_nothing_is_sampled(tmp_path):
    files = _sample_tree(tmp_path)

    sel = bundled.select_scope(files, tmp_path, _SAMPLE_INHERITED, {"pkg/mod.py"})

    assert sel.chain == [] and len(sel.excluded) == 4
    assert len(sel.fork_only) == 3, "no chain edit: every fork-owned file runs, as --scope fork always did"


def test_the_skip_list_wins_over_the_sample(tmp_path):
    files = _sample_tree(tmp_path)

    sel = bundled.select_scope(files, tmp_path, _SAMPLE_INHERITED, {"conftest.py"},
                               skipped={"tests/other/deep/test_a_small.py"})

    assert _rels(tmp_path, sel.chain) == ["tests/other/deep/test_up2.py", "tests/pkg/test_fork.py",
                                          "tests/third/test_fork_unreached.py"]


# ── ADR 0016: --scope full and --since-merge never run the whole tree ──


def _args(**kw):
    import argparse

    base = dict(scope=bundled.SCOPE_FORK, since=None, since_merge=None, manifest=None)
    return argparse.Namespace(**{**base, **kw})


def test_scope_full_over_a_directory_refuses_with_the_adr_pointer(tmp_path, capsys):
    files = _tree(tmp_path)

    sel = scope.select_for_run(_args(scope=bundled.SCOPE_FULL), files, tmp_path, [tmp_path / "tests"], {})

    assert sel is None, "main exits 2 on None"
    assert "0016 — No whole-tree run, ever" in capsys.readouterr().err


def test_scope_full_over_named_files_runs_exactly_those_files(tmp_path, capsys):
    _tree(tmp_path)
    named = [tmp_path / "tests/pkg/test_up.py", tmp_path / "tests/pkg/test_fork.py"]

    sel = scope.select_for_run(_args(scope=bundled.SCOPE_FULL), named, tmp_path, named, {})

    assert _rels(tmp_path, sel.selected) == ["tests/pkg/test_fork.py", "tests/pkg/test_up.py"]
    assert capsys.readouterr().err == ""


def test_since_merge_treats_a_chain_path_as_contract_plus_sample(tmp_path, capsys):
    repo = tmp_path / "repo"
    merge = _merged_pyproject(repo, after_edit=True)
    for rel in ("tests/pkg/test_b.py", "tests/tooling/test_session_chain_contract.py", "tests/tooling/test_other.py"):
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_text("x = 1\n" * (40 if rel.endswith("test_b.py") else 1), encoding="utf-8")
    manifest = tmp_path / "manifest.txt"
    manifest.write_text("tests/pkg/test_a.py\ntests/pkg/test_b.py\n", encoding="utf-8")
    files = sorted((repo / "tests").rglob("test_*.py"))

    sel = scope.select_for_run(_args(since_merge=merge, manifest=manifest), files, repo, [repo / "tests"], {})

    assert _rels(repo, sel.fork_only) == ["tests/tooling/test_session_chain_contract.py"], "never every fork file"
    assert _rels(repo, sel.chain) == ["tests/pkg/test_a.py"], "one sample for the folder nothing else reached"
    assert _rels(repo, sel.excluded) == ["tests/pkg/test_b.py", "tests/tooling/test_other.py"]
    assert "contract + sample" in capsys.readouterr().out


def test_scope_features_runs_every_file_but_the_skip_list_and_full_still_refuses(tmp_path, capsys):
    files = _tree(tmp_path)
    import types

    skip = {"tests/pkg/test_up.py": types.SimpleNamespace(why="upstream red")}

    sel = scope.select_for_run(_args(scope=scope.SCOPE_FEATURES), files, tmp_path, [tmp_path / "tests"], skip)

    assert _rels(tmp_path, sel.selected) == ["tests/other/deep/test_up2.py", "tests/pkg/test_fork.py"], (
        "every fork and upstream file, no reach rule, the skip list still out")
    assert _rels(tmp_path, sel.skipped_red) == ["tests/pkg/test_up.py"]
    assert "never a gate" in capsys.readouterr().out
    assert scope.select_for_run(_args(scope=bundled.SCOPE_FULL), files, tmp_path, [tmp_path / "tests"], {}) is None
