"""The bundled-desktop profile's switches, each proven through the reader its surface uses.

Every test writes the PROFILE's config (``apply_to_config`` over an empty config) into the
hermetic HERMES_HOME's ``config.yaml`` and carries a POSITIVE CONTROL: the same call under the
default config (no ``config.yaml``) takes today's path, so "refused" is never the subject simply
not reaching the switch.

Killing mutations (applied, red recorded, reverted — see the commit message):

* ``mcp_server_enabled`` returns ``"url" in cfg or True``            -> stdio test red.
* ``_create_environment`` drops the ``external_backends_allowed`` check -> backends test red.
* ``_create_adapter`` drops the ``platform_adapters_allowed`` check     -> adapters test red.
* ``_resolve_piper_voice_path`` drops the ``allow_download`` refusal    -> piper test red.
* ``build_stamp._resolve`` drops the ``checkout_bound_enabled`` branch  -> checkout test red.
* ``_voice_toggle_mode`` drops the ``_voice_mode_available`` check      -> voice test red.
* the profile drops ``auth.adopt_external_logins: false``               -> external-logins test red.
* ``_load_nemo_relay`` drops its ``ModuleNotFoundError`` branch          -> nemo-relay test red.
* ``provider_login_catalog`` / ``build_provider_visibility`` /
  ``ProviderSignIns.begin`` / the post-ladder guard each drop their
  ``provider_disabled`` check                                            -> qwen test red.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import types
from pathlib import Path

import pytest

from agent_runtime.bundle_profiles.manifest import apply_to_config, load_profile

PROFILE = "bundled-desktop"
REPO_ROOT = Path(__file__).resolve().parents[2]


def _profile_config() -> dict:
    return apply_to_config(load_profile(PROFILE), {})


def _install_profile() -> None:
    """Write the profile's config as this HERMES_HOME's config.yaml (YAML is a JSON superset)."""
    from hermes_constants import get_hermes_home

    home = Path(get_hermes_home())
    home.mkdir(parents=True, exist_ok=True)
    (home / "config.yaml").write_text(json.dumps(_profile_config()), encoding="utf-8")


def test_stdio_mcp_servers_are_off_and_http_servers_kept():
    from tools.mcp_tool_common import mcp_server_enabled

    stdio, http = {"command": "npx", "args": ["-y", "server"]}, {"url": "https://mcp.example/mcp"}
    assert mcp_server_enabled(stdio) and mcp_server_enabled(http)  # positive control

    _install_profile()
    assert not mcp_server_enabled(stdio)
    assert mcp_server_enabled(http)


def test_phone_profile_runs_no_mcp_client(monkeypatch):
    """``mcp.client`` (bundled-phone): no server is enabled and discovery never starts, so the
    client runtime is never imported. The desktop profile keeps its HTTP server (control)."""
    import logging

    from hermes_cli import mcp_startup
    from hermes_constants import get_hermes_home
    from tools.mcp_tool_common import mcp_client_enabled, mcp_server_enabled

    http = {"url": "https://mcp.example/mcp"}
    home = Path(get_hermes_home())
    home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(mcp_startup, "_mcp_discovery_started", set())
    monkeypatch.setattr(mcp_startup, "_mcp_discovery_thread", {})
    monkeypatch.setattr(mcp_startup, "_discover_mcp_tools_without_interactive_oauth", lambda: None)

    def install(profile: str) -> None:
        config = apply_to_config(load_profile(profile), {"mcp_servers": {"docs": http}})
        (home / "config.yaml").write_text(json.dumps(config), encoding="utf-8")

    install("bundled-desktop")  # positive control: the same server is on and would be discovered
    assert mcp_client_enabled() and mcp_server_enabled(http)
    assert mcp_startup._has_configured_mcp_servers()

    install("bundled-phone")
    assert not mcp_client_enabled() and not mcp_server_enabled(http)
    assert not mcp_startup._has_configured_mcp_servers()
    mcp_startup.start_background_mcp_discovery(logger=logging.getLogger("t"), thread_name="t")
    assert mcp_startup._mcp_discovery_started == set() and mcp_startup._mcp_discovery_thread == {}


def test_external_execution_backends_are_refused_before_their_builder(monkeypatch):
    from tools import terminal_tool_backends as backends

    built: list[str] = []
    for name in ("docker", "local"):
        monkeypatch.setitem(backends._ENV_BUILDERS, name,
                            lambda _n=name, **_kw: built.append(_n) or types.SimpleNamespace())

    backends._create_environment("docker", "image", "/work", 10)  # positive control
    assert built == ["docker"]

    _install_profile()
    built.clear()
    with pytest.raises(ValueError, match="terminal.external_backends"):
        backends._create_environment("docker", "image", "/work", 10)
    assert built == []
    backends._create_environment("local", "", "/work", 10)  # the pinned backend stays
    assert built == ["local"]


def test_messaging_gateway_starts_no_platform_adapter():
    from gateway.config import Platform
    from gateway.run_adapters import GatewayAdapterLifecycleMixin

    class _Runner(GatewayAdapterLifecycleMixin):
        def __init__(self):
            self.made = []

        def _instantiate_adapter(self, platform, config):
            self.made.append(platform)
            return types.SimpleNamespace()

    runner = _Runner()
    assert runner._create_adapter(Platform.TELEGRAM, object()) is not None  # positive control
    assert runner.made == [Platform.TELEGRAM]

    _install_profile()
    runner.made.clear()
    assert runner._create_adapter(Platform.TELEGRAM, object()) is None
    assert runner.made == []


def test_piper_never_downloads_a_voice_by_name(monkeypatch, tmp_path):
    from tools import tts_tool, tts_tool_local

    helper_calls: list[list] = []

    def _helper(cmd, timeout):
        helper_calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 1, "", "offline")

    monkeypatch.setattr(tts_tool_local, "_run_helper", _helper)
    monkeypatch.setattr(tts_tool, "_import_piper", lambda: object)
    piper = {"voice": "en_US-test-low", "voices_dir": str(tmp_path)}

    with pytest.raises(RuntimeError, match="download failed"):  # positive control: it tries
        tts_tool_local._load_piper_voice_for_config({"piper": piper})
    assert helper_calls and "piper.download_voices" in helper_calls[0]

    helper_calls.clear()
    profile_piper = _profile_config()["tts"]["piper"]
    with pytest.raises(RuntimeError, match="voice downloads are off"):
        tts_tool_local._load_piper_voice_for_config({"piper": {**piper, **profile_piper}})
    assert helper_calls == []


def test_checkout_bound_features_never_consult_git(monkeypatch):
    from agent_runtime import build_stamp, dirty_state

    git_calls: list = []

    def _no_git(*args, **kwargs):
        git_calls.append(args)
        raise FileNotFoundError("git")

    resolved: list[str] = []
    monkeypatch.setattr(build_stamp, "run_git", _no_git)
    monkeypatch.setattr(dirty_state, "resolve_affected_repo_workdir", lambda repo: resolved.append(repo))
    try:
        # Positive control: this checkout HAS a .git, so the default stamp asks git.
        assert build_stamp.build_stamp(refresh=True).reason == "git_missing"
        assert git_calls
        assert dirty_state.repo_dirty_states(["hermes"])[0]["error"] == "repo_unresolved"
        assert resolved == ["hermes"]

        _install_profile()
        git_calls.clear()
        resolved.clear()
        stamp = build_stamp.build_stamp(refresh=True)
        assert stamp.reason == build_stamp.REASON_CHECKOUT_BOUND_OFF
        assert git_calls == []
        states = dirty_state.repo_dirty_states(["hermes"])
        assert [s["error"] for s in states] == ["checkout_bound_off"]
        assert states[0]["dirty"] is None
        assert resolved == []
    finally:
        build_stamp.reset_build_stamp_cache()


def _dispatch(request: dict) -> dict:
    from tui_gateway import server
    from tui_gateway.transport import bind_transport, reset_transport

    token = bind_transport(None)
    try:
        return server.handle_request(request)
    finally:
        reset_transport(token)


def test_voice_mode_and_wake_word_are_not_offered(monkeypatch):
    from tui_gateway import server

    monkeypatch.setattr(server, "_load_cfg", lambda: {})
    monkeypatch.setitem(sys.modules, "tools.voice_mode", types.SimpleNamespace(
        check_voice_requirements=lambda: {"available": True, "details": ""}))
    monkeypatch.setenv("HERMES_VOICE", "0")
    toggle_on = {"id": "v", "method": "voice.toggle", "params": {"action": "on"}}
    wake = {"id": "w", "method": "wake.start", "params": {"surface": "gui"}}

    assert "result" in _dispatch(toggle_on)  # positive control
    assert os.environ["HERMES_VOICE"] == "1"
    assert (_dispatch(wake).get("result") or {}).get("reason") != "voice_mode_unavailable"

    _install_profile()
    monkeypatch.setenv("HERMES_VOICE", "0")
    refused = _dispatch(toggle_on)
    assert refused["error"]["code"] == 4015 and "voice.mode_enabled" in refused["error"]["message"]
    assert os.environ["HERMES_VOICE"] == "0"
    assert _dispatch(wake)["result"] == {"started": False, "reason": "voice_mode_unavailable"}


def test_external_cli_logins_are_never_adopted(monkeypatch):
    import hermes_cli.auth as auth
    from hermes_cli.auth_codex import _recover_codex_tokens_from_cli

    reads: list[bool] = []
    monkeypatch.setattr(auth, "_import_codex_cli_tokens", lambda: reads.append(True) or None)

    assert _recover_codex_tokens_from_cli("test") is None  # positive control: it reads the CLI file
    assert reads == [True]

    _install_profile()
    reads.clear()
    assert _recover_codex_tokens_from_cli("test") is None
    assert reads == []


def test_dashboard_config_schema_loads_without_wake_word():
    """The bundle omits ``tools.wake_word``; the dashboard config schema must still import."""

    def providers(block_wake_word: bool) -> list:
        code = ("import json, sys\n"
                + ("sys.modules['tools.wake_word'] = None\n" if block_wake_word else "")
                + "import hermes_cli.web_server_config as m\n"
                  "print(json.dumps(m.CONFIG_SCHEMA['wake_word.provider']['options']))\n")
        done = subprocess.run([sys.executable, "-c", code], cwd=REPO_ROOT, capture_output=True, text=True,
                              timeout=120, check=True)
        return json.loads(done.stdout.strip().splitlines()[-1])

    assert len(providers(block_wake_word=False)) > 1  # positive control: the engines are offered
    assert providers(block_wake_word=True) == ["auto"]


def test_without_nemo_relay_the_relay_host_is_noop(monkeypatch):
    from agent import relay_runtime

    monkeypatch.setitem(sys.modules, "nemo_relay", types.SimpleNamespace(tag="relay"))
    assert relay_runtime._load_nemo_relay().tag == "relay"  # positive control: present -> loaded

    monkeypatch.setitem(sys.modules, "nemo_relay", None)  # the bundle omits the distribution
    with pytest.raises(relay_runtime.RelayUnavailable):
        relay_runtime._load_nemo_relay()
    host = relay_runtime.RelayHostRegistry().for_profile("bundled-profile-key")
    assert isinstance(host, relay_runtime.NoopRelayRuntime)
    assert host.reason == "nemo-relay is not installed in this Hermes"
    assert host.managed_execution_enabled() is False


def test_qwen_oauth_is_refused_on_every_surface(monkeypatch):
    import agent.credential_pool as credential_pool
    import hermes_cli.runtime_provider as runtime_provider
    from agent_runtime.provider_signin import ProviderSignIns, SignInRefused
    from hermes_cli.harness_parts.provider_visibility import build_provider_visibility
    from hermes_cli.provider_login_catalog import provider_login_catalog

    pools_read: list[str] = []
    monkeypatch.setattr(credential_pool, "load_pool",
                        lambda provider: pools_read.append(provider) or types.SimpleNamespace(entries=lambda: []))
    # The ladder is stubbed: "auto" lands on qwen-oauth without touching any credential file.
    monkeypatch.setattr(runtime_provider, "_ladder_rungs",
                        lambda *a, **k: iter([{"provider": "qwen-oauth", "api_mode": "chat_completions"}]))

    def sign_in_reason() -> str:
        with pytest.raises(SignInRefused) as refused:
            ProviderSignIns(spawn=lambda *a: None).begin("qwen-oauth")
        return refused.value.reason

    # Positive controls: by default qwen-oauth is offered, read, reached by sign-in and resolved.
    assert "qwen-oauth" in [row["id"] for row in provider_login_catalog()]
    build_provider_visibility()
    assert "qwen-oauth" in pools_read
    assert sign_in_reason() == "provider_unsupported"
    assert runtime_provider.resolve_runtime_provider()["provider"] == "qwen-oauth"

    _install_profile()
    pools_read.clear()
    assert "qwen-oauth" not in [row["id"] for row in provider_login_catalog()]
    build_provider_visibility()
    assert "qwen-oauth" not in pools_read and pools_read  # other providers still read
    assert sign_in_reason() == "provider_disabled"
    for requested in ("qwen-oauth", None):  # named, and "auto" landing on it
        with pytest.raises(ValueError, match="providers.qwen-oauth.enabled: false"):
            runtime_provider.resolve_runtime_provider(requested=requested)
