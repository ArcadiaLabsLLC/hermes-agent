"""Provider packs: which pack carries a missing provider SDK, and loading one without a restart.

OWNER RULING 2026-10-15: the bundled Eternia Harness ships no Bedrock / Vertex / Azure
identity / Mistral SDK; each is a pack per release the Launcher downloads only when the
user signs in to that provider. The runtime reports the pack and never installs.
"""

from __future__ import annotations

import importlib
import json
import os
import sys
from pathlib import Path

import pytest

from agent_runtime import provider_dependencies as deps
from agent_runtime import provider_packs
from agent_runtime.provider_account import ProviderRefused
from hermes_cli import runtime_environment

COMMIT = "c0ffee" * 6 + "abcd"
PACKS = {"speech": ["speech-tts", "stt-onnx"], "provider-bedrock": ["bedrock"], "provider-vertex": ["vertex"]}


def _bundle(root: Path, packs=PACKS, commit=COMMIT) -> Path:
    """A packager-shaped bundle root: ``app/`` beside ``bundle-manifest.json``."""
    app = root / "app"
    app.mkdir(parents=True)
    (root / "bundle-manifest.json").write_text(json.dumps({"schema": 1, "commit": commit, "packs": packs}),
                                               encoding="utf-8")
    return app


def _pack(root: Path, name: str, module: str, commit=COMMIT) -> Path:
    """An unpacked pack: ``engine-pack.json`` beside ``site-packages/`` holding ``module``."""
    site_dir = root / name / "site-packages"
    site_dir.mkdir(parents=True)
    (site_dir / f"{module}.py").write_text("ANSWER = 42\n", encoding="utf-8")
    (root / name / "engine-pack.json").write_text(json.dumps({"schema": 1, "pack": name, "commit": commit}),
                                                  encoding="utf-8")
    return site_dir


@pytest.fixture
def bundled(tmp_path, monkeypatch):
    app = _bundle(tmp_path / "bundle")
    monkeypatch.setattr(provider_packs, "_APP_DIR", app)
    monkeypatch.setattr(deps, "_sdk_free", lambda: False)
    monkeypatch.setattr(deps, "_supported", lambda extra: True)
    return app


@pytest.fixture
def isolated_path(monkeypatch):
    monkeypatch.setattr(sys, "path", list(sys.path))
    monkeypatch.delenv(provider_packs.ENGINE_PACKS_ENV, raising=False)


def test_a_checkout_has_no_packs():
    """The Developer Edition runs from a checkout, whose root is not ``app/``: it installs extras."""
    assert provider_packs.bundle_packs() == (None, {})
    assert provider_packs.pack_for_extra("bedrock") is None


def test_the_pack_carrying_an_extra_is_named_from_the_bundle_record(bundled):
    """Killing mutation: drop the ``PROVIDER_PACK_PREFIX`` filter -> ``stt-onnx`` answers ``speech``."""
    assert provider_packs.pack_for_extra("bedrock") == {"name": "provider-bedrock", "commit": COMMIT}
    assert provider_packs.pack_for_extra("stt-onnx") is None
    assert provider_packs.pack_for_extra("mistral") is None
    assert provider_packs.pack_for_extra(None) is None


def test_a_bundle_reports_the_pack_and_offers_no_install(bundled, monkeypatch):
    """Killing mutation: report ``installable`` without the ``not bundled`` term -> anthropic is offered."""
    monkeypatch.setattr(runtime_environment, "missing_runtime_packages_for",
                        lambda *, provider=None, **_: {"bedrock": ["boto3"], "anthropic": ["anthropic"]}.get(provider, []))
    rows = {row["provider"]: row for row in deps.provider_dependency_report()["providers"]}
    assert rows["bedrock"] == {"provider": "bedrock", "missing": ["boto3"], "extra": "bedrock",
                               "installable": False, "pack_available": True,
                               "pack": {"name": "provider-bedrock", "commit": COMMIT}}
    # Positive control: a missing SDK no pack carries is neither installable nor pack-backed.
    assert (rows["anthropic"]["installable"], rows["anthropic"]["pack_available"]) == (False, False)


def test_a_bundle_refuses_the_install_and_names_the_pack(bundled, monkeypatch):
    monkeypatch.setattr(runtime_environment, "missing_runtime_packages_for",
                        lambda *, provider=None, **_: ["boto3"])
    with pytest.raises(ProviderRefused) as refused:
        deps.install_provider_dependency("bedrock", extend=lambda reqs: pytest.fail("a bundle installed"))
    assert (refused.value.reason, refused.value.data["pack"]) == ("pack_required", "provider-bedrock")


def test_an_unpacked_pack_imports_without_a_restart(bundled, tmp_path, isolated_path):
    """Killing mutation: drop ``site.addsitedir`` -> the import fails."""
    module = "w1015i_fake_provider_sdk"
    site_dir = _pack(tmp_path / "packs", "provider-bedrock", module)
    with pytest.raises(ImportError):
        importlib.import_module(module)
    result = provider_packs.activate_pack(str(site_dir))
    try:
        assert result == {"pack": "provider-bedrock", "site_packages": str(site_dir.resolve()), "activated": True}
        assert importlib.import_module(module).ANSWER == 42
        assert os.environ[provider_packs.ENGINE_PACKS_ENV] == str(site_dir.resolve())
        again = provider_packs.activate_pack(str(site_dir))
        assert again["activated"] is False
        assert os.environ[provider_packs.ENGINE_PACKS_ENV] == str(site_dir.resolve())
    finally:
        sys.modules.pop(module, None)


@pytest.mark.parametrize("name,commit,reason", [
    ("provider-azure-identity", COMMIT, "pack_unknown"),   # not a pack this bundle offers
    ("provider-bedrock", "0" * 40, "pack_mismatch"),        # built from another release
])
def test_a_pack_this_bundle_did_not_build_is_refused(bundled, tmp_path, isolated_path, name, commit, reason):
    """Killing mutation: drop the commit comparison -> the other release's pack loads."""
    site_dir = _pack(tmp_path / "packs", name, "w1015i_refused_sdk", commit=commit)
    with pytest.raises(ProviderRefused) as refused:
        provider_packs.activate_pack(str(site_dir))
    assert refused.value.reason == reason
    assert str(site_dir.resolve()) not in sys.path


def test_activation_outside_a_bundle_or_of_a_missing_folder_is_refused(tmp_path, monkeypatch, isolated_path):
    with pytest.raises(ProviderRefused) as refused:
        provider_packs.activate_pack(str(tmp_path))
    assert refused.value.reason == "not_a_bundle"
    monkeypatch.setattr(provider_packs, "_APP_DIR", _bundle(tmp_path / "bundle"))
    for path in (str(tmp_path / "absent"), "relative/site-packages"):
        with pytest.raises(ProviderRefused) as refused:
            provider_packs.activate_pack(path)
        assert refused.value.reason == "pack_not_found"


def test_the_activate_method_answers_a_frame(bundled, tmp_path, isolated_path):
    from agent_runtime.serve_rpc import provider as family

    site_dir = _pack(tmp_path / "packs", "provider-vertex", "w1015i_frame_sdk")
    try:
        frame = family._runtime_provider_pack_activate(1, {"site_packages": str(site_dir)})
        assert frame["result"]["pack"] == "provider-vertex"
        missing = family._runtime_provider_pack_activate(2, {})
        assert missing["error"]["data"]["reason"] == "site_packages_required"
    finally:
        sys.modules.pop("w1015i_frame_sdk", None)
