"""The character generation verbs have typed calls on the running Hermes: ``runtime.characters.<verb>``.

Row ``RT-EVERY-ACTION-ETERNIA-SENDS-HAS-A-TYPED-CALL-ON-THE-RUNNING-HERMES``, family "characters": base,
turnaround, reroll_direction, approve_direction, rows, reroll_row, compose, auto, reopen, add_state. Each runs
the argv handler through the operation-result sink; the image-generating six take the serve's long-run posture
(the worker lane, ``defer_or_refuse``). Driven on the fake draftsman, so nothing bills. Mutations per test.
"""

from __future__ import annotations

import argparse
import io
import json
from contextlib import redirect_stdout

import pytest

pytest.importorskip("PIL")

from agent.charsheet import pipeline
from agent.charsheet.fake_draftsman import FakeDraftsman, square_image
from agent_runtime.call_authorization import STDIO_OWNER
from agent_runtime.serve_rpc import handle_request
from agent_runtime.serve_rpc.protocol import DEFERRED, ERR_CONFLICT, ERR_INVALID_PARAMS, RpcContext

LONG = ("turnaround", "reroll_direction", "rows", "reroll_row", "compose", "auto")


def argv(*words: str) -> dict:
    from hermes_cli.harness import build_parser

    parser = argparse.ArgumentParser()
    build_parser(parser.add_subparsers(dest="command"))
    args = parser.parse_args(["harness", "characters", *words, "--json"])
    out = io.StringIO()
    with redirect_stdout(out):
        args.func(args)
    return json.loads(out.getvalue())


def rpc(verb: str, **params) -> dict:
    """One call through a worker lane that runs the deferred reply at once (the serve's own shape)."""
    spawned = []
    context = RpcContext(caller=STDIO_OWNER, spawn_reply=lambda build: spawned.append(build) or True)
    frame = handle_request({"jsonrpc": "2.0", "id": "c", "method": f"runtime.characters.{verb}", "params": params},
                           context)
    if frame is DEFERRED:
        assert len(spawned) == 1
        return spawned[0]()
    return frame


@pytest.fixture
def draft(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "home"))
    monkeypatch.setattr(pipeline.provider, "_generate_image",
                        FakeDraftsman(tmp_path / "generated", strip_size=(512, 192), square_px=384, glyph_px=44))
    base = tmp_path / "base.png"
    square_image("s", size_px=384).save(base, format="PNG")
    return argv("start", "--concept", "an arrow knight", "--slug", "arrow-knight", "--states", "idle:2,walk:2",
                "--directions", "4", "--base-image", str(base))["draft"]


def test_the_whole_pipeline_runs_through_the_typed_calls(draft, tmp_path):
    """Mutation: point ``rows`` at the turnaround handler in ``operation._handlers`` -> compose refuses, red."""
    base = tmp_path / "base2.png"
    square_image("n", size_px=384).save(base, format="PNG")
    assert rpc("base", draft=draft, image=str(base))["result"]["ok"] is True
    assert rpc("turnaround", draft=draft)["result"]["stage"] == "turnaround"
    rerolled = rpc("reroll_direction", draft=draft, direction="e", note="brighter")["result"]
    assert rerolled["direction"] == "e" and rerolled["attempt"] == 1
    assert rpc("approve_direction", draft=draft, all=True)["result"]["stage"] == "rows"
    rows = rpc("rows", draft=draft)["result"]
    assert rows["ok"] is True and rows["rows"]
    row_key = sorted(rows["rows"])[0]
    assert rpc("reroll_row", draft=draft, row=row_key, note="slower")["result"]["row"] == row_key
    composed = rpc("compose", draft=draft)["result"]
    assert composed["stage"] == "composed" and composed["slug"] == "arrow-knight"
    assert rpc("reopen", draft=draft)["result"]["stage"] == "rows"
    added = rpc("add_state", draft=draft, state="jumping:3")["result"]
    assert added["state"]["name"] == "jumping" and added["rows"]


def test_auto_answers_its_summary_with_every_receipt(draft):
    """Mutation: answer the first line instead of the last in ``characters_operation_result`` -> red."""
    result = rpc("auto", draft=draft)["result"]
    assert result["step"] == "auto" and result["ok"] is True
    assert result["receipts"], result
    assert all("ok" in line for line in result["receipts"])
    assert argv("status", "--draft", draft)["stage"] == "composed"


def test_a_step_the_draft_refuses_is_the_verbs_own_refusal(draft):
    """Mutation: answer ``ok: false`` as a result -> the 4090 is lost, red."""
    reply = rpc("rows", draft=draft)  # stage is still turnaround
    assert reply["error"]["code"] == ERR_CONFLICT
    assert reply["error"]["data"]["ok"] is False and reply["error"]["data"]["draft"] == draft
    assert reply["error"]["data"]["reason"]


@pytest.mark.parametrize("verb,params,field", [
    ("turnaround", {}, "draft"),
    ("turnaround", {"draft": "d", "extra": 1}, "extra"),
    ("base", {"draft": "d"}, "image"),
    ("rows", {"draft": "d", "only": "walk-e"}, "only"),
    ("approve_direction", {"draft": "d"}, "direction"),
    ("approve_direction", {"draft": "d", "direction": "e", "all": True}, "direction"),
    ("approve_direction", {"draft": "d", "all": True, "attempt": 2}, "attempt"),
    ("auto", {"draft": "d", "through": "everything"}, "through"),
    ("compose", {"draft": "d", "accept_handedness": ["", "x"]}, "accept_handedness"),
])
def test_a_malformed_call_is_refused_before_any_draft_loads(verb, params, field):
    """Mutation: drop the exclusive-pair check -> ``direction`` with ``all`` reaches the draft, red."""
    reply = rpc(verb, **params)
    assert reply["error"]["code"] == ERR_INVALID_PARAMS
    assert reply["error"]["data"] == {"reason": "invalid_request", "field": field}


@pytest.mark.parametrize("verb", LONG)
def test_a_generation_never_runs_on_the_reader_loop(verb):
    """Mutation: answer the long verbs with ``defer_or_inline`` -> answered inline on a lane with no worker, red."""
    params = {"draft": "d", **({"direction": "e"} if verb == "reroll_direction" else {}),
              **({"row": "walk-e"} if verb == "reroll_row" else {})}
    frame = handle_request({"jsonrpc": "2.0", "id": "c", "method": f"runtime.characters.{verb}", "params": params},
                           RpcContext(caller=STDIO_OWNER))
    assert frame["error"]["data"]["reason"] == "runtime_stopping"


def test_all_ten_are_console_tier_on_the_manifest():
    from agent_runtime.serve_rpc import manifest, method_tier

    names = {f"runtime.characters.{verb}" for verb in ("base", "turnaround", "reroll_direction",
             "approve_direction", "rows", "reroll_row", "compose", "auto", "reopen", "add_state")}
    assert names <= set(manifest()["methods"])
    assert {method_tier(name) for name in names} == {"console"}
