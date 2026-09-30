"""Bundle profile manifest: the bundled-desktop profile switches its toolsets off through
Hermes's own ``agent.disabled_toolsets`` pipeline, and its refused download routes refuse.

Killing mutations (applied, red recorded, reverted — see the commit message):

* ``apply_to_config`` merges ``[*existing]`` only (drop the profile's toolsets)
  -> ``test_profile_switches_the_listed_toolsets_off`` red.
* ``validate_manifest`` skips the unknown-toolset check
  -> ``test_unknown_toolset_is_refused`` red.
* ``ProfileRouteGate.refuses`` returns ``False``
  -> ``test_switched_off_download_route_refuses`` red.
"""

from __future__ import annotations

import pytest

from agent_runtime.bundle_profiles.manifest import (
    ProfileManifestError,
    apply_to_config,
    load_profile,
    parse_manifest,
)

PROFILE = "bundled-desktop"


def _selected(disabled):
    """The tool names Hermes's own selection produces for the CLI bundle (before check_fn filtering)."""
    import model_tools

    return model_tools._select_tool_names(["hermes-cli"], disabled, True)


def test_profile_switches_the_listed_toolsets_off():
    from toolsets import resolve_toolset

    manifest = load_profile(PROFILE)
    config = apply_to_config(manifest, {"agent": {"disabled_toolsets": []}})
    disabled = config["agent"]["disabled_toolsets"]

    before = _selected([])
    after = _selected(disabled)

    # Positive control: the same selection without the profile carries the shell family.
    assert {"terminal", "process_manage", "execute_code", "browser_navigate"} <= before
    for toolset in manifest.disabled_toolsets:
        leaked = set(resolve_toolset(toolset)) & after
        assert not leaked, f"{toolset} still selected: {sorted(leaked)}"
    # Everything the profile keeps survives.
    assert {"read_file", "web_search", "memory", "delegate_task", "clarify"} <= after


def test_profile_config_switches_are_applied_and_existing_disables_kept():
    manifest = load_profile(PROFILE)
    config = apply_to_config(manifest, {"agent": {"disabled_toolsets": ["spotify"]}, "security": {"x": 1}})

    assert config["agent"]["disabled_toolsets"][0] == "spotify"
    assert config["security"] == {"x": 1, "allow_lazy_installs": False}
    assert config["updates"]["check"] is False
    assert config["wake_word"]["enabled"] is False
    assert manifest.environment["HF_HUB_OFFLINE"] == "1"


def _raw(**overrides):
    data = {"schema_version": 1, "profile": "p", "toolsets": {"disabled": ["terminal"]}, "config": {}}
    data.update(overrides)
    return data


def test_unknown_toolset_is_refused():
    parse_manifest(_raw())  # positive control: a known toolset loads
    with pytest.raises(ProfileManifestError, match="unknown toolsets"):
        parse_manifest(_raw(toolsets={"disabled": ["no_such_toolset"]}))


def test_invented_config_key_is_refused():
    parse_manifest(_raw(config={"updates.check": False}))  # positive control
    with pytest.raises(ProfileManifestError, match="config keys"):
        parse_manifest(_raw(config={"updates.invented_switch": False}))


def test_every_bundle_exclusion_states_its_reason():
    parse_manifest(_raw(packaging={"excluded_data": {"site-packages/x/data": "why"}}))  # positive control
    with pytest.raises(ProfileManifestError, match="non-empty reasons"):
        parse_manifest(_raw(packaging={"excluded_data": {"site-packages/x/data": " "}}))


@pytest.mark.parametrize("profile", [PROFILE, "bundled-phone"])
def test_bundled_plugins_name_real_plugin_directories(profile):
    from pathlib import Path

    manifest = load_profile(profile)
    plugins = Path(__file__).resolve().parents[2] / "plugins"
    assert manifest.packaging_plugins
    assert [p for p in manifest.packaging_plugins if not (plugins / p).is_dir()] == []


@pytest.mark.parametrize("profile", [PROFILE, "bundled-phone"])
def test_packaging_modules_name_real_modules(profile):
    """Every closure root and switched-off prefix names a first-party module in this tree."""
    from scripts.bundle_profile_closure import module_index

    index = module_index()
    manifest = load_profile(profile)
    missing = [
        name for name in (*manifest.packaging_roots, *manifest.switched_off_modules)
        if not any(m == name or m.startswith(name + ".") for m in index)
    ]
    assert not missing


# -- refused routes -----------------------------------------------------------------------------


def _local_models_app(gated: bool):
    from fastapi import FastAPI

    from hermes_cli.web_routers import local_models

    app = FastAPI()
    app.include_router(local_models.router)
    if gated:
        from agent_runtime.bundle_profiles.route_gate import install_route_gate

        install_route_gate(app, load_profile(PROFILE))
    return app


def _code(response):
    try:
        return response.json().get("code")
    except ValueError:
        return None


def test_switched_off_download_route_refuses():
    from starlette.testclient import TestClient

    # Positive control: ungated, the same request reaches upstream's handler.
    with TestClient(_local_models_app(gated=False)) as client:
        assert _code(client.post("/api/local-models/download/pause", json={})) != "disabled_by_profile"

    with TestClient(_local_models_app(gated=True)) as client:
        for method, path in (("post", "/api/local-models/download"), ("get", "/api/local-models/catalog"),
                             ("post", "/api/local-models/download/pause"),
                             ("post", "/api/local-models/quickstart")):
            response = getattr(client, method)(path, json={}) if method == "post" else client.get(path)
            assert response.status_code == 404, path
            assert response.json()["code"] == "disabled_by_profile", path
            assert response.json()["feature"] == "model_downloads"
        # A route the profile keeps (engine install / job status) is not refused.
        assert _code(client.get("/api/local-models/jobs")) != "disabled_by_profile"


def test_gate_refuses_to_install_over_a_missing_route():
    from fastapi import FastAPI

    from agent_runtime.bundle_profiles.route_gate import RouteGateError, install_route_gate

    with pytest.raises(RouteGateError, match="name no mounted route"):
        install_route_gate(FastAPI(), load_profile(PROFILE))


def test_the_cpu_speech_pack_keeps_only_what_the_numpy_preprocessors_read():
    """Mutation: widen the onnx-asr globs to ``preprocessors/data/*`` -> the positive controls go
    red (``fbanks.npz`` holds both engines' mel filterbanks; the 16 kHz resamplers load at model
    start); drop the ``whisper*`` entry -> the Whisper graphs ship unused."""
    from scripts.bundle_profile_package import _excluded

    excluded = load_profile(PROFILE).excluded_data
    for dropped in ("nemo128.onnx", "whisper80.onnx", "whisper128_conv.onnx"):
        assert _excluded(f"site-packages/onnx_asr/preprocessors/data/{dropped}", excluded), dropped
    for kept in ("fbanks.npz", "resample_8_16.onnx", "resample_48_16.onnx"):
        assert not _excluded(f"site-packages/onnx_asr/preprocessors/data/{kept}", excluded), kept


def test_the_speech_pack_runs_whisper_on_onnx_asr_and_ships_no_ctranslate2():
    """Owner ruling 2026-09-29: Whisper runs on onnxruntime, so the speech pack carries no
    ctranslate2 (and with it no Intel OpenMP) and no faster-whisper. The pack's closure is taken
    from ``uv.lock`` through the packager's own graph. Mutation: put ``stt-whisper`` back in the
    pack's extras -> red; positive control: onnx-asr and onnxruntime are in the closure."""
    from scripts.bundle_profile_closure import Graph, _lock, declared

    manifest = load_profile(PROFILE)
    _, extras = declared()
    roots = set().union(*(extras[extra] for extra in manifest.packaging_packs["speech"]))
    closure = Graph(_lock(), placeholders=manifest.placeholder_distributions).closure(roots)
    assert {"onnx-asr", "onnxruntime", "numpy"} <= closure
    assert not {"ctranslate2", "faster-whisper", "av", "tokenizers"} & closure


def test_the_closure_report_walks_enclosing_packages(monkeypatch):
    """The report walks the way the packager does (``parents=True``), so its counts
    include what a kept module's package ``__init__`` imports."""
    from scripts import bundle_profile_closure as closure_script

    seen = {}

    def fake_closure(profile, **kwargs):
        seen.update(kwargs)
        raise SystemExit(0)

    monkeypatch.setattr(closure_script, "closure", fake_closure)
    with pytest.raises(SystemExit):
        closure_script.main(["--no-boot"])
    assert seen == {"boot": False, "parents": True}


# -- local_models.downloads: the Launcher is the one model downloader --------------------------------


def _downloads(value):
    """Write ``local_models.downloads`` into the hermetic home's config (None = absent)."""
    import os
    from pathlib import Path

    from agent_runtime import yaml_io

    home = Path(os.environ["HERMES_HOME"])
    home.mkdir(parents=True, exist_ok=True)
    data = {} if value is None else {"local_models": {"downloads": value}}
    (home / "config.yaml").write_text(yaml_io.dump(data), encoding="utf-8")


@pytest.mark.parametrize("profile", ["bundled-desktop", "bundled-phone"])
def test_both_bundled_profiles_switch_model_downloads_off(profile):
    from agent_runtime.bundle_profiles.model_downloads import FEATURE, MODEL_DOWNLOAD_ROUTES

    manifest = load_profile(profile)
    assert manifest.config["local_models.downloads"] is False
    assert manifest.refused_routes.feature == FEATURE
    assert frozenset(manifest.refused_routes.paths) == MODEL_DOWNLOAD_ROUTES


def test_the_serve_loop_goes_offline_when_downloads_are_off(monkeypatch):
    import io

    from hermes_cli.harness_parts.serve.session import serve_loop

    monkeypatch.setenv("HF_HUB_OFFLINE", "set-so-teardown-restores-absence")
    monkeypatch.delenv("HF_HUB_OFFLINE")
    _downloads(None)  # positive control: absent = today's behaviour, the Hub stays reachable
    assert serve_loop(iter(()), io.StringIO(), dispatch=lambda *_a, **_k: None) == 0
    assert "HF_HUB_OFFLINE" not in __import__("os").environ
    _downloads(False)
    assert serve_loop(iter(()), io.StringIO(), dispatch=lambda *_a, **_k: None) == 0
    assert __import__("os").environ["HF_HUB_OFFLINE"] == "1"


def test_a_host_chosen_offline_value_is_kept(monkeypatch):
    from agent_runtime.bundle_profiles.model_downloads import apply_model_download_switch

    _downloads(False)
    environ = {"HF_HUB_OFFLINE": "0"}
    assert apply_model_download_switch(environ) is True
    assert environ == {"HF_HUB_OFFLINE": "0"}
    environ = {}
    assert apply_model_download_switch(environ) is True and environ == {"HF_HUB_OFFLINE": "1"}


def _harness_dashboard_app(monkeypatch):
    """Mount the harness plugin's dashboard API module the way upstream's
    ``_mount_plugin_api_routes`` does: imported while ``hermes_cli.web_server.app`` exists."""
    import importlib.util
    import sys
    import types
    from pathlib import Path

    from fastapi import FastAPI
    from hermes_cli.web_routers import local_models

    app = FastAPI()
    app.include_router(local_models.router)
    monkeypatch.setitem(sys.modules, "hermes_cli.web_server", types.SimpleNamespace(app=app))
    path = Path(__file__).resolve().parents[2] / "plugins/eternia-harness/dashboard/plugin_api.py"
    spec = importlib.util.spec_from_file_location("eternia_harness_plugin_api_under_test", path)
    spec.loader.exec_module(importlib.util.module_from_spec(spec))
    return app


def test_the_harness_dashboard_refuses_model_downloads_when_they_are_off(monkeypatch):
    from starlette.testclient import TestClient

    _downloads(True)  # positive control: on, the same request reaches upstream's handler
    with TestClient(_harness_dashboard_app(monkeypatch)) as client:
        assert _code(client.get("/api/local-models/catalog")) != "disabled_by_profile"

    _downloads(False)
    with TestClient(_harness_dashboard_app(monkeypatch)) as client:
        for method, path in (("get", "/api/local-models/catalog"), ("post", "/api/local-models/download"),
                             ("get", "/api/local-models/search"), ("post", "/api/local-models/quickstart")):
            response = getattr(client, method)(path, json={}) if method == "post" else client.get(path)
            assert response.status_code == 404, path
            assert response.json()["code"] == "disabled_by_profile", path
            assert response.json()["key"] == "local_models.downloads"
        # The engine install / job status the Launcher still drives is not refused.
        assert _code(client.get("/api/local-models/jobs")) != "disabled_by_profile"


def test_the_model_download_gate_refuses_to_install_over_a_renamed_route(monkeypatch):
    from fastapi import FastAPI

    from agent_runtime.bundle_profiles import model_downloads
    from agent_runtime.bundle_profiles.route_gate import RouteGateError

    _downloads(False)
    monkeypatch.setattr(model_downloads, "MODEL_DOWNLOAD_ROUTES", model_downloads.MODEL_DOWNLOAD_ROUTES | {"/api/local-models/gone"})
    with pytest.raises(RouteGateError, match="name no mounted route"):
        model_downloads.gate_model_download_routes(FastAPI())
