"""The Claude Code version a device without the ``claude`` command names on a subscription request.

RT-FU-A-CLAUDE-SUBSCRIPTION-TURN-ON-A-PHONE-REPORTS-A-CURRENT-CLAUDE-CODE-VERSION: on the owner's phone
every Claude Opus 5.5 turn was refused ``HTTP 400: Claude Code 2.1.74 does not support this model``;
the phone's stand-in answered upstream's static fallback. Killing mutations (applied, red recorded,
reverted — see the commit message): the stand-in back to ``mod._CLAUDE_CODE_VERSION_FALLBACK``;
``current_claude_code_version`` returning a kept release however old.
"""

from __future__ import annotations

import io
import json

import pytest

from agent_runtime import claude_code_release
from agent_runtime.claude_code_release import MAX_AGE, current_claude_code_version

FALLBACK = "2.1.74"


class _Registry:
    """The registry's ``latest`` answer, or a failure; counts the reads."""

    def __init__(self, version: str | None = None, error: Exception | None = None, body: bytes | None = None):
        self.version, self.error, self.body, self.reads = version, error, body, []

    def __call__(self, request, timeout):
        self.reads.append((request.full_url, timeout))
        if self.error is not None:
            raise self.error
        return io.BytesIO(self.body if self.body is not None else json.dumps({"version": self.version}).encode())


@pytest.fixture
def store(tmp_path):
    return tmp_path / "cache" / "claude_code_release.json"


def _keep(store, version: str, at: float) -> None:
    store.parent.mkdir(parents=True, exist_ok=True)
    store.write_text(json.dumps({"version": version, "read_at": at}), encoding="utf-8")


def test_with_nothing_kept_the_published_release_is_read_and_kept(monkeypatch, store):
    registry = _Registry("2.1.280")
    monkeypatch.setattr(claude_code_release, "urlopen", registry)
    assert current_claude_code_version(FALLBACK, now=lambda: 1000.0, store=store) == "2.1.280"
    assert registry.reads == [(claude_code_release.RELEASE_URL, 4.0)]
    assert json.loads(store.read_text(encoding="utf-8")) == {"version": "2.1.280", "read_at": 1000.0}


def test_a_current_kept_release_answers_without_a_read(monkeypatch, store):
    _keep(store, "2.1.281", 1000.0)
    registry = _Registry("9.9.9")
    monkeypatch.setattr(claude_code_release, "urlopen", registry)
    assert current_claude_code_version(FALLBACK, now=lambda: 1000.0 + MAX_AGE - 1, store=store) == "2.1.281"
    assert registry.reads == []


def test_a_stale_kept_release_is_read_again(monkeypatch, store):
    _keep(store, "2.1.200", 1000.0)
    monkeypatch.setattr(claude_code_release, "urlopen", _Registry("2.1.290"))
    assert current_claude_code_version(FALLBACK, now=lambda: 1000.0 + MAX_AGE + 1, store=store) == "2.1.290"


def test_offline_the_last_kept_release_answers_however_old(monkeypatch, store):
    _keep(store, "2.1.200", 1000.0)
    monkeypatch.setattr(claude_code_release, "urlopen", _Registry(error=OSError("offline")))
    assert current_claude_code_version(FALLBACK, now=lambda: 1000.0 + 10 * MAX_AGE, store=store) == "2.1.200"


@pytest.mark.parametrize("registry", [
    _Registry(error=OSError("offline")),
    _Registry(body=b"not json"),
    _Registry(version="latest"),
])
def test_with_nothing_kept_and_no_valid_release_the_fallback_answers(monkeypatch, store, registry):
    monkeypatch.setattr(claude_code_release, "urlopen", registry)
    assert current_claude_code_version(FALLBACK, now=lambda: 1000.0, store=store) == FALLBACK
    assert not store.exists()


def test_the_phone_stand_in_names_the_current_release_not_the_static_fallback(monkeypatch):
    """The stand-in the phone entry binds over ``_detect_claude_code_version`` asks this module."""
    from types import SimpleNamespace

    from agent_runtime.spawn_stand_ins import SPAWN_STAND_INS

    row = next(s for s in SPAWN_STAND_INS
               if s.target == "agent.anthropic_adapter._detect_claude_code_version")
    asked = []

    def current(fallback, **_k):
        asked.append(fallback)
        return "2.1.280"

    monkeypatch.setattr(claude_code_release, "current_claude_code_version", current)
    assert row.answer(SimpleNamespace(_CLAUDE_CODE_VERSION_FALLBACK=FALLBACK)) == "2.1.280"
    assert asked == [FALLBACK]
