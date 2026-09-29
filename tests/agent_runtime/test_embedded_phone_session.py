"""The phone entry end to end: the embedded serve over the in-memory transport, a fake host store.

Embedded-hermes plan Stage 2 exit ("against the fake host store, no secret and no chat text is
on disk in plaintext"), proven through the entry the phone shim calls rather than through each
seam on its own. One app folder, the ``bundled-phone`` profile's config, a fake host secure
store bound over the folder; then, over ``EmbeddedServe`` frames only:

1. ``runtime.provider.signin.*`` signs in a fake provider — the in-process runner
   (``auth.subprocess_signin: false``) runs the provider's driver, which saves the key
   through Hermes's own ``.env`` writer (the host-store seam);
2. ``runtime.conversation.open`` / ``send`` / ``read`` runs one chat turn — the in-process
   worker (``conversations.subprocess_worker: false``) and the SDK-free client
   (``agent.provider_sdks: false``) against a loopback provider, which must receive the key;
3. a byte scan of the whole app folder finds neither the key nor a word of the chat.

POSITIVE CONTROLS: the key reached the provider and sits in the host store's slots; the chat
reached the provider and the state DB the scan read decrypts (through the bound store) to a
transcript carrying it — so the scan looked where the bytes are. No Hermes process was started
(the gateway's git branch probe is the one named spawn left; see the assertion).

The entry's refusals: unbound, ``EmbeddedServe.start`` raises ``HostStoreNotBound`` and writes
nothing; a binding whose root does not hold the Hermes home raises ``OutsideStoreRoot``; the
loop's lifecycle placeholders are registered before the serve thread exists.

Killing mutations (applied, red recorded, reverted — see the commit message).
"""

from __future__ import annotations

import json
import os
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
import yaml

from agent_runtime.host_store import binding
from agent_runtime.host_store.fake import FakeHostSecureStore
from hermes_cli.harness_parts.serve.in_memory import EmbeddedServe, app_folder_environment

pytestmark = pytest.mark.timeout(180)

SECRET = "phone-e2e-provider-key-4c7a"
CHAT = "saffron-lighthouse-cadenza"
REPLY = "vermilion-harbour-sonnet"
NEEDLES = (SECRET, CHAT, REPLY)
KEY_ENV = "PHONE_E2E_PROVIDER_KEY"
PROVIDER = "phone-test"


class Provider(BaseHTTPRequestHandler):
    requests: list = []

    def log_message(self, *_):
        pass

    def do_GET(self):
        self._send("application/json", json.dumps({"object": "list", "data": [{"id": "test-model"}]}).encode())

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.requests.append((self.headers.get("Authorization"), body))
        base = {"id": "r", "object": "chat.completion.chunk", "created": 1, "model": "test-model"}
        rows = [{**base, "choices": [{"index": 0, "delta": {"role": "assistant", "content": REPLY},
                                      "finish_reason": None}]},
                {**base, "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                 "usage": {"prompt_tokens": 12, "completion_tokens": 3, "total_tokens": 15}}]
        self._send("text/event-stream", ("".join("data: " + json.dumps(r) + "\n\n" for r in rows)
                                         + "data: [DONE]\n\n").encode())

    def _send(self, kind, data):
        self.send_response(200)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


class Frames:
    """The host side of the in-memory pipe: every frame, and a wait for a reply by id."""

    def __init__(self) -> None:
        self.frames: list[dict] = []
        self._cond = threading.Condition()

    def on_frame(self, line: str) -> None:
        if not line:
            return
        with self._cond:
            self.frames.append(json.loads(line))
            self._cond.notify_all()

    def wait_for(self, match, timeout: float = 60.0) -> dict:
        deadline = time.monotonic() + timeout
        with self._cond:
            while True:
                found = next((f for f in self.frames if match(f)), None)
                if found is not None:
                    return found
                left = deadline - time.monotonic()
                assert left > 0, f"no matching frame; last frames: {self.frames[-5:]}"
                self._cond.wait(left)


class Phone:
    def __init__(self, serve: EmbeddedServe, frames: Frames) -> None:
        self.serve, self.frames, self._n = serve, frames, 0

    def call(self, method: str, params: dict) -> dict:
        self._n += 1
        rid = f"r{self._n}"
        self.serve.send(json.dumps({"jsonrpc": "2.0", "id": rid, "method": method, "params": params}))
        frame = self.frames.wait_for(lambda f: f.get("id") == rid and ("result" in f or "error" in f))
        assert "result" in frame, frame
        return frame["result"]


@pytest.fixture()
def app(tmp_path, monkeypatch):
    from agent_runtime import provider_signin

    # Named gap: ``tools.process_registry``'s import-time recovery opens ``state.db`` with raw sqlite
    # (``tools/async_delegation.py``) — when a background import wins the race against the sealed
    # store, the history becomes a plaintext database. The phone wheel does not ship the module,
    # but the loop and the in-process gateway still import it (and the rest of the switched-off
    # tree) on the turn path — runtime-queue rows filed by lane p1-hint. Imported here, BEFORE the
    # app folder exists, so its side effect lands in the test's own home and the run is deterministic.
    import tools.process_registry  # noqa: F401

    app_dir = tmp_path / "app"
    for name, value in app_folder_environment(app_dir).items():
        Path(value).mkdir(parents=True, exist_ok=True)
        monkeypatch.setenv(name, value)
    monkeypatch.delenv(KEY_ENV, raising=False)
    monkeypatch.setattr(provider_signin, "_REGISTRY", None)  # the registry binds the profile's runner
    binding.unbind_host_store()
    yield app_dir
    binding.unbind_host_store()


def _phone_config(home: Path, port: int) -> None:
    from agent_runtime.bundle_profiles.manifest import apply_to_config, load_profile

    base = {"model": {"default": "test-model", "provider": f"custom:{PROVIDER}"},
            "providers": {PROVIDER: {"api": f"http://127.0.0.1:{port}/v1", "key_env": KEY_ENV}},
            "dashboard": {"turn_isolation": False}, "mcp_servers": {}}
    (home / "config.yaml").write_text(yaml.safe_dump(apply_to_config(load_profile("bundled-phone"), base)),
                                      encoding="utf-8")


def _sign_in_driver(verify, flow):
    """The fake provider's grant: show a device code, then save the key the way Hermes saves one."""
    from hermes_cli import config

    verify("https://provider.example/device", "PHON-E2E1")
    config.save_env_value(KEY_ENV, SECRET)


def _leaks(root: Path) -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    for path in root.rglob("*"):
        if path.is_file():
            data = path.read_bytes()
            for needle in NEEDLES:
                if needle.encode("utf-8") in data or needle.encode("utf-16-le") in data:
                    found.setdefault(needle, []).append(path.relative_to(root).as_posix())
    return found


def _no_spawn(monkeypatch) -> list:
    spawned: list = []
    real_popen = subprocess.Popen

    def recording_popen(*args, **kwargs):
        spawned.append(args[0] if args else kwargs.get("args"))
        return real_popen(*args, **kwargs)

    monkeypatch.setattr(subprocess, "Popen", recording_popen)
    return spawned


def _settle(phone: Phone, ids: dict, session_id: str, turn_id: str) -> dict:
    deadline = time.monotonic() + 90
    while True:
        result = phone.call("runtime.conversation.read", {**ids, "session_id": session_id, "turn_id": turn_id})
        if result["turn"]["state"] not in {"dispatching", "running"}:
            return result
        assert time.monotonic() < deadline, "the in-process turn did not settle"
        time.sleep(.05)


def test_sign_in_and_one_chat_turn_leave_no_secret_and_no_chat_text_on_disk(app, monkeypatch):
    from hermes_cli import provider_browser_login as wire

    home = Path(os.environ["HERMES_HOME"])
    Provider.requests = []
    provider = ThreadingHTTPServer(("127.0.0.1", 0), Provider)
    threading.Thread(target=provider.serve_forever, daemon=True).start()
    _phone_config(home, provider.server_port)
    monkeypatch.setitem(wire._DRIVERS, PROVIDER, _sign_in_driver)
    store = FakeHostSecureStore()
    store.bind(profile="phone-e2e", store_root=app)
    spawned = _no_spawn(monkeypatch)

    frames = Frames()
    serve = EmbeddedServe(frames.on_frame)
    serve.start()
    phone = Phone(serve, frames)
    try:
        ready = frames.wait_for(lambda f: f.get("event") == "ready")
        install_id = ready["install"]["install_id"]
        assert install_id

        login = phone.call("runtime.provider.signin.begin", {"provider": PROVIDER})
        deadline = time.monotonic() + 30
        while (view := phone.call("runtime.provider.signin.poll", {"login_id": login["login_id"]}))["state"] \
                not in {"succeeded", "failed", "cancelled"}:
            assert time.monotonic() < deadline, view
            time.sleep(.05)
        assert view["state"] == "succeeded", view
        os.environ.pop(KEY_ENV, None)  # the chat must find the key through the host store, not this process

        ids = {"install_id": install_id, "client_scope": "phone-account", "profile": "default"}
        opened = phone.call("runtime.conversation.open", {**ids, "key": "chat", "cwd": str(app),
                                                          "profile_home": str(home)})
        sid = opened["session_id"]
        phone.call("runtime.conversation.send", {**ids, "session_id": sid, "turn_id": "turn-1",
                                                 "prompt": {"text": f"Please remember {CHAT}", "images": []}})
        result = _settle(phone, ids, sid, "turn-1")
        assert result["turn"]["state"] == "completed", json.dumps(result)[-3000:]
        done = [e["frame"]["params"]["payload"] for e in result["events"]
                if e["turn_id"] == "turn-1" and e["frame"].get("params", {}).get("type") == "message.complete"]
        assert done and done[-1]["text"] == REPLY
    finally:
        serve.close()
        exit_code = serve.wait(60)
        provider.shutdown()
        provider.server_close()
    assert exit_code is not None, "the embedded serve did not end at EOF"

    # Positive controls: the key and the chat really travelled, and the history the scan reads holds them.
    chat = [(auth, body) for auth, body in Provider.requests if CHAT in json.dumps(body)]
    assert chat and all(auth == f"Bearer {SECRET}" for auth, _ in chat)
    assert any(SECRET.encode() in value for value in store.slots.values())
    assert (home / "state.db").is_file() and (home / "state.db").stat().st_size > 0
    from hermes_state import SessionDB

    db = SessionDB(home / "state.db")
    try:
        transcript = json.dumps([db.get_messages(row["id"]) for row in db.list_sessions_rich(limit=10)])
    finally:
        db.close()
    assert CHAT in transcript and REPLY in transcript

    # No Hermes child: no worker subprocess, no `hermes auth login`, no python/pip probe. The one
    # spawn left is the native gateway's git branch probe (tui_gateway/git_probe.py), which has no
    # switch yet — a named gap, filed in the runtime queue (lane p1-hint), not a pass.
    assert all(argv and Path(str(argv[0])).stem.lower() == "git" for argv in spawned), spawned
    assert _leaks(app) == {}


def test_an_unbound_host_store_is_refused_before_any_request(app):
    home = Path(os.environ["HERMES_HOME"])
    serve = EmbeddedServe(lambda _line: None)
    with pytest.raises(binding.HostStoreNotBound):
        serve.start()
    serve.send(json.dumps({"jsonrpc": "2.0", "id": "x", "method": "runtime.map.list", "params": {}}))
    assert [p for p in app.rglob("*") if p.is_file()] == []  # nothing served, nothing written
    assert not (home / "state.db").exists()

    # A binding whose root does not hold the Hermes home gives its secret files no slot.
    FakeHostSecureStore().bind(profile="elsewhere", store_root=app.parent / "not-the-app")
    with pytest.raises(binding.OutsideStoreRoot):
        EmbeddedServe(lambda _line: None).start()
    binding.unbind_host_store()

    # Positive control: bound over the app folder, the same entry serves.
    FakeHostSecureStore().bind(profile="phone", store_root=app)
    frames = Frames()
    serve = EmbeddedServe(frames.on_frame)
    serve.start()
    serve.close()
    assert serve.wait(60) is not None
    assert any(f.get("event") == "ready" for f in frames.frames)


def test_the_loop_placeholders_are_registered_before_the_serve_thread(app, monkeypatch):
    from agent_runtime import loop_tool_lifecycles

    seen: list = []
    monkeypatch.setattr(loop_tool_lifecycles, "ensure_lifecycle_placeholders",
                        lambda: seen.append(threading.active_count()) or ())
    FakeHostSecureStore().bind(profile="phone", store_root=app)
    threads_before = threading.active_count()
    serve = EmbeddedServe(lambda _line: None)
    serve.start()
    serve.close()
    assert serve.wait(60) is not None
    assert seen == [threads_before]
