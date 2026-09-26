"""The runtime.local_llama.* adapter: the guarantees the retired fork manager carried, pinned
on the adapter that now serves them over upstream's hermes_cli/local_runtime engine.

Real files, receipts and journals; the engine (upstream's supervisor) is replaced by a fake that
records what the manager asked of it, except where a test drives the real preset writer.
"""
from copy import deepcopy
import configparser
import socket
import struct
import threading
import time
from types import SimpleNamespace
import uuid

import pytest

from agent_runtime import serve_rpc
from agent_runtime.call_authorization import CALLER_PEER, UNKNOWN_CALLER, RpcCaller
from agent_runtime.local_llama_adapter import PROVIDER_ID, binding, model_alias, provider, rpc
from agent_runtime.local_llama_adapter.config import GENERATION_DEFAULTS, LOAD_DEFAULTS, LocalLlamaError, default_config
from agent_runtime.local_llama_adapter.engine import scan, validate_model, write_preset
from agent_runtime.local_llama_adapter.manager import LocalLlamaManager

SECRET = "adapter-test-secret"
ENDPOINT = "http://127.0.0.1:18181/v1"


class FakeEngine:
    def __init__(self, directory):
        self.directory = directory
        self.log_path = directory / "llama-server.log"
        self.preset_path = directory / "models.ini"
        self.block = threading.Event()
        self.block.set()
        self.entered = threading.Event()
        self.started = self.stopped = 0
        self.loads, self.unloads = [], []
        self.running = False

    def start(self, config):
        self.started += 1
        self.entered.set()
        assert self.block.wait(5)
        self.running = True

    def load(self, model):
        self.loads.append(deepcopy(model))
        write_preset(self.preset_path, model)
        return {"chat_template_caps": {"supports_tools": True, "supports_tool_calls": True},
                "default_generation_settings": {"n_ctx": model["load"]["context_size"]}}

    def unload(self, model_id):
        self.unloads.append(model_id)

    def stop(self):
        self.stopped += 1
        self.running = False

    def close(self):
        self.block.set()
        self.stop()

    def alive(self):
        return self.running

    def endpoint(self):
        return ENDPOINT, SECRET

    def secret(self):
        return SECRET


@pytest.fixture
def manager(tmp_path):
    m = LocalLlamaManager(tmp_path / "runtime", tmp_path / "config.yaml", "install-test", engine_factory=FakeEngine)
    m.config["executable_path"] = "test-executable"
    yield m
    m.close()


def guards(m, **extra):
    state = m.status()
    return {"request_id": str(uuid.uuid4()), "expect_epoch": state["epoch"],
            "expect_revision": state["revision"], "expect_config_revision": state["config_revision"], **extra}


def settle(m, request):
    end = time.monotonic() + 5
    while time.monotonic() < end:
        operation = m.status(request_id=request["request_id"])["operation"]
        if operation["state"] not in ("queued", "running"):
            return operation
        time.sleep(.01)
    pytest.fail("operation did not settle")


def gguf(path, **extra):
    fields = {"general.architecture": "qwen3", "general.name": "Test model", "qwen3.context_length": 8192, **extra}

    def string(value):
        data = value.encode()
        return struct.pack("<Q", len(data)) + data
    data = b"GGUF" + struct.pack("<IQQ", 3, 0, len(fields))
    for key, value in fields.items():
        data += string(key) + struct.pack("<I", 8 if isinstance(value, str) else 4)
        data += string(value) if isinstance(value, str) else struct.pack("<I", value)
    path.write_bytes(data)
    return path


def ready(m, tmp_path, **load):
    model_id = str(uuid.uuid4())
    weights = gguf(tmp_path / (model_id + ".gguf"))
    m.config["presets"] = [{"model_id": model_id, "display_name": "Local", "gguf_path": str(weights), "revision": 0,
                            "load": deepcopy(LOAD_DEFAULTS) | {"context_size": 8192} | load,
                            "generation": deepcopy(GENERATION_DEFAULTS)}]
    m.server = "running"
    m.engine.running = True
    return model_id


# ── receipts, guards, lease (rows 12, 13) ───────────────────────────────


def test_duplicate_request_id_has_one_effect_and_a_changed_payload_is_refused(manager):
    manager.engine.block.clear()
    request = guards(manager)
    first = manager.submit("start", request)
    second = manager.submit("start", request)
    assert first["operation"]["operation_id"] == second["operation"]["operation_id"]
    manager.engine.block.set()
    assert settle(manager, request)["state"] == "succeeded"
    assert manager.engine.started == 1
    with pytest.raises(LocalLlamaError) as caught:
        manager.submit("stop", request)
    assert caught.value.reason == "idempotency_conflict"


def test_a_new_epoch_refuses_the_old_one_and_replays_the_old_receipt(tmp_path):
    first = LocalLlamaManager(tmp_path / "runtime", tmp_path / "config.yaml", "install-test", engine_factory=FakeEngine)
    request = guards(first)
    first.submit("stop", request)
    old = settle(first, request)["operation_id"]
    first.close()
    replacement = LocalLlamaManager(tmp_path / "runtime", tmp_path / "config.yaml", "install-test", engine_factory=FakeEngine)
    try:
        assert replacement.submit("stop", request)["operation"]["operation_id"] == old
        assert replacement.engine.stopped == 0
        with pytest.raises(LocalLlamaError) as caught:
            replacement.submit("stop", {**request, "request_id": str(uuid.uuid4())})
        assert caught.value.reason == "stale_epoch"
    finally:
        replacement.close()


def test_a_stale_revision_and_a_busy_manager_are_refused(manager):
    manager.engine.block.clear()
    request = guards(manager)
    manager.submit("start", request)
    # The start bumps the revision on its way into the engine; take the guards only once it is
    # parked there, or the refusal is stale_revision and the busy arm is never proven.
    assert manager.engine.entered.wait(5)
    with pytest.raises(LocalLlamaError) as caught:
        manager.submit("stop", guards(manager))
    assert caught.value.reason == "operation_busy"
    manager.engine.block.set()
    settle(manager, request)
    with pytest.raises(LocalLlamaError) as caught:
        manager.submit("stop", {**request, "request_id": str(uuid.uuid4())})
    assert caught.value.reason == "stale_revision"


def test_a_receipt_running_at_restart_reads_interrupted(tmp_path):
    first = LocalLlamaManager(tmp_path / "runtime", tmp_path / "config.yaml", "install-test", engine_factory=FakeEngine)
    first.config["executable_path"] = "test-executable"
    first.engine.block.clear()
    request = guards(first)
    first.submit("start", request)
    # A crash, not a close: the receipt file still says running.
    replacement = LocalLlamaManager(tmp_path / "runtime", tmp_path / "config.yaml", "install-test", engine_factory=FakeEngine)
    try:
        assert replacement.status(request_id=request["request_id"])["operation"]["state"] == "interrupted"
    finally:
        replacement.close()
        first.close()


def test_the_turn_lease_refuses_unload_and_stop_and_releases_on_failure(manager, tmp_path, monkeypatch):
    model_id = ready(manager, tmp_path)
    manager.loaded = model_id
    manager.model_states[model_id] = {"state": "ready", "active_parameters": {"effective_context_size": 8192}}
    monkeypatch.setattr("hermes_cli.runtime_provider.resolve_runtime_provider",
                        lambda **kw: {"provider": "custom", "api_mode": "chat_completions", "base_url": ENDPOINT, "api_key": SECRET})
    with pytest.raises(RuntimeError):
        with manager.lease(model_id, "turn-1", "agent-1"):
            for kind, extra in (("unload", {"model_id": model_id}), ("stop", {})):
                with pytest.raises(LocalLlamaError) as caught:
                    manager.submit(kind, guards(manager, **extra))
                assert caught.value.reason == "active_turns"
            raise RuntimeError("turn failed")
    assert manager.status()["active_turns"] == []
    assert manager.engine.unloads == []


def test_a_storage_failure_starts_no_unrecorded_process(manager, monkeypatch):
    with monkeypatch.context() as patch:
        patch.setattr(manager, "_persist", lambda: (_ for _ in ()).throw(OSError("disk unavailable")))
        with pytest.raises(LocalLlamaError) as caught:
            manager.submit("start", guards(manager))
    assert caught.value.reason == "storage_unavailable"
    assert manager.engine.started == 0 and manager.operation is None


def test_shutdown_interrupts_the_pending_operation_and_refuses_new_ones(manager):
    manager.engine.block.clear()
    request = guards(manager)
    manager.submit("start", request)
    manager.close()
    assert manager.status(request_id=request["request_id"])["operation"]["state"] == "interrupted"
    with pytest.raises(LocalLlamaError) as caught:
        manager.submit("start", guards(manager))
    assert caught.value.reason == "manager_unavailable"


def test_a_failed_replacement_keeps_the_loaded_model(manager, tmp_path):
    old = ready(manager, tmp_path)
    manager.loaded = old
    manager.model_states[old] = {"state": "ready", "active_parameters": {
        "load": deepcopy(LOAD_DEFAULTS), "generation": deepcopy(GENERATION_DEFAULTS)}}
    new = str(uuid.uuid4())
    manager.config["presets"].append({"model_id": new, "display_name": "missing", "revision": 0,
        "gguf_path": str(tmp_path / "gone.gguf"), "load": deepcopy(LOAD_DEFAULTS), "generation": deepcopy(GENERATION_DEFAULTS)})
    request = guards(manager, model_id=new, preset_revision=0, load=deepcopy(LOAD_DEFAULTS),
                     generation=deepcopy(GENERATION_DEFAULTS), replace_model_id=old)
    manager.submit("load", request)
    assert settle(manager, request)["error"]["reason"] == "missing_file"
    assert manager.loaded == old and manager.server == "running"
    assert manager.engine.unloads == []


def test_status_and_config_never_carry_host_paths_or_the_engine_credential(manager):
    manager.config["presets"] = [{"model_id": str(uuid.uuid4()), "display_name": "Remote weights", "revision": 2,
                                  "load": {"context_size": 8192}, "gguf_path": "private-host-path.gguf"}]
    state = manager.status()
    assert state["configured"] is True and state["models"][0]["context_length"] == 8192
    assert "private-host-path" not in str(state) and "test-executable" not in str(state)
    assert SECRET not in str(state) and SECRET not in str(manager.config_get())


# ── knobs (row 9) and the turn route (rows 10, 19, 21) ──────────────────


def test_load_applies_the_requested_knobs_to_the_router_preset(manager, tmp_path):
    model_id = ready(manager, tmp_path)
    knobs = deepcopy(manager.config["presets"][0]["load"]) | {"gpu_layers": 12, "flash_attention": "on",
                                                              "cache_type_k": "q8_0", "cache_type_v": "q4_0"}
    request = guards(manager, model_id=model_id, preset_revision=0, load=knobs, generation=deepcopy(GENERATION_DEFAULTS))
    manager.submit("load", request)
    assert settle(manager, request)["state"] == "succeeded"
    ini = configparser.ConfigParser()
    # The router's preset carries a sectionless ``version`` line first.
    ini.read_string("[preamble]\n" + manager.engine.preset_path.read_text())
    section = ini[model_alias(model_id)]
    assert (section["n-gpu-layers"], section["flash-attn"], section["cache-type-k"], section["cache-type-v"]) == ("12", "on", "q8_0", "q4_0")
    assert section["ctx-size"] == "8192"
    assert manager.status()["models"][0]["active_parameters"]["load"] == knobs


def test_the_turn_route_is_upstreams_llamacpp_resolution_pinned_to_this_engine(manager, tmp_path, monkeypatch):
    model_id = ready(manager, tmp_path)
    manager.loaded = model_id
    manager.model_states[model_id] = {"state": "ready", "active_parameters": {"effective_context_size": 8192}}
    asked = []

    def resolve(**kwargs):
        asked.append(kwargs)
        return {"provider": "custom", "api_mode": "chat_completions", "base_url": ENDPOINT, "api_key": SECRET}
    monkeypatch.setattr("hermes_cli.runtime_provider.resolve_runtime_provider", resolve)
    runtime = manager.runtime(model_id)
    assert asked == [{"requested": "llamacpp"}]
    # The router alias is a persisted spelling (session rows carry it), so it is pinned literally.
    assert (runtime["model"], runtime["base_url"], runtime["provider"]) == ("hermes-local-" + model_id, ENDPOINT, "custom")


def test_a_foreign_server_on_the_managed_endpoint_gets_no_turn(manager, tmp_path, monkeypatch):
    model_id = ready(manager, tmp_path)
    manager.loaded = model_id
    manager.model_states[model_id] = {"state": "ready", "active_parameters": {}}
    monkeypatch.setattr("hermes_cli.runtime_provider.resolve_runtime_provider",
                        lambda **kw: {"provider": "custom", "base_url": "http://127.0.0.1:18434/v1", "api_key": "other"})
    with pytest.raises(LocalLlamaError) as caught:
        manager.runtime(model_id)
    assert caught.value.reason == "model_not_ready"


def runtime_row():
    return {"provider": "custom", "model": "hermes-local-example", "base_url": ENDPOINT, "api_key": SECRET,
            "local_parameters": {"effective_context_size": 8192,
                                 "generation": {"max_output_tokens": 1024, "temperature": .7, "top_p": .9, "top_k": 40}}}


def test_the_read_projection_pins_the_window_and_routes_aux_without_credentials():
    from hermes_cli.config_read_scope import project_readonly_config, readonly_config_scope
    original = {"model": {"provider": "cloud"}, "auxiliary": {"compression": {"provider": "cloud", "api_key": "cloud-key"}}}
    before = deepcopy(original)
    with readonly_config_scope(lambda cfg: provider.project_config(cfg, runtime_row())):
        projected = project_readonly_config(original)
    assert projected["model"]["context_length"] == 8192
    assert projected["auxiliary"]["compression"]["provider"] == "main"
    assert "cloud-key" not in str(projected) and SECRET not in str(projected)
    assert original == before


def test_generation_parameters_ride_the_factory_and_bust_the_resident_actor():
    resolved = runtime_row()
    kwargs = provider.construction_kwargs(resolved)
    assert (kwargs["requested_provider"], kwargs["max_tokens"], kwargs["request_overrides"]["extra_body"]["top_k"]) == (PROVIDER_ID, 1024, 40)
    old = provider.actor_signature(resolved, "session")
    resolved["local_parameters"]["generation"]["max_output_tokens"] = 2048
    assert provider.actor_signature(resolved, "session") != old
    assert provider.construction_kwargs({"provider": "cloud"}) == {} and provider.actor_signature({}, "session") == "session"


def test_the_runner_resolves_a_local_persona_through_the_adapter_never_the_cloud(monkeypatch):
    from agent_runtime import profile_runner
    monkeypatch.setattr(profile_runner.execute, "resolve_runtime_provider", lambda **kw: pytest.fail("reached the cloud resolver"))
    calls = []
    monkeypatch.setattr(provider, "resolve", lambda model, *, root=None: calls.append(model) or runtime_row())
    request = profile_runner.AgentRunRequest(profile=None, provider=PROVIDER_ID, model="saved-id")
    assert profile_runner._resolve_request_runtime(request)["model"] == "hermes-local-example"
    assert calls == ["saved-id"]


def test_the_local_provider_profile_needs_no_api_key():
    profile = provider.provider_profile()
    assert (profile.name, profile.api_mode, tuple(profile.env_vars or ())) == (PROVIDER_ID, "chat_completions", ())


# ── the settings document (rows 9, 10, 13) ─────────────────────────────


def test_a_quantized_v_cache_needs_flash_attention_on():
    from agent_runtime.local_llama_adapter.config import validate_parameters
    load = deepcopy(LOAD_DEFAULTS) | {"cache_type_v": "q8_0", "flash_attention": "on"}
    validate_parameters(load, deepcopy(GENERATION_DEFAULTS))
    with pytest.raises(LocalLlamaError, match="Flash Attention"):
        validate_parameters(load | {"flash_attention": "auto"}, deepcopy(GENERATION_DEFAULTS))


def test_an_interrupted_config_publication_is_finished_on_restart(tmp_path):
    from agent_runtime.local_llama_adapter.config import ConfigStore
    from utils import atomic_json_write
    store = ConfigStore(tmp_path / "config.yaml")
    after = default_config() | {"port": 8189}
    store.write(after)
    directory = tmp_path / "runtime" / "local_llama"
    directory.mkdir(parents=True)
    # The crash landed after the config write and before the revision publish.
    atomic_json_write(directory / "config-journal.json", {"before": default_config(), "after": after, "revision": 7})
    manager = LocalLlamaManager(tmp_path / "runtime", tmp_path / "config.yaml", "install-test", engine_factory=FakeEngine)
    try:
        assert (manager.config_revision, manager.config["port"]) == (7, 8189)
        assert not (directory / "config-journal.json").exists()
    finally:
        manager.close()


# ── log cursor (row 17) ─────────────────────────────────────────────────


def test_the_log_cursor_pages_forward_without_repeats(manager):
    for index in range(5):
        manager._log(f"line {index}")
    first = manager.logs_get(limit=2)
    assert [r["message"] for r in first["lines"]] == ["line 3", "line 4"]
    manager._log("line 5")
    manager._log("line 6")
    page = manager.logs_get(cursor=first["next_cursor"], limit=1)
    assert [r["message"] for r in page["lines"]] == ["line 5"] and page["truncated"] is True
    rest = manager.logs_get(cursor=page["next_cursor"], limit=10)
    assert [r["message"] for r in rest["lines"]] == ["line 6"] and rest["truncated"] is False


def test_the_server_log_tail_reaches_the_cursor_with_the_credential_redacted(manager):
    manager.engine.log_path.write_text(f"# spawn: ['llama-server', '--api-key', '{SECRET}']\nmain: server is listening\npartial", encoding="utf-8")
    messages = [r["message"] for r in manager.logs_get(limit=200)["lines"]]
    assert "main: server is listening" in messages
    assert not any(SECRET in m for m in messages) and any("[redacted]" in m for m in messages)
    assert "partial" not in messages


# ── GAP-PR-2 fallback: extra model roots ───────────────────────────────


def test_a_rescan_adds_each_complete_model_once_and_skips_projectors(tmp_path):
    nested = tmp_path / "models"
    nested.mkdir()
    gguf(nested / "model.gguf")
    gguf(tmp_path / "mmproj.gguf")
    config = default_config() | {"model_roots": [str(tmp_path)]}
    found, report = scan(config)
    assert len(found["presets"]) == 1 and found["presets"][0]["load"]["context_size"] == 8192
    again, _ = scan(found)
    assert again == found and config["presets"] == [] and not report["errors"]


def test_a_split_model_needs_every_matching_shard(tmp_path):
    first = gguf(tmp_path / "model-00001-of-00002.gguf", **{"split.count": 2, "split.no": 0})
    with pytest.raises(LocalLlamaError, match="missing"):
        validate_model(first)
    second = gguf(tmp_path / "model-00002-of-00002.gguf", **{"split.count": 2, "split.no": 1})
    assert validate_model(first)["split.count"] == 2
    gguf(second, **{"split.count": 2, "split.no": 1, "general.name": "Different"})
    with pytest.raises(LocalLlamaError, match="same model"):
        validate_model(first)


# ── the engine drives upstream's supervisor ─────────────────────────────


def test_the_engine_serves_one_resident_model_under_upstreams_supervisor(tmp_path, monkeypatch):
    from agent_runtime.local_llama_adapter.engine import Engine
    binary = tmp_path / "bin" / "llama-server.exe"
    binary.parent.mkdir()
    binary.write_bytes(b"")
    built = []

    class Supervisor:
        def __init__(self, binary, models_dir, **kwargs):
            self.binary, self.kwargs = binary, kwargs
            self.base_url, self.api_key, self.primary_model = ENDPOINT, SECRET, None
            self.proc = SimpleNamespace(poll=lambda: None)
            built.append(self)

        def start(self, timeout_s):
            pass

        def load_model(self, alias):
            self.loading = alias

        def stop(self):
            self.proc = None
    routes = []

    def get(base, key, route, timeout):
        routes.append(route)
        if route == "/models":
            return {"data": [{"id": built[0].loading, "status": {"value": "loaded"}}]}
        return {"default_generation_settings": {"n_ctx": 8192}} if route.startswith("/props") else {}
    monkeypatch.setattr("hermes_cli.local_runtime.supervisor.LlamaServerSupervisor", Supervisor)
    monkeypatch.setattr("hermes_cli.local_runtime.endpoint.managed_get_json", get)
    engine = Engine(tmp_path / "state")
    with socket.socket() as port:
        port.bind(("127.0.0.1", 0))
        free = port.getsockname()[1]
    engine.start({"executable_path": str(binary), "port": free})
    assert built[0].kwargs["models_max"] == 1 and built[0].kwargs["preset_path"] == engine.preset_path
    # Upstream's supervisor takes the exact binary (2026-09-25 merge), never its directory.
    assert built[0].binary == binary
    model = {"model_id": str(uuid.uuid4()), "gguf_path": str(tmp_path / "m.gguf"), "load": deepcopy(LOAD_DEFAULTS)}
    assert engine.load(model)["default_generation_settings"]["n_ctx"] == 8192
    assert routes[0] == "/models?reload=1"
    # Upstream's watchdog reloads its primary model after a router restart.
    assert built[0].primary_model == model_alias(model["model_id"])
    engine.close()
    assert not engine.alive()


# ── dispatch and authorization ─────────────────────────────────────────


@pytest.fixture
def dispatched(manager, monkeypatch):
    monkeypatch.setattr(rpc, "get_manager", lambda: manager)
    return manager


def call(suffix, params=None, caller=None):
    context = serve_rpc.RpcContext() if caller is None else serve_rpc.RpcContext(caller=caller)
    return serve_rpc.handle_request({"jsonrpc": "2.0", "id": "test-call", "method": "runtime.local_llama." + suffix,
                                     "params": params or {}}, context)


def test_real_dispatch_serves_every_verb_with_typed_errors(dispatched):
    manifest = serve_rpc.manifest()
    for name in list(rpc.METHODS) + list(rpc.SETUP_FIELDS):
        assert "runtime.local_llama." + name in manifest["methods"]
    assert call("status")["result"]["server"]["state"] == "off"
    assert call("start")["error"]["code"] == -32602
    assert call("status", {"request_id": str(uuid.uuid4())})["error"]["code"] == 4001


def test_an_unknown_caller_or_a_peer_reaches_no_console_verb(dispatched, monkeypatch):
    monkeypatch.setattr(rpc, "get_manager", lambda: pytest.fail("an unauthorized call reached the manager"))
    peer = RpcCaller(kind=CALLER_PEER, transport="gateway", peer_install_id="peer-test")
    for suffix in list(rpc.METHODS) + list(rpc.SETUP_FIELDS):
        assert "error" in call(suffix, caller=peer)
        if suffix not in ("status", "setup.capabilities"):
            assert "error" in call(suffix, caller=UNKNOWN_CALLER)


# ── setup over upstream's installer ────────────────────────────────────


def test_an_install_runs_upstreams_installer_and_stays_inactive_until_activated(manager, tmp_path, monkeypatch):
    """Setup asks upstream's PM-owned engine API: the release is the backend's PM pin, the
    install is ``ensure_engine(backend)``, and the inventory row is ``installed_engine``."""
    from agent_runtime.local_llama_adapter import setup as module
    from hermes_cli.local_runtime import binaries
    installs, engines = [], {}
    binary = tmp_path / "store" / "llamacpp-cpu" / "llama-server.exe"

    def ensure_engine(backend, progress=None, **_kw):
        binary.parent.mkdir(parents=True, exist_ok=True)
        binary.write_bytes(b"fixture")
        progress("download", 1, 1, "")
        installs.append(backend)
        engines[backend] = binaries.Engine(backend, "b9999", binary)
        return engines[backend]
    monkeypatch.setattr(binaries, "unavailable_reason", lambda backend, target=None: None if backend == "cpu" else "no")
    monkeypatch.setattr(binaries, "pinned_tag", lambda backend: "b9999")
    monkeypatch.setattr(binaries, "ensure_engine", ensure_engine)
    monkeypatch.setattr(binaries, "installed_engine", lambda backend="auto", **_kw: engines.get(backend))
    monkeypatch.setattr("pm.paths.store_root", lambda: tmp_path)
    monkeypatch.setattr(module, "probe", lambda p: {"executable_path": str(p), "sha256": "x", "version": "v",
                                                   "compatibility": "compatible", "capabilities": []})
    release = manager.setup.releases()["releases"][0]
    variant = next(v for v in release["variants"] if v["backend"] == "cpu")
    plan = manager.setup.plan({"tag": release["tag"], "release_id": release["release_id"],
                               "variant_id": variant["variant_id"], "destination_parent": str(tmp_path)})["plan"]
    manager.config["executable_path"] = None
    request = guards(manager, plan_id=plan["plan_id"], plan_revision=1, acknowledged_warning_ids=[])
    manager.setup.submit("install", request)
    manager.setup.worker.join(5)
    status = manager.setup.status(request_id=request["request_id"])
    assert status["requested_operation"]["state"] == "succeeded", status
    assert release["tag"] == "b9999"
    assert installs == ["cpu"] and manager.config["executable_path"] is None
    row = next(r for r in status["inventory"] if r["tag"] == release["tag"])
    activate = guards(manager, installation_id=row["installation_id"], expect_inventory_revision=status["inventory_revision"])
    manager.setup.submit("activate", activate)
    manager.setup.worker.join(5)
    assert manager.setup.status(request_id=activate["request_id"])["requested_operation"]["state"] == "succeeded"
    assert manager.config["executable_path"] == row["executable_path"]


def test_setup_mutations_pass_the_same_epoch_guard(manager):
    with pytest.raises(LocalLlamaError) as caught:
        manager.setup.submit("activate", {**guards(manager), "expect_epoch": str(uuid.uuid4()),
                                          "validation_token": "t", "expect_inventory_revision": 0})
    assert caught.value.reason == "stale_epoch"


# ── the upstream ``llamacpp`` provider id is an input alias (lane LLAMA-ALIAS) ──
@pytest.mark.parametrize("provider_id", [PROVIDER_ID, "llamacpp"])
def test_either_provider_id_takes_the_whole_turn_lease(provider_id, monkeypatch):
    from contextlib import contextmanager, nullcontext
    leases = []

    class _Manager:
        @contextmanager
        def lease(self, model, turn, agent):
            leases.append((model, turn, agent))
            yield runtime_row()

    monkeypatch.setattr(binding, "get_manager", lambda root=None, create=False: _Manager())
    monkeypatch.setattr(provider, "_routed", lambda runtime: nullcontext())
    request = SimpleNamespace(provider=provider_id, model="preset-id", turn_id="turn-1", session_id=None,
                              persona_instance_id="agent-1", runtime_root=None, prewarm_only=False)
    with provider.turn_scope(request):
        pass
    assert leases == [("preset-id", "turn-1", "agent-1")]


def test_a_cloud_provider_takes_no_lease(monkeypatch):
    monkeypatch.setattr(binding, "get_manager", lambda **kw: pytest.fail("a cloud turn reached the lease"))
    with provider.turn_scope(SimpleNamespace(provider="anthropic", model="claude-x")):
        pass


@pytest.mark.parametrize("provider_id", [PROVIDER_ID, "llamacpp"])
def test_either_provider_id_resolves_through_the_adapter(provider_id, monkeypatch):
    from agent_runtime import profile_runner
    monkeypatch.setattr(profile_runner.execute, "resolve_runtime_provider", lambda **kw: pytest.fail("reached the cloud resolver"))
    calls = []
    monkeypatch.setattr(provider, "resolve", lambda model, *, root=None: calls.append(model) or runtime_row())
    request = profile_runner.AgentRunRequest(profile=None, provider=provider_id, model="preset-id")
    assert profile_runner._resolve_request_runtime(request)["model"] == "hermes-local-example"
    assert calls == ["preset-id"]


@pytest.mark.parametrize("provider_id", [PROVIDER_ID, "llamacpp"])
def test_either_provider_id_is_ready_on_the_local_catalog_not_a_credential(provider_id, monkeypatch):
    from agent_runtime import profile_readiness
    monkeypatch.setattr(provider, "catalog_visibility",
                        lambda: {"models": [{"model_id": "preset-id", "selectable": True}]})
    persona = SimpleNamespace(provider=provider_id, model="preset-id")
    assert profile_readiness._provider_issue(persona) is None
    missing = SimpleNamespace(provider=provider_id, model="other-id")
    assert profile_readiness._provider_issue(missing)[0] == profile_readiness.READINESS_CONFIG_ERROR
