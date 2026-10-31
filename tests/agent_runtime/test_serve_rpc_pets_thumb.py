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
