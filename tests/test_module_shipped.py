"""module_shipped(): a distribution may omit a tool module; its importers stay quiet."""

import subprocess
import sys
from pathlib import Path

import pytest

import hermes_constants
from hermes_constants import mark_modules_omitted, module_shipped

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _fresh_registry(monkeypatch):
    monkeypatch.setattr(hermes_constants, "_OMITTED_MODULES", set())
    monkeypatch.setattr(hermes_constants, "_FOUND_MODULES", {})


def test_full_install_ships_what_it_finds():
    assert module_shipped("json") is True
    assert module_shipped("tools.terminal_tool") is True
    assert module_shipped("no.such.module") is False


def test_declared_prefix_is_omitted_and_its_importer_skips(monkeypatch):
    mark_modules_omitted("tools.terminal_tool")
    assert module_shipped("tools.terminal_tool") is False
    assert module_shipped("tools.terminal_tool.anything") is False
    assert module_shipped("tools.terminal_tool_sudo") is True  # a sibling, not a submodule

    from agent.relay_cwd import _recorded_cwd

    monkeypatch.delitem(sys.modules, "tools.terminal_tool", raising=False)
    assert _recorded_cwd("task-1") == ""
    assert "tools.terminal_tool" not in sys.modules


def test_missing_process_registry_wires_and_tears_down_quietly(monkeypatch):
    monkeypatch.setitem(sys.modules, "tools.process_registry", None)  # the stdlib way to fail an import
    assert module_shipped("tools.process_registry") is False

    from tui_gateway import server

    server._wire_desktop_sinks()
    server._start_notification_poller("sid-1", {}).set()

    import run_agent
    from agent.client_lifecycle import ClientLifecycleMixin

    # Run only the process step, unswallowed: an ImportError there must not happen.
    monkeypatch.setattr(run_agent, "_quietly", lambda fn: fn() if fn.__name__ == "kill_processes" else None)
    ClientLifecycleMixin._close_task_resources(ClientLifecycleMixin(), "task-1")


def test_gateway_cache_imports_without_the_local_runtime():
    code = (
        "import sys; sys.modules['hermes_cli.local_runtime'] = None\n"
        "import gateway.run_agent_cache as m; print(sorted(m.LLAMACPP_ALIASES))"
    )
    out = subprocess.run([sys.executable, "-c", code], cwd=REPO, capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr
    assert "llamacpp" in out.stdout
