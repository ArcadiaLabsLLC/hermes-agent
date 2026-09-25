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

_TCC_ALIAS = (
    "tests/hermes_cli/test_macos_tcc_anchor.py::TestEnsureTccAnchor::"
    "test_alias_failure_leaves_anchor_unmarked"
)

#: pytest's own marks and the plugins' — not the fork's to register.
_BUILTIN_MARKS = frozenset({"xfail", "skip", "skipif", "timeout"})

#: Applied by id AND by upstream's own tests, read by ``tests/conftest.py``'s
#: live-system guard, and registered NOWHERE (not in ``pyproject.toml``'s
#: ``markers``, not by any conftest). Upstream vocabulary, named here so the
#: control below stays a red for a NEW unregistered name rather than for this one.
_UPSTREAM_UNREGISTERED = frozenset({"spawns_gateway_lookalike"})


@pytest.mark.skipif(sys.platform != "win32", reason="the one cross-class key is a win32 row")
def test_a_key_in_two_classes_carries_both_marks():
    """The TCC alias id is a scoped-undo row (fork) AND a POSIX-venv xfail
    (posix). The assembler CONCATENATES, in class order, so it carries both —
    an assembler that overrode instead would silently drop one."""

    names = [mark.name for mark in hooks.ID_MARKS[_TCC_ALIAS]]

    assert names == ["scoped_monkeypatch_undo", "xfail"]
    # The only such key today. This set moves only when a lane adds a
    # cross-class row on purpose — and then says so here.
    assert hooks.SHARED_KEYS == frozenset({_TCC_ALIAS})


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
    ini = {line.split(":", 1)[0].strip() for line in request.config.getini("markers")}
    registered = _registered_by_the_fork() | ini | _BUILTIN_MARKS | _UPSTREAM_UNREGISTERED

    assert applied - registered == set()
    # Positive control: the registrars were actually read (an empty set would
    # make the subset check above vacuous for every fork mark).
    assert {"scoped_monkeypatch_undo", "real_windows_gateway_pause"} <= _registered_by_the_fork()
