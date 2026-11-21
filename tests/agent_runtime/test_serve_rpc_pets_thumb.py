"""RT-PETS-THUMB-RPC: ``runtime.pets.thumb`` answers a pet's portrait bytes inline.

Launcher plan ``REMOTE_COMPANION_PORTRAIT_TRANSPORT_2026-10-31.md`` §H1: an installed
pet answers bytes whose handle is ``media_handles.handle_for_bytes`` of exactly those
bytes; an uninstalled slug answers ``ok: false, not_installed``; the manifest lists the
method under ``read`` with its honoured params.

Killing mutation (recorded in the landing commit): hand back the handle of the SHEET
bytes instead of the thumbnail -> ``test_an_installed_pet_answers_its_thumbnail_bytes``
red on the handle equality.
"""

from __future__ import annotations

import base64
import json

import pytest

pytest.importorskip("PIL")

from agent_runtime.call_authorization import STDIO_OWNER
from agent_runtime.media_handles import handle_for_bytes
from agent_runtime.serve_rpc import handle_request, manifest, method_tier
from agent_runtime.serve_rpc.protocol import ERR_INVALID_PARAMS, RpcContext


def _write_pet(home, slug="milo"):
    from PIL import Image, ImageDraw

    from agent.pet import constants

    pets = home / "pets" / slug
    pets.mkdir(parents=True)
    sheet = Image.new("RGBA", (constants.FRAME_W * constants.FRAMES_PER_STATE, constants.FRAME_H * 2), (0, 0, 0, 0))
    ImageDraw.Draw(sheet).rectangle((20, 20, 120, 150), fill=(30, 90, 220, 255))
    sheet.save(pets / "spritesheet.png")
    (pets / "pet.json").write_text(json.dumps({"id": slug, "displayName": "Milo", "spritesheetPath": "spritesheet.png"}),
                                   encoding="utf-8")
    return pets / "spritesheet.png"


def rpc(params: dict) -> dict:
    return handle_request({"jsonrpc": "2.0", "id": "r", "method": "runtime.pets.thumb", "params": params},
                          RpcContext(caller=STDIO_OWNER))


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "home"))
    return tmp_path / "home"


def test_an_installed_pet_answers_its_thumbnail_bytes(home):
    from agent.pet import store

    sheet = _write_pet(home)
    reply = rpc({"slug": "milo"})["result"]
    data = base64.b64decode(reply["data_base64"])
    assert reply["ok"] is True and reply["slug"] == "milo"
    assert reply["media_type"] == "image/png"
    assert data.startswith(b"\x89PNG") and data == store.thumbnail_png("milo")
    assert data != sheet.read_bytes(), "the fixture must make the thumbnail differ from the sheet"
    assert reply["handle"] == handle_for_bytes(data)


def test_an_uninstalled_slug_answers_not_installed(home):
    _write_pet(home)  # positive control: the store is live, only the slug differs
    assert rpc({"slug": "ghost"})["result"] == {"ok": False, "slug": "ghost", "reason": "not_installed"}
    assert rpc({"slug": "ghost", "url": "https://evil.example/sheet.png"})["result"]["reason"] == "not_installed"


def test_an_installed_pet_whose_sheet_will_not_crop_answers_unavailable(home, monkeypatch):
    from agent.pet import store

    _write_pet(home).write_bytes(b"not a png")
    assert rpc({"slug": "milo"})["result"] == {"ok": False, "slug": "milo", "reason": "unavailable"}

    def _refuse(url, timeout):
        raise OSError("offline")

    monkeypatch.setattr(store, "_http_get", _refuse)
    reply = rpc({"slug": "ghost", "url": "https://petdex.dev/pets/ghost/spritesheet.png"})["result"]
    assert reply == {"ok": False, "slug": "ghost", "reason": "not_installed"}


def test_a_missing_slug_is_refused_as_invalid_params(home):
    assert rpc({})["error"]["code"] == ERR_INVALID_PARAMS
    assert rpc({"slug": 3})["error"]["data"]["reason"] == "param_type_invalid"


def test_the_manifest_lists_it_read_tier_with_its_params():
    published = manifest()
    assert "runtime.pets.thumb" in published["methods"]
    assert method_tier("runtime.pets.thumb") == "read" == published["tiers"]["runtime.pets.thumb"]
    assert published["params"]["runtime.pets.thumb"] == ["slug", "url"]


# ── runtime.pets.gallery (RT-PETS-PAIRING-GATEWAY-ID-AND-UNPAIR-HAVE-THEIR-OWN-CALLS-ON-THE-RUNNING-HERMES) ──
#
# Killing mutations, each seen red:
# * in ``_runtime_pets_gallery`` pass ``local_only=False`` regardless -> the local-only read fetches the manifest,
#   ``test_the_gallery_answers_the_verbs_own_payload`` red on ``localOnly`` and the extra row;
# * in ``_runtime_pets_sprite`` pass ``no_sheet=include_sheet`` -> ``test_sprite_answers_the_verbs_own_payload``
#   red (the sheet bytes and the path swap places);
# * drop ``"runtime.pets.install"`` from ``LOCAL_CONSOLE_METHODS`` -> ``test_install_is_this_consoles_alone`` red.


def _gallery(params: dict) -> dict:
    return handle_request({"jsonrpc": "2.0", "id": "g", "method": "runtime.pets.gallery", "params": params},
                          RpcContext(caller=STDIO_OWNER))


@pytest.fixture
def manifest_rows(monkeypatch):
    from agent.pet import manifest as pet_manifest

    rows = [pet_manifest.ManifestEntry.from_dict({"slug": "bolt", "displayName": "Bolt",
                                                  "spritesheetUrl": "https://petdex.dev/curated/bolt.png"})]
    monkeypatch.setattr(pet_manifest, "fetch_manifest", lambda **kwargs: rows)
    return rows


def test_the_gallery_answers_the_verbs_own_payload(home, manifest_rows, capsys):
    import argparse

    from hermes_cli import harness

    _write_pet(home)
    parser = argparse.ArgumentParser(prog="hermes")
    harness.build_parser(parser.add_subparsers(dest="command"))
    for flags, params in (([], {}), (["--local-only"], {"local_only": True}), (["--query", "bol"], {"query": "bol"})):
        args = parser.parse_args(["harness", "pets", "gallery", *flags, "--json"])
        args.func(args)
        printed = json.loads(capsys.readouterr().out)
        assert _gallery(params)["result"] == printed, flags
    local = _gallery({"local_only": True})["result"]
    assert local["localOnly"] is True and [row["slug"] for row in local["pets"]] == ["milo"]
    assert [row["slug"] for row in _gallery({})["result"]["pets"]] == ["bolt", "milo"]
    assert capsys.readouterr().out == "", "the typed door printed to stdout"


def test_an_unreachable_manifest_still_answers_the_installed_pets(home, monkeypatch):
    from agent.pet import manifest as pet_manifest

    def offline(**kwargs):
        raise OSError("offline")

    monkeypatch.setattr(pet_manifest, "fetch_manifest", offline)
    _write_pet(home)
    result = _gallery({})["result"]
    assert [row["slug"] for row in result["pets"]] == ["milo"]
    assert result["manifestError"] == "manifest unavailable: offline"


@pytest.mark.parametrize("params", [{"local_only": "yes"}, {"limit": -1}, {"limit": "3"}, {"query": 3}])
def test_a_malformed_gallery_read_is_refused(home, params):
    assert _gallery(params)["error"]["code"] == ERR_INVALID_PARAMS


def test_the_gallery_is_read_tier_with_its_params():
    published = manifest()
    assert method_tier("runtime.pets.gallery") == "read" == published["tiers"]["runtime.pets.gallery"]
    assert published["params"]["runtime.pets.gallery"] == ["limit", "local_only", "query"]


def _cli_pets(capsys, *argv: str) -> dict:
    import argparse

    from hermes_cli import harness

    parser = argparse.ArgumentParser(prog="hermes")
    harness.build_parser(parser.add_subparsers(dest="command"))
    args = parser.parse_args(["harness", "pets", *argv, "--json"])
    args.func(args)
    return json.loads(capsys.readouterr().out)


def _pets(method: str, params: dict) -> dict:
    return handle_request({"jsonrpc": "2.0", "id": "p", "method": method, "params": params},
                          RpcContext(caller=STDIO_OWNER))


def test_sprite_answers_the_verbs_own_payload(home, capsys):
    _write_pet(home)
    whole = _pets("runtime.pets.sprite", {"slug": "milo"})["result"]
    assert whole == _cli_pets(capsys, "sprite", "milo")
    assert whole["ok"] is True and whole["pet"]["spritesheetBase64"] and "sheet" not in whole["pet"]
    light = _pets("runtime.pets.sprite", {"slug": "milo", "include_sheet": False})["result"]
    assert light == _cli_pets(capsys, "sprite", "milo", "--no-sheet")
    assert light["pet"]["sheet"].endswith("spritesheet.png") and "spritesheetBase64" not in light["pet"]
    missing = _pets("runtime.pets.sprite", {"slug": "ghost"})["result"]
    assert missing == {"ok": False, "slug": "ghost", "error": "pet 'ghost' is not installed"}
    assert _pets("runtime.pets.sprite", {})["error"]["code"] == ERR_INVALID_PARAMS


def test_install_answers_the_verbs_own_payload(home, monkeypatch, capsys):
    from agent.pet import store

    _write_pet(home)
    asked = []

    def install(slug, force=False):
        asked.append((slug, force))
        if slug == "ghost":
            raise store.PetStoreError("no pet 'ghost' in the manifest")
        return store.load_pet(slug)

    monkeypatch.setattr(store, "install_pet", install)
    result = _pets("runtime.pets.install", {"slug": "milo", "force": True})["result"]
    assert result == _cli_pets(capsys, "install", "milo", "--force")
    assert result["ok"] is True and result["pet"]["slug"] == "milo"
    assert asked == [("milo", True), ("milo", True)]
    refused = _pets("runtime.pets.install", {"slug": "ghost"})["result"]
    assert refused == {"ok": False, "slug": "ghost", "error": "no pet 'ghost' in the manifest"}
    assert _pets("runtime.pets.install", {"slug": "milo", "force": "yes"})["error"]["code"] == ERR_INVALID_PARAMS


def test_install_is_this_consoles_alone():
    from agent_runtime.call_authorization import (LOCAL_CONSOLE, LOCAL_CONSOLE_METHODS, TIER_CONSOLE, RpcCaller,
                                                  authorize_call)

    assert "runtime.pets.install" in LOCAL_CONSOLE_METHODS
    tier = method_tier("runtime.pets.install")
    assert tier == TIER_CONSOLE
    device = RpcCaller(kind="device", device_id="dev_1", device_tier=TIER_CONSOLE)
    assert authorize_call(tier, device, method="runtime.pets.install").ok is False
    assert authorize_call(tier, LOCAL_CONSOLE, method="runtime.pets.install").ok is True
    reader = RpcCaller(kind="device", device_id="dev_2", device_tier="read")
    for read in ("runtime.pets.gallery", "runtime.pets.sprite"):
        assert authorize_call(method_tier(read), reader, method=read).ok is True
