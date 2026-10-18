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

An ``unused`` row (a feature the fork does not ship, ADR 0015) may keep any
upstream file out, and must cite "ADR 0015"; a fork file is refused under
``unused`` exactly as under every other class.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

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
    """(the files ``select_scope`` put in ``skipped_red``, the listed paths discovery offers), over the real tree.

    A listed file under one of discovery's ``_SKIP_PARTS`` folders (``tests/docker``) never reaches
    ``select_scope``: it is not run either way, so it is not expected in ``skipped_red``.
    """

    rows = plan.load_skip_list(list_path)
    files = bundled.rtp._discover_files([_REPO_ROOT / "tests"])
    sel = bundled.select_scope(files, _REPO_ROOT, bundled.load_manifest(MANIFEST), set(), skipped=rows)
    offered = {bundled._rel(p, _REPO_ROOT) for p in files}
    return {bundled._rel(p, _REPO_ROOT) for p in sel.skipped_red}, {rel for rel, row in rows.items() if not row.node and rel in offered}


def listed_files_discovery_drops_outside_its_skip_parts(list_path: Path) -> list[str]:
    """Listed files discovery never offers that are NOT under a ``_SKIP_PARTS`` folder: a hole in the gate."""

    offered = {bundled._rel(p, _REPO_ROOT) for p in bundled.rtp._discover_files([_REPO_ROOT / "tests"])}
    return sorted(
        rel
        for rel, row in plan.load_skip_list(list_path).items()
        if not row.node and rel not in offered and not set(Path(rel).parts) & bundled.rtp._SKIP_PARTS
    )


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


def unused_rows_without_the_adr(list_path: Path) -> list[str]:
    """``unused`` rows whose ``why`` does not cite the ruling that made the feature unused."""

    return [key for key, row in plan.load_skip_list(list_path).items() if row.klass == "unused" and "ADR 0015" not in row.why]


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


def test_a_listed_file_discovery_never_offers_sits_under_a_skip_part():
    offenders = listed_files_discovery_drops_outside_its_skip_parts(SKIP_LIST)
    assert not offenders, f"listed, never discovered, and not under {sorted(bundled.rtp._SKIP_PARTS)}: {offenders}"


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


def test_every_unused_row_cites_adr_0015():
    offenders = unused_rows_without_the_adr(SKIP_LIST)
    assert not offenders, f"an `unused` row cites the ruling: add \"(ADR 0015)\" to its why: {offenders}"


def test_an_unused_row_without_the_adr_on_a_copy_of_the_list_is_refused(tmp_path):
    """The control: a planted `unused` row with no ADR citation is caught."""

    planted = tmp_path / "upstream_skip_list.txt"
    planted.write_text(
        SKIP_LIST.read_text(encoding="utf-8") + "tests/hermes_cli/test_kanban_cli.py · unused: kanban · e6899c8090\n",
        encoding="utf-8",
    )
    assert unused_rows_without_the_adr(planted) == ["tests/hermes_cli/test_kanban_cli.py"]


def test_a_fork_file_marked_unused_on_a_copy_of_the_list_is_refused(tmp_path):
    """`unused` widens the file-row rule for upstream files only: a fork file stays refused."""

    planted = tmp_path / "upstream_skip_list.txt"
    planted.write_text(
        SKIP_LIST.read_text(encoding="utf-8")
        + "tests/agent_runtime/test_config.py · unused: planted fork file (ADR 0015) · e6899c8090\n",
        encoding="utf-8",
    )
    assert fork_files_skipped(planted) == ["tests/agent_runtime/test_config.py"]
    assert "unused" in plan.SKIP_CLASSES


_UNUSED_FILE = "tests/hermes_cli/test_kanban_cli.py"  # imports hermes_cli.kanban_db; tests/hermes_cli/conftest.py above it
_REACHES_IT = {
    "an edit to a source module it imports": {"hermes_cli/kanban_db.py"},
    "an edit to its conftest": {"tests/hermes_cli/conftest.py"},
}


def _select(rows, changed, *, since_merge, named=()):
    files = bundled.rtp._discover_files([_REPO_ROOT / "tests" / "hermes_cli"])
    sel = bundled.select_scope(
        files, _REPO_ROOT, bundled.load_manifest(MANIFEST), changed, named=named, skipped=rows,
    )  # since ADR 0016 --scope fork and --since-merge select alike; both ids stay so either reach is pinned
    return {bundled._rel(p, _REPO_ROOT) for p in sel.selected}, {bundled._rel(p, _REPO_ROOT) for p in sel.skipped_red}


@pytest.mark.parametrize("since_merge", [False, True], ids=["scope-fork", "since-merge"])
@pytest.mark.parametrize("reach", sorted(_REACHES_IT))
def test_a_change_that_reaches_an_unused_file_does_not_select_it(reach, since_merge, tmp_path):
    """Landings never include an unused feature (owner, ADR 0015): skip wins over reach; naming the file runs it."""

    planted = tmp_path / "upstream_skip_list.txt"
    planted.write_text(
        SKIP_LIST.read_text(encoding="utf-8") + f"{_UNUSED_FILE} · unused: kanban (ADR 0015) · e6899c8090\n",
        encoding="utf-8",
    )
    rows = plan.load_skip_list(planted)
    assert rows[_UNUSED_FILE].klass == "unused"
    changed = _REACHES_IT[reach]
    unlisted = {key: row for key, row in rows.items() if key != _UNUSED_FILE}
    assert _UNUSED_FILE in _select(unlisted, changed, since_merge=since_merge)[0], f"control: {reach} reaches the file"
    selected, skipped = _select(rows, changed, since_merge=since_merge)
    assert _UNUSED_FILE not in selected and _UNUSED_FILE in skipped, f"{reach} selected an unused file"
    named, _ = _select(rows, changed, since_merge=since_merge, named=[_REPO_ROOT / _UNUSED_FILE])
    assert _UNUSED_FILE in named, "a named unused file runs"
