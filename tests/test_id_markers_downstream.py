"""The id table's own guarantees, pinned where they live (lane B5, 2026-09-25).

``tests/_downstream/id_markers/`` splits the table by the CLASS that retires a
row and assembles it with ``hooks._merge``. These are the positive controls
for that assembly and for the two hooks nothing else exercised: a key in two
class tables carries BOTH marks, the lent import-time attribute is taken back,
and every mark the table applies is a name somebody registered (the suite
runs without ``--strict-markers``, so a misspelled mark is otherwise applied
silently and read by nothing).
"""

from __future__ import annotations

import os
import sys
from types import SimpleNamespace

import pytest

from tests._downstream import conftest_plugin
from tests._downstream import hermes_cli_conftest
from tests._downstream.id_markers import hooks

#: A fork timeout raise (fork_marks: the payload build runs 72-245 s) AND an
#: upstream Windows red (upstream_reds: the win32 launcher imports
#: hermes_bootstrap, which the fixture never copies) — cross-class on purpose
#: (lane h11-env): the xfail still runs the body, so it still needs the budget.
_BUNDLE_NATIVE = (
    "tests/scripts/test_bundle_native.py::"
    "test_bundle_stages_git_tree_and_runs_native_children_before_manifest"
)

#: pytest's own marks and the plugins' — not the fork's to register.
_BUILTIN_MARKS = frozenset({"xfail", "skip", "skipif", "timeout"})

#: Applied by id AND by upstream's own tests, read by ``tests/conftest.py``'s
#: live-system guard, and registered NOWHERE (not in ``pyproject.toml``'s
#: ``markers``, not by any conftest). Upstream vocabulary, named here so the
#: control below stays a red for a NEW unregistered name rather than for this one.
_UPSTREAM_UNREGISTERED = frozenset({"spawns_gateway_lookalike"})


@pytest.mark.skipif(sys.platform != "win32", reason="the cross-class keys are win32 rows")
def test_a_key_in_two_classes_carries_both_marks():
    """The bundle-native id is a timeout raise (fork) AND an upstream red. The
    assembler CONCATENATES, in class order, so it carries both — an assembler
    that overrode instead would silently drop one."""

    assert [mark.name for mark in hooks.ID_MARKS[_BUNDLE_NATIVE]] == ["timeout", "xfail"]
    # This set moves only when a lane adds a cross-class row on purpose — and
    # then says so here (_BUNDLE_NATIVE: lane h11-env, 2026-09-29).
    assert hooks.SHARED_KEYS == frozenset({_BUNDLE_NATIVE})


_UNDO_MODULE = """
def drops_its_stub(monkeypatch):
    monkeypatch.setattr("os.sep", "x")
    monkeypatch.undo()

def decorated(fn):
    return fn

@decorated
def decorated_dropper(mp):
    mp.undo()

def keeps_its_stub(monkeypatch):
    monkeypatch.setattr("os.sep", "x")
"""


class _Item:
    def __init__(self, nodeid, function, fixturenames=("monkeypatch",)):
        self.nodeid, self.function, self.fixturenames, self.marks = nodeid, function, fixturenames, []

    def add_marker(self, mark):
        self.marks.append(mark)

    def get_closest_marker(self, name):
        return next((m for m in self.marks if m.name == name), None)


def test_a_mid_body_undo_is_found_by_the_ast_and_scoped_at_collection(tmp_path):
    """No id row: an upstream test that calls ``.undo()`` in its body gets the
    scoped-undo mark at collection, whatever the receiver is spelled; one that
    does not, or that takes no ``monkeypatch``, gets nothing."""

    import importlib.util

    path = tmp_path / "undo_mod.py"
    path.write_text(_UNDO_MODULE, encoding="utf-8")
    spec = importlib.util.spec_from_file_location("undo_mod", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    items = [
        _Item("x.py::drops_its_stub", mod.drops_its_stub),
        _Item("x.py::decorated_dropper", mod.decorated_dropper),
        _Item("x.py::keeps_its_stub", mod.keeps_its_stub),
        _Item("x.py::no_fixture", mod.drops_its_stub, fixturenames=()),
    ]
    hooks.pytest_collection_modifyitems(SimpleNamespace(args=[], rootpath=tmp_path), items)

    scoped = [item.nodeid for item in items if item.get_closest_marker("scoped_monkeypatch_undo")]
    assert scoped == ["x.py::drops_its_stub", "x.py::decorated_dropper"]


@pytest.mark.skipif(
    not hooks.IMPORT_TIME_POSIX_SHIMS, reason="no import-time shim on this host"
)
def test_import_time_posix_shims_are_taken_back():
    """``pytest_make_collect_report`` lends ``os.geteuid`` to ONE module's
    import and must take it back in its ``finally`` — a leaked ``geteuid``
    turns every later ``hasattr(os, "geteuid")`` probe on win32 into a lie."""

    nodeid = "tests/agent/test_prompt_builder.py"
    assert not hasattr(os, "geteuid")
    wrapper = hooks.pytest_make_collect_report(SimpleNamespace(nodeid=nodeid))
    next(wrapper)
    assert hasattr(os, "geteuid"), "positive control: the shim is lent during the import"
    with pytest.raises(StopIteration):
        wrapper.send(SimpleNamespace(failed=False))

    assert not hasattr(os, "geteuid")


@pytest.mark.skipif(
    not hooks.IMPORT_TIME_POSIX_MODULES, reason="no import-time POSIX module row on this host"
)
def test_only_the_rows_own_missing_module_turns_a_collection_error_into_a_skip():
    """A row's module missing at import is a skip; any other collection error still fails."""

    nodeid, module = next(iter(hooks.IMPORT_TIME_POSIX_MODULES.items()))
    collector = SimpleNamespace(nodeid=nodeid, path=nodeid)

    def failed(message: str):
        return SimpleNamespace(failed=True, nodeid=nodeid, longrepr=message)

    skipped = hooks._skip_if_posix_module_missing(
        collector, failed(f"ModuleNotFoundError: No module named '{module}'")
    )
    assert skipped.outcome == "skipped", "positive control: the row's own import is a skip"

    other = failed("ModuleNotFoundError: No module named 'not_a_posix_module'")
    assert hooks._skip_if_posix_module_missing(collector, other) is other


def _registered_by_the_fork() -> set[str]:
    lines: list[str] = []
    config = SimpleNamespace(
        pluginmanager=SimpleNamespace(hasplugin=lambda name: False),
        option=SimpleNamespace(),
        addinivalue_line=lambda name, line: lines.append(line) if name == "markers" else None,
    )
    conftest_plugin.pytest_configure(config)
    hermes_cli_conftest.pytest_configure(config)
    return {line.split(":", 1)[0].split("(", 1)[0].strip() for line in lines}


def test_every_applied_mark_name_is_registered(request):
    """A typo on either side — the table or a registrar — is a mark nothing
    reads. Without ``--strict-markers`` this is the only check that says so."""

    applied = {mark.name for marks in hooks.ID_MARKS.values() for mark in marks}
    # A registration line is `name(signature): help` or `name: help`; the name is before both.
    ini = {line.split(":", 1)[0].split("(", 1)[0].strip() for line in request.config.getini("markers")}
    registered = _registered_by_the_fork() | ini | _BUILTIN_MARKS | _UPSTREAM_UNREGISTERED

    assert applied - registered == set()
    # Positive control: the registrars were actually read (an empty set would
    # make the subset check above vacuous for every fork mark).
    assert {"scoped_monkeypatch_undo", "real_windows_gateway_pause"} <= _registered_by_the_fork()
