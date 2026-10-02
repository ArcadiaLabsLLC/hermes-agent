"""Reviewed input crosses the real RPC, parser and native history boundaries."""
import argparse
import base64
import json
from contextlib import closing
from io import BytesIO
from types import SimpleNamespace

import pytest
from PIL import Image

from agent_runtime.operator_input import REVIEWED_INPUT_KIND, operator_input
from hermes_cli.harness_parts.persona.chat_input import input_from_args
from agent_runtime.persona_chat_continuity.wire import native_wire_row, safe_native_history
from agent_runtime.persona_chat_history.curation import _safe_curated_messages
from agent_runtime.profile_runner.models import AgentRunRequest
from agent_runtime.profile_runner.model_input_observability import _wire_user_message
from agent_runtime.reviewed_prompt import MAX_PROMPT_BYTES
from hermes_state import SessionDB
from tests.agent_runtime.test_operator_conversation_attachment import call, fixture
from tests.agent_runtime.test_send_path_turn_bounds import _composed_row


def reviewed_prompt():
    output = BytesIO()
    Image.new("RGB", (2, 2), (10, 20, 30)).save(output, format="PNG")
    return {"text": "Explain this:\n\n```python\n    pass\n```\n" + "context\n" * 6000,
            "images": [{"name": "sample.png", "data": base64.b64encode(output.getvalue()).decode()}]}


def test_rpc_admission_parser_and_duplicate_payload_share_one_door(tmp_path, monkeypatch):
    from hermes_cli import harness

    target = fixture(tmp_path / "home", monkeypatch, "Amelia")
    prompt = reviewed_prompt()
    params = {**target, "turn_request_id": "reviewed-turn", "prompt": prompt}
    spawned = []
    send = lambda: call("message", params, spawn=lambda *args: spawned.append(args))
    assert send()["result"]["accepted"]
    assert send()["result"]["idempotent_replay"]
    assert len(spawned) == 1
    parser = argparse.ArgumentParser()
    harness.build_parser(parser.add_subparsers(dest="cmd"))
    parsed = parser.parse_args(spawned[0][1])
    submitted = input_from_args(parsed)
    assert submitted.text == prompt["text"]
    assert list(submitted.images) == prompt["images"]
    params["prompt"] = {**prompt, "text": "different"}
    assert send()["error"]["data"]["reason"] == "turn_payload_conflict"
    assert len(spawned) == 1


@pytest.mark.parametrize("mutation", ["bytes", "type", "size", "conflict"])
def test_invalid_input_never_reaches_admission(tmp_path, monkeypatch, mutation):
    target = fixture(tmp_path / "home", monkeypatch, "Amelia")
    prompt = reviewed_prompt()
    params = {**target, "turn_request_id": "invalid", "prompt": prompt}
    if mutation == "bytes":
        prompt["images"][0]["data"] = base64.b64encode(b"not an image").decode()
    elif mutation == "type":
        prompt["images"] = "not a list"
    elif mutation == "size":
        prompt["text"] = "x" * MAX_PROMPT_BYTES
    else:
        params["message"] = "conflicting text"
    spawned = []
    result = call("message", params, spawn=lambda *args: spawned.append(args))
    assert "error" in result, result
    assert not spawned


def test_native_images_and_reviewed_text_survive_database_reconstruction(tmp_path):
    prompt = reviewed_prompt()
    submitted = operator_input(prompt=prompt)
    composed, _ = _composed_row(message=submitted.text)
    content = submitted.content(composed)
    original = dict(role="user", content=content, display_kind=REVIEWED_INPUT_KIND)
    wire = native_wire_row(original)
    assert wire.row == original
    assert wire.holds and not wire.notes
    assert wire.submitted_chars == wire.wire_chars == len(composed)
    with closing(SessionDB(db_path=tmp_path / "state.db")) as db:
        db.create_session("reviewed", source="mission_chat")
        db.append_message("reviewed", "user", wire.row["content"], display_kind=REVIEWED_INPUT_KIND)
    with closing(SessionDB(db_path=tmp_path / "state.db")) as db:
        history = safe_native_history(db.get_messages_as_conversation("reviewed"))
        assert history[0]["content"] == content
        assert history[0]["display_kind"] == REVIEWED_INPUT_KIND
        visible, _, error = _safe_curated_messages(db, session_id="reviewed")
    assert error is None and visible
    assert "data:image" not in json.dumps(visible)
    assert prompt["images"][0]["data"] not in json.dumps(visible)
    assert "runtime_context" not in visible[0]["text"]
    assert visible[0]["text"].startswith("Explain this:")
    agent = SimpleNamespace(messages=history, _persist_user_message_idx=0)
    preview, receipt = _wire_user_message(agent=agent, request=AgentRunRequest(profile=None, user_message=content))
    assert preview == composed
    assert receipt["source"] == "agent_wire" and not receipt["bounded"]
    assert prompt["images"][0]["data"] not in preview
