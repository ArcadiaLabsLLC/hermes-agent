"""Frozen Job2 registration order, namespace and optional bundle semantics."""
import ast
import builtins
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
ORDER = ['session_transports', 'session_reaper', 'session_lifecycle', 'session_workdir', 'compute_host_bridge', 'model_switch', 'session_compression', 'change_watcher', 'tool_progress', 'session_notifications', 'prompt_attachments', 'session_history', 'agent_callbacks', 'session_auto_continue', 'plugin_inject', 'rpc_dispatch', 'methods_complete_helpers', 'methods_slash', 'methods_voice', 'methods_browser', 'methods_browser_control', 'methods_session', 'methods_prompt', 'methods_pdf', 'methods_config', 'methods_config_set', 'methods_complete', 'methods_tools', 'methods_profiles', 'methods_images', 'methods_bot_relay', 'prompt_turn', 'billing_view', 'methods_projects', 'methods_session_foreign', 'methods_session_control', 'methods_subagents', 'methods_vault', 'methods_free_tier', 'methods_connectors', 'methods_connectors_account', 'methods_display', 'methods_display_watch', 'methods_onboarding', 'methods_i18n', 'methods_shared_metrics', 'session_recovery', 'session_retirement']


def registration(monkeypatch, failure=None, *, inspect_pdf_import=False):
    source = (ROOT / "tui_gateway/server.py").read_text(encoding="utf-8")
    source = source[source.index("# ── Split @method handler modules"):]
    server = ModuleType("tui_gateway._job2_registration_test")
    server.__package__ = "tui_gateway"
    server.sys = sys
    server.calls = []
    monkeypatch.setitem(sys.modules, server.__name__, server)
    real_import = builtins.__import__
    def importing(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "tui_gateway" or (not name and level == 1):
            modules = {}
            for child in fromlist:
                if inspect_pdf_import and child == "methods_pdf":
                    assert hasattr(server, "_methods_connectors")
                    assert hasattr(server, "_methods_connectors_account")
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
    server = registration(monkeypatch, inspect_pdf_import=True)
    assert server.calls == ORDER
    assert server._CONNECTOR_RPC_METHODS == frozenset({"connectors.fixture"})
    for name in ("methods_connectors", "methods_connectors_account", "methods_pdf", "session_recovery", "session_retirement"):
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
    # not part of this MOVE. PDF already distinguishes internal failures.
    server = registration(monkeypatch, ("methods_connectors_account", "connectors.internal_dependency"))
    assert server._CONNECTOR_RPC_METHODS == frozenset()


@pytest.mark.parametrize("error_name", ["tui_gateway", "tui_gateway.methods_pdf"])
def test_omitted_pdf_has_no_handler_and_preserves_remaining_order(monkeypatch, error_name):
    server = registration(monkeypatch, ("methods_pdf", error_name))
    assert server.calls == [name for name in ORDER if name != "methods_pdf"]
    assert callable(server._methods_pdf.register)


def test_pdf_internal_import_error_propagates(monkeypatch):
    with pytest.raises(ImportError) as error:
        registration(monkeypatch, ("methods_pdf", "pdf.internal_dependency"))
    assert error.value.name == "pdf.internal_dependency"


def test_live_handlers_keep_server_namespace_and_native_owner_handles():
    from tui_gateway import server
    assert server._methods["pdf.attach"].__globals__ is vars(server)
    assert server._methods_pdf.__name__ == "tui_gateway.methods_pdf"
    assert server._session_recovery.__name__ == "tui_gateway.session_recovery"
    assert server._session_retirement.__name__ == "tui_gateway.session_retirement"
    for name in ("session.recover", "session.recovery.history", "session.recovery.inflight", "session.retire"):
        assert callable(server._methods[name])
    response = server._methods["session.retire"]("job2", {"session_id": "job2-missing"})
    assert response["id"] == "job2" and response["result"] == {"status": "retired"}


def test_gateway_helper_remains_fork_owned():
    # The helper cannot become a second upstream registration owner.
    manifest = (ROOT / "tests/fixtures/upstream_manifest.txt").read_text(encoding="utf-8")
    assert "agent_runtime/gateway_extensions.py" not in manifest
    ast.parse((ROOT / "tui_gateway/server.py").read_text(encoding="utf-8"))
