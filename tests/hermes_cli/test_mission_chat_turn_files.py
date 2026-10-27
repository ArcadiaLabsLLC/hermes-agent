"""A mission-chat turn carrying reviewed files (``RT-MISSION-CHAT-MESSAGE-TAKES`` S3,
plan ``archive/p10-turn-2026-10-19.md`` §3.5 test 6).

Drives the real ``mission-chat message`` handler over the turn-phases fixture with ``--file``
references stored by ``agent_runtime.operator_files``. The request text the runtime is handed and
the user row this lane mirrors are compared: both carry the ``FILE:`` lines, and the write-ahead
record keeps ``pending_user_files``.

Killing mutation: ``chat_message = self.message`` in ``chat_turn_commit/run.py::_build_context``
(the request text skips ``with_file_lines``) -> the request carries no ``FILE:`` line and differs
from the mirrored row.
"""

from __future__ import annotations

import base64
from types import SimpleNamespace

import pytest

from hermes_cli.harness_parts.persona import chat_turn_message
from hermes_cli.harness_parts.persona.chat_turn_commit import run as commit_run

from agent_runtime import operator_files as of
from agent_runtime.mission_chat_outcome import ChatErrorKind
from tests.hermes_cli.test_mission_chat_turn_phases import (  # type: ignore
    _args,
    _record_on_disk,
    isolate_agent_runtime_root,  # (re-exported fixture)
)
from tests.hermes_cli.test_mission_chat_budget_payload import _seed  # type: ignore


def _provider(seen: list):
    class _Provider:
        def __init__(self, *args, **kwargs):
            pass

        def mission_chat_reply(self, persona, message, *args, **kwargs):
            seen.append(message)
            return SimpleNamespace(
                final_response="read it", input_tokens=1, output_tokens=2, total_tokens=3,
                latency_ms=4, profile_timing={}, raw={}, turn_outcome=None,
            )

    return _Provider


def _stored(*parts):
    files = of.normalize_files([
        {"name": name, "media_type": media_type, "data": base64.b64encode(data).decode("ascii")}
        for name, media_type, data in parts
    ])
    return of.store_files(files)


def test_a_turn_with_files_names_them_by_path_on_the_request_and_the_row(
    monkeypatch, capsys, isolate_agent_runtime_root,
):
    refs = _stored(("notes.txt", "text/plain", b"alpha\n"), ("cfg.json", "application/json", b"{}"))
    resolved = of.resolve_refs(refs)
    seen_requests: list = []
    mirrored: list = []
    real_mirror = commit_run._mirror_persona_chat_message
    monkeypatch.setattr(commit_run, "_mirror_persona_chat_message",
                        lambda **kw: (mirrored.append(kw["text"]), real_mirror(**kw))[1])
    _seed(monkeypatch, _provider(seen_requests))
    args = _args("files_ok", stream=False)
    args.files = refs
    code = chat_turn_message._cmd_mission_chat_message(args)
    out = capsys.readouterr().out
    assert code == 0, out

    file_lines = [f"FILE:{item.path}" for item in resolved]
    [request] = seen_requests
    assert request.splitlines()[0] == "please answer"
    assert request.splitlines()[-2:] == file_lines
    assert of.FILE_GUIDANCE.format(names="notes.txt, cfg.json") in request
    assert mirrored == [request]  # the row the lane mirrors is the text the runtime was handed
    record = _record_on_disk(isolate_agent_runtime_root, "files_ok")
    assert record["pending_user_files"] == [str(item.path) for item in resolved]
    assert record["pending_user_message"] == "please answer"


def test_a_dangling_file_reference_refuses_the_turn_file_invalid(
    monkeypatch, capsys, isolate_agent_runtime_root,
):
    seen_requests: list = []
    _seed(monkeypatch, _provider(seen_requests))
    args = _args("files_gone", stream=False)
    args.files = ["sha256:" + "e" * 64 + ".txt"]
    code = chat_turn_message._cmd_mission_chat_message(args)
    out = capsys.readouterr().out
    assert code == 2 and ChatErrorKind.FILE_INVALID.value in out
    assert not seen_requests


# -- RT-PENDING-ATTACHMENTS-NO-READER: the retry is the write-ahead lists' reader -----------------
# Killing mutations: (1) _reattach_retried returns before re-attaching -> the retry's request has no
# FILE:/MEDIA: line; (2) the resolver's existence check skipped -> the refusal test runs a turn.

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 24


def _refuse_then_reply(seen: list, calls: list):
    from agent_runtime.profile_runner import ProfileRunnerError

    class _Provider:
        def __init__(self, *args, **kwargs):
            pass

        def mission_chat_reply(self, persona, message, *args, **kwargs):
            calls.append(kwargs.get("user_image_paths"))
            if len(calls) == 1:
                kwargs["agent_ready_callback"](object())
                raise ProfileRunnerError("HTTP 429: The usage limit has been reached", provider_error={
                    "status_code": 429, "reason": "usage_limit_reached", "failure_reason": "rate_limit",
                    "message": "The usage limit has been reached"})
            seen.append(message)
            return SimpleNamespace(
                final_response="read it", input_tokens=1, output_tokens=2, total_tokens=3,
                latency_ms=4, profile_timing={}, raw={}, turn_outcome=None,
            )

    return _Provider


def _send(cmid, *, retry_of=None, files=None, images=None):
    args = _args(cmid, stream=False)
    if retry_of:
        args.retry_of = retry_of
    if files:
        args.files = files
    if images:
        args.images = images
    return chat_turn_message._cmd_mission_chat_message(args)


def test_a_retry_without_files_reattaches_the_retried_turns_files(monkeypatch, capsys, isolate_agent_runtime_root):
    refs = _stored(("notes.txt", "text/plain", b"alpha\n"))
    [item] = of.resolve_refs(refs)
    seen, calls = [], []
    _seed(monkeypatch, _refuse_then_reply(seen, calls))
    assert _send("files_first", files=refs) == 2
    first = _record_on_disk(isolate_agent_runtime_root, "files_first")
    assert first["state"] == "provider_refused"
    assert first["pending_user_files"] == [str(item.path)]
    capsys.readouterr()

    code = _send("files_retry", retry_of="files_first")
    assert code == 0, capsys.readouterr().out
    [request] = seen
    assert request.splitlines()[-1] == f"FILE:{item.path}"
    retry = _record_on_disk(isolate_agent_runtime_root, "files_retry")
    assert retry["pending_user_files"] == first["pending_user_files"]
    assert retry["retry_of"] == "files_first"


def test_a_retry_whose_file_is_gone_refuses_attachment_missing(monkeypatch, capsys, isolate_agent_runtime_root):
    refs = _stored(("notes.txt", "text/plain", b"beta\n"))
    [item] = of.resolve_refs(refs)
    seen, calls = [], []
    _seed(monkeypatch, _refuse_then_reply(seen, calls))
    assert _send("gone_first", files=refs) == 2
    capsys.readouterr()
    item.path.unlink()

    code = _send("gone_retry", retry_of="gone_first")
    out = capsys.readouterr().out
    assert code == 2, out
    assert ChatErrorKind.ATTACHMENT_MISSING.value in out and item.path.name in out
    assert len(calls) == 1 and not seen  # nothing ran
    with pytest.raises(AssertionError):
        _record_on_disk(isolate_agent_runtime_root, "gone_retry")  # no write-ahead record


def _stored_image():
    from agent_runtime import operator_images as oi

    [image] = oi.normalize_images([{"media_type": "image/png",
                                    "data_b64": base64.b64encode(PNG).decode("ascii")}])
    return oi.store_images([image])


def test_a_retry_without_images_reattaches_the_retried_turns_images(monkeypatch, capsys, isolate_agent_runtime_root):
    from agent_runtime import operator_images as oi

    monkeypatch.setattr(oi, "vision_supported", lambda *a, **k: True)
    refs = _stored_image()
    [path] = oi.resolve_refs(refs)
    seen, calls = [], []
    _seed(monkeypatch, _refuse_then_reply(seen, calls))
    assert _send("img_first", images=refs) == 2
    first = _record_on_disk(isolate_agent_runtime_root, "img_first")
    assert first["pending_user_images"] == [str(path)]
    capsys.readouterr()

    code = _send("img_retry", retry_of="img_first")
    assert code == 0, capsys.readouterr().out
    assert list(calls[1]) == [str(path)]  # the provider is handed the same image
    retry = _record_on_disk(isolate_agent_runtime_root, "img_retry")
    assert retry["pending_user_images"] == first["pending_user_images"]


def test_a_retry_whose_image_is_gone_refuses_attachment_missing(monkeypatch, capsys, isolate_agent_runtime_root):
    from agent_runtime import operator_images as oi

    monkeypatch.setattr(oi, "vision_supported", lambda *a, **k: True)
    refs = _stored_image()
    [path] = oi.resolve_refs(refs)
    seen, calls = [], []
    _seed(monkeypatch, _refuse_then_reply(seen, calls))
    assert _send("imggone_first", images=refs) == 2
    capsys.readouterr()
    path.unlink()

    code = _send("imggone_retry", retry_of="imggone_first")
    out = capsys.readouterr().out
    assert code == 2 and ChatErrorKind.ATTACHMENT_MISSING.value in out and path.name in out, out
    assert len(calls) == 1
