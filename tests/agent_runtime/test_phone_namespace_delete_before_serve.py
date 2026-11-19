"""A phone's account data, in namespaces like the desktop's, deleted before the embedded serve starts.

Row RT-PHONE-NAMESPACE-DELETE-BEFORE-SERVE; plan
``docs/agent-runtime-harness/planned/phone-namespace-delete-before-serve-2026-11-19.md`` (S1-S3; S4 is
``tests/scripts/test_bundle_namespace_closure.py``). The phone has no CLI process to spawn, so the host
calls :func:`delete_namespace` in its own interpreter before :class:`EmbeddedServe` starts, and gets the
JSON ``hermes namespace delete`` prints. Temp app folders only.

Killing mutations (applied, red recorded, reverted — see the commit message).
"""

from __future__ import annotations

import importlib
import json
import os
import sys
from pathlib import Path

import pytest

import agent_runtime
from agent_runtime.host_store import binding
from agent_runtime.host_store.fake import FakeHostSecureStore
from hermes_cli import _namespace_bootstrap as ns
from hermes_cli import namespace_cmd
from hermes_cli.harness_parts.serve import in_memory
from hermes_cli.harness_parts.serve.in_memory import EmbeddedServe, configure_app_folder, delete_namespace

A = "acct-00000000000000aa"
B = "acct-00000000000000bb"
SWITCHED_OFF = ("agent_runtime.serve_registry", "agent_runtime.serve_socket")
#: Every variable a namespace configure exports into ``os.environ`` (restored after each test).
_EXPORTED = ("HERMES_HOME", "HERMES_AGENT_RUNTIME_ROOT", "HERMES_HEAD_HOME", ns.ENV, ns.SOURCE_ENV, ns.DIR_ENV,
             ns.DEPENDENCY_ENV, ns.LAUNCHER_ENV, ns.ORIGIN_ENV, ns.AUTH_HOME_ENV, *ns.FENCE_DEFAULTS)


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.setattr(ns, "long_paths_enabled", lambda: True)
    for key in _EXPORTED:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(in_memory, "_SERVING_NAMESPACE", [])
    binding.unbind_host_store()
    yield
    binding.unbind_host_store()


def _make(app: Path, ns_id: str) -> Path:
    """Namespace *ns_id* of *app*, created by the host's own configure (into a scratch env), with data."""
    values = configure_app_folder(app, {}, namespace=ns_id)
    (Path(values["HERMES_HOME"]) / "memories").mkdir(parents=True, exist_ok=True)
    (Path(values["HERMES_HOME"]) / "memories" / "MEMORY.md").write_text("account data\n", encoding="utf-8")
    return app / ns.DIRNAME / ns_id


def _cli_delete(app: Path, ns_id: str, monkeypatch, capsys, *, inside: str | None = None) -> dict:
    """What ``hermes namespace delete <id>`` prints over the same app folder (in namespace *inside*)."""
    with monkeypatch.context() as patch:
        base = str(app / "hermes")
        for key, value in {"HERMES_HOME": base, ns.DEPENDENCY_ENV: base, ns.LAUNCHER_ENV: "1",
                           **({ns.ENV: inside} if inside else {})}.items():
            patch.setenv(key, value)
        capsys.readouterr()
        namespace_cmd.main(["delete", ns_id])
        return json.loads(capsys.readouterr().out)


def test_namespace_admin_imports_and_deletes_without_the_switched_off_modules(tmp_path, monkeypatch):
    """S1: the phone bundle ships neither the serve registry nor the socket lane; the verb still loads."""
    app = tmp_path / "app"
    root = _make(app, B)
    for name in [m for m in sys.modules if m.startswith(SWITCHED_OFF)] + list(SWITCHED_OFF):
        monkeypatch.setitem(sys.modules, name, None)  # `import x` of a None entry raises ImportError
    monkeypatch.setattr(agent_runtime, "namespace_admin", agent_runtime.namespace_admin)
    monkeypatch.delitem(sys.modules, "agent_runtime.namespace_admin")
    with pytest.raises(ImportError):  # positive control: the modules really are blocked
        importlib.import_module("agent_runtime.serve_socket.owner_lock")
    fresh = importlib.import_module("agent_runtime.namespace_admin")
    env = {"HERMES_HOME": str(app / "hermes"), ns.DEPENDENCY_ENV: str(app / "hermes"), ns.LAUNCHER_ENV: "1"}
    assert fresh.list_namespaces(env)["namespaces"][0]["busy"] is None
    assert fresh.delete(B, env)["ok"] is True
    assert not root.exists()


def test_configure_names_the_namespace_as_the_desktop_resolves_it(tmp_path):
    """S2: the CLI's own resolution over the app folder — the same home, store root and manifest."""
    app = tmp_path / "app"
    environ: dict[str, str] = {}
    values = configure_app_folder(app, environ, namespace=A, origin=ns.ORIGIN_ACCOUNT)
    root = app / ns.DIRNAME / A
    assert environ == values
    assert values["HERMES_HOME"] == str(root / "profiles" / "base")
    assert values["HERMES_AGENT_RUNTIME_ROOT"] == str(root / "agent-runtime")
    assert values[ns.ENV] == A and values[ns.DEPENDENCY_ENV] == str(app / "hermes")
    assert Path(values["HERMES_HOME"]).is_dir() and Path(values["HERMES_AGENT_RUNTIME_ROOT"]).is_dir()
    manifest = json.loads((root / ns.MANIFEST_NAME).read_text(encoding="utf-8"))
    assert manifest["id"] == A and manifest["origin"] == ns.ORIGIN_ACCOUNT and manifest["epoch"]
    # Without a namespace: today's base-root layout, unchanged.
    assert configure_app_folder(app, {}) == in_memory.app_folder_environment(app)


@pytest.mark.parametrize("ns_id, reason", [("Bad/Id", "namespace_invalid_id"), ("base", "namespace_reserved")])
def test_configure_refuses_a_bad_namespace_and_sets_nothing(tmp_path, ns_id, reason):
    environ: dict[str, str] = {}
    with pytest.raises(ns.NamespaceRefused) as refused:
        configure_app_folder(tmp_path / "app", environ, namespace=ns_id)
    assert refused.value.reason.value == reason
    assert environ == {}


def test_configure_refuses_a_store_newer_than_this_build_and_sets_nothing(tmp_path):
    from agent_runtime import store_epoch

    app = tmp_path / "app"
    root = _make(app, A)
    manifest_path = root / ns.MANIFEST_NAME
    record = json.loads(manifest_path.read_text(encoding="utf-8"))
    record["epoch"]["value"] = store_epoch.STORE_EPOCH + 1
    manifest_path.write_text(json.dumps(record), encoding="utf-8")
    environ: dict[str, str] = {}
    with pytest.raises(ns.NamespaceRefused) as refused:
        configure_app_folder(app, environ, namespace=A)
    assert refused.value.reason.value == "namespace_epoch_newer"
    assert environ == {}
    assert json.loads(manifest_path.read_text(encoding="utf-8")) == record  # a refusal writes nothing


def test_delete_answers_what_the_cli_prints(tmp_path, monkeypatch, capsys):
    """S3: every refusal is the CLI's payload; a delete is the CLI's verb, without touching os.environ."""
    app = tmp_path / "app"
    _make(app, A)
    before = dict(os.environ)
    for ns_id in ("acct-00000000000000cc", "base", "Bad/Id"):
        mine = delete_namespace(app, ns_id)
        assert mine["ok"] is False and mine == _cli_delete(app, ns_id, monkeypatch, capsys), ns_id
    assert {r["reason"] for r in (delete_namespace(app, i) for i in ("base", "Bad/Id"))} == {
        "namespace_reserved", "namespace_invalid_id"}
    _make(app, B)
    cli = _cli_delete(app, B, monkeypatch, capsys)
    _make(app, B)
    assert delete_namespace(app, B) == cli and cli["ok"] is True
    assert os.environ == before


def test_one_process_deletes_one_namespace_then_serves_another(tmp_path, monkeypatch, capsys):
    """The row's done-when: delete B, configure A, start the embedded serve in A — in one process.
    After start, A is held: its delete is refused as the CLI refuses the namespace it runs in."""
    app = tmp_path / "app"
    gone = _make(app, B)
    assert delete_namespace(app, B)["ok"] is True
    assert not gone.exists()
    values = configure_app_folder(app, namespace=A)
    assert os.environ["HERMES_HOME"] == values["HERMES_HOME"]
    store = FakeHostSecureStore()
    store.bind(profile="phone", store_root=app)
    frames: list[dict] = []
    serve = EmbeddedServe(lambda line: frames.append(json.loads(line)))
    serve.start()
    try:
        refused = delete_namespace(app, A)
        assert refused["reason"] == "namespace_in_use_by_this_process", refused
        assert refused == _cli_delete(app, A, monkeypatch, capsys, inside=A)
        assert (app / ns.DIRNAME / A / ns.MANIFEST_NAME).is_file()
    finally:
        serve.close()
        assert serve.wait(60) is not None
    assert any(f.get("event") == "ready" for f in frames), frames[:3]
    assert store.protected == [values["HERMES_HOME"]]
    assert not gone.exists()
