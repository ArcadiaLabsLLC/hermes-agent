"""RT-SERVE-STALE-ENV-AFTER-SET-KEY: a serve sees the key another process wrote to the home ``.env``.

``auth set-key`` / ``auth remove`` run in their own process; the serve's provider verbs re-read the home
``.env`` before answering (``serve_rpc/provider.py::_answer`` -> ``home_env_freshness.refresh_home_env``).
"""

from __future__ import annotations

import os

import pytest

from agent_runtime import home_env_freshness
from agent_runtime.home_env_freshness import refresh_home_env
from agent_runtime.provider_credential_source import present_credential_sources
from agent_runtime.serve_rpc.provider import _answer

KEY = "ANTHROPIC_API_KEY"


@pytest.fixture
def env_file(monkeypatch):
    from hermes_cli.config import get_env_path

    monkeypatch.delenv(KEY, raising=False)
    monkeypatch.delenv("ANTHROPIC_TOKEN", raising=False)
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    home_env_freshness.reset_home_env_freshness()
    path = get_env_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("# boot\n", encoding="utf-8")
    yield path
    home_env_freshness.reset_home_env_freshness()


def _api_key_present() -> bool:
    reply = _answer(1, "runtime.provider.list", lambda: {"present": present_credential_sources("anthropic")})
    return reply["result"]["present"]["api_key"]


def test_a_key_written_by_another_process_is_seen_by_the_next_provider_read(env_file):
    """Mutation: drop the ``refresh_home_env()`` call in ``_answer`` -> api_key stays False after the write, red."""
    assert _api_key_present() is False
    env_file.write_text(f"{KEY}=sk-ant-api03-written-elsewhere\n", encoding="utf-8")
    assert _api_key_present() is True and os.environ[KEY] == "sk-ant-api03-written-elsewhere"


def test_a_key_removed_from_the_file_leaves_the_serve(env_file):
    """Mutation: drop the removal loop in ``refresh_home_env`` -> the removed key stays present, red."""
    env_file.write_text(f"{KEY}=sk-ant-api03-old\n", encoding="utf-8")
    assert _api_key_present() is True
    env_file.write_text("# removed by auth remove\n", encoding="utf-8")
    assert _api_key_present() is False and KEY not in os.environ


def test_a_launch_environment_key_the_file_never_named_is_kept(env_file, monkeypatch):
    """Mutation: remove every known key missing from the file (``reload_env``'s rule) -> the launch key is lost, red."""
    monkeypatch.setenv(KEY, "sk-ant-api03-from-the-launch")
    assert refresh_home_env() == 0
    env_file.write_text("OTHER_SETTING=1\n", encoding="utf-8")
    monkeypatch.delenv("OTHER_SETTING", raising=False)
    refresh_home_env()
    assert os.environ[KEY] == "sk-ant-api03-from-the-launch"


def test_an_unchanged_file_is_not_re_read(env_file, monkeypatch):
    """Mutation: drop the signature early return -> load_env runs on the second look, red."""
    refresh_home_env()
    calls = []
    from hermes_cli import config

    real = config.load_env
    monkeypatch.setattr(config, "load_env", lambda: calls.append(1) or real())
    refresh_home_env()
    assert calls == []
