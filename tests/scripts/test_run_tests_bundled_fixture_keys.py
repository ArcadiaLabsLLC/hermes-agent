"""Fixture-scoped keys: a fixture edit misses only the files that set that fixture up.

Row (fork-hygiene, 2026-10-15): a 29-line edit to ``tests/_downstream/conftest_plugin.py``
missed 6,309 of 6,563 cached greens as ``changed``, because every recorded module
keyed by its whole blob. ``scripts/run_tests_bundled_fixtures.py`` keys a fixture
module by its core plus the fixtures the file used, when the record names them.
Every negative below has its positive control beside it: the same edit, one
variable changed, and the key MUST move.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from scripts import run_tests_bundled as bundled

cache = bundled.cache
fixtures = bundled._fixtures
plan = bundled.plan
T = "tests/test_t.py"
CONF = "tests/conftest.py"

_CONFTEST = '''import pytest


def _helper():
    return 1


def pytest_collection_modifyitems(items):
    return None


@pytest.fixture
def used():
    return _helper()


@pytest.fixture(name="renamed")
def _renamed_impl():
    return 2


@pytest.fixture
def unused():
    return 3
'''


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


def _write(root: Path, rel: str, text: str) -> None:
    (root / rel).parent.mkdir(parents=True, exist_ok=True)
    (root / rel).write_text(text, encoding="utf-8", newline="\n")


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q")
    _write(root, T, "def test_ok(used, renamed):\n    pass\n")
    _write(root, CONF, _CONFTEST)
    _write(root, "pkg/mod.py", "VALUE = 1\n")
    _git(root, "add", "-A")
    _git(root, "-c", "user.name=fg", "-c", "user.email=fg@example.invalid", "commit", "-q", "-m", "seed")
    return root


def _key(root: Path, *, fx=("used", "renamed"), own=(), opaque=(), in_paths=False) -> str:
    snap = cache.TreeSnapshot.take(root, bundled.scope._scope_git)
    fixed = cache.FixedInputs.collect(snap, [], {}, interp=["interp\tpinned"])
    shapes = fixtures.Fingerprints(root, snap.blob, cache.git_blob_id)
    keyer = cache.Keyer(snap, fixed, {}, shapes)
    deps = cache.FileDeps(paths={T} | ({CONF} if in_paths else set()), mods={CONF, "pkg/mod.py"})
    if fx is not None:
        deps.merge_deps({"fx": list(fx), "own": list(own)}, ())
    for path in opaque:
        deps.merge_child({"paths": [path]})
    return keyer.key_fresh(T, deps)


def _edit(root: Path, old: str, new: str) -> None:
    text = (root / CONF).read_text(encoding="utf-8")
    assert old in text
    _write(root, CONF, text.replace(old, new))


@pytest.mark.parametrize("in_paths", [False, True], ids=["imported-from-pyc", "source-opened-at-import"])
def test_an_unused_fixture_edit_keeps_the_key_and_a_used_one_moves_it(repo, in_paths):
    before = _key(repo, in_paths=in_paths)
    _edit(repo, "    return 3\n", "    return 33\n")
    assert _key(repo, in_paths=in_paths) == before, "an edit to a fixture the file never set up missed it"
    _edit(repo, "    return _helper()\n", "    return _helper() + 1\n")
    assert _key(repo, in_paths=in_paths) != before, "positive control: the used fixture's edit must miss"


def test_a_name_kwarg_fixture_is_tracked_by_its_registered_name(repo):
    before = _key(repo)
    _edit(repo, "    return 2\n", "    return 22\n")
    assert _key(repo) != before


@pytest.mark.parametrize("old,new", [
    ("    return 1\n", "    return 11\n"),  # a helper the used fixture calls
    ("    return None\n", "    return items\n"),  # a hook every process runs
    ("import pytest\n", "import pytest\nimport os\n"),  # module-level code
])
def test_a_core_edit_misses_every_file(repo, old, new):
    before = _key(repo, fx=())
    _edit(repo, old, new)
    assert _key(repo, fx=()) != before


def test_comments_and_line_moves_change_no_key(repo):
    before = _key(repo)
    _edit(repo, "def _helper():\n", "# a comment\n\n\ndef _helper():  # trailing\n")
    assert _key(repo) == before


@pytest.mark.parametrize("variant", ["no-fx-record", "file-opened-it", "child-loaded-it"])
def test_without_fx_or_when_the_source_was_read_as_data_the_blob_keys(repo, variant):
    kwargs = {
        "no-fx-record": dict(fx=None),
        "file-opened-it": dict(own=(CONF,)),
        "child-loaded-it": dict(opaque=(CONF,)),
    }[variant]
    before = _key(repo, **kwargs)
    _edit(repo, "    return 3\n", "    return 33\n")
    assert _key(repo, **kwargs) != before, "the whole-blob fallback must still miss on any edit"


def test_a_new_definition_of_a_used_fixture_name_misses(repo):
    before = _key(repo)
    _edit(repo, "@pytest.fixture\ndef unused", "@pytest.fixture(name='used')\ndef shadow():\n    return 9\n\n\n"
          "@pytest.fixture\ndef unused")
    assert _key(repo) != before


def test_a_record_names_its_fixtures_only_when_every_deps_line_did():
    deps = cache.FileDeps()
    deps.merge_deps({"fx": ["a"], "own": ["x.py"]}, ())
    assert deps.fx == ["a"] and deps.own == {"x.py"}
    deps.merge_deps({"paths": []}, ())  # an older recorder's line, or an item without a request
    assert deps.fx is None
    assert cache.FileDeps().fx is None


def test_the_store_round_trips_fx_and_the_blob_kept_paths(tmp_path):
    store = cache.GateStore(tmp_path / "store")
    deps = cache.FileDeps(paths={T}, mods={CONF})
    deps.merge_deps({"fx": ["used"], "own": ["data.txt"]}, ())
    deps.merge_child({"paths": ["child.txt"]})
    old = cache.FileDeps(paths={T})
    store.write_deps({T: deps, "tests/old.py": old}, "r1")
    loaded = store.load_deps()
    assert loaded[T].fx == ["used"] and loaded[T].keep == ["child.txt", "data.txt"]
    assert loaded["tests/old.py"].fx is None and loaded["tests/old.py"].keep == []


def test_only_conftests_and_the_chain_helpers_are_fixture_modules():
    assert fixtures.is_fixture_module("conftest.py")
    assert fixtures.is_fixture_module("tests/agent/conftest.py")
    assert fixtures.is_fixture_module("tests/_downstream/conftest_plugin.py")
    assert not fixtures.is_fixture_module("tests/agent/test_x.py")
    assert not fixtures.is_fixture_module("agent/conftest.txt")
    assert fixtures.shape_of(b"def (:") is None


def test_the_plan_line_states_the_expected_wall_before_the_run():
    wall, line = plan.expected_wall({"a.py": 600.0, "b.py": 60.0, "c.py": None}, 2, 30.0)
    assert wall == 600.0, "the longest file is the floor when it outweighs Σ / jobs"
    assert "~10 min at -j 2" in line and "1 without a recorded time counted at 30s" in line
    wall, _line = plan.expected_wall({f"f{i}.py": 60.0 for i in range(80)}, 8, 30.0)
    assert wall == 600.0
    assert plan.chain_split_hint(wall, ["tests/_downstream/conftest_plugin.py"]) is None
    hint = plan.chain_split_hint(3 * 3600.0, ["tests/_downstream/conftest_plugin.py"])
    assert hint and "land that change alone" in hint
    assert plan.chain_split_hint(3 * 3600.0, []) is None
