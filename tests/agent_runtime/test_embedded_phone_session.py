"""The phone entry end to end: the embedded serve over the in-memory transport, a fake host store.

Embedded-hermes plan Stage 2 exit, as amended by the owner ruling of 2026-09-30 ("no secret is on
disk in plaintext; the chat history is upstream's files under the OS's file protection"), proven
through the entry the phone shim calls rather than through each seam on its own. One app folder, the ``bundled-phone`` profile's config, a fake host secure
store bound over the folder; then, over ``EmbeddedServe`` frames only:

1. ``runtime.provider.signin.*`` signs in a fake provider — the in-process runner
   (``auth.subprocess_signin: false``) runs the provider's driver, which saves the key
   through Hermes's own ``.env`` writer (the host-store seam);
2. ``runtime.conversation.open`` / ``send`` / ``read`` runs one chat turn — the in-process
   worker (``conversations.subprocess_worker: false``) and the SDK-free client
   (``agent.provider_sdks: false``) against a loopback provider, which must receive the key;
3. a byte scan of the whole app folder finds no key, and the host was asked to protect the
   Hermes home (``protect_history_dir``) before the serve ran.

POSITIVE CONTROLS: the key reached the provider and sits in the host store's slots; the chat
reached the provider and the same byte scan FINDS it in the history (upstream's state DB), so
the scan looked where the bytes are. No Hermes process was started
(the gateway's git branch probe is the one named spawn left; see the assertion).

The entry's refusals: unbound, ``EmbeddedServe.start`` raises ``HostStoreNotBound`` and writes
nothing; a binding whose root does not hold the Hermes home raises ``OutsideStoreRoot``; a
binding with no ``protect_history_dir`` raises ``HistoryProtectionMissing``; the loop's lifecycle placeholders are registered before the serve thread exists.

Killing mutations (applied, red recorded, reverted — see the commit message).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from agent_runtime.host_store import binding
from agent_runtime.host_store.fake import FakeHostSecureStore
from hermes_cli.harness_parts.serve.in_memory import EmbeddedServe, app_folder_environment

pytestmark = pytest.mark.timeout(180)

REPO_ROOT = Path(__file__).resolve().parents[2]

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
    config = apply_to_config(load_profile("bundled-phone"), base)
    # Hermes's own YAML writer: the test environment carries Hermes's dependencies, which do not
    # include PyYAML (the file errored at import under scripts/run_tests.sh).
    from hermes_yaml import safe_dump

    (home / "config.yaml").write_text(safe_dump(config), encoding="utf-8")


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


def _settle(phone: Phone, ids: dict, session_id: str, turn_id: str) -> dict:
    deadline = time.monotonic() + 90
    while True:
        result = phone.call("runtime.conversation.read", {**ids, "session_id": session_id, "turn_id": turn_id})
        if result["turn"]["state"] not in {"dispatching", "running"}:
            return result
        assert time.monotonic() < deadline, "the in-process turn did not settle"
        time.sleep(.05)


def _sign_in(phone: Phone) -> None:
    login = phone.call("runtime.provider.signin.begin", {"provider": PROVIDER})
    deadline = time.monotonic() + 30
    while (view := phone.call("runtime.provider.signin.poll", {"login_id": login["login_id"]}))["state"] \
            not in {"succeeded", "failed", "cancelled"}:
        assert time.monotonic() < deadline, view
        time.sleep(.05)
    assert view["state"] == "succeeded", view


def _chat_turn(phone: Phone, install_id: str, app: Path, home: Path) -> dict:
    ids = {"install_id": install_id, "client_scope": "phone-account", "profile": "default"}
    opened = phone.call("runtime.conversation.open", {**ids, "key": "chat", "cwd": str(app),
                                                      "profile_home": str(home)})
    sid = opened["session_id"]
    phone.call("runtime.conversation.send", {**ids, "session_id": sid, "turn_id": "turn-1",
                                             "prompt": {"text": f"Please remember {CHAT}", "images": []}})
    return _settle(phone, ids, sid, "turn-1")


def _what_the_turn_left(home: Path, store: FakeHostSecureStore) -> dict:
    """Read back the history the byte scan covers, and what the host was asked to protect."""
    from hermes_state import SessionDB

    db = SessionDB(home / "state.db")
    try:
        transcript = json.dumps([db.get_messages(row["id"]) for row in db.list_sessions_rich(limit=10)])
    finally:
        db.close()
    return {
        "chat_auth": [auth for auth, body in Provider.requests if CHAT in json.dumps(body)],
        "key_in_store": any(SECRET.encode() in value for value in store.slots.values()),
        "state_db_bytes": (home / "state.db").stat().st_size if (home / "state.db").is_file() else 0,
        "transcript": [needle for needle in (CHAT, REPLY) if needle in transcript],
        "protected": list(store.protected),
        "home": str(home),
    }


def phone_turn(app: Path) -> dict:
    """Sign in and run one chat turn over ``EmbeddedServe`` frames; report what the turn left.

    Runs in the child interpreter the test starts (:data:`_CHILD`), so the phone wheel's absent
    modules are really absent and nothing an earlier test imported is already loaded.
    """
    from agent_runtime import provider_signin
    from hermes_cli import provider_browser_login as wire

    for name, value in app_folder_environment(app).items():
        Path(value).mkdir(parents=True, exist_ok=True)
        os.environ[name] = value
    os.environ.pop(KEY_ENV, None)
    provider_signin._REGISTRY = None
    home = Path(os.environ["HERMES_HOME"])
    Provider.requests = []
    provider = ThreadingHTTPServer(("127.0.0.1", 0), Provider)
    threading.Thread(target=provider.serve_forever, daemon=True).start()
    _phone_config(home, provider.server_port)
    wire._DRIVERS[PROVIDER] = _sign_in_driver
    store = FakeHostSecureStore()
    store.bind(profile="phone-e2e", store_root=app)
    spawned: list = []
    real_popen = subprocess.Popen

    class RecordingPopen(real_popen):  # a class: asyncio's Windows loop subclasses subprocess.Popen at import
        def __init__(self, args, *rest, **kwargs):
            spawned.append(str(args))
            super().__init__(args, *rest, **kwargs)

    subprocess.Popen = RecordingPopen
    frames = Frames()
    serve = EmbeddedServe(frames.on_frame)
    serve.start()
    phone = Phone(serve, frames)
    try:
        install_id = frames.wait_for(lambda f: f.get("event") == "ready")["install"]["install_id"]
        assert install_id
        _sign_in(phone)
        os.environ.pop(KEY_ENV, None)  # the chat must find the key through the host store, not this process
        result = _chat_turn(phone, install_id, app, home)
    finally:
        serve.close()
        exit_code = serve.wait(60)
        provider.shutdown()
        provider.server_close()
        subprocess.Popen = real_popen
    done = [e["frame"]["params"]["payload"] for e in result["events"]
            if e["turn_id"] == "turn-1" and e["frame"].get("params", {}).get("type") == "message.complete"]
    return {"turn": result["turn"]["state"], "turn_tail": json.dumps(result)[-3000:],
            "reply": done[-1]["text"] if done else None, "exit_code": exit_code, "spawned": spawned,
            **_what_the_turn_left(home, store)}


#: The child. ``phone``: its only first-party tree is the phone wheel's app tree
#: (:func:`_stage_phone_wheel`) — directory scans (the tool registry, the plugin loader) see only the
#: files the wheel ships, and with no ``.git`` nothing asks ``git`` for Hermes's version. A finder on
#: top records every import of a switched-off module outside a ``find_spec`` presence probe, with the
#: line that made it — a turn that swallows the ImportError still reached into the switched-off
#: tree. ``full``: the checkout, every module installed, the version primed as a wheel's stamp.
_CHILD = r"""
import json, sys
from pathlib import Path

app, test_file, wheel, checkout = Path(sys.argv[1]), sys.argv[2], sys.argv[3], Path(sys.argv[4]).resolve()
OFF = tuple(json.loads(sys.argv[5]))
root = Path.cwd().resolve()
if sys.platform == "win32":
    # CPython's platform module asks WMI for the Windows version and, when WMI times out on a busy
    # box, spawns `cmd /c ver` -- a process the `spawned == []` assertion then (rightly) sees. The
    # version is a test-host fact, not the turn's: read it without a subprocess (2 of ~11 runs).
    import platform as _platform

    def _ver_without_a_subprocess(system="", release="", version="", supported_platforms=()):
        w = sys.getwindowsversion()
        return system or "Microsoft Windows", release, f"{w.major}.{w.minor}.{w.build}"

    _platform._syscmd_ver = _ver_without_a_subprocess
if wheel == "phone":
    sys.path[:] = [p for p in sys.path if Path(p or ".").resolve() != checkout]
attempts = []

def _off(name):
    return any(name == m or name.startswith(m + ".") for m in OFF)

def _importer(frame):
    probe = False
    site = None
    while frame is not None:
        code = frame.f_code
        name = code.co_filename.replace("\\", "/")
        if code.co_name == "find_spec" and name.endswith(("importlib/util.py", "importlib.util>")):
            probe = True
        if site is None and not name.startswith("<") and "/importlib/" not in name:
            site = (Path(code.co_filename).resolve(), frame.f_lineno)
        frame = frame.f_back
    return probe, site

class PhoneWheel:
    def find_spec(self, name, path=None, target=None):
        if _off(name):
            probe, site = _importer(sys._getframe(1))
            if not probe and site is not None:
                where, line = site
                rel = where.relative_to(root).as_posix() if where.is_relative_to(root) else str(where)
                attempts.append({"module": name, "site": rel, "line": line})
            raise ModuleNotFoundError(f"not in the phone wheel: {name}", name=name)

if wheel == "phone":
    sys.meta_path.insert(0, PhoneWheel())
    import hermes_cli
    if not Path(hermes_cli.__file__).resolve().is_relative_to(root):
        raise SystemExit(f"control failed: hermes_cli imported from {hermes_cli.__file__}, not the staged wheel")
    try:
        import tools.terminal_tool  # noqa: F401
        raise SystemExit("control failed: tools.terminal_tool imported")
    except ModuleNotFoundError:
        pass

if wheel == "full":  # a checkout carries .git; the wheel's version is its stamp, never `git describe`'s
    import hermes_cli.version_info as version_info
    version_info._cached_version_info = version_info.VersionInfo("0.0.0", "0.0.0", 0, "0" * 39 + "1", None, "build")

import importlib.util
spec = importlib.util.spec_from_file_location("phone_turn_scenario", test_file)
scenario = importlib.util.module_from_spec(spec)
spec.loader.exec_module(scenario)
result = scenario.phone_turn(app)
result["attempted"] = attempts
result["registry_loaded"] = "tools.process_registry" in sys.modules
print("RESULT " + json.dumps(result), flush=True)
# The turn's daemon threads (auto-title, the token writer) outlive the serve; interpreter exit with
# one of them holding the import lock hangs in SessionDB.__del__'s lazy import (a runtime-queue row).
# The scenario is over: leave without finalizing.
sys.stderr.flush()
import os
os._exit(0)
"""


def _stage_phone_wheel(dest: Path) -> tuple[str, ...]:
    """Lay out the phone wheel's app tree at *dest*: the profile gate's kept modules (the closure walk,
    their enclosing packages) with the packager's own file list (package data, resources, the build
    stamp). Not the packager's forced set — the switched-off modules kept code imports unguarded are
    the gate's work list, and the turn must not reach them. Returns the switched-off prefixes."""
    import shutil

    from agent_runtime.bundle_profiles.manifest import load_profile
    from scripts.bundle_profile_closure import profile_walk
    from scripts.bundle_profile_package import (
        BUILD_SHA_FILE, Plan, _with_parents, bake_dir, first_party_files, tracked_files,
    )

    manifest = load_profile("bundled-phone")
    walk, index = profile_walk(manifest, parents=True)
    plan = Plan(profile=manifest.profile, target="android_arm64", python_version="3.14",
                first_party=_with_parents(set(walk.kept), index), pinned=set(), distributions=set())
    for rel in first_party_files(plan, index, tracked_files(), manifest.packaging_resources,
                                 manifest.excluded_data, manifest.packaging_skill_platforms):
        (dest / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REPO_ROOT / rel, dest / rel)
    (dest / BUILD_SHA_FILE).write_text("0" * 39 + "1\n", encoding="utf-8")
    # The host's secure store is the app's, not the wheel's: the CI fake stands in for it.
    shutil.copyfile(REPO_ROOT / "agent_runtime/host_store/fake.py", dest / "agent_runtime/host_store/fake.py")
    # The wheel ships its bytecode baked (``--bake-with``). Unbaked, every import of the turn compiles,
    # and a daemon thread still compiling at exit holds the import lock that ``SessionDB.__del__``'s
    # lazy import then waits on forever (a runtime-queue row).
    bake_dir(dest, Path(sys.executable))
    return tuple(manifest.switched_off_modules)


def _unseamed(attempts: list[dict]) -> list[dict]:
    """The attempts not made by a module-level ``try: import … except ImportError`` seam.

    A module-level guarded import is the profile's seam (the gate reads the same shape as
    "not pinned"): it binds a stand-in and the importer loads. Anything else — a lazy import
    whose ImportError the caller swallowed, an unguarded one — is the turn reaching into code
    the phone does not have.
    """
    from scripts.bundle_profile_closure import _imports

    seams = {}
    out = []
    for attempt in attempts:
        path = REPO_ROOT / attempt["site"]
        if path not in seams:
            module = attempt["site"][:-3].replace("/", ".").removesuffix(".__init__")
            seams[path] = {line for _dotted, eager, guarded, line in _imports(path, module, path.name == "__init__.py")
                           if eager and guarded} if path.is_file() else set()
        if attempt["line"] not in seams[path]:
            out.append(attempt)
    return out


@pytest.mark.timeout(300)  # the phone case stages the wheel first (the packager's walk, ~40 s)
@pytest.mark.parametrize("wheel", ["phone", "full"])
def test_sign_in_and_one_chat_turn_leave_no_secret_on_disk_and_protect_the_history(tmp_path, wheel):
    """``phone``: the switched-off modules are absent. ``full``: every module is installed, so the
    background drain loads the process registry, whose import-time delegation recovery opens the
    state DB — the key must still be only in the host store."""
    from agent_runtime.bundle_profiles.manifest import load_profile

    app = tmp_path / "app"
    if wheel == "phone":
        cwd = tmp_path / "wheel"
        off = _stage_phone_wheel(cwd)
    else:
        cwd, off = REPO_ROOT, tuple(load_profile("bundled-phone").switched_off_modules)
    proc = subprocess.run([sys.executable, "-c", _CHILD, str(app), __file__, wheel, str(REPO_ROOT), json.dumps(off)],
                          cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=200)
    lines = [line for line in proc.stdout.splitlines() if line.startswith("RESULT ")]
    assert proc.returncode == 0 and lines, (proc.stdout[-3000:], proc.stderr[-6000:])
    result = json.loads(lines[-1][len("RESULT "):])

    assert result["turn"] == "completed", result["turn_tail"]
    assert result["reply"] == REPLY
    assert result["exit_code"] is not None, "the embedded serve did not end at EOF"
    # Positive controls: the key and the chat really travelled, and the history holds the chat.
    assert result["chat_auth"] and all(auth == f"Bearer {SECRET}" for auth in result["chat_auth"])
    assert result["key_in_store"]
    assert result["state_db_bytes"] > 0 and result["transcript"] == [CHAT, REPLY]
    # The phone boot asked the host to protect the history folder, once, before the serve ran.
    assert result["protected"] == [result["home"]]
    # The phone wheel: nothing on the turn path reached a switched-off module except through a
    # module-level seam (not even into an ImportError it swallowed), and no process was started —
    # no worker, no `hermes auth login`, no python/pip probe, no git probe. Positive control: the
    # recorder saw the native gateway's own seam (tui_gateway/server.py's environments import).
    if wheel == "phone":
        assert (unseamed := _unseamed(result["attempted"])) == [], unseamed
        assert any(a["site"] == "tui_gateway/server.py" for a in result["attempted"]), result["attempted"]
    else:
        assert result["registry_loaded"]  # the full wheel really ran the recovery the seam routes
    assert result["spawned"] == []
    leaks = _leaks(app)
    assert SECRET not in leaks, leaks  # the key is only in the host store
    assert CHAT in leaks, leaks  # positive control: the scan reads the (OS-protected) history


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

    # A host that cannot protect the history folder is refused before any request.
    bare = FakeHostSecureStore()
    binding.bind_host_store(binding.HostStoreCallbacks(read=bare.read, write=bare.write, delete=bare.delete),
                            profile="phone", store_root=app)
    with pytest.raises(binding.HistoryProtectionMissing):
        EmbeddedServe(lambda _line: None).start()
    assert not (home / "state.db").exists()
    binding.unbind_host_store()

    # Positive control: bound over the app folder, the same entry serves — and asked the host to
    # protect the Hermes home before its serve thread existed.
    store = FakeHostSecureStore()
    store.bind(profile="phone", store_root=app)
    frames = Frames()
    serve = EmbeddedServe(frames.on_frame)
    serve.start()
    assert store.protected == [str(home)]
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


def test_the_phone_entry_serves_the_phone_platform_hint(app, monkeypatch):
    """The phone agent is told its limits through upstream's ``PLATFORM_HINTS["phone"]``, which the
    embedded serve (the phone's entry) fills before it serves a request — ``agent/prompt_builder.py``
    keeps upstream's bytes (lane h11-fp). Positive control: the key is absent until the entry runs.
    Killing mutation (recorded in the commit): drop the install call from ``EmbeddedServe._run`` -> red."""
    from agent.prompt_builder import PLATFORM_HINTS
    from agent.system_prompt import _default_platform_hint
    from agent_runtime.bundle_profiles.phone_hint import phone_platform_hint

    monkeypatch.delitem(PLATFORM_HINTS, "phone", raising=False)
    assert _default_platform_hint("phone") == ""
    FakeHostSecureStore().bind(profile="phone", store_root=app)
    serve = EmbeddedServe(lambda _line: None)
    serve.start()
    serve.close()
    assert serve.wait(60) is not None
    assert _default_platform_hint("phone") == PLATFORM_HINTS["phone"] == phone_platform_hint()
