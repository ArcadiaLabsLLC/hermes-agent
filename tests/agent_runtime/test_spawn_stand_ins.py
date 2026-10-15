"""The phone's function-level stand-ins for upstream functions that start a process (plan lane G3, M3).

A row rebinds one named function on its module — at once when the module is loaded, on import
otherwise — to a stand-in that raises the typed ``SpawnNotAvailable`` (an ``OSError``, ``ENOTSUP``,
optionally also the function's own documented error) or returns the function's documented
no-process result. A row naming a function the module lacks raises ``SpawnSeamStale``. The phone
entry's ``ensure_spawn_stand_ins`` does nothing while the profile ships a provider SDK (desktop).
The profile gate's proof over the REAL table is ``tests/scripts/test_bundle_profile_gate.py``.
"""

from __future__ import annotations

import asyncio
import errno
import importlib
import sys
import textwrap
import types

import pytest

from agent_runtime import spawn_stand_ins as ssi
from agent_runtime.spawn_stand_ins import SpawnNotAvailable, SpawnSeamStale, StandIn

_SOURCE = """
    import subprocess

    class DocumentedError(RuntimeError):
        pass

    FALLBACK = "static"

    def loud():
        return subprocess.run(["git"])

    def quiet():
        return subprocess.run(["git"])

    def computed(arg):
        return subprocess.run([arg])

    def contract():
        raise DocumentedError("real")

    async def later():
        return subprocess.run(["x"])

    def untouched():
        return "real"

    class Owner:
        @staticmethod
        def static():
            return subprocess.run(["x"])

        def method(self):
            return subprocess.run(["x"])
"""

_TABLE = (
    StandIn("fake_spawner", "loud"),
    StandIn("fake_spawner", "quiet", returns=None),
    StandIn("fake_spawner", "computed", answer=lambda mod, arg: f"{mod.FALLBACK}:{arg}"),
    StandIn("fake_spawner", "contract", error="DocumentedError"),
    StandIn("fake_spawner", "later", returns=0),
    StandIn("fake_spawner", "Owner.static", returns=False),
    StandIn("fake_spawner", "Owner.method"),
)


@pytest.fixture()
def fake(tmp_path, monkeypatch):
    (tmp_path / "fake_spawner.py").write_text(textwrap.dedent(_SOURCE), encoding="utf-8")
    (tmp_path / "fake_importer.py").write_text("from fake_spawner import loud\n", encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    for name in ("fake_spawner", "fake_importer"):
        sys.modules.pop(name, None)
    yield tmp_path
    ssi.remove_spawn_stand_ins(_TABLE)
    for name in ("fake_spawner", "fake_importer"):
        sys.modules.pop(name, None)


def _answers(mod) -> None:
    with pytest.raises(SpawnNotAvailable) as raised:
        mod.loud()
    assert isinstance(raised.value, OSError) and raised.value.errno == errno.ENOTSUP
    assert "fake_spawner.loud" in str(raised.value) and "phone" in str(raised.value)
    assert mod.quiet() is None
    assert mod.computed("arg") == "static:arg"
    with pytest.raises(mod.DocumentedError) as documented:  # the callers' own except still catches it
        mod.contract()
    assert isinstance(documented.value, SpawnNotAvailable)
    assert asyncio.run(mod.later()) == 0
    assert mod.Owner.static() is False and mod.Owner().static() is False
    with pytest.raises(SpawnNotAvailable):
        mod.Owner().method()
    assert mod.untouched() == "real"  # a function no row names keeps its body
    assert all(ssi.spawn_stand_in_of(vars(mod).get(n) or vars(mod.Owner)[n.split(".")[-1]])
               == ("fake_spawner", n) for n in ("loud", "quiet", "Owner.static", "Owner.method"))


def test_a_loaded_module_is_rebound_at_once_and_restored_on_removal(fake):
    mod = importlib.import_module("fake_spawner")
    real_loud = mod.loud
    assert ssi.install_spawn_stand_ins(_TABLE) == tuple(row.target for row in _TABLE)
    _answers(mod)
    assert mod.loud.__wrapped__ is real_loud
    ssi.remove_spawn_stand_ins(_TABLE)
    assert mod.loud is real_loud and not ssi.is_spawn_stand_in(vars(mod.Owner)["static"])


def test_a_module_imported_later_is_rebound_before_any_importer_copies_the_function(fake):
    ssi.install_spawn_stand_ins(_TABLE)
    assert "fake_spawner" not in sys.modules
    importer = importlib.import_module("fake_importer")  # `from fake_spawner import loud` at module level
    _answers(sys.modules["fake_spawner"])
    assert ssi.is_spawn_stand_in(importer.loud)


def test_a_row_naming_a_function_the_module_lacks_fails_loudly(fake):
    importlib.import_module("fake_spawner")
    with pytest.raises(SpawnSeamStale, match="gone"):
        ssi.install_spawn_stand_ins((StandIn("fake_spawner", "gone"),))
    with pytest.raises(SpawnSeamStale, match="FALLBACK"):  # a value is not a function
        ssi.install_spawn_stand_ins((StandIn("fake_spawner", "FALLBACK"),))
    with pytest.raises(SpawnSeamStale, match="NoSuchError"):
        ssi.install_spawn_stand_ins((StandIn("fake_spawner", "loud", error="NoSuchError"),))
    sys.modules.pop("fake_spawner")
    ssi.install_spawn_stand_ins((StandIn("fake_spawner", "gone"),))  # not loaded: raised by the import itself
    with pytest.raises(SpawnSeamStale, match="gone"):
        importlib.import_module("fake_spawner")
    ssi.remove_spawn_stand_ins((StandIn("fake_spawner", "gone"),))


def test_the_phone_entry_installs_only_when_the_profile_ships_no_provider_sdk(fake, monkeypatch):
    from agent.transports import httpx_client

    mod = importlib.import_module("fake_spawner")
    monkeypatch.setattr(httpx_client, "provider_sdks_enabled", lambda: True)  # desktop
    assert ssi.ensure_spawn_stand_ins(_TABLE) == ()
    assert not any(ssi.is_spawn_stand_in(v) for v in vars(mod).values())
    assert ssi._FINDER is None or "fake_spawner" not in ssi._FINDER.rows
    monkeypatch.setattr(httpx_client, "provider_sdks_enabled", lambda: False)  # positive control: the phone
    assert ssi.ensure_spawn_stand_ins(_TABLE)
    _answers(mod)


def test_every_row_of_the_real_table_names_a_function_of_its_module():
    """The cheap, in-process half of the gate's proof (the gate imports each module with the
    phone's absences in place and checks the rebinding itself)."""
    assert len({row.target for row in ssi.SPAWN_STAND_INS}) == len(ssi.SPAWN_STAND_INS)
    for row in ssi.SPAWN_STAND_INS:
        owner, name = ssi._stand_in_owner(row, importlib.import_module(row.module))
        raw = vars(owner).get(name)
        function = raw.__func__ if isinstance(raw, (staticmethod, classmethod)) else raw
        assert isinstance(function, types.FunctionType), row.target
        if isinstance(row.error, str):
            assert issubclass(getattr(sys.modules[row.module], row.error), BaseException), row.target


def test_a_typed_slash_command_is_unavailable_on_the_phone_before_any_process(monkeypatch):
    """Owner decision D5 (2026-09-30): no typed slash commands on the phone. The gateway's slash
    worker is a stand-in there, so ``slash.exec`` answers "unavailable" and never starts
    ``python -m tui_gateway.slash_worker``. Positive control: removed, the real ``__init__`` is back.
    Killing mutation (recorded in the commit): delete the ``_SlashWorker.__init__`` row -> the gate
    refuses the phone (``subprocess_call`` in ``tui_gateway.server``)."""
    import subprocess

    from tui_gateway import server

    row = next(r for r in ssi.SPAWN_STAND_INS if r.target == "tui_gateway.server._SlashWorker.__init__")
    real = server._SlashWorker.__init__
    started: list = []
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: started.append(a) or pytest.fail("a process"))
    ssi.install_spawn_stand_ins((row,))
    try:
        with pytest.raises(ssi.SlashCommandsUnavailable, match="slash commands are unavailable on this device"):
            server._SlashWorker("session-key", "test-model")
        assert isinstance(ssi.SlashCommandsUnavailable("x"), OSError)  # callers' `except Exception` answer it
    finally:
        ssi.remove_spawn_stand_ins((row,))
    assert server._SlashWorker.__init__ is real
    assert started == []

