"""A mission-chat turn carrying reviewed files (``RT-MISSION-CHAT-MESSAGE-TAKES`` S3,
plan ``planned/p10-turn-2026-10-19.md`` §3.5 test 6).

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

from hermes_cli.harness_parts.persona import chat_turn_message
from hermes_cli.harness_parts.persona.chat_turn_commit import run as commit_run

from agent_runtime import operator_files as of
from agent_runtime.mission_chat_outcome import ChatErrorKind
from tests.hermes_cli.test_mission_chat_turn_phases import (  # type: ignore
    _args,
    _record_on_disk,
    isolate_agent_runtime_root,  # noqa: F401  (re-exported fixture)
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
    monkeypatch, capsys, isolate_agent_runtime_root,  # noqa: F811
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
    monkeypatch, capsys, isolate_agent_runtime_root,  # noqa: F811
):
    seen_requests: list = []
    _seed(monkeypatch, _provider(seen_requests))
    args = _args("files_gone", stream=False)
    args.files = ["sha256:" + "e" * 64 + ".txt"]
    code = chat_turn_message._cmd_mission_chat_message(args)
    out = capsys.readouterr().out
    assert code == 2 and ChatErrorKind.FILE_INVALID.value in out
    assert not seen_requests
