"""The verbs' pattern dialects match without backtracking, and the bounds hold.

Row ``MC-FU-PROJECT-FOLDER-SEARCH-NARROWS-BY-FILE-NAME-AND-TAKES-A-PATTERN`` (Eternia): the glob and
the line wildcard (``agent_runtime/project_files/patterns.py``) take patterns from remote callers,
so neither may be a regular expression whose match a deadline cannot stop. The shared behaviour is
the spec's golden cases (``test_project_files_spec_cases.py``); these pin the matcher's worst cases
and the deadline on the reader itself.
"""

from __future__ import annotations

import time

import pytest

from agent_runtime.project_files import reader
from agent_runtime.project_files.patterns import Deadline, LinePattern, NameGlob
from agent_runtime.project_files.rules import MAX_WILDCARDS, ProjectFileRefusal


@pytest.mark.parametrize(("glob", "name", "matches"), [
    ("*.py", "a.py", True),
    ("*.py", "a.pyc", False),
    ("?.py", "ab.py", False),
    ("a*b*c", "aXbYc", True),
    ("a*b*c", "aXcYb", False),
    ("*", "anything", True),
    ("[ab].txt", "a.txt", False),
    ("[ab].txt", "[ab].txt", True),
    ("**", "x", True),
])
def test_a_glob_matches_the_whole_name(glob, name, matches):
    assert NameGlob.parse(glob).matches(name) is matches


def test_the_worst_admitted_glob_over_a_long_name_is_fast():
    """MUTATION (``NameGlob.matches``): compile to ``re`` as ``.*`` runs instead (the GenUI glob's
    shape), and this name and glob backtrack for far longer than the bound."""

    glob = NameGlob.parse("*a" * MAX_WILDCARDS + "b")
    name = "a" * 255
    started = time.monotonic()
    for _ in range(100):
        assert not glob.matches(name)
    assert time.monotonic() - started < 1.0


def test_the_worst_admitted_wildcard_over_a_long_line_is_one_pass():
    """MUTATION (``LinePattern.matches``): restart the whole search from each found first piece
    (a backtracking matcher), and the 16 pieces over a 1 MB line take far longer than the bound."""

    pattern = LinePattern.parse("a*" * MAX_WILDCARDS + "b", wildcard=True)
    line = "a" * 1_000_000
    started = time.monotonic()
    assert not pattern.matches(line)
    assert time.monotonic() - started < 0.5


def test_a_wildcard_finds_its_pieces_in_order_on_one_line():
    pattern = LinePattern.parse("def *(*):", wildcard=True)
    assert pattern.matches("    def run(self):")
    assert not pattern.matches("(self): def run")


def test_a_reader_search_past_its_deadline_is_refused(tmp_path):
    """MUTATION (``reader.grep_matches``): drop ``deadline.check()`` before each file and the walk's
    check, and this grep over 50 files is answered instead of refused."""

    root = tmp_path / "root"
    root.mkdir()
    for index in range(50):
        (root / f"f{index}.txt").write_text("hit\n", encoding="utf-8")
    with pytest.raises(ProjectFileRefusal) as refused:
        reader.grep_matches(str(root), "hit", deadline=Deadline(0.0))
    assert refused.value.code == "search_timeout"
    with pytest.raises(ProjectFileRefusal) as refused:
        reader.tree_entries(str(root), glob="*.txt", deadline=Deadline(0.0))
    assert refused.value.code == "search_timeout"
