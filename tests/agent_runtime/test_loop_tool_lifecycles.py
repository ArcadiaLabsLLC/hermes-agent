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
                                "tools.computer_use.tool", "tools.browser_tool_cloud",
                                "tools.environments.local"]  # blocked here; file_tools is not
    assert report["loaded"] == []


def test_an_installation_that_ships_the_lifecycles_gets_no_placeholder():
    import tools.terminal_tool_lifecycle as real

    from agent_runtime.loop_tool_lifecycles import ensure_lifecycle_placeholders, is_lifecycle_placeholder

    assert ensure_lifecycle_placeholders() == ()
    assert sys.modules["tools.terminal_tool_lifecycle"] is real and not is_lifecycle_placeholder(real)


_UPSTREAM_IMPORTERS_CHILD = r'''
import json, sys
OFF = ("tools.environments", "tools.tts_tool_local", "hermes_cli.local_runtime")

class Absent:
    def find_spec(self, name, path=None, target=None):
        if name.startswith(OFF):
            raise ModuleNotFoundError(f"switched off: {name}", name=name)

sys.meta_path.insert(0, Absent())
out = {}
if sys.argv[1] == "control":
    try:
        import agent.transports.codex_app_server  # noqa: F401
        out["imported"] = True
    except ModuleNotFoundError as exc:
        out["imported"], out["missing"] = False, exc.name
    print(json.dumps(out)); raise SystemExit
from agent_runtime.loop_tool_lifecycles import LifecycleNotShipped, ensure_lifecycle_placeholders
out["placed"] = sorted(m for m in ensure_lifecycle_placeholders() if m.startswith(OFF))
import agent.copilot_acp_client as acp, agent.transports.codex_app_server as app_server
import tools.tts_tool_lifecycle as tts_lifecycle, tools.tts_tool  # noqa: F401
from agent.image_routing import _probe_managed_runtime
out["managed_probe"] = _probe_managed_runtime("custom", "m", {})
out["model_caches"] = dict(tts_lifecycle._LOCAL_TTS_MODEL_CACHES)
for name, fn in (("acp", acp.hermes_subprocess_env), ("app_server", app_server.hermes_subprocess_env)):
    try:
        fn()
        out[name] = "ran"
    except LifecycleNotShipped:
        out[name] = "refused"
print(json.dumps(out))
'''


def _run_importers_child(mode: str, tmp_path) -> dict:
    proc = subprocess.run(
        [sys.executable, "-c", _UPSTREAM_IMPORTERS_CHILD, mode], cwd=REPO_ROOT, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=240,
        env={**__import__("os").environ, "HERMES_HOME": str(tmp_path), "PYTHONPATH": str(REPO_ROOT)})
    assert proc.returncode == 0, proc.stderr[-4000:]
    return json.loads(proc.stdout.strip().splitlines()[-1])


def test_upstream_importers_of_a_switched_off_module_load_on_its_stand_in_unedited(tmp_path):
    """``agent.copilot_acp_client``, ``agent.transports.codex_app_server``, ``tools.tts_tool(_lifecycle)``
    and ``agent.image_routing`` carry upstream's bytes: with the environments package, the local TTS
    engines and the local runtime absent, they load on the stand-ins and answer as the absent feature
    does — no managed local runtime, no model cache, and a loud refusal to start a child process.

    Positive control: without the stand-ins the same child cannot import the app-server transport, so
    the block is real and the stand-in is what carries the load.
    Killing mutation (recorded in the commit): drop ``LOCAL_ENVIRONMENT`` from ``_LOOP_NAMES`` -> red."""
    control = _run_importers_child("control", tmp_path)
    assert control == {"imported": False, "missing": "tools.environments"}

    out = _run_importers_child("seam", tmp_path)
    assert out["placed"] == ["hermes_cli.local_runtime.capabilities", "tools.environments.local",
                             "tools.tts_tool_local"]
    assert out["managed_probe"] is None
    assert out["model_caches"] == {}
    assert out["acp"] == out["app_server"] == "refused"


_FORK_SEAMS_CHILD = r'''
import json, sys
OFF = ("agent_runtime.git_cmd",)

class Absent:
    def find_spec(self, name, path=None, target=None):
        if name in OFF or name.startswith(tuple(m + "." for m in OFF)):
            raise ModuleNotFoundError(f"switched off: {name}", name=name)

sys.meta_path.insert(0, Absent())
out = {}
if sys.argv[1] == "control":
    for module in ("agent_runtime.build_stamp", "agent_runtime.repo_context"):
        try:
            __import__(module)
            out[module] = "imported"
        except ModuleNotFoundError as exc:
            out[module] = exc.name
    print(json.dumps(out)); raise SystemExit
from agent_runtime.loop_tool_lifecycles import LifecycleNotShipped, ensure_lifecycle_placeholders
out["placed"] = sorted(m for m in ensure_lifecycle_placeholders() if m in OFF)
import agent_runtime.build_stamp, agent_runtime.repo_context  # noqa: F401,E401
from agent_runtime.build_identity import code_tree_for
out["code_tree"] = code_tree_for(sys.argv[2]).reason
for name, call in (("run_git", lambda: agent_runtime.build_stamp.run_git(["status"])),
                   ("repo_context", lambda: agent_runtime.repo_context._run_git_quiet(sys.argv[2], ["git", "status"]))):
    try:
        call()
        out[name] = "ran"
    except LifecycleNotShipped:
        out[name] = "refused"
print(json.dumps(out))
'''


def test_the_fork_git_chokepoint_loads_on_its_stand_in(tmp_path):
    """Phone-gate lane G2: ``agent_runtime.git_cmd`` (the one fork git door) is switched off on the
    phone; its module-level importers load on the stand-in, a git call refuses loudly, and the build
    identity still never raises (it reads the refusal as ``git_error``).

    Positive control: without the stand-in the same child cannot import the build stamp or repo context.
    Killing mutation (recorded in the commit): drop ``GIT_COMMAND`` from ``_LOOP_NAMES`` -> red."""
    control = _run_seams_child("control", tmp_path)
    assert control == {"agent_runtime.build_stamp": "agent_runtime.git_cmd",
                       "agent_runtime.repo_context": "agent_runtime.git_cmd"}

    out = _run_seams_child("seam", tmp_path)
    assert out["placed"] == ["agent_runtime.git_cmd"]
    assert out["code_tree"] == "git_error"
    assert out["run_git"] == out["repo_context"] == "refused"


def _run_seams_child(mode: str, tmp_path) -> dict:
    proc = subprocess.run(
        [sys.executable, "-c", _FORK_SEAMS_CHILD, mode, str(REPO_ROOT)], cwd=REPO_ROOT, capture_output=True,
        text=True, encoding="utf-8", errors="replace", timeout=240,
        env={**__import__("os").environ, "HERMES_HOME": str(tmp_path), "PYTHONPATH": str(REPO_ROOT)})
    assert proc.returncode == 0, proc.stderr[-4000:]
    return json.loads(proc.stdout.strip().splitlines()[-1])


_VAULT_CHILD = r'''
import json, sys
OFF = ("agent.vault_store", "agent.vault_backends")

class Absent:
    def find_spec(self, name, path=None, target=None):
        if name in OFF or name.startswith(tuple(m + "." for m in OFF)):
            raise ModuleNotFoundError(f"switched off: {name}", name=name)

sys.meta_path.insert(0, Absent())
out = {}
if sys.argv[1] == "control":
    try:
        from agent.vault_backends import unlock  # noqa: F401
        out["unlock"] = "imported"
    except ModuleNotFoundError as exc:
        out["unlock"] = exc.name
    print(json.dumps(out)); raise SystemExit
from agent_runtime.loop_tool_lifecycles import LifecycleNotShipped, ensure_lifecycle_placeholders
out["placed"] = sorted(m for m in ensure_lifecycle_placeholders() if m.startswith(OFF))
from agent.vault_backends import unlock
from agent.vault_backends.unlock import set_unlock_prompt_callback
from tools.thread_context import _callback_api
set_unlock_prompt_callback(lambda *a: "pw")
out["prompt"] = unlock.get_unlock_prompt_callback()
out["pairs"] = len(_callback_api())
unlock.release_session("s1")
for name, call in (("enabled_backends", lambda: __import__("agent.vault_backends", fromlist=["x"]).enabled_backends()),
                   ("vault_store", lambda: __import__("agent.vault_store", fromlist=["x"]).get_vault_store()),
                   ("lock", lambda: unlock.lock())):
    try:
        call()
        out[name] = "ran"
    except LifecycleNotShipped:
        out[name] = "refused"
print(json.dumps(out))
'''


def test_the_turn_wires_no_password_manager_where_the_vault_is_switched_off(tmp_path):
    """Owner decision D3 (2026-09-30): the phone drops ``agent.vault_store`` and ``agent.vault_backends``.
    Every turn still wires the managers' prompt callbacks (``tui_gateway.agent_callbacks``,
    ``tools.thread_context``) and a session's end releases its unlocks: on the stand-in there is no
    manager to prompt for, and the store and the managers refuse loudly (the ``vault.*`` RPCs).

    Positive control: without the stand-in the same child cannot import the unlock callbacks.
    Killing mutation: drop ``VAULT_UNLOCK`` from ``_LOOP_NAMES`` -> red."""
    control = _run_vault_child("control", tmp_path)
    assert control == {"unlock": "agent.vault_backends"}

    out = _run_vault_child("seam", tmp_path)
    assert out["placed"] == ["agent.vault_backends", "agent.vault_backends.base", "agent.vault_backends.unlock",
                             "agent.vault_store"]
    assert out["prompt"] is None and out["pairs"] == 5
    assert out["enabled_backends"] == out["vault_store"] == out["lock"] == "refused"


def _run_vault_child(mode: str, tmp_path) -> dict:
    proc = subprocess.run(
        [sys.executable, "-c", _VAULT_CHILD, mode], cwd=REPO_ROOT, capture_output=True,
        text=True, encoding="utf-8", errors="replace", timeout=240,
        env={**__import__("os").environ, "HERMES_HOME": str(tmp_path), "PYTHONPATH": str(REPO_ROOT)})
    assert proc.returncode == 0, proc.stderr[-4000:]
    return json.loads(proc.stdout.strip().splitlines()[-1])
