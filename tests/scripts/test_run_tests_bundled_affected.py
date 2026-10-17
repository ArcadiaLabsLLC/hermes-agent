"""``--affected <base>``: the landing gate selects only what the change can reach.

Owner ruling 2026-10-16: the whole tree runs only at a release merge; every other
landing runs ``scripts/run_tests_bundled.sh --affected origin/main``.
``scripts/run_tests_bundled_affected.py`` owns the selection; each reason has a
negative beside its positive.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts import run_tests_bundled as bundled

affected = bundled.affected
Reason = affected.Reason

_TREE = {
    "pkg/__init__.py": "",
    "pkg/a.py": "VALUE = 1\n",
    "pkg/b.py": "from pkg import a\n",
    "pkg/lonely.py": "X = 1\n",
    "tests/test_uses_b.py": "import pkg.b\n\ndef test_b():\n    pass\n",
    "tests/test_unrelated.py": "def test_u():\n    pass\n",
    "tests/test_reads_data.py": "def test_r():\n    pass\n",
    "tests/sub/conftest.py": "",
    "tests/sub/test_small.py": "def test_s(): pass\n",
    "tests/sub/test_bigger_file.py": "def test_big():\n    assert 1 + 1 == 2\n" * 5,
    "tests/sub/test_upstream_owned.py": "def test_up(): pass\n",
    "tests/_downstream/helper.py": "def helper():\n    return 1\n",
    "tests/test_imports_helper.py": "from tests._downstream import helper\n",
    "tests/test_gate.py": "def test_g(): pass\n",
}


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "repo"
    for rel, text in _TREE.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text, encoding="utf-8", newline="\n")
    return root


def _select(repo: Path, changed, *, records=None, gates=None, skipped=(), named=(), pool=None, graph=None):
    files = sorted(p for p in (repo / "tests").rglob("test_*.py"))
    return affected.select_affected(
        files, repo, changed, base="BASE", records=records or {}, gates=gates or {},
        skipped=skipped, named=[repo / n for n in named], sample_pool=pool, graph=graph,
    )


def _reasons(sel) -> dict:
    return {rel: (pick.reason, pick.via) for rel, pick in sel.picks.items()}


def test_a_touched_test_file_is_selected_and_nothing_else(repo):
    assert _reasons(_select(repo, ["tests/test_unrelated.py"])) == {
        "tests/test_unrelated.py": (Reason.TOUCHED, "tests/test_unrelated.py"),
    }


def test_a_module_selects_its_transitive_importers_only(repo):
    sel = _select(repo, ["pkg/a.py"])
    assert _reasons(sel) == {"tests/test_uses_b.py": (Reason.IMPORTER, "pkg/a.py")}
    assert _reasons(_select(repo, ["pkg/lonely.py"])) == {}, "positive control: a module nobody imports selects nothing"


def test_a_recorded_open_selects_the_file_that_read_it(repo):
    records = {"tests/test_reads_data.py": affected.Record(frozenset({"data/table.json"}), frozenset())}
    sel = _select(repo, ["data/table.json"], records=records)
    assert _reasons(sel) == {"tests/test_reads_data.py": (Reason.IMPORTER, "data/table.json")}
    assert sel.picks["tests/test_reads_data.py"].source == "record+ast"


def test_a_conftest_above_a_file_selects_it(repo):
    sel = _select(repo, ["tests/sub/conftest.py"])
    assert set(sel.picks) == {"tests/sub/test_small.py", "tests/sub/test_bigger_file.py", "tests/sub/test_upstream_owned.py"}


def test_a_declared_gate_is_selected_by_its_glob(repo):
    gates = {"tests/test_gate.py": ("pkg/*.py",)}
    assert _reasons(_select(repo, ["pkg/lonely.py"], gates=gates)) == {
        "tests/test_gate.py": (Reason.GATE, "pkg/lonely.py"),
    }
    assert _reasons(_select(repo, ["docs/x.md"], gates=gates)) == {}


def test_a_chain_change_samples_the_smallest_file_of_every_folder_in_the_pool(repo):
    pool = {"tests/test_unrelated.py", "tests/test_gate.py", "tests/sub/test_small.py", "tests/sub/test_bigger_file.py"}
    sel = _select(repo, ["tests/_downstream/helper.py"], pool=pool)
    samples = {rel for rel, pick in sel.picks.items() if pick.reason is Reason.SAMPLE}
    assert samples == {"tests/sub/test_small.py", "tests/test_gate.py"}
    assert "tests/sub/test_upstream_owned.py" not in sel.picks, "a file outside the pool is never a sample"
    assert sel.picks["tests/test_imports_helper.py"].reason is Reason.IMPORTER, "a static importer of the chain path"
    assert sel.chain_paths == ["tests/_downstream/helper.py"]


def test_a_chain_path_selects_through_the_files_own_opens_never_the_sessions(repo):
    chain = "tests/_downstream/helper.py"
    records = {
        "tests/test_unrelated.py": affected.Record(frozenset({chain}), frozenset()),
        "tests/test_reads_data.py": affected.Record(frozenset({chain}), frozenset({chain})),
    }
    sel = _select(repo, [chain], records=records, pool=set())
    assert "tests/test_unrelated.py" not in sel.picks
    assert sel.picks["tests/test_reads_data.py"].reason is Reason.IMPORTER


def test_the_runner_is_session_chain_and_a_doc_under_the_chain_is_not():
    assert affected.in_session_chain("scripts/run_tests_bundled_gate.py")
    assert affected.in_session_chain("scripts/_bundle_plugin/sitecustomize.py")
    assert affected.in_session_chain("tests/conftest.py")
    assert not affected.in_session_chain("tests/_downstream/README.md")
    assert not affected.in_session_chain("agent_runtime/serve.py")


def test_a_skip_listed_file_runs_only_when_named(repo):
    changed = ["tests/test_unrelated.py"]
    assert _select(repo, changed, skipped={"tests/test_unrelated.py"}).picks == {}
    sel = _select(repo, changed, skipped={"tests/test_unrelated.py"}, named=["tests/test_unrelated.py"])
    assert sel.picks["tests/test_unrelated.py"].reason is Reason.NAMED


def test_the_import_memo_parses_a_file_once_per_blob(repo):
    blobs = {"tests/test_uses_b.py": "b1", "pkg/b.py": "b2", "pkg/a.py": "b3", "pkg/__init__.py": "b4"}
    first = affected.ImportGraph(repo, lambda rel: blobs.get(rel, "z" + rel))
    before = _reasons(_select(repo, ["pkg/a.py"], graph=first))
    assert first.fresh, "the first walk parses"
    second = affected.ImportGraph(repo, lambda rel: blobs.get(rel, "z" + rel), dict(first.memo))
    assert _reasons(_select(repo, ["pkg/a.py"], graph=second)) == before
    assert second.fresh == {}, "nothing changed: nothing is parsed again"
    blobs["pkg/b.py"] = "b2-edited"
    third = affected.ImportGraph(repo, lambda rel: blobs.get(rel, "z" + rel), dict(first.memo))
    _select(repo, ["pkg/a.py"], graph=third)
    assert list(third.fresh) == ["b2-edited\tpkg"], "a changed blob is parsed again"


def test_the_memo_round_trips_through_the_store(tmp_path):
    affected.save_import_memo(tmp_path, {"k1\tpkg": ["os", "pkg.a"]})
    (tmp_path / affected.ImportGraph.MEMO).open("a", encoding="utf-8").write('{"k": "torn')
    assert affected.load_import_memo(tmp_path) == {"k1\tpkg": ["os", "pkg.a"]}


def test_the_gate_list_parses_and_every_declared_gate_exists():
    root = Path(bundled.__file__).resolve().parents[1]
    gates = affected.load_gate_paths(root / affected.GATE_PATHS_LIST)
    assert gates, "the shipped list declares the tooling gates"
    missing = [gate for gate in gates if not (root / gate).is_file()]
    assert missing == []


def test_the_runner_takes_affected_and_select_only_as_its_own_flags():
    ours, passthrough = bundled._split_argv(["--affected", "origin/main", "--select-only", "-q", "tests"])
    assert passthrough == ["-q"]
    assert ours == ["--affected", "origin/main", "--select-only", "tests"]


def test_the_selection_prints_its_count_and_a_reason_per_file(repo):
    lines = _select(repo, ["pkg/a.py"]).lines()
    assert lines[0].startswith("Affected since BASE (1 changed path(s)): 1 of ")
    assert lines[1] == "  importer (ast): tests/test_uses_b.py  <- pkg/a.py"
