"""``tests/_downstream/call_graph.py`` over the fixture package
``tests/fixtures/call_graph/cgpkg``: a direct caller, a two-hop caller through
an imported helper (by name and by module attribute), a re-export, a
function-local import, a same-named function in another module, a cycle, and
the calls that cannot resolve.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests._downstream.call_graph import CallGraph, reaches, resolve_calls

ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "call_graph"
EMIT = ("cgpkg.root", "emit")


def _reaches(name: str) -> bool:
    return reaches("cgpkg.root", "emit", ("cgpkg.callers", name), ("cgpkg",), root=ROOT)


@pytest.mark.parametrize("name", [
    "direct",
    "two_hop",
    "two_hop_through_module_attribute",
    "through_a_reexport",
    "local_import",
])
def test_a_caller_that_reaches_the_root_is_found(name):
    assert _reaches(name)


def test_a_same_named_function_in_another_module_is_not_the_root():
    # Resolving ``twin.emit`` by its attribute alone would read it as the root.
    assert ("cgpkg.twin", "emit") in resolve_calls(ROOT / "cgpkg" / "callers.py", ROOT).calls["same_name_other_module"]
    assert not _reaches("same_name_other_module")


@pytest.mark.timeout(5)
def test_a_cycle_terminates_and_does_not_reach():
    assert not _reaches("cycle_a")


def test_unresolved_calls_are_recorded_not_dropped():
    table = resolve_calls(ROOT / "cgpkg" / "callers.py", ROOT)
    assert table.calls["unresolved"] == set()
    assert table.unresolved["unresolved"] == {"handler.emit", "mystery"}


def test_reaching_answers_many_starts_at_once():
    starts = [("cgpkg.callers", n) for n in ("direct", "two_hop", "cycle_a", "same_name_other_module")]
    assert CallGraph(ROOT, ("cgpkg",)).reaching({EMIT}, starts) == {("cgpkg.callers", "direct"),
                                                                       ("cgpkg.callers", "two_hop")}


def test_modules_outside_limit_to_are_not_parsed():
    graph = CallGraph(ROOT, ("cgpkg.callers",))
    assert not graph.reaching({EMIT}, [("cgpkg.callers", "two_hop")])
    assert graph.reaching({EMIT}, [("cgpkg.callers", "direct")])
