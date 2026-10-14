"""All declared provider/mode combinations use import names, not distributions."""
from importlib.machinery import PathFinder
from itertools import product
from types import ModuleType
import sys

import pytest

from hermes_cli import runtime_environment as runtime


@pytest.fixture
def installed_sdk_fixture(tmp_path, monkeypatch):
    for name in ("openai", "anthropic", "boto3"):
        (tmp_path / f"{name}.py").write_text("")
    google = tmp_path / "google"
    google.mkdir()
    (google / "auth.py").write_text("")
    probes = []
    def available(name):
        probes.append(name)
        parent, _, leaf = name.rpartition(".")
        return PathFinder.find_spec(leaf if parent else name, [str(tmp_path / parent) if parent else str(tmp_path)]) is not None
    monkeypatch.setattr(runtime, "module_available", available)
    monkeypatch.setattr(runtime, "venv_integrity_issues", lambda _: [])
    jiter = ModuleType("jiter")
    jiter.from_json = lambda _: None
    monkeypatch.setitem(sys.modules, "jiter", jiter)
    return tmp_path, probes


def test_installed_requirement_matrix(installed_sdk_fixture):
    providers = {"openai-codex": ["openai"], "openai": ["openai"], "anthropic": ["anthropic"], "bedrock": ["boto3"], "vertex": ["google-auth"], "opencode-zen": []}
    modes = {None: [], "codex_responses": ["openai"], "responses": ["openai"], "anthropic_messages": ["anthropic"]}
    for provider, mode in product((*runtime._PROVIDER_PACKAGE_REQUIREMENTS, "opencode-zen"), (None, *runtime._API_MODE_PACKAGE_REQUIREMENTS)):
        expected = list(dict.fromkeys(providers[provider] + modes[mode]))
        assert runtime.required_packages_for(provider=provider, api_mode=mode) == expected
        assert runtime.missing_runtime_packages_for(provider=provider, api_mode=mode) == []
    assert runtime.required_packages_for(model="codex-model") == ["openai"]


def test_import_name_decides_and_absence_is_reported(installed_sdk_fixture):
    tmp_path, probes = installed_sdk_fixture
    assert runtime.missing_runtime_packages_for(provider="vertex") == []
    assert "google.auth" in probes and "google-auth" not in probes
    (tmp_path / "anthropic.py").unlink()
    assert runtime.missing_runtime_packages_for(provider="opencode-zen", api_mode="anthropic_messages") == ["anthropic"]
    missing = runtime.runtime_environment_status(["anthropic"]).issues
    assert missing[0]["kind"] == "runtime_dependency_missing"
    assert "hermes pm install --extra anthropic" in missing[0]["summary"]
