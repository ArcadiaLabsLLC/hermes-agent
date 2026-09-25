"""Fork half of ``tests/test_tests_tree_layout.py``.

Upstream's ``test_every_test_directory_mirrors_a_source_directory_or_is_declared``
is a strict xfail row in ``tests/_downstream/id_markers.py``: the fork's own test
directories mirror no source package and the fork does not edit upstream's
``_NON_MIRROR_DIRS``. This runs the same check with the fork's directories
declared beside upstream's table.
"""

from __future__ import annotations

from tests.test_tests_tree_layout import TESTS_ROOT, _NON_MIRROR_DIRS, _source_dirs

# tests/<name>/ directories the fork owns, with the reason each needs no mirror.
_FORK_NON_MIRROR_DIRS = {
    "_downstream": "fork test plumbing: id marks, the conftest plugin, directory conftests",
    "tooling": "fork gates over the whole tree (plugin import fence, refactor gates)",
}


def test_every_test_directory_mirrors_a_source_directory_or_is_declared_by_fork():
    declared = set(_NON_MIRROR_DIRS) | set(_FORK_NON_MIRROR_DIRS)
    offenders = sorted(
        d.name
        for d in TESTS_ROOT.iterdir()
        if d.is_dir()
        and d.name != "__pycache__"
        and d.name not in _source_dirs()
        and d.name not in declared
    )
    assert not offenders, (
        f"tests/ directories that mirror no source package: {offenders}. File the "
        "tests under tests/<source dir>/, or add a fork directory to "
        "_FORK_NON_MIRROR_DIRS here with a reason."
    )


def test_every_fork_non_mirror_dir_still_exists_and_is_not_upstreams():
    """A fork row that no longer applies must fail, not rot."""
    for name in _FORK_NON_MIRROR_DIRS:
        assert (TESTS_ROOT / name).is_dir(), f"tests/{name}/ is gone; drop its row"
        assert name not in _NON_MIRROR_DIRS, f"upstream now declares {name}; drop its row"
