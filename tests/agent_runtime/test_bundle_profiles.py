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


def test_packaging_modules_name_real_modules():
    """Every closure root and switched-off prefix names a first-party module in this tree."""
    from scripts.bundle_profile_closure import module_index

    index = module_index()
    manifest = load_profile(PROFILE)
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
