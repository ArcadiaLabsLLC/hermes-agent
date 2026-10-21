"""The palette op log: ``recolour`` records a swatch edit as a draft step, and compose replays it.

Runs the real draft machine under a temp ``HERMES_HOME`` with the deterministic draftsman
(the same seam ``test_charsheet_draft.py`` uses), so the op log, the installed sheet and both
``palette.json`` copies are exercised on real files.

Killing mutations (applied, red recorded, reverted — see the commit message):
* ``Composer._validate`` skips :func:`replay` -> ``test_a_recompose_replays_the_log_to_the_same_sheet`` red.
* :func:`agent.charsheet.palette.recolour` drops the ``alpha > 0`` term of its mask
  -> ``test_recolour_is_exact_keeps_alpha_and_never_paints_the_backdrop`` red.
"""

from __future__ import annotations

import json

import pytest

pytest.importorskip("PIL")

from PIL import Image

from agent.charsheet import palette, pipeline
from agent.charsheet.draft import (
    DRAFT_FILENAME,
    MANIFEST_FILENAME,
    PALETTE_FILENAME,
    PALETTE_OPS_KEY,
    SHEET_FILENAME,
    CharacterDraft,
    characters_dir,
)
from tests.agent.test_charsheet_draft import draftsman, run_to_composed, run_to_rows, write_base


@pytest.fixture
def composed(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "home"))
    monkeypatch.setattr(pipeline.provider, "_generate_image", draftsman(tmp_path / "generated"))
    return run_to_composed(write_base(tmp_path / "src"))


def installed_sheet(draft) -> Image.Image:
    with Image.open(characters_dir() / draft.slug / SHEET_FILENAME) as sheet:
        return sheet.convert("RGBA")


def opaque_rgb(image) -> set[tuple[int, int, int]]:
    return {(r, g, b) for _, (r, g, b, a) in image.getcolors(image.width * image.height) if a}


def rgb(text: str) -> tuple[int, int, int]:
    return tuple(int(text[i:i + 2], 16) for i in (1, 3, 5))


def test_recolour_is_exact_keeps_alpha_and_never_paints_the_backdrop():
    image = Image.new("RGBA", (4, 1))
    image.putdata([(10, 20, 30, 255), (10, 20, 30, 90), (10, 20, 31, 255), (0, 0, 0, 0)])
    out, pixels = palette.recolour(image, "#0a141e", "#ff0000ff")
    assert pixels == 2
    assert [out.getpixel((x, 0)) for x in range(4)] == [(255, 0, 0, 255), (255, 0, 0, 90), (10, 20, 31, 255), (0, 0, 0, 0)]
    black, painted = palette.recolour(image, "#000000", "#00ff00")
    assert painted == 0 and black.getpixel((3, 0)) == (0, 0, 0, 0)


@pytest.mark.parametrize("bad", ["#0a141e80", "0a141", "#zzzzzz", ""])
def test_a_colour_that_is_not_opaque_hex_is_refused(bad):
    with pytest.raises(ValueError, match="RRGGBB"):
        palette.opaque_hex(bad)


def test_recolour_records_the_op_and_rewrites_the_installed_sheet_and_both_tables(composed):
    swatch = json.loads((composed.directory / PALETTE_FILENAME).read_text(encoding="utf-8"))[0]
    result = composed.recolour(swatch, "#123456")
    source = swatch[:7]
    assert result["op"]["from"] == source and result["op"]["to"] == "#123456" and result["pixels"] > 0
    recorded = json.loads((composed.directory / DRAFT_FILENAME).read_text(encoding="utf-8"))[PALETTE_OPS_KEY]
    assert [(op["op"], op["from"], op["to"]) for op in recorded] == [("recolour", source, "#123456")]
    colours = opaque_rgb(installed_sheet(composed))
    assert rgb(source) not in colours and (0x12, 0x34, 0x56) in colours
    for directory in (composed.directory, characters_dir() / composed.slug):
        table = json.loads((directory / PALETTE_FILENAME).read_text(encoding="utf-8"))
        assert "#123456ff" in table and swatch not in table


def test_a_recompose_replays_the_log_to_the_same_sheet(composed):
    swatches = json.loads((composed.directory / PALETTE_FILENAME).read_text(encoding="utf-8"))
    composed.recolour(swatches[0], "#123456")
    composed.recolour("#123456", "#654321")  # in order: the second op edits the first one's output
    composed.recolour(swatches[1], "#abcdef")
    edited = installed_sheet(composed).tobytes()
    composed.reopen()
    answer = CharacterDraft.load(composed.id).compose()
    assert [op["pixels"] > 0 for op in answer["paletteOps"]] == [True, True, True]
    assert installed_sheet(composed).tobytes() == edited


def test_recolour_refuses_before_compose_an_unknown_swatch_and_a_no_op(tmp_path, monkeypatch, composed):
    with pytest.raises(ValueError, match="not a swatch"):
        composed.recolour("#010203", "#123456")
    swatch = json.loads((composed.directory / PALETTE_FILENAME).read_text(encoding="utf-8"))[0]
    with pytest.raises(ValueError, match="changes nothing"):
        composed.recolour(swatch, swatch[:7].upper())
    other = run_to_rows(write_base(tmp_path / "src2"), slug="other-knight")
    with pytest.raises(ValueError, match="requires draft stage 'composed'"):
        other.recolour(swatch, "#123456")
    assert PALETTE_OPS_KEY not in json.loads((composed.directory / DRAFT_FILENAME).read_text(encoding="utf-8"))


def test_recolour_refuses_a_sheet_another_draft_installed(composed):
    manifest_path = characters_dir() / composed.slug / MANIFEST_FILENAME
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest_path.write_text(json.dumps({**manifest, "draftId": "someone-else"}), encoding="utf-8")
    swatch = json.loads((composed.directory / PALETTE_FILENAME).read_text(encoding="utf-8"))[0]
    with pytest.raises(ValueError, match="is not draft"):
        composed.recolour(swatch, "#123456")


def test_the_rpc_twin_is_console_tier_and_answers_the_verb(composed):
    from agent_runtime.call_authorization import STDIO_OWNER
    from agent_runtime.serve_rpc import handle_request, method_tier
    from agent_runtime.serve_rpc.protocol import ERR_INVALID_PARAMS, RpcContext

    def rpc(params):
        return handle_request({"jsonrpc": "2.0", "id": "r", "method": "runtime.characters.recolour",
                               "params": params}, RpcContext(caller=STDIO_OWNER))

    assert method_tier("runtime.characters.recolour") == "console"
    swatch = json.loads((composed.directory / PALETTE_FILENAME).read_text(encoding="utf-8"))[0]
    answer = rpc({"draft": composed.id, "from": swatch, "to": "#123456"})["result"]
    assert answer["ok"] is True and answer["stage"] == "composed" and answer["op"]["to"] == "#123456"
    refused = rpc({"draft": composed.id, "from": "#010203", "to": "#123456"})["error"]
    assert refused["code"] == ERR_INVALID_PARAMS and refused["data"]["reason"] == "invalid_request"
