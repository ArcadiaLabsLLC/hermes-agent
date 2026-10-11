"""D2.10: the ``runtime.characters.*`` read twins answer their argv verb's payload."""

from __future__ import annotations

import argparse
import base64
import io
import json
from contextlib import redirect_stdout

import pytest

pytest.importorskip("PIL")

from agent.charsheet import pipeline  # noqa: E402
from agent.charsheet.fake_draftsman import FakeDraftsman, square_image  # noqa: E402
from agent_runtime.call_authorization import STDIO_OWNER  # noqa: E402
from agent_runtime.serve_rpc import handle_request, manifest, method_tier  # noqa: E402
from agent_runtime.serve_rpc.protocol import ERR_INVALID_PARAMS, ERR_NOT_FOUND, RpcContext  # noqa: E402

TWINS = ("runtime.characters.list", "runtime.characters.status",
         "runtime.characters.thumb", "runtime.characters.sprite")


@pytest.fixture
def composed(tmp_path, monkeypatch):
    """One composed character (draft + install), built through the argv verbs."""
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "home"))
    monkeypatch.setattr(pipeline.provider, "_generate_image",
                        FakeDraftsman(tmp_path / "generated", strip_size=(512, 192), square_px=384, glyph_px=44))
    base = tmp_path / "base.png"
    square_image("s", size_px=384).save(base, format="PNG")
    draft = argv("start", "--concept", "an arrow knight", "--slug", "arrow-knight", "--states",
                 "idle:2,walk:2", "--directions", "4", "--base-image", str(base))["draft"]
    for verb in (("turnaround",), ("approve-direction", "--all"), ("rows",), ("compose",)):
        assert argv(verb[0], "--draft", draft, *verb[1:])["ok"] is True
    return draft


def argv(*words: str) -> dict:
    from hermes_cli.harness import build_parser

    parser = argparse.ArgumentParser()
    build_parser(parser.add_subparsers(dest="command"))
    args = parser.parse_args(["harness", "characters", *words, "--json"])
    out = io.StringIO()
    with redirect_stdout(out):
        args.func(args)
    return json.loads(out.getvalue())


def rpc(name: str, params: dict) -> dict:
    return handle_request({"jsonrpc": "2.0", "id": "r", "method": name, "params": params},
                          RpcContext(caller=STDIO_OWNER))


def test_every_twin_is_read_tier_and_publishes_its_honoured_params():
    assert {name: method_tier(name) for name in TWINS} == dict.fromkeys(TWINS, "read")
    published = manifest()["params"]
    assert published["runtime.characters.list"] == []
    assert published["runtime.characters.status"] == ["draft"]
    assert published["runtime.characters.thumb"] == [
        "attempt", "direction", "draft", "frame", "row", "scale", "square"]
    assert published["runtime.characters.sprite"] == ["include_sheet", "slug"]


def test_list_and_status_equal_their_argv_payloads(composed):
    assert rpc("runtime.characters.list", {})["result"] == argv("list")
    assert rpc("runtime.characters.status", {"draft": composed})["result"] == argv("status", "--draft", composed)


def test_thumb_is_the_argv_payload_plus_the_media_block(composed):
    reply = rpc("runtime.characters.thumb", {"draft": composed, "row": "walk-e"})["result"]
    media = reply.pop("media")
    assert reply == argv("thumb", "--draft", composed, "--row", "walk-e")
    assert reply["withinConsoleBudget"] is True
    with open(reply["path"], "rb") as handle:
        data = handle.read()
    assert media["media_type"] == "image/png" and media["encoding"] == "base64"
    assert base64.b64decode(media["data"]) == data and media["size_bytes"] == len(data)
    assert media["handle"].startswith("sha256:")


def test_a_thumb_over_the_console_budget_ships_no_pixels_and_keeps_the_path(composed):
    one = rpc("runtime.characters.thumb", {"draft": composed, "row": "walk-e", "scale": 1})["result"]
    deep = next(s for s in range(2, 128)
                if one["width"] * one["height"] * s * s > pipeline.MAX_CONSOLE_CARD_PIXELS)
    reply = rpc("runtime.characters.thumb", {"draft": composed, "row": "walk-e", "scale": deep})["result"]
    assert reply["withinConsoleBudget"] is False
    assert reply["media"] is None and reply["path"].endswith(".png")


def test_sprite_is_the_metadata_payload_plus_the_sheet_block(composed):
    reply = rpc("runtime.characters.sprite", {"slug": "arrow-knight"})["result"]
    assert reply["character"] == argv("sprite", "arrow-knight", "--no-sheet")["character"]
    full = argv("sprite", "arrow-knight")["character"]
    assert base64.b64decode(reply["sheet_media"]["data"]) == base64.b64decode(full["spritesheetBase64"])
    assert reply["sheet_media"]["media_type"] == "image/webp"
    bare = rpc("runtime.characters.sprite", {"slug": "arrow-knight", "include_sheet": False})["result"]
    assert "sheet_media" not in bare and bare["character"] == reply["character"]


@pytest.mark.parametrize("name, params, code, reason", [
    ("runtime.characters.status", {"draft": "no-such-draft"}, ERR_NOT_FOUND, "not_found"),
    ("runtime.characters.sprite", {"slug": "nobody"}, ERR_NOT_FOUND, "not_found"),
    ("runtime.characters.status", {}, ERR_INVALID_PARAMS, "invalid_request"),
    ("runtime.characters.thumb", {"draft": "d", "attempt": "1"}, ERR_INVALID_PARAMS, "invalid_request"),
    ("runtime.characters.sprite", {"slug": "s", "include_sheet": 1}, ERR_INVALID_PARAMS, "invalid_request"),
])
def test_refusals_speak_the_argv_vocabulary(tmp_path, monkeypatch, name, params, code, reason):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "home"))
    error = rpc(name, params)["error"]
    assert (error["code"], error["data"]["reason"]) == (code, reason)


def test_a_frame_asked_of_a_reference_is_refused_as_argv_refuses_it(composed):
    error = rpc("runtime.characters.thumb", {"draft": composed, "direction": "s", "frame": 1})["error"]
    assert (error["code"], error["data"]["reason"]) == (ERR_INVALID_PARAMS, "invalid_request")
    assert error["data"]["draft"] == composed
