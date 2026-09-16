"""Real files/journals/extraction; deterministic release and executable boundaries."""
from copy import deepcopy
import io
import json
from pathlib import Path
import threading
import time
import uuid
import zipfile

import pytest

from agent_runtime.local_llama.config import LocalLlamaError, ConfigStore
from agent_runtime.local_llama.manager import LocalLlamaManager
from agent_runtime.local_llama import setup_manager as module
from agent_runtime.local_llama.setup_io import extract_zip, digest, host_path
from agent_runtime.local_llama.setup_releases import ReleaseCatalog
from agent_runtime.local_llama.config_journal import recover
from utils import atomic_json_write


@pytest.fixture
def manager(tmp_path, monkeypatch):
    m = LocalLlamaManager(tmp_path / "root", tmp_path / "config.yaml", "setup-host")
    monkeypatch.setattr(module.platform, "system", lambda: "Windows")
    monkeypatch.setattr(module.platform, "machine", lambda: "AMD64")
    yield m
    m.close()


def guards(m, **extra):
    state = m.status()
    return {"request_id": str(uuid.uuid4()), "expect_epoch": state["epoch"],
            "expect_revision": state["revision"], "expect_config_revision": state["config_revision"], **extra}


def settle(m, request):
    end = time.monotonic() + 5
    while time.monotonic() < end:
        row = m.setup.status(request_id=request["request_id"])["requested_operation"]
        if row["state"] not in module.ACTIVE:
            return row
        time.sleep(.01)
    pytest.fail("setup did not settle")


def bundle(m, tmp_path, monkeypatch):
    archive = tmp_path / "official.zip"
    with zipfile.ZipFile(archive, "w") as out:
        out.writestr("build/bin/llama-server.exe", b"fixture executable")
        out.writestr("build/bin/ggml.dll", b"fixture dependency")
    variant = {"variant_id": "win-x64-cpu", "backend": "cpu", "download_bytes": archive.stat().st_size,
               "artifacts": [{"asset_id": "1", "name": "official.zip", "url": "https://github.com/fixture",
                              "size_bytes": archive.stat().st_size, "sha256": digest(archive)}]}
    monkeypatch.setattr(m.setup.catalog, "pinned", lambda *_: deepcopy(variant))
    def download(url, **kwargs):
        Path(kwargs["destination"]).write_bytes(archive.read_bytes())
        kwargs["tick"](archive.stat().st_size, archive.stat().st_size)
    monkeypatch.setattr(module, "official_get", download)
    monkeypatch.setattr(module, "probe", lambda p: {"executable_path": str(p), "sha256": digest(p),
                                                   "version": "version: 12345", "compatibility": "compatible", "capabilities": []})
    plan = m.setup.plan({"tag": "b12345", "release_id": "77", "variant_id": "win-x64-cpu", "destination_parent": str(tmp_path)})["plan"]
    return plan, variant


def apply(m, plan):
    request = guards(m, plan_id=plan["plan_id"], plan_revision=1, acknowledged_warning_ids=[])
    m.setup.submit("install", request)
    return request


def test_install_is_inactive_then_explicit_activation_and_rollback(manager, tmp_path, monkeypatch):
    plan, _ = bundle(manager, tmp_path, monkeypatch)
    request = apply(manager, plan)
    result = settle(manager, request)
    assert result["state"] == "succeeded", result
    assert result["result"]["cleanup"] == "complete"
    assert manager.config["executable_path"] is None
    row = manager.setup.status()["inventory"][0]
    assert "files" not in row
    activate = guards(manager, installation_id=row["installation_id"], expect_inventory_revision=1)
    manager.setup.submit("activate", activate)
    assert settle(manager, activate)["state"] == "succeeded"
    assert manager.config["executable_path"] == row["executable_path"]
    assert manager.server == "off" and manager.loaded is None
    # Repeated exact request is the original durable receipt, not a new activation.
    assert manager.setup.submit("activate", activate)["operation"]["operation_id"] == settle(manager, activate)["operation_id"]
    changed = dict(activate, installation_id=str(uuid.uuid4()))
    with pytest.raises(LocalLlamaError, match="different operation"):
        manager.setup.submit("activate", changed)


def test_install_reservation_blocks_legacy_and_cancel_waits_for_cleanup(manager, tmp_path, monkeypatch):
    plan, _ = bundle(manager, tmp_path, monkeypatch)
    entered, release = threading.Event(), threading.Event()
    def blocked(*_, **kwargs):
        entered.set()
        assert release.wait(3)
        kwargs["tick"](1, 2)
    monkeypatch.setattr(module, "official_get", blocked)
    request = apply(manager, plan)
    assert entered.wait(2)
    op = manager.setup.status(request_id=request["request_id"])["requested_operation"]
    assert manager.status()["active_operation"]["kind"] == "setup.install"
    with pytest.raises(LocalLlamaError) as error:
        manager.submit("start", guards(manager))
    assert error.value.reason == "operation_busy"
    manager.setup.cancel(op["operation_id"], str(uuid.uuid4()))
    assert manager.setup.status()["active_operation"]["state"] == "cancelling"
    release.set()
    terminal = settle(manager, request)
    assert terminal["state"] == "cancelled"
    assert terminal["result"]["cleanup"] == "complete"
    assert not Path(plan["directory"]).exists()
    assert manager.setup.status()["inventory"] == []


def test_plan_guard_cannot_be_rebased_onto_new_config(manager, tmp_path, monkeypatch):
    plan, _ = bundle(manager, tmp_path, monkeypatch)
    manager.config_revision += 1
    with pytest.raises(LocalLlamaError) as exc:
        apply(manager, plan)
    assert exc.value.reason == "plan_changed"
    assert manager.setup.status()["inventory"] == []


def test_off_guard_and_active_turn_guard(manager, tmp_path, monkeypatch):
    plan, _ = bundle(manager, tmp_path, monkeypatch)
    manager.server = "running"
    with pytest.raises(LocalLlamaError) as exc:
        apply(manager, plan)
    assert exc.value.reason == "server_must_be_off"
    manager.server = "off"
    manager.leases["busy"] = {}
    with pytest.raises(LocalLlamaError) as exc:
        apply(manager, plan)
    assert exc.value.reason == "active_turns"
    manager.leases.clear()


def test_digest_failure_preserves_existing_config(manager, tmp_path, monkeypatch):
    plan, _ = bundle(manager, tmp_path, monkeypatch)
    def corrupt(*_, **kwargs):
        Path(kwargs["destination"]).write_bytes(b"not the approved archive")
    monkeypatch.setattr(module, "official_get", corrupt)
    op = settle(manager, apply(manager, plan))
    assert op["state"] == "failed" and op["error"]["reason"] == "digest_mismatch"
    assert manager.config["executable_path"] is None
    assert not Path(plan["directory"]).exists()


def test_persist_failure_never_starts_install(manager, tmp_path, monkeypatch):
    plan, _ = bundle(manager, tmp_path, monkeypatch)
    with monkeypatch.context() as patch:
        patch.setattr(manager.setup, "_persist", lambda: (_ for _ in ()).throw(OSError("disk full")))
        with pytest.raises(LocalLlamaError) as error:
            apply(manager, plan)
        assert error.value.reason == "storage_unavailable"
    assert manager.setup.active is None
    assert not Path(plan["directory"]).exists()


@pytest.mark.parametrize("name", ["../escape", "/absolute", "C:/escape", "a/../escape", "nul.txt", "a:stream", "name. "])
def test_archive_rejects_unsafe_paths(tmp_path, name):
    archive = tmp_path / "bad.zip"
    with zipfile.ZipFile(archive, "w") as out:
        out.writestr(name, "unsafe")
    dest = tmp_path / "out"
    dest.mkdir()
    with pytest.raises(LocalLlamaError):
        extract_zip(archive, dest)


def test_archive_rejects_duplicate_case_and_symlinks(tmp_path):
    for index, entries in enumerate((("a.dll", "A.dll"), ("link",))):
        archive = tmp_path / f"bad{index}.zip"
        with zipfile.ZipFile(archive, "w") as out:
            for name in entries:
                info = zipfile.ZipInfo(name)
                if name == "link":
                    info.external_attr = 0o120777 << 16
                out.writestr(info, "x")
        dest = tmp_path / f"out{index}"
        dest.mkdir()
        with pytest.raises(LocalLlamaError):
            extract_zip(archive, dest)


def test_config_journal_recovers_committed_revision_and_refuses_foreign_edit(manager):
    before = deepcopy(manager.config)
    after = dict(before, port=8199)
    atomic_json_write(manager.directory / "config-journal.json", {"before": before, "after": after, "revision": 1})
    manager.config_store.write(after)
    recover(manager.directory, manager.config_store)
    assert json.loads((manager.directory / "state.json").read_text())["config_revision"] == 1
    atomic_json_write(manager.directory / "config-journal.json", {"before": before, "after": after, "revision": 1})
    manager.config_store.write(dict(after, port=8200))
    with pytest.raises(LocalLlamaError) as error:
        recover(manager.directory, manager.config_store)
    assert error.value.reason == "recovery_required"


def test_external_edit_cannot_be_overwritten(manager):
    manager.config_store.write(dict(manager.config, port=8199))
    with pytest.raises(LocalLlamaError) as error:
        manager._save(dict(manager.config, port=8200))
    assert error.value.reason == "stale_revision"
    assert manager.config_store.read()["port"] == 8199


def test_stable_pointer_and_cuda_dependency_are_resolved_from_official_rows():
    names = ["llama-b12345-bin-win-cpu-x64.zip", "llama-b12345-bin-win-cuda-13.3-x64.zip", "cudart-llama-bin-win-cuda-13.3-x64.zip"]
    row = {"id": 77, "tag_name": "b12345", "prerelease": True, "assets": [
        {"id": i, "name": n, "size": 123, "digest": "sha256:" + "a" * 64, "browser_download_url": "https://github.com/asset"} for i, n in enumerate(names)]}
    pointer = {"tag_name": "v1", "assets": [{"name": "nightly-tag.txt", "browser_download_url": "https://github.com/pointer"}]}
    def get(url, **kwargs):
        if url.endswith("pointer"):
            return b"b12345\n"
        return json.dumps(row if "/tags/" in url else [pointer, row]).encode()
    rows = ReleaseCatalog(get).list()
    assert len(rows) == 1 and rows[0]["stable_alias"] == "v1"
    assert len(next(v for v in rows[0]["variants"] if v["backend"] == "cuda")["artifacts"]) == 2


def test_setup_dispatch_permissions_and_independent_lookup(manager, monkeypatch):
    from agent_runtime import serve_rpc
    from agent_runtime.call_authorization import UNKNOWN_CALLER, RpcCaller, CALLER_PEER
    from agent_runtime.local_llama import setup_rpc
    monkeypatch.setattr(setup_rpc, "get_manager", lambda: manager)
    def call(suffix, caller=None, params=None):
        ctx = serve_rpc.RpcContext() if caller is None else serve_rpc.RpcContext(caller=caller)
        return serve_rpc.handle_request({"jsonrpc": "2.0", "id": "setup", "method": "runtime.local_llama." + suffix, "params": params or {}}, ctx)
    assert call("setup.status")["result"]["inventory"] == []
    unknown = call("setup.status", params={"request_id": str(uuid.uuid4())})["result"]
    assert unknown["lookup_state"] == "not_found" and unknown["active_operation"] is None
    for suffix in setup_rpc.FIELDS:
        if suffix != "setup.capabilities":
            assert "error" in call(suffix, UNKNOWN_CALLER)
        assert "error" in call(suffix, RpcCaller(kind=CALLER_PEER, transport="gateway", peer_install_id="peer"))
    assert call("setup.capabilities", UNKNOWN_CALLER)["result"]["features"]["host_browser"] is False


def test_published_install_recovers_after_missing_terminal_receipt(manager, tmp_path, monkeypatch):
    plan, _ = bundle(manager, tmp_path, monkeypatch)
    request = apply(manager, plan)
    assert settle(manager, request)["state"] == "succeeded"
    saved = manager.setup.data
    saved["receipts"][request["request_id"]]["operation"]["state"] = "running"
    saved["inventory"] = []  # crash between atomic directory publication and inventory commit
    manager.setup._persist()
    manager.close()
    recovered = LocalLlamaManager(tmp_path / "root", tmp_path / "config.yaml", "setup-host")
    try:
        state = recovered.setup.status(request_id=request["request_id"])
        assert state["requested_operation"]["state"] == "interrupted"
        assert len(state["inventory"]) == 1
        assert recovered.config["executable_path"] is None
        assert Path(state["inventory"][0]["executable_path"]).is_file()
    finally:
        recovered.close()


def test_managed_dependency_tamper_refuses_activation(manager, tmp_path, monkeypatch):
    plan, _ = bundle(manager, tmp_path, monkeypatch)
    request = apply(manager, plan)
    assert settle(manager, request)["state"] == "succeeded"
    row = manager.setup.status()["inventory"][0]
    (Path(row["directory"]) / "build/bin/ggml.dll").write_bytes(b"changed")
    request = guards(manager, installation_id=row["installation_id"], expect_inventory_revision=1)
    manager.setup.submit("activate", request)
    assert settle(manager, request)["error"]["reason"] == "recovery_required"
    assert manager.config["executable_path"] is None
