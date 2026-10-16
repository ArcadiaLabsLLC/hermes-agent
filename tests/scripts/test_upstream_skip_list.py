"""Stage 1 gate: the upstream skip list names upstream files only, and the runner skips exactly them.

Plan: ``docs/agent-runtime-harness/planned/suite-speed-2026-10-05.md`` §3 Stage 1.
``tests/fixtures/upstream_skip_list.txt`` keeps whole upstream test files out of
``scripts/run_tests_bundled.py`` runs (both scopes) unless the file is named.
A FORK file is never listed: fork reds are fixed, not skipped.

The positive guarantee is read off the runner itself: ``select_scope`` over the
real tree with the real list is BUILT, and its ``skipped_red`` bucket is read —
every listed file is in it, and no file outside the upstream manifest is.
Killing mutation (recorded in the landing commit): append the fork-owned
``tests/agent_runtime/test_config.py`` to the list → "fork files are fixed,
never skipped".
"""

from __future__ import annotations

import re
from pathlib import Path

from scripts import run_tests_bundled as bundled

_REPO_ROOT = Path(__file__).resolve().parents[2]
plan = bundled.plan
SKIP_LIST = _REPO_ROOT / plan.SKIP_LIST
MANIFEST = _REPO_ROOT / "tests" / "fixtures" / "upstream_manifest.txt"
_SHA = re.compile(r"^[0-9a-f]{10,40}$")
_P0 = {
    "tests/hermes_cli/test_source_check.py",
    "tests/hermes_cli/test_source_launcher_publication.py",
    "tests/hermes_cli/test_source_release_channels.py",
    "tests/hermes_cli/test_source_release_probe.py",
}


def _skipped_by_the_runner(list_path: Path) -> tuple[set[str], set[str]]:
    """(the files ``select_scope`` put in ``skipped_red``, the listed paths), over the real tree."""

    rows = plan.load_skip_list(list_path)
    files = bundled.rtp._discover_files([_REPO_ROOT / "tests"])
    sel = bundled.select_scope(files, _REPO_ROOT, bundled.load_manifest(MANIFEST), set(), skipped=rows)
    return {bundled._rel(p, _REPO_ROOT) for p in sel.skipped_red}, {rel for rel, row in rows.items() if not row.node}


def file_rows_naming_a_node(list_path: Path) -> list[str]:
    """File rows whose ``why`` names one of that file's own tests: those are node rows."""

    offenders = []
    for rel, row in plan.load_skip_list(list_path).items():
        if row.node:
            continue
        defined = set(re.findall(r"def (test_\w+)", (_REPO_ROOT / rel).read_text(encoding="utf-8")))
        if defined & set(re.findall(r"\btest_\w+", row.why)):
            offenders.append(rel)
    return offenders


def fork_files_skipped(list_path: Path) -> list[str]:
    skipped, _rows = _skipped_by_the_runner(list_path)
    return sorted(skipped - bundled.load_manifest(MANIFEST))


def test_no_fork_file_is_ever_skipped():
    offenders = fork_files_skipped(SKIP_LIST)
    assert not offenders, (
        "fork files are fixed, never skipped — these are on tests/fixtures/upstream_skip_list.txt but are "
        f"not upstream's (absent from the upstream manifest): {offenders}"
    )


def test_the_runner_skips_every_listed_file_and_nothing_else():
    skipped, listed = _skipped_by_the_runner(SKIP_LIST)
    assert skipped == listed, f"listed but run: {sorted(listed - skipped)}; skipped but unlisted: {sorted(skipped - listed)}"


def test_every_row_is_an_existing_upstream_file_with_a_class_and_a_sha():
    inherited = bundled.load_manifest(MANIFEST)
    for key, row in plan.load_skip_list(SKIP_LIST).items():
        rel = row.file
        assert (_REPO_ROOT / rel).is_file(), f"{rel}: listed but not in the tree — drop the row"
        if row.node:
            name = row.node.rsplit("::", 1)[-1].split("[", 1)[0]
            assert f"def {name}(" in (_REPO_ROOT / rel).read_text(encoding="utf-8"), f"{key}: no such test"
        assert rel in inherited, f"{rel}: not in the upstream manifest — a fork file is fixed, never listed"
        assert row.klass in plan.SKIP_CLASSES, f"{rel}: why must start with one of {plan.SKIP_CLASSES}: {row.why!r}"
        assert _SHA.match(row.sha), f"{rel}: the third field must be the upstream SHA it was recorded at: {row.sha!r}"


def test_the_p0_freeze_files_are_listed_as_p0():
    rows = plan.load_skip_list(SKIP_LIST)
    assert {rel for rel, row in rows.items() if row.klass == "P0"} >= _P0


def test_a_fork_path_on_a_copy_of_the_list_is_refused(tmp_path):
    """The killing mutation, kept as a control: the gate above is not vacuous."""

    planted = tmp_path / "upstream_skip_list.txt"
    planted.write_text(
        SKIP_LIST.read_text(encoding="utf-8")
        + "tests/agent_runtime/test_config.py · env: planted fork file · ee5f49b943\n",
        encoding="utf-8",
    )
    assert fork_files_skipped(planted) == ["tests/agent_runtime/test_config.py"]


def test_a_file_row_never_names_one_of_its_tests():
    offenders = file_rows_naming_a_node(SKIP_LIST)
    assert not offenders, f"cut these to `path::node` rows — the file runs, the one node is deselected: {offenders}"


def test_a_file_row_naming_a_node_on_a_copy_of_the_list_is_refused(tmp_path):
    """The control: a planted file row whose why names one of its tests is caught."""

    planted = tmp_path / "upstream_skip_list.txt"
    planted.write_text(
        SKIP_LIST.read_text(encoding="utf-8")
        + "tests/agent/test_skill_commands.py · upstream: test_scan_never_publishes_a_partially_built_map flakes"
        " · 71d34bad10\n",
        encoding="utf-8",
    )
    assert file_rows_naming_a_node(planted) == ["tests/agent/test_skill_commands.py"]


def test_a_node_row_runs_its_file_and_deselects_only_the_node():
    rows = plan.load_skip_list(SKIP_LIST)
    nodes = {key for key, row in rows.items() if row.node}
    assert nodes, "the list carries at least one node row"
    skipped, _listed = _skipped_by_the_runner(SKIP_LIST)
    assert not {rows[key].file for key in nodes} & skipped, "a node row's file must still run"
    args = plan.deselect_args(rows)
    assert args[1::2] == sorted(nodes, key=list(rows).index) and set(args[0::2]) == {"--deselect"}
    named = next(iter(nodes))
    assert named not in plan.deselect_args(rows, named={rows[named].file}), "a named file runs whole (O1)"
