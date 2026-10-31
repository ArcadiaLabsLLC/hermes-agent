"""RT-PROFILE-AVATAR-RPC: ``runtime.profiles.avatar`` answers a profile's avatar bytes inline.

Launcher plan ``REMOTE_PROFILE_AVATAR_TRANSPORT_2026-10-31.md`` §H1: a profile with
``assets/avatar.png`` answers bytes whose handle is ``media_handles.handle_for_bytes`` and
``media_type`` ``image/png``; ``.webp`` answers ``image/webp``; no asset answers ``not_found``; a
token with a path separator answers ``invalid_profile`` and reads no file; the manifest lists the
method under ``read``.

Killing mutation (recorded in the landing commit): resolve the home as
``get_hermes_home().parent / profile`` (the profiles root joined with the raw token) instead of
``_profile_home_for_token`` -> the separator arm reads the planted file -> red.
"""

from __future__ import annotations

import base64
from pathlib import Path

import pytest

from agent_runtime.call_authorization import STDIO_OWNER
from agent_runtime.media_handles import handle_for_bytes
from agent_runtime.serve_rpc import handle_request, manifest, method_tier
from agent_runtime.serve_rpc.protocol import ERR_INVALID_PARAMS, RpcContext

PNG = b"\x89PNG\r\n\x1a\n" + b"avatar-png-bytes"
WEBP = b"RIFF\x10\x00\x00\x00WEBPVP8 avatar"


def rpc(params: dict) -> dict:
    return handle_request({"jsonrpc": "2.0", "id": "r", "method": "runtime.profiles.avatar", "params": params},
                          RpcContext(caller=STDIO_OWNER))


@pytest.fixture
def home(tmp_path: Path, monkeypatch) -> Path:
    """The ACTIVE profile's home; ``_profile_home_for_token`` maps its own name to it."""

    active = tmp_path / "root" / "profiles" / "alice"
    active.mkdir(parents=True)
    monkeypatch.setenv("HERMES_HOME", str(active))
    monkeypatch.setenv("HERMES_PROFILE", "alice")
    return active


def _plant(home: Path, name: str, data: bytes) -> Path:
    assets = home / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    (assets / name).write_bytes(data)
    return assets / name


def test_a_png_avatar_answers_its_bytes_and_handle(home: Path):
    _plant(home, "avatar.png", PNG)
    reply = rpc({"profile": "alice"})["result"]
    assert reply["ok"] is True and reply["profile"] == "alice"
    assert reply["media_type"] == "image/png"
    assert base64.b64decode(reply["data_base64"]) == PNG
    assert reply["handle"] == handle_for_bytes(PNG)


def test_another_profile_on_the_install_answers_its_own_avatar(home: Path):
    _plant(home, "avatar.png", PNG)
    _plant(home.parent / "bob", "avatar.webp", WEBP)
    reply = rpc({"profile": "bob"})["result"]
    assert reply["profile"] == "bob" and base64.b64decode(reply["data_base64"]) == WEBP


def test_a_webp_avatar_answers_image_webp(home: Path):
    _plant(home, "avatar.webp", WEBP)
    reply = rpc({"profile": "alice"})["result"]
    assert reply["media_type"] == "image/webp" and base64.b64decode(reply["data_base64"]) == WEBP


def test_png_outranks_webp_in_the_launchers_order(home: Path):
    _plant(home, "avatar.webp", WEBP)
    _plant(home, "avatar.png", PNG)
    assert rpc({"profile": "alice"})["result"]["media_type"] == "image/png"


def test_no_asset_answers_not_found(home: Path):
    (home / "assets").mkdir()
    assert rpc({"profile": "alice"})["result"] == {"ok": False, "profile": "alice", "reason": "not_found"}


def test_an_empty_or_oversized_avatar_answers_unavailable(home: Path, monkeypatch):
    from agent_runtime.serve_rpc import profiles

    path = _plant(home, "avatar.png", b"")
    assert rpc({"profile": "alice"})["result"]["reason"] == "unavailable"
    path.write_bytes(PNG)
    monkeypatch.setattr(profiles, "AVATAR_MAX_BYTES", len(PNG) - 1)
    assert rpc({"profile": "alice"})["result"]["reason"] == "unavailable"
    monkeypatch.setattr(profiles, "AVATAR_MAX_BYTES", len(PNG))  # positive control: at the ceiling
    assert rpc({"profile": "alice"})["result"]["ok"] is True


def test_a_separator_token_is_invalid_and_reads_no_file(home: Path):
    # A planted avatar a traversal WOULD reach: profiles/alice/../bob/assets/avatar.png.
    _plant(home.parent / "bob", "avatar.png", PNG)
    for token in ("alice/../bob", "..\\bob", "/etc", "C:bob", ".."):
        assert rpc({"profile": token})["result"] == {"ok": False, "profile": token, "reason": "invalid_profile"}


def test_an_avatar_that_symlinks_out_of_the_home_is_unavailable(home: Path, tmp_path: Path):
    outside = tmp_path / "secret.png"
    outside.write_bytes(PNG)
    (home / "assets").mkdir()
    try:
        (home / "assets" / "avatar.png").symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable")
    assert rpc({"profile": "alice"})["result"]["reason"] == "unavailable"


def test_a_missing_profile_is_refused_as_invalid_params(home: Path):
    assert rpc({})["error"]["code"] == ERR_INVALID_PARAMS
    assert rpc({"profile": 3})["error"]["data"]["reason"] == "param_type_invalid"


def test_the_manifest_lists_it_read_tier_with_its_params():
    published = manifest()
    assert "runtime.profiles.avatar" in published["methods"]
    assert method_tier("runtime.profiles.avatar") == "read" == published["tiers"]["runtime.profiles.avatar"]
    assert published["params"]["runtime.profiles.avatar"] == ["profile"]
