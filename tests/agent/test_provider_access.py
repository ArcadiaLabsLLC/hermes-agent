"""ProviderAccess: one bound provider authority, consulted at the provider read sites.

Unbound (nothing registered) every reader returns what it returned before the port existed.
"""
from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

from agent import provider_access as access
from hermes_constants import reset_hermes_home_override, set_hermes_home_override


class _Access(access.ProviderAccess):
    def __init__(self, name="bound", *, secrets=None, files_under=None, providers=None,
                 forward=None, bound=True):
        self.name = name
        self._secrets = secrets or {}
        self._files_under = files_under
        self._providers = providers
        self._forward = forward
        self._bound = bound

    def is_bound(self):
        return self._bound

    def secret(self, name):
        return self._secrets.get(name, "")

    def credential_file(self, name, profile_home):
        return (self._files_under or profile_home) / name

    def configuration(self, profile):
        return profile if self._providers is None else {**profile, "providers": self._providers}

    def forward_model_switch(self, server, rid, params, session):
        return None if self._forward is None else self._forward(server, rid, params, session)


@pytest.fixture
def bind():
    saved = dict(access._providers)
    yield access.register_provider
    with access._lock:
        access._providers.clear()
        access._providers.update(saved)


def test_unbound_readers_return_todays_values(tmp_path):
    profile = {"model": {"default": "x"}}
    assert access.current_access() is None
    assert access.provider_secret("OPENAI_API_KEY") is None
    assert access.provider_credential_file("auth.json", tmp_path) == tmp_path / "auth.json"
    assert access.provider_configuration(profile) is profile


def test_registered_but_unbound_access_is_not_consulted(bind, monkeypatch):
    bind(_Access(secrets={"PA_TEST_KEY": "from-access"}, bound=False))
    monkeypatch.setenv("PA_TEST_KEY", "from-env")
    from agent.secret_scope import get_secret
    assert get_secret("PA_TEST_KEY") == "from-env"


def test_get_secret_reads_the_bound_access_never_environ(bind, monkeypatch):
    from agent.secret_scope import get_secret

    monkeypatch.setenv("PA_TEST_KEY", "from-env")
    monkeypatch.setenv("PA_TEST_MISSING", "from-env")
    bind(_Access(secrets={"PA_TEST_KEY": "from-access"}))
    assert get_secret("PA_TEST_KEY") == "from-access"
    # "" is an authoritative miss: the caller's default, never os.environ.
    assert get_secret("PA_TEST_MISSING", "dflt") == "dflt"
    assert get_secret("PA_TEST_MISSING") is None


def test_anthropic_oauth_file_is_the_access_path(bind, tmp_path):
    from agent.anthropic_credentials import _get_hermes_oauth_file

    bind(_Access(files_under=tmp_path / "owned"))
    assert _get_hermes_oauth_file() == tmp_path / "owned" / ".anthropic_oauth.json"


def test_picker_context_sees_projected_providers(bind, monkeypatch):
    import hermes_cli.config as config_mod
    from hermes_cli.inventory import load_picker_context

    monkeypatch.setattr(config_mod, "load_config", lambda: {"model": {"default": "m", "provider": "custom"}})
    bind(_Access(providers={"owned-endpoint": {"base_url": "http://127.0.0.1:9/v1"}}))
    ctx = load_picker_context()
    assert "owned-endpoint" in repr(ctx)


def _session(**extra):
    base = dict(
        agent=None, agent_ready=threading.Event(), session_key="pa-key", history=[],
        history_version=0, history_lock=threading.Lock(), running=False,
        attached_images=[], image_counter=0, cols=80, slash_worker=None,
        show_reasoning=False, tool_progress_mode="all", inflight_turn=None,
        created_at=time.time(), last_active=time.time())
    base.update(extra)
    return base


def _set_model(server, sid):
    return server.handle_request(
        {"id": "1", "method": "config.set",
         "params": {"session_id": sid, "key": "model", "value": "anthropic/claude-sonnet-4.6"}})


def test_idle_compute_host_pick_forwards_through_the_bound_access(bind):
    from tui_gateway import server

    seen = []

    def forward(srv, rid, params, session):
        seen.append((srv, rid, params["value"]))
        return {"jsonrpc": "2.0", "id": rid, "result": {"key": "model", "value": "forwarded", "scope": "live"}}

    bind(_Access(forward=forward))
    session = _session(_compute_host_active=True)
    server._sessions["sid-pa-fwd"] = session
    try:
        resp = _set_model(server, "sid-pa-fwd")
    finally:
        server._sessions.pop("sid-pa-fwd", None)
    assert resp["result"]["value"] == "forwarded"
    assert seen == [(server, "1", "anthropic/claude-sonnet-4.6")]
    assert "pending_model_switch" not in session


@pytest.mark.parametrize("running", [False, True])
def test_compute_host_pick_stashes_without_a_forwarder(bind, running):
    from tui_gateway import server

    bind(_Access())  # bound, but forward_model_switch keeps the default (None)
    session = _session(_compute_host_active=True, running=running)
    server._sessions["sid-pa-stash"] = session
    try:
        resp = _set_model(server, "sid-pa-stash")
    finally:
        server._sessions.pop("sid-pa-stash", None)
    assert resp["result"].get("deferred") is True
    assert session["pending_model_switch"]["raw"] == "anthropic/claude-sonnet-4.6"


_PLUGIN = '''
from agent.provider_access import ProviderAccess
from hermes_constants import get_hermes_home

class Access(ProviderAccess):
    name = "resources"
    def is_bound(self):
        return True
    def secret(self, name):
        return "" if name == "MISSING" else "key-" + get_hermes_home().name
    def credential_file(self, name, profile_home):
        return profile_home / "provider" / name
    def configuration(self, profile):
        return {**profile, "providers": {"selected": get_hermes_home().name}}

def register(ctx):
    ctx.register_provider_access(Access())
'''


def test_plugin_access_is_profile_scoped_and_unloads(tmp_path):
    from hermes_cli.plugins import get_plugin_manager

    homes = [tmp_path / name for name in ("a", "b")]
    for home in homes:
        plugin = home / "plugins" / "resources"
        plugin.mkdir(parents=True)
        (plugin / "plugin.yaml").write_text("name: resources\nversion: '1'\n", encoding="utf-8")
        (plugin / "__init__.py").write_text(_PLUGIN, encoding="utf-8")
        (home / "config.yaml").write_text("plugins:\n  enabled: [resources]\n", encoding="utf-8")
    profile = {"model": {"default": "local"}}
    for home in (homes[0], homes[1], homes[0]):
        token = set_hermes_home_override(home)
        try:
            get_plugin_manager().discover_and_load()
            assert access.provider_configuration(profile) == {**profile, "providers": {"selected": home.name}}
            assert "providers" not in profile
            assert access.provider_secret("API_KEY") == "key-" + home.name
            assert access.provider_secret("MISSING") == ""
            assert access.provider_credential_file("auth.json", home) == home / "provider" / "auth.json"
        finally:
            reset_hermes_home_override(token)
    token = set_hermes_home_override(homes[0])
    try:
        get_plugin_manager().unload("resources")
        assert access.provider_secret("API_KEY") is None
        assert access.provider_configuration(profile) is profile
    finally:
        reset_hermes_home_override(token)


def test_two_bound_authorities_raise(bind, tmp_path):
    bind(_Access("first"))
    bind(_Access("second"))
    for call in (lambda: access.provider_secret("API_KEY"),
                 lambda: access.provider_credential_file("auth.json", Path(tmp_path)),
                 lambda: access.provider_configuration({})):
        with pytest.raises(RuntimeError, match="More than one"):
            call()
