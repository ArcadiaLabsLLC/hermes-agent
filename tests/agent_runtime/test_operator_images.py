"""Pasted images on the operator chat send (RT-OPERATOR-CHAT-SEND-PERSONA).

Fork module ``agent_runtime/operator_images.py``: bounded PNG/JPEG parts on ``runtime.chat.message``,
stored content-addressed and named on argv by reference, refused ``vision_unsupported`` for a model
upstream's ``decide_image_input_mode`` answers ``text`` for, sent as image parts otherwise.
"""

from __future__ import annotations

import base64
from types import SimpleNamespace

import pytest

from agent_runtime import operator_images as oi
from agent_runtime.chat_turn import ChatTurnInvalid, normalize_chat_message
from agent_runtime.mission_chat_outcome import ChatErrorKind
from agent_runtime.profile_runner.execute import AgentRunExecution
from agent_runtime.profile_runner.models import AgentRunRequest

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 32


def _part(data=PNG, media_type="image/png"):
    return {"media_type": media_type, "data_b64": base64.b64encode(data).decode("ascii")}


@pytest.fixture
def store(tmp_path, monkeypatch):
    root = tmp_path / "store"
    monkeypatch.setattr(oi, "images_dir", lambda store_root=None: root / oi.IMAGES_DIRNAME)
    return root / oi.IMAGES_DIRNAME


def _send(**extra):
    return {"turn_request_id": "t-1", "persona_id": "alice", "message": "what is this?", **extra}


def test_bounded_png_and_jpeg_parts_are_admitted_and_stored_by_reference(store):
    request = normalize_chat_message(_send(images=[_part(), _part(JPEG, "image/jpeg")]))
    flags = [request.argv[i + 1] for i, token in enumerate(request.argv) if token == oi.IMAGE_FLAG]
    assert len(flags) == 2 and flags[0].endswith(".png") and flags[1].endswith(".jpg")
    paths = oi.resolve_refs(flags)
    assert [p.read_bytes() for p in paths] == [PNG, JPEG]
    # Content-addressed: the same bytes are the same reference, so a replay fingerprints the same.
    again = normalize_chat_message(_send(images=[_part()]))
    assert again.argv[again.argv.index(oi.IMAGE_FLAG) + 1] == flags[0]


def test_a_send_without_images_is_argv_unchanged(store):
    assert oi.IMAGE_FLAG not in normalize_chat_message(_send()).argv


@pytest.mark.parametrize(("images", "reason"), [
    ([_part(b"GIF89a....", "image/png")], oi.REASON_IMAGE_INVALID),          # magic mismatch
    ([_part(PNG, "image/gif")], oi.REASON_IMAGE_INVALID),                     # type not admitted
    ([{"media_type": "image/png", "data_b64": "!!notb64!!"}], oi.REASON_IMAGE_INVALID),
    ([_part()] * (oi.MAX_IMAGES + 1), oi.REASON_IMAGE_INVALID),               # too many
    ("not-a-list", oi.REASON_IMAGE_INVALID),
])
def test_invalid_parts_are_refused_typed(store, images, reason):
    with pytest.raises(ChatTurnInvalid) as caught:
        normalize_chat_message(_send(images=images))
    assert caught.value.reason == reason


def test_an_oversized_part_is_refused_image_too_large(store, monkeypatch):
    monkeypatch.setattr(oi, "MAX_IMAGE_BYTES", 16)
    with pytest.raises(ChatTurnInvalid) as caught:
        normalize_chat_message(_send(images=[_part()]))
    assert caught.value.reason == oi.REASON_IMAGE_TOO_LARGE


def test_a_reference_must_name_a_stored_file(store):
    with pytest.raises(oi.OperatorImagesInvalid):
        oi.resolve_refs(["../../etc/passwd"])
    with pytest.raises(oi.OperatorImagesInvalid):
        oi.resolve_refs(["sha256:" + "0" * 64 + ".png"])


def test_vision_capability_is_upstreams_decision(monkeypatch):
    seen = {}

    def decide(provider, model, cfg, *, requested_provider=""):
        seen["args"] = (provider, model)
        return "native" if model == "vision-model" else "text"

    monkeypatch.setattr("agent.image_routing.decide_image_input_mode", decide)
    assert oi.vision_supported("openrouter", "vision-model") is True
    assert oi.vision_supported("openrouter", "text-model") is False
    assert seen["args"] == ("openrouter", "text-model")


def test_the_provider_sees_image_parts_and_the_transcript_keeps_media_lines(store, tmp_path):
    (path,) = oi.resolve_refs(oi.store_images([oi.OperatorImage("image/png", PNG)]))
    request = AgentRunRequest(profile=None, user_message="HUD\n\nwhat is this?", user_image_paths=(str(path),))
    kwargs = AgentRunExecution.conversation_kwargs(SimpleNamespace(request=request))
    parts = kwargs["user_message"]
    assert parts[0]["type"] == "text" and "what is this?" in parts[0]["text"]
    assert parts[1]["type"] == "image_url" and parts[1]["image_url"]["url"].startswith("data:image/png;base64,")
    assert kwargs["persist_user_message"].endswith(f"MEDIA:{path}")
    assert "data:image" not in kwargs["persist_user_message"]


def test_a_turn_without_images_keeps_its_plain_message():
    request = AgentRunRequest(profile=None, user_message="hi")
    kwargs = AgentRunExecution.conversation_kwargs(SimpleNamespace(request=request))
    assert kwargs["user_message"] == "hi" and "persist_user_message" not in kwargs


def _admit(monkeypatch, refs, *, vision):
    from hermes_cli.harness_parts.persona.chat_turn_commit import admit

    emitted = []
    monkeypatch.setattr(admit, "_mission_chat_emit", lambda args, data, *a, **k: emitted.append(data))
    monkeypatch.setattr(oi, "vision_supported", lambda provider, model, **k: vision)
    turn = SimpleNamespace(
        args=SimpleNamespace(images=refs), normalized_persona="alice", session_id="root-1",
        instance=SimpleNamespace(id="personainst_alice"),
        persona=SimpleNamespace(provider="openrouter", model="text-model"),
        model_selection={}, cfg=SimpleNamespace(default_provider="", default_model=""),
    )
    code = admit._AdmitPhases._admit_images(turn)
    return code, emitted, turn


def test_a_model_without_vision_refuses_the_turn_vision_unsupported(store, monkeypatch):
    refs = oi.store_images([oi.OperatorImage("image/png", PNG)])
    code, emitted, _turn = _admit(monkeypatch, refs, vision=False)
    assert code == 2 and emitted[0]["error_kind"] == ChatErrorKind.VISION_UNSUPPORTED
    assert emitted[0]["model"] == "text-model"


def test_a_vision_model_admits_the_images(store, monkeypatch):
    refs = oi.store_images([oi.OperatorImage("image/png", PNG)])
    code, emitted, turn = _admit(monkeypatch, refs, vision=True)
    assert code is None and not emitted
    assert turn.user_image_paths == tuple(str(p) for p in oi.resolve_refs(refs))


def test_a_dangling_reference_refuses_the_turn_image_invalid(store, monkeypatch):
    code, emitted, _turn = _admit(monkeypatch, ["sha256:" + "a" * 64 + ".png"], vision=True)
    assert code == 2 and emitted[0]["error_kind"] == ChatErrorKind.IMAGE_INVALID


def test_the_serve_route_forwards_every_image_reference():
    from hermes_cli.harness_parts.persona.chat_serve_route import send_argv

    args = SimpleNamespace(persona_id="alice", message="hi", images=["sha256:" + "a" * 64 + ".png", "sha256:" + "b" * 64 + ".jpg"])
    argv = send_argv(args)
    assert [t for t in argv if t.startswith("--image=")] == [f"--image={r}" for r in args.images]
