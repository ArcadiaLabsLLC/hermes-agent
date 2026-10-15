"""The phone's provider and contract path loads, and works, with no provider SDK and no pydantic importable.

A fresh interpreter makes ``openai``, ``anthropic``, ``jiter``, ``pydantic`` and
``pydantic_core`` unimportable (as on a phone, where they are not packaged), switches
``agent.provider_sdks`` and ``tui_gateway.pydantic_contracts`` off, and then imports the
client chokepoints, the auxiliary client and the in-process worker's contract readers, builds
a client on each wire and answers a contract question. This is the runtime proof behind the
profile gate's static one (``scripts/bundle_profile_gate.py`` no longer reports
``provider_sdk``): a guarded import site the gate accepts must also be a site that RUNS.

The native gateway itself (``tui_gateway.server``) loads too: its connectors RPCs, the one
module-level door into the pydantic contract models, sit behind a seam the phone wheel leaves out.

The child registers the phone's ``openai`` shim first (``agent_runtime.provider_sdk_shim``, as the
embedded entry does), so upstream's own SDK import sites run unguarded on the SDK-free classes; the
only ``openai`` modules loaded are the shim's.

Killing mutations (applied, red recorded, reverted — see the commit messages): unguard the
module-level ``from openai import ...`` in ``agent/auxiliary_wire.py`` with no shim -> red; the
shim registers no ``openai.types.chat.chat_completion_message_tool_call`` -> red.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]

CHILD = textwrap.dedent('''
    import importlib.abc, json, os, sys
    RESULT = os.fdopen(os.dup(1), "w")  # the gateway owns stdout (its JSON-RPC stream) once imported
    BLOCKED = {"openai", "anthropic", "jiter", "pydantic", "pydantic_core"}

    class Blocker(importlib.abc.MetaPathFinder):
        def find_spec(self, name, path=None, target=None):
            if name.split(".")[0] in BLOCKED:
                raise ImportError("not packaged on a phone: " + name)

    sys.meta_path.insert(0, Blocker())
    from agent_runtime.provider_sdk_shim import ensure_provider_sdk_shim, is_shim
    assert ensure_provider_sdk_shim()
    from types import SimpleNamespace
    import agent.auxiliary_wire, agent.codex_runtime, agent.chat_completion_helpers, agent.acp_openai_bridge
    from agent.agent_runtime_helpers import create_openai_client
    from agent.anthropic_adapter import build_anthropic_client
    from agent.auxiliary_client import _create_openai_client, _to_async_client
    from agent_runtime.conversations import in_process_peer, questions
    from tui_gateway.contract_seam import registry
    import tui_gateway.server

    agent = SimpleNamespace(provider="openrouter", api_mode="codex_responses", _client_log_context=lambda: "",
                            _build_keepalive_http_client=lambda *a, **k: None)
    aux = _create_openai_client(api_key="k", base_url="https://p.example/v1")
    out = {
        "codex": type(create_openai_client(agent, {"api_key": "k", "base_url": "https://p.example/v1"},
                                           reason="t", shared=False)).__name__,
        "anthropic": type(build_anthropic_client("sk-ant-api03-k", "https://api.anthropic.com")).__name__,
        "aux": type(aux).__name__,
        "aux_async": type(_to_async_client(aux, "m")[0]).__name__,
        "unknown_key": registry.validate_params(registry.METHODS["session.create"], {"zz_unknown": 1})[1],
        "admits_profile": in_process_peer._admits_profile("session.create"),
    }
    questions.validate_answer({"method": "approval", "params": {"choices": ["once", "deny"]}}, {"choice": "once"})
    out["loaded"] = sorted(m for m in sys.modules if m.split(".")[0] in BLOCKED and not is_shim(sys.modules[m]))
    out["shim"] = sorted(m for m in sys.modules if is_shim(sys.modules[m]))
    from agent.auxiliary_wire import prepare_chat_messages
    from agent.chat_completion_helpers import _is_sse_connection_error
    from agent.transports.httpx_client import AsyncSdkFreeClient, ProviderStreamError
    messages = [{"role": "user", "content": "x"}, {"role": "assistant", "content": "y",
                "reasoning_details": [{"type": "reasoning.text", "text": "r"}]}]
    out["hygiene"] = [prepare_chat_messages(c, {"model": "m", "messages": messages})["messages"] is not messages
                      for c in (aux, AsyncSdkFreeClient(aux), object())]
    out["sse_drop"] = _is_sse_connection_error(ProviderStreamError("Network connection lost.", body=None))
    bridge = sys.modules["agent.acp_openai_bridge"]
    call = bridge.ChatCompletionMessageToolCall(id="c1", type="function",
                                                function=bridge.Function(name="f", arguments="{}"))
    out["tool_call"] = [call.id, call.function.name]
    out["connector_rpcs"] = sorted(tui_gateway.server._CONNECTOR_RPC_METHODS)
    print(json.dumps(out), file=RESULT, flush=True)
''')


def test_the_phone_path_runs_without_any_sdk_or_pydantic(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    (home / "config.yaml").write_text(json.dumps({"agent": {"provider_sdks": False},
                                                  "tui_gateway": {"pydantic_contracts": False}}), encoding="utf-8")
    env = {**os.environ, "HERMES_HOME": str(home), "PYTHONPATH": str(REPO)}
    result = subprocess.run([sys.executable, "-c", CHILD], cwd=REPO, env=env, capture_output=True, text=True,
                            timeout=240)
    assert result.returncode == 0, result.stderr[-4000:]
    out = json.loads(result.stdout.strip().splitlines()[-1])
    assert out["loaded"] == []
    assert out["shim"] == ["openai", "openai.types", "openai.types.chat",
                           "openai.types.chat.chat_completion_message_tool_call"]
    assert out["hygiene"] == [True, True, False]  # the SDK-free clients are the chat wire; object() is not
    assert out["sse_drop"] is True  # an in-stream drop is the shim's openai.APIError
    assert out["tool_call"] == ["c1", "f"]
    assert out["connector_rpcs"] == []  # the seam's stand-in: no connector method is served
    assert (out["codex"], out["anthropic"], out["aux"], out["aux_async"]) == (
        "SdkFreeClient", "SdkFreeAnthropicClient", "SdkFreeClient", "AsyncSdkFreeClient")
    assert "zz_unknown: Extra inputs are not permitted" in out["unknown_key"]
    assert out["admits_profile"] is True
