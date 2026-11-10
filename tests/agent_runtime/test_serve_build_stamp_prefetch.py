"""RT-HARNESS-SERVE-COLD-BOOT: the serve's build stamp resolves beside its imports, once.

``hermes harness serve --ndjson`` starts ``build_stamp``'s git work on a daemon thread at the
verb's entry, so the ``ready`` frame's ``build`` block no longer waits for up to three git
processes in the middle of the boot. The value must not change: the boot's reader gets the
prefetch's answer and the stamp is resolved exactly once per process.
"""

from __future__ import annotations

import os
import threading
from types import SimpleNamespace

import pytest

from agent_runtime import build_stamp as build_stamp_module
from agent_runtime.build_stamp import build_stamp, prefetch_build_stamp, reset_build_stamp_cache


@pytest.fixture(autouse=True)
def _fresh_stamp():
    reset_build_stamp_cache()
    yield
    reset_build_stamp_cache()


def _counting_resolve(monkeypatch, *, gate: threading.Event | None = None) -> list:
    calls: list = []
    real_baked = build_stamp_module.baked_build_stamp

    def _resolve():
        calls.append(threading.current_thread().name)
        if gate is not None:
            assert gate.wait(10)
        return real_baked()

    monkeypatch.setattr(build_stamp_module, "_resolve", _resolve)
    return calls


def test_prefetch_resolves_on_its_own_thread_and_the_reader_reuses_it(monkeypatch):
    calls = _counting_resolve(monkeypatch)

    thread = prefetch_build_stamp()

    assert thread is not None
    thread.join(10)
    stamp = build_stamp()
    assert calls == ["build-stamp-prefetch"]
    assert build_stamp() is stamp


def test_a_reader_during_the_prefetch_waits_for_it_instead_of_resolving_again(monkeypatch):
    gate = threading.Event()
    calls = _counting_resolve(monkeypatch, gate=gate)
    thread = prefetch_build_stamp()
    assert thread is not None
    got: list = []
    reader = threading.Thread(target=lambda: got.append(build_stamp()), daemon=True)
    reader.start()
    reader.join(0.2)
    assert reader.is_alive()  # parked on the cache lock the prefetch holds

    gate.set()
    thread.join(10)
    reader.join(10)

    assert calls == ["build-stamp-prefetch"]
    assert got and got[0] is build_stamp()


def test_prefetch_is_a_no_op_once_the_stamp_is_cached(monkeypatch):
    calls = _counting_resolve(monkeypatch)
    build_stamp()

    assert prefetch_build_stamp() is None
    assert calls == ["MainThread"]


def _drive_serve_verb(monkeypatch, *, ndjson: bool) -> list[str]:
    from hermes_cli.harness_parts.parser import machine as parser_machine
    from hermes_cli.harness_parts.serve import commands as serve_commands

    order: list[str] = []
    monkeypatch.setattr(build_stamp_module, "prefetch_build_stamp", lambda: order.append("prefetch"))
    monkeypatch.setattr(
        serve_commands,
        "_claim_protocol_pipes",
        lambda: (os.open(os.devnull, os.O_RDONLY), os.open(os.devnull, os.O_WRONLY)),
    )
    monkeypatch.setattr(serve_commands, "serve_loop", lambda reader, writer, **kw: order.append("serve") or 0)
    parser_machine._cmd_serve(SimpleNamespace(ndjson=ndjson, pool_size=1, no_socket=True))
    return order


def test_the_serve_verb_starts_the_prefetch_before_the_loop(monkeypatch):
    assert _drive_serve_verb(monkeypatch, ndjson=True) == ["prefetch", "serve"]


def test_a_refused_serve_starts_no_git_work(monkeypatch, capsys):
    assert _drive_serve_verb(monkeypatch, ndjson=False) == []
    assert "unsupported_transport" in capsys.readouterr().out
