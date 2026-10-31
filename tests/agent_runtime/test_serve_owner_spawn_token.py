"""The socket-owner record carries Eternia's owned-spawn token (row RT-OWNER-RECORD-SPAWN-TOKEN).

Eternia spawns hermes with ``ETERNIA_OWNED_SPAWN=<token>``; every descendant inherits it. The
serve writes that token into ``serve_socket.owner.json`` as ``spawn_token`` so the client's
recovery-lane reap (``MissionServeSocketOwner.spawnToken`` → ``killHostProcessTree``
``environmentToken``) can find a previous instance's detached descendants. Unset or blank, the key
is absent and the reap is the pid walk alone.
"""

from __future__ import annotations

import json
from pathlib import Path

from agent_runtime.serve_socket.owner_lock import SocketOwnerLock, read_socket_owner, socket_owner_path
from agent_runtime.serve_socket.vocabulary import (
    SOCKET_OWNER_SPAWN_TOKEN_ENV,
    SOCKET_OWNER_SPAWN_TOKEN_KEY,
)


def _published(root: Path, monkeypatch, token: str | None) -> dict:
    if token is None:
        monkeypatch.delenv(SOCKET_OWNER_SPAWN_TOKEN_ENV, raising=False)
    else:
        monkeypatch.setenv(SOCKET_OWNER_SPAWN_TOKEN_ENV, token)
    lock = SocketOwnerLock(root)
    assert lock.acquire().acquired
    try:
        lock.publish_owner({"pid": 1, "port": 5})
        return json.loads(socket_owner_path(root).read_text(encoding="utf-8"))
    finally:
        lock.release()


def test_the_names_are_the_client_contract():
    # EterniaLauncher lib/core/process/owned_spawn_token.dart::kOwnedSpawnEnvironmentVariable and
    # lib/core/services/hermes/runtime/data/mission_serve_socket_owner.dart's `parsed['spawn_token']`.
    assert SOCKET_OWNER_SPAWN_TOKEN_ENV == "ETERNIA_OWNED_SPAWN"
    assert SOCKET_OWNER_SPAWN_TOKEN_KEY == "spawn_token"


def test_a_set_token_rides_the_owner_record_and_the_reader(tmp_path: Path, monkeypatch):
    raw = _published(tmp_path, monkeypatch, "  tok-0123abcd  ")
    assert raw["spawn_token"] == "tok-0123abcd"
    assert raw["port"] == 5  # the caller's record is kept beside it


def test_the_reader_exposes_it_while_the_lock_is_held(tmp_path: Path, monkeypatch):
    monkeypatch.setenv(SOCKET_OWNER_SPAWN_TOKEN_ENV, "tok-live")
    lock = SocketOwnerLock(tmp_path)
    assert lock.acquire().acquired
    try:
        lock.publish_owner({"pid": 1, "port": 5})
        assert read_socket_owner(tmp_path)["spawn_token"] == "tok-live"
        assert lock.mark_draining("2026-10-31T00:00:00Z")
        assert read_socket_owner(tmp_path)["spawn_token"] == "tok-live"  # the drain stamp keeps it
    finally:
        lock.release()


def test_unset_or_blank_leaves_the_key_out(tmp_path: Path, monkeypatch):
    assert "spawn_token" not in _published(tmp_path / "unset", monkeypatch, None)
    assert "spawn_token" not in _published(tmp_path / "blank", monkeypatch, "   ")
