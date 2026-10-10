"""The provider-access port never runs plugin discovery (v0216 plan §1).

A first credential read used to pay full ``discover_plugins()`` — 650-900 ms at v0.21.6's
53 plugins, plus loader threads — on the hottest path of every process. The port now reads
its registry as-is; a bound provider home registers the harness's access on first read, so
a process with ``HERMES_AUTH_HOME`` bound still reads the owner's ``auth.json``.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

import agent.provider_access as access
from agent_runtime.profile_home import set_hermes_auth_home_override

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def no_discovery(monkeypatch):
    import hermes_cli.plugins as plugins

    def _refuse(*_args, **_kwargs):
        raise AssertionError("the provider-access port ran plugin discovery")

    monkeypatch.setattr(plugins, "discover_plugins", _refuse)
    monkeypatch.setattr(access, "_providers", {})
    monkeypatch.setattr(access, "_scoped_providers", {})
    monkeypatch.setattr(access._registry, "_providers", access._providers)
    monkeypatch.setattr(access._registry, "_scoped_providers", access._scoped_providers)
    monkeypatch.delenv("HERMES_AUTH_HOME", raising=False)


def test_an_unbound_read_takes_the_native_path_without_discovery(no_discovery, tmp_path):
    profile = {"model": {"default": "local"}}
    assert access.provider_credential_file("auth.json", tmp_path) == tmp_path / "auth.json"
    assert access.provider_secret("API_KEY") is None
    assert access.provider_configuration(profile) is profile
    assert access.list_providers() == []


def test_an_env_bound_read_registers_the_harness_and_reads_the_owners_store(
        no_discovery, tmp_path, monkeypatch):
    owner = tmp_path / "owner"
    owner.mkdir()
    monkeypatch.setenv("HERMES_AUTH_HOME", str(owner))
    profile_home = tmp_path / "profile"
    assert access.provider_credential_file("auth.json", profile_home) == owner.resolve() / "auth.json"
    assert [entry.name for entry in access.list_providers()] == ["eternia-harness"]


def test_a_contextvar_bound_read_registers_the_harness_and_reads_the_owners_store(
        no_discovery, tmp_path):
    owner = tmp_path / "owner"
    owner.mkdir()
    token = set_hermes_auth_home_override(owner)
    try:
        assert access.provider_credential_file("auth.json", tmp_path / "p") == owner.resolve() / "auth.json"
    finally:
        from agent_runtime.profile_home import reset_hermes_auth_home_override

        reset_hermes_auth_home_override(token)
    assert [entry.name for entry in access.list_providers()] == ["eternia-harness"]


@pytest.mark.timeout(120)
def test_a_fresh_process_first_credential_read_loads_no_plugins(tmp_path):
    """Positive runtime proof: a real interpreter's first ``_auth_file_path()`` never discovers."""
    home = tmp_path / ".hermes"
    home.mkdir()
    code = (
        "import hermes_cli.auth as auth, hermes_cli.plugins as plugins\n"
        "auth._auth_file_path()\n"
        "print('DISCOVERED' if plugins.get_plugin_manager()._discovered else 'CLEAN')\n"
    )
    env = {**os.environ, "HERMES_HOME": str(home), "PYTHONPATH": str(REPO_ROOT)}
    env.pop("HERMES_AUTH_HOME", None)
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                         timeout=100, cwd=REPO_ROOT, env=env)
    assert out.returncode == 0, out.stderr[-2000:]
    assert out.stdout.strip().splitlines()[-1] == "CLEAN"
