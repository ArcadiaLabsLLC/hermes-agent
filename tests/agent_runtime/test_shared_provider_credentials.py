"""Real credential readers; separate provider authority from profile/tool identity."""
import json
from contextlib import contextmanager

from agent_runtime.profile_home import (
    reset_hermes_auth_home_override, set_hermes_auth_home_override,
)
from hermes_constants import get_hermes_home, reset_hermes_home_override, set_hermes_home_override


@contextmanager
def bound(profile, owner):
    from agent.secret_scope import build_profile_secret_scope, reset_secret_scope, set_secret_scope

    home = set_hermes_home_override(profile)
    auth = set_hermes_auth_home_override(owner)
    secrets = set_secret_scope(build_profile_secret_scope(profile), profile_home=str(profile))
    try:
        yield
    finally:
        reset_secret_scope(secrets)
        reset_hermes_auth_home_override(auth)
        reset_hermes_home_override(home)


def test_shared_provider_keys_follow_owner_without_sharing_tools_or_copying(tmp_path, monkeypatch):
    from agent.credential_pool import get_env_prefer_dotenv, load_pool
    from agent.secret_scope import get_secret
    from hermes_cli.auth import _auth_file_path
    from hermes_cli.runtime_provider import resolve_runtime_provider
    from agent.auxiliary_client import _scoped_key_env
    from agent.anthropic_credentials import _getenv

    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    owners = [tmp_path / name for name in ("account-a", "account-b")]
    profiles = [tmp_path / name for name in ("agent-a", "agent-b")]
    for folder in owners + profiles:
        folder.mkdir()
        (folder / "config.yaml").write_text("model:\n  provider: openrouter\n", encoding="utf-8")
        (folder / ".env").write_text(
            f"OPENROUTER_API_KEY=test-{folder.name}\nANTHROPIC_API_KEY=test-{folder.name}\n"
            f"GITHUB_TOKEN=tool-{folder.name}\n", encoding="utf-8")
    for owner in (owners[0], owners[1], owners[0]):
        for profile in profiles:
            with bound(profile, owner):
                assert get_hermes_home() == profile
                assert _auth_file_path() == owner / "auth.json"
                assert get_env_prefer_dotenv("OPENROUTER_API_KEY") == f"test-{owner.name}"
                assert _scoped_key_env("OPENROUTER_API_KEY") == f"test-{owner.name}"
                assert _getenv("ANTHROPIC_API_KEY") == f"test-{owner.name}"
                assert get_secret("GITHUB_TOKEN") == f"tool-{profile.name}"
                pool = load_pool("openrouter")
                assert any(e.runtime_api_key == f"test-{owner.name}" for e in pool.entries())
                runtime = resolve_runtime_provider(requested="openrouter", target_model="test/model")
                assert runtime["api_key"] == f"test-{owner.name}"
                assert not (profile / "auth.json").exists()
            # Env-backed entries persist references, never another copy of the key.
            assert f"test-{owner.name}" not in (owner / "auth.json").read_text(encoding="utf-8")
    (owners[0] / ".env").write_text("GITHUB_TOKEN=owner-tool\n", encoding="utf-8")
    with bound(profiles[0], owners[0]):
        assert get_env_prefer_dotenv("OPENROUTER_API_KEY") == ""
        assert _scoped_key_env("OPENROUTER_API_KEY") == ""
        assert _getenv("ANTHROPIC_API_KEY") == ""
    with bound(profiles[0], None):
        assert get_env_prefer_dotenv("OPENROUTER_API_KEY") == "test-agent-a"


def test_oauth_singleton_and_pool_keep_one_owner_across_profile_switches(tmp_path, monkeypatch):
    from agent.anthropic_credentials import _get_hermes_oauth_file
    from hermes_cli.auth import _auth_file_path, read_credential_pool, write_credential_pool

    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    owner, a, b = (tmp_path / name for name in ("owner", "a", "b"))
    for folder in (owner, a, b):
        folder.mkdir()
    for profile in (a, b, a):
        with bound(profile, owner):
            assert _get_hermes_oauth_file() == owner / ".anthropic_oauth.json"
            write_credential_pool("openai-codex", [{"id": "shared", "source": "device_code",
                "access_token": "synthetic-token", "refresh_token": "synthetic-refresh"}])
            assert read_credential_pool("openai-codex")[0]["refresh_token"] == "synthetic-refresh"
            assert _auth_file_path() == owner / "auth.json"
    assert not (a / "auth.json").exists() and not (b / "auth.json").exists()
    assert json.loads((owner / "auth.json").read_text())["credential_pool"]


def test_bound_owner_never_borrows_a_different_global_store(tmp_path, monkeypatch):
    from agent.anthropic_credentials import _root_hermes_oauth_file
    from hermes_cli.auth import _load_auth_store, _load_provider_state, read_credential_pool

    root, owner, profile = [tmp_path / name for name in ("root", "owner", "agent")]
    for home in (root, owner, profile):
        home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(root))
    monkeypatch.delenv("HERMES_AUTH_HOME", raising=False)
    (root / "auth.json").write_text(json.dumps({
        "version": 1,
        "providers": {"nous": {"access_token": "synthetic-other-account"}},
        "credential_pool": {"openai-codex": [{"id": "other", "source": "device_code",
            "access_token": "synthetic-other-account"}]},
    }), encoding="utf-8")
    with bound(profile, None):
        assert read_credential_pool("openai-codex")[0]["id"] == "other"
    with bound(profile, owner):
        assert read_credential_pool("openai-codex") == []
        assert _load_provider_state(_load_auth_store(), "nous") is None
        assert _root_hermes_oauth_file() is None
    with bound(profile, None):
        assert read_credential_pool("openai-codex")[0]["id"] == "other"
