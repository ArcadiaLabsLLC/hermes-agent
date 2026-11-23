"""RT-FU-A-COLD-HARNESS-SERVE-REGISTERS-SECONDS-SOONER: a verb's early start runs before the setup.

``hermes harness serve`` waits on its build stamp's git work. The harness entry starts that work
(the handler's ``__harness_early_start__``) BEFORE the start-time setup, so the git runs beside
the setup and the serve's imports instead of after them.
"""

from __future__ import annotations

from types import SimpleNamespace

from agent_runtime.core_cache import home as core_cache_home
from hermes_cli import harness
from hermes_cli.harness_parts import start_time_setup
from hermes_cli.harness_parts.parser import machine


def test_the_early_start_runs_before_the_start_time_setup(monkeypatch):
    order: list[str] = []
    monkeypatch.setattr(start_time_setup, "run_start_time_setup", lambda: order.append("setup"))
    monkeypatch.setattr(core_cache_home, "capture_for_harness_command", lambda args: order.append("capture"))

    def handler(args):
        order.append("handler")
        return 0

    handler.__harness_early_start__ = lambda args: order.append(f"early:{args.ndjson}")

    assert harness._harness_entry(handler)(SimpleNamespace(ndjson=True)) == 0
    assert order == ["early:True", "setup", "capture", "handler"]


def test_the_serve_verb_declares_its_build_stamp_prefetch_as_its_early_start(monkeypatch):
    started: list = []
    import agent_runtime.build_stamp as build_stamp_module

    monkeypatch.setattr(build_stamp_module, "prefetch_build_stamp", lambda: started.append(True))

    early = machine._cmd_serve_trampoline.__harness_early_start__
    early(SimpleNamespace(ndjson=False))
    assert started == []
    early(SimpleNamespace(ndjson=True))
    assert started == [True]
