"""RT-LENS-CREDENTIAL-PREVIEW — Lens credentials live in a fork-owned 0600 file, never the pool.

Owner ruling 2026-10-18: upstream's dashboard ``GET /api/credentials/pool`` lists every
credential-pool slice with a ``redact_key`` token preview, and a Lens credential is
write-only (set / not set / rotated, never any part of the value). So the values live
in ``HERMES_HOME/lens/credentials.json`` (0600) behind the unchanged
``lens.credentials`` API, and a value an earlier build wrote to the pool's ``lens``
slice is migrated out one way.

Gates:

* after ``set_credential`` the dashboard's pool listing shows no ``lens`` slice and
  no fragment of the value (the defect: ``token_preview`` showed head and tail);
* every Lens read path answers presence and rotation only;
* a pool row this home wrote is moved into the file and removed from the pool; a row
  another home stamped is left alone.
"""

from __future__ import annotations

import asyncio
import json
import os
import stat

from agent_runtime.lens import credentials as lens_credentials
from agent_runtime.lens.credentials import (
    LEGACY_POOL_PROVIDER,
    credential_status,
    credentials_path,
    resolve_credential,
    set_credential,
)

SECRET = "zq7Wx-lens-only-Kp4Rv"


def _fragments() -> list[str]:
    # redact_key's preview is head 4 + tail 4; any 4-character run of the value is a leak.
    return [SECRET[i:i + 4] for i in range(len(SECRET) - 3)]


def _leaks(text: str) -> list[str]:
    return [fragment for fragment in _fragments() if fragment in text]


def _dashboard_pool() -> str:
    from hermes_cli.web_routers.ops import list_credential_pool

    return json.dumps(asyncio.run(list_credential_pool()))


def test_a_lens_credential_never_reaches_the_dashboard_pool_listing():
    set_credential("status-token", scheme="bearer", secret=SECRET)
    listing = _dashboard_pool()
    assert '"lens"' not in listing and _leaks(listing) == []
    assert resolve_credential("status-token").secret == SECRET  # still resolvable for a read


def test_the_file_is_under_the_home_and_private():
    set_credential("db", scheme="basic", secret=SECRET, username="watcher")
    path = credentials_path()
    assert path.parent.name == "lens" and path.is_file()
    if os.name == "posix":
        assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_every_lens_read_path_answers_presence_and_rotation_only():
    from agent_runtime import serve_rpc

    def call(method: str, params: dict) -> dict:
        return serve_rpc.handle_request({"jsonrpc": "2.0", "id": 1, "method": method, "params": params})

    replies = [call("runtime.lens.credential.set", {"ref": "k", "scheme": "bearer", "secret": SECRET})]
    manifest = {"version": 1, "monitor_id": "status",
                "feeds": [{"version": 1, "id": "api", "kind": "http_json", "interval_ms": 5000,
                           "source": {"url": "https://status.example.invalid/h", "selector": "$.cpu"},
                           "credential_ref": "k"}],
                "rules": [], "automation": {"level": "notify", "when": "urgent", "daily_turn_cap": 0},
                "persona_id": None}
    replies.append(call("runtime.lens.create", {"manifest": manifest}))
    replies.append(call("runtime.lens.get", {"monitor_id": "status"}))
    assert replies[-1]["result"]["credentials"] == [{"feed_id": "api", "ref": "k", "set": True,
                                                     "rotated_at": replies[0]["result"]["rotated_at"]}]
    assert _leaks(json.dumps(replies) + json.dumps(credential_status("k")) + repr(resolve_credential("k"))) == []


def _plant_legacy_row(ref: str, *, stamp: str) -> None:
    from hermes_cli.auth import write_credential_pool

    write_credential_pool(LEGACY_POOL_PROVIDER, [{
        "id": ref, "label": f"lens:{ref}", "auth_type": "api_key", "priority": 0, "source": "manual:lens",
        "access_token": SECRET, "lens_scheme": "basic", "lens_username": "watcher", "lens_home": stamp,
        "lens_rotated_at": "2026-10-16T12:00:00.000Z"}])


def test_a_pool_row_this_home_wrote_is_migrated_out_one_way(monkeypatch):
    from hermes_cli.auth import read_credential_pool

    monkeypatch.setattr(lens_credentials, "_MIGRATED", set())
    _plant_legacy_row("old", stamp=lens_credentials._legacy_home_digest(lens_credentials._home()))
    assert credential_status("old") == {"ref": "old", "set": True, "rotated_at": "2026-10-16T12:00:00.000Z"}
    assert read_credential_pool(LEGACY_POOL_PROVIDER) == []
    moved = resolve_credential("old")
    assert (moved.secret, moved.username, moved.scheme.value) == (SECRET, "watcher", "basic")
    listing = _dashboard_pool()
    assert '"lens"' not in listing and _leaks(listing) == []


def test_a_pool_row_another_home_stamped_is_left_alone(monkeypatch):
    from hermes_cli.auth import read_credential_pool

    monkeypatch.setattr(lens_credentials, "_MIGRATED", set())
    _plant_legacy_row("theirs", stamp="0" * 24)
    assert credential_status("theirs")["set"] is False
    assert [row["id"] for row in read_credential_pool(LEGACY_POOL_PROVIDER)] == ["theirs"]
    assert not credentials_path().exists()  # nothing to move, nothing written


def test_the_file_wins_over_a_stale_pool_row(monkeypatch):
    monkeypatch.setattr(lens_credentials, "_MIGRATED", set())
    set_credential("k", scheme="bearer", secret="newer-value-in-file")
    lens_credentials._MIGRATED.clear()
    _plant_legacy_row("k", stamp=lens_credentials._legacy_home_digest(lens_credentials._home()))
    assert resolve_credential("k").secret == "newer-value-in-file"
