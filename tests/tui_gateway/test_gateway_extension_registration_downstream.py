"""Frozen Job2 registration order, namespace and optional bundle semantics."""
import ast
import builtins
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
ORDER = ['session_registry', 'agent_factory', 'slash_worker_client', 'session_transports', 'session_reaper', 'session_lifecycle', 'session_workdir', 'compute_host_bridge', 'model_switch', 'session_compression', 'change_watcher', 'tool_progress', 'session_notifications', 'prompt_attachments', 'session_history', 'agent_callbacks', 'session_auto_continue', 'plugin_inject', 'rpc_dispatch', 'methods_complete_helpers', 'methods_slash', 'methods_voice', 'methods_browser', 'methods_session', 'methods_prompt', 'methods_config', 'methods_config_set', 'methods_complete', 'methods_tools', 'methods_tools_plugin_servers', 'methods_profiles', 'methods_images', 'methods_bot_relay', 'prompt_turn', 'billing_view', 'methods_projects', 'methods_session_foreign', 'methods_session_control', 'methods_subagents', 'methods_vault', 'methods_free_tier', 'methods_connectors', 'methods_connectors_account', 'methods_display', 'methods_display_watch', 'methods_onboarding', 'methods_i18n', 'methods_machine', 'methods_shared_metrics', 'methods_plugin_catalog', 'session_recovery', 'session_retirement', 'ssh_remote_cwd']


def registration(monkeypatch, failure=None):
    source = (ROOT / "tui_gateway/server.py").read_text(encoding="utf-8")
    source = source[source.index("# ── Split @method handler modules"):]
    server = ModuleType("tui_gateway._job2_registration_test")
    server.__package__ = "tui_gateway"
    server.sys = sys
    server.calls = []
    server.imported = []
    server._methods = {}
    server.register_method = lambda name, handler: server._methods.__setitem__(name, handler)
    server._profile_scoped = lambda handler: handler
    monkeypatch.setitem(sys.modules, server.__name__, server)
    real_import = builtins.__import__
    def importing(name, globals=None, locals=None, fromlist=(), level=0):
        if name in ("tui_gateway", "agent_runtime.gateway") or (not name and level == 1):
            modules = {}
            for child in fromlist:
                server.imported.append(child)
                if failure and child == failure[0]:
                    raise ImportError("fixture omitted dependency", name=failure[1])
                def register(owner, child=child):
                    assert owner is server
                    owner.calls.append(child)
                    if child == "methods_connectors":
                        owner._CONNECTOR_RPC_METHODS = frozenset({"connectors.fixture"})
                modules[child] = SimpleNamespace(register=register)
            return SimpleNamespace(**modules)
        if name == "agent_runtime" and fromlist == ("gateway_extensions",):
            extension = ModuleType("agent_runtime.gateway_extensions")
            extension.__dict__["__builtins__"] = {**vars(builtins), "__import__": importing}
            exec(compile((ROOT / "agent_runtime/gateway_extensions.py").read_text(encoding="utf-8"), "gateway_extensions.py", "exec"), extension.__dict__)
            return SimpleNamespace(gateway_extensions=extension)
        return real_import(name, globals, locals, fromlist, level)
    server.__dict__["__builtins__"] = {**vars(builtins), "__import__": importing}
    exec(compile(source, "server-registration-tail", "exec"), server.__dict__)
    return server


def test_registration_order_and_server_aliases_are_preserved(monkeypatch):
    server = registration(monkeypatch)
    assert server.calls == ORDER
    assert callable(server._methods["eternia.subagents.list"])
    assert server._CONNECTOR_RPC_METHODS == frozenset({"connectors.fixture"})
    for name in ("methods_connectors", "methods_connectors_account", "session_recovery", "session_retirement"):
        assert hasattr(server, "_" + name)


@pytest.mark.parametrize("missing", ["methods_connectors", "methods_connectors_account"])
def test_omitted_connector_pair_registers_empty_rpc_set(monkeypatch, missing):
    server = registration(monkeypatch, (missing, "tui_gateway"))
    assert server.calls == [name for name in ORDER if not name.startswith("methods_connectors")]
    assert server._CONNECTOR_RPC_METHODS == frozenset()
    assert server._methods_connectors is server._methods_connectors_account
    assert callable(server._no_connector_rpcs)


def test_connector_internal_import_failure_retains_existing_optional_semantics(monkeypatch):
    # Existing connectors catch every ImportError; tightening this is a CHANGE,
    # not part of this MOVE.
    server = registration(monkeypatch, ("methods_connectors_account", "connectors.internal_dependency"))
    assert server._CONNECTOR_RPC_METHODS == frozenset()


def test_live_handlers_keep_server_namespace_and_native_owner_handles():
    from tui_gateway import server
    assert server._methods["pdf.attach"].__globals__ is vars(server)
    assert server._session_recovery.__name__ == "agent_runtime.gateway.session_recovery"
    assert server._session_retirement.__name__ == "agent_runtime.gateway.session_retirement"
    for name in ("session.recover", "session.recovery.history", "session.recovery.inflight", "session.retire"):
        assert callable(server._methods[name])
    response = server._methods["session.retire"]("job2", {"session_id": "job2-missing"})
    assert response["id"] == "job2" and response["result"] == {"status": "retired"}


def test_gateway_helper_remains_fork_owned():
    # The helper cannot become a second upstream registration owner.
    manifest = (ROOT / "tests/fixtures/upstream_manifest.txt").read_text(encoding="utf-8")
    assert "agent_runtime/gateway_extensions.py" not in manifest
    ast.parse((ROOT / "tui_gateway/server.py").read_text(encoding="utf-8"))


def test_the_phone_unregisters_pdf_attach_and_the_desktop_keeps_it(monkeypatch):
    """pdf.attach is upstream's handler in methods_prompt again (FH-FOOTPRINT-PDF-ATTACH-UPSTREAM-BYTES);
    the phone (``agent.provider_sdks: false``) drops it after registration, the desktop keeps it.

    Killing mutation (2026-11-10): ``drop_phone_methods`` returns before popping -> the phone row red."""
    from agent.transports import httpx_client
    from agent_runtime.spawn_stand_ins import drop_phone_methods

    desktop = SimpleNamespace(_methods={"pdf.attach": object(), "file.attach": object()})
    assert drop_phone_methods(desktop) == () and "pdf.attach" in desktop._methods
    monkeypatch.setattr(httpx_client, "provider_sdks_enabled", lambda: False)
    phone = SimpleNamespace(_methods={"pdf.attach": object(), "file.attach": object()})
    assert drop_phone_methods(phone) == ("pdf.attach",)
    assert sorted(phone._methods) == ["file.attach"]


def test_the_phone_gate_answers_spawns_inside_a_dropped_handler_only(tmp_path):
    """The profile gate answers a spawn call inside ``@method("pdf.attach")`` for the phone, and not one
    in any other handler, nor for a profile that keeps its SDKs (positive controls).

    Killing mutation (2026-11-10): ``_registered_method`` ignores the decorator name -> red."""
    from agent_runtime.bundle_profiles.manifest import load_profile
    from scripts.bundle_profile_gate import dropped_method_seams, module_findings

    path = tmp_path / "handlers.py"
    path.write_text(
        "import subprocess\n"
        "@method('pdf.attach')\n"
        "def _(rid, params):\n"
        "    return subprocess.run(['pdftoppm'])\n"
        "@method('file.attach')\n"
        "def _(rid, params):\n"
        "    return subprocess.run(['cp'])\n", encoding="utf-8")
    findings = module_findings("handlers", path)
    assert [f["line"] for f in findings] == [4, 7]
    kept, answered = dropped_method_seams(load_profile("bundled-phone"), findings, {"handlers": path})
    assert [f["line"] for f in kept] == [7] and answered == {"handlers": ["4: pdf.attach"]}
    kept, answered = dropped_method_seams(load_profile("bundled-desktop", validate=False), findings, {"handlers": path})
    assert kept == findings and answered == {}
