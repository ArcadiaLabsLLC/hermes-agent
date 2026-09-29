"""Upstream's agent loop runs a turn with no provider SDK and no desktop tool lifecycle.

Embedded-hermes plan Stage 2 step 7: the phone path is a SEAM on upstream's own loop
(the lifecycle placeholders of ``agent_runtime.loop_tool_lifecycles`` + the SDK-free
client), never a second loop and no edit to the loop.
The proof runs ``AIAgent.run_conversation`` in a fresh interpreter where ``openai``,
``anthropic``, ``psutil``, ``pty`` and the terminal / browser / process / code-execution
tool modules cannot be imported — what the phone wheel leaves out — against a local
SSE server, once with no tools and once with the one safe tool ``todo_list``.

Positive controls, inside the child: the blocker really refuses ``import openai``, the
tool turn really executed ``todo_list`` (its JSON result reached the second request),
both placeholders were placed (so the real lifecycles were absent, not merely unused),
and nothing unshipped was loaded behind the seam's back. A second test pins the
desktop side: with the real modules installed, nothing is placed.

Killing mutations (applied, red recorded, reverted — see the commit message):

* ``ensure_lifecycle_placeholders`` places nothing                        -> red (run_agent cannot import).
* ``sdk_free_client`` returns ``None`` (the SDK path)                       -> red.
* the placeholder's ``get_active_env`` raises ``LifecycleNotShipped``       -> red (the tool turn fails).
* no ``tools.delegate_tool`` placeholder                                    -> red (the tool round fails).
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

_CHILD = r'''
import json, os, sys, threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

UNSHIPPED = ("openai", "anthropic", "psutil", "pty")
UNSHIPPED_TOOLS = ("tools.terminal_tool", "tools.browser", "tools.environments", "tools.process_registry",
                   "tools.code_execution", "tools.computer_use", "tools.delegate_tool")

class NotShipped:
    def find_spec(self, name, path=None, target=None):
        if name.split(".")[0] in UNSHIPPED or name.startswith(UNSHIPPED_TOOLS):
            raise ModuleNotFoundError(f"not shipped: {name}", name=name)

sys.meta_path.insert(0, NotShipped())
try:
    import openai  # noqa: F401
    raise SystemExit("control failed: openai imported")
except ModuleNotFoundError:
    pass

home = sys.argv[1]
with open(os.path.join(home, "config.yaml"), "w", encoding="utf-8") as handle:
    json.dump({"agent": {"provider_sdks": False}, "tools": {"tool_search": {"enabled": "off"}}}, handle)

requests = []

def sse(*chunks):
    return "".join("data: " + json.dumps(c) + "\n\n" for c in chunks) + "data: [DONE]\n\n"

def chunk(delta, finish=None):
    return {"id": "c", "model": "m", "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}

USAGE = {"id": "c", "model": "m", "choices": [], "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5}}
CALL = {"index": 0, "id": "call_1", "type": "function", "function": {"name": "todo_list", "arguments": "{}"}}

class Provider(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if not self.path.endswith("/chat/completions"):
            self.send_response(404); self.end_headers(); return
        requests.append(body)
        wants_tool = any(t["function"]["name"] == "todo_list" for t in body.get("tools") or [])
        if wants_tool and body["messages"][-1]["role"] == "user":
            out = sse(chunk({"role": "assistant", "tool_calls": [CALL]}), chunk({}, "tool_calls"), USAGE)
        else:
            out = sse(chunk({"role": "assistant", "content": "all "}), chunk({"content": "done"}, "stop"), USAGE)
        data = out.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

server = ThreadingHTTPServer(("127.0.0.1", 0), Provider)
threading.Thread(target=server.serve_forever, daemon=True).start()

from agent_runtime.loop_tool_lifecycles import ensure_lifecycle_placeholders, is_lifecycle_placeholder

placed = ensure_lifecycle_placeholders()
from run_agent import AIAgent

def turn(toolsets):
    before = len(requests)
    agent = AIAgent(base_url=f"http://127.0.0.1:{server.server_port}/v1", api_key="phone-key", provider="custom",
                    model="m", enabled_toolsets=toolsets, quiet_mode=True, skip_memory=True, skip_context_files=True)
    result = agent.run_conversation("hello")
    sent = requests[before:]
    return {
        "client": type(agent.client).__name__,
        "final": result.get("final_response"),
        "tools": [t["function"]["name"] for t in sent[0].get("tools") or []],
        "roles": [m["role"] for m in sent[-1]["messages"]],
        "tool_results": [m.get("content") for m in sent[-1]["messages"] if m["role"] == "tool"],
    }

print(json.dumps({
    "plain": turn(["clarify"]),
    "tool": turn(["todo"]),
    "placed": list(placed),
    "loaded": sorted(m for m, mod in sys.modules.items()
                     if (m.split(".")[0] in UNSHIPPED or m.startswith(UNSHIPPED_TOOLS)) and not is_lifecycle_placeholder(mod)),
}))
'''


def test_the_loop_runs_a_turn_without_sdks_or_desktop_tool_lifecycles(tmp_path):
    proc = subprocess.run(
        [sys.executable, "-c", _CHILD, str(tmp_path)], cwd=REPO_ROOT, capture_output=True, text=True,
        encoding="utf-8", errors="replace",
        timeout=240, env={**__import__("os").environ, "HERMES_HOME": str(tmp_path), "PYTHONPATH": str(REPO_ROOT)},
    )
    assert proc.returncode == 0, proc.stderr[-4000:]
    report = json.loads(proc.stdout.strip().splitlines()[-1])

    plain, tool = report["plain"], report["tool"]
    assert plain["client"] == tool["client"] == "SdkFreeClient"
    assert plain["final"] == tool["final"] == "all done"
    assert "todo_list" not in plain["tools"] and plain["roles"] == ["system", "user"]
    assert "todo_list" in tool["tools"]
    assert tool["roles"] == ["system", "user", "assistant", "tool"]
    assert json.loads(tool["tool_results"][0])["todos"] == []  # the safe tool really ran
    assert report["placed"] == ["tools.terminal_tool_lifecycle", "tools.browser_tool_lifecycle", "tools.delegate_tool",
                                "tools.computer_use.tool", "tools.browser_tool_cloud"]  # blocked here; file_tools is not
    assert report["loaded"] == []


def test_an_installation_that_ships_the_lifecycles_gets_no_placeholder():
    import tools.terminal_tool_lifecycle as real

    from agent_runtime.loop_tool_lifecycles import ensure_lifecycle_placeholders, is_lifecycle_placeholder

    assert ensure_lifecycle_placeholders() == ()
    assert sys.modules["tools.terminal_tool_lifecycle"] is real and not is_lifecycle_placeholder(real)
