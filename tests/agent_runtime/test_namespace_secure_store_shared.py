"""On a shared namespace both editions read the OS secure store (row RT-NAMESPACE-SECURE-STORE-SHARED).

Launcher plan EDITION_SWITCH_NAMESPACE_STORE §6 R1, owner ruling Q3 (2026-10-20). The bundled edition
binds the secure store and MOVES plaintext ``auth.json`` into it; without a shared rule the Developer
Edition (switch off) would then find no ``auth.json`` and be signed out. The first bind records
``secure_store: true`` in ``namespace.json`` and every edition honours it. Temp homes and an
in-memory store only — no real OS store, no real home.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_runtime.bundle_profiles.manifest import apply_to_config, load_profile
from agent_runtime.host_store import binding, desktop_binding
from agent_runtime.host_store.fake import FakeHostSecureStore
from hermes_cli import _namespace_bootstrap as ns

NS = "acct-0123456789abcdef"
SECRET = {"providers": {"nous": {"access_token": "shared-store-token-6c1a"}}}


@pytest.fixture(autouse=True)
def _unbound_after():
    binding.unbind_host_store()
    yield
    binding.unbind_host_store()


@pytest.fixture
def home(tmp_path: Path, monkeypatch) -> Path:
    monkeypatch.setattr(ns, "long_paths_enabled", lambda: True)
    env = {"HERMES_DEPENDENCY_ROOT": str(tmp_path / ".hermes"), "HERMES_NAMESPACES_DIR": str(tmp_path / "ns"),
           "HERMES_NAMESPACE": NS}
    item = ns.layout(NS, env)
    ns.ensure_manifest(item)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("HERMES_HOME", str(item.home()))
    monkeypatch.setenv("HERMES_SHARED_AUTH_DIR", str(item.root / "shared"))
    item.home().mkdir(parents=True)
    return item.home()


def _edition(home: Path, *, bundled: bool) -> None:
    config = apply_to_config(load_profile("bundled-desktop"), {}) if bundled else {}
    (home / "config.yaml").write_text(json.dumps(config), encoding="utf-8")


def _manifest(home: Path) -> dict:
    return json.loads((home.parents[1] / ns.MANIFEST_NAME).read_text(encoding="utf-8"))


def test_the_developer_edition_reads_the_store_the_bundled_edition_moved_its_login_into(home: Path):
    store = FakeHostSecureStore()  # one OS store, as DPAPI is one per user
    factory = lambda _blob_dir: store
    (home / "auth.json").write_text(json.dumps(SECRET), encoding="utf-8")
    _edition(home, bundled=False)
    assert desktop_binding.bind_desktop_host_store(store_factory=factory) is None  # nothing set it yet
    _edition(home, bundled=True)
    bundled = desktop_binding.bind_desktop_host_store(store_factory=factory)
    assert bundled is not None and not (home / "auth.json").exists()  # moved, plaintext gone
    assert _manifest(home)[desktop_binding.NAMESPACE_FACT] is True
    binding.unbind_host_store()
    _edition(home, bundled=False)  # the Developer Edition: its own switch is off
    developer = desktop_binding.bind_desktop_host_store(store_factory=factory)
    assert developer is not None, "the Developer Edition is signed out of a shared namespace"
    assert json.loads(developer.callbacks.read(developer.slot(home / "auth.json"))) == SECRET


def test_the_base_root_has_no_namespace_fact(home: Path, monkeypatch):
    monkeypatch.delenv("HERMES_NAMESPACE")
    _edition(home, bundled=False)
    assert desktop_binding.namespace_secure_store() is False
    assert desktop_binding.record_namespace_secure_store() is False
