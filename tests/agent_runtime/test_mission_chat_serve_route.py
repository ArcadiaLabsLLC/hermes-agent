"""opus-w4-serve-send: a shell's ``mission-chat message`` hands the turn to the live serve.

On 2026-10-09 a Claude session ran ``hermes harness mission-chat message
--persona neko_supervisor`` under the root home: the turn ran in that shell's
process, resolved the ``neko`` profile with no Codex login, and exited 2, while
the serve one socket away held the right home. These pin the cut: with a live
serve the parsed send rides the serve's argv lane and the in-process handler is
called ZERO times; with no serve it runs in-process and says why on stderr;
inside a serve request, or with ``--in-process``, it never dials.
"""

from __future__ import annotations

import argparse
import io
import json

import pytest

from hermes_cli.harness_parts.persona import chat_serve_route, chat_turn_message
from hermes_cli.harness_parts.serve.frames import current_serve_request_id
from tests.agent_runtime.test_serve_socket_lane import running_serve


def _parser() -> argparse.ArgumentParser:
    from hermes_cli.harness import build_parser

    parser = argparse.ArgumentParser()
    build_parser(parser.add_subparsers(dest="command"))
    return parser


def _parse(*extra: str) -> argparse.Namespace:
    return _parser().parse_args(
        ["harness", "mission-chat", "message", "--persona", "neko_supervisor", "--message", "hi", *extra]
    )


class _ServeSpy:
    """The serve's dispatch: records what it was asked, answers like the handler."""

    def __init__(self, code: int = 3) -> None:
        self.code = code
        self.calls: list[dict] = []

    def __call__(self, argv):
        self.calls.append({"argv": list(argv), "serve_request_id": current_serve_request_id()})
        print(json.dumps({"ok": True, "answered_by": "the-serve"}))
        return self.code


def _refuse_in_process(args):
    raise AssertionError("the turn ran in the asking process")


def test_a_parsed_send_runs_in_the_live_serve_and_relays_its_answer(monkeypatch):
    spy = _ServeSpy(code=3)
    monkeypatch.setattr(chat_turn_message, "_cmd_mission_chat_message", _refuse_in_process)
    # The serve under test is a thread of THIS process, so its registry row
    # carries this pid; the self-dial guard would (correctly) refuse it.
    monkeypatch.setattr(chat_serve_route, "_this_pid", lambda: -1)

    args = _parse("--persona-instance-id", "personainst_neko_supervisor", "--json", "--max-seconds", "90")
    out = io.StringIO()
    with running_serve(dispatch=spy):
        # The parser's func: the serve's exit code, the in-process handler never called.
        assert args.func(args) == 3
        # The relay itself, onto a sink the test owns (the serve under test is a
        # thread of this process and owns its stdout).
        assert chat_serve_route.relay_send_via_serve(args, out=out) == 3

    assert len(spy.calls) == 2, spy.calls
    assert spy.calls[0]["serve_request_id"], spy.calls
    assert spy.calls[0]["argv"] == [
        "harness",
        "mission-chat",
        "message",
        "--persona=neko_supervisor",
        "--persona-instance-id=personainst_neko_supervisor",
        "--message=hi",
        "--surface-prompt=",
        "--intent-hint=chat",
        "--requested-by=cli",
        "--max-seconds=90.0",
        "--json",
    ]
    assert spy.calls[1]["argv"] == spy.calls[0]["argv"]
    assert json.loads(out.getvalue().strip()) == {"ok": True, "answered_by": "the-serve"}


def test_with_no_live_serve_the_send_runs_in_process_and_says_why(monkeypatch, capsys):
    ran: list[object] = []
    monkeypatch.setattr(chat_turn_message, "_cmd_mission_chat_message", lambda args: ran.append(args) or 0)

    args = _parse("--json")
    assert args.func(args) == 0
    assert ran == [args]
    err = capsys.readouterr().err
    assert err.strip() == "mission-chat message: running in-process (no live serve for this runtime root)"


def test_inside_a_serve_request_the_send_never_dials(monkeypatch):
    from hermes_cli.harness_parts.serve import frames as serve_frames

    def _refuse(args, **_kwargs):
        raise AssertionError("the serve's own send dialled the serve")

    ran: list[object] = []
    monkeypatch.setattr(chat_serve_route, "relay_send_via_serve", _refuse)
    monkeypatch.setattr(chat_turn_message, "_cmd_mission_chat_message", lambda args: ran.append(args) or 0)
    token = serve_frames._request_id.set("req-inside-serve")
    try:
        args = _parse()
        assert args.func(args) == 0
    finally:
        serve_frames._request_id.reset(token)
    assert len(ran) == 1


def test_in_process_flag_never_dials(monkeypatch):
    def _refuse(args, **_kwargs):
        raise AssertionError("--in-process dialled the serve")

    ran: list[object] = []
    monkeypatch.setattr(chat_serve_route, "relay_send_via_serve", _refuse)
    monkeypatch.setattr(chat_turn_message, "_cmd_mission_chat_message", lambda args: ran.append(args) or 0)
    args = _parse("--in-process")
    assert args.in_process is True
    assert args.func(args) == 0
    assert len(ran) == 1


def test_every_send_option_reaches_the_serve_and_round_trips():
    parser = _parser()
    full = parser.parse_args(
        [
            "harness", "mission-chat", "message",
            "--persona", "qa", "--persona-instance-id", "personainst_qa_1",
            "--session-id", "s-1", "--new-session", "--clarify-token", "ct",
            "--title", "T", "--message=-h looks like a flag", "--provider", "p",
            "--model", "m", "--surface-prompt", "sp", "--agents-file", "/x/AGENTS.md",
            "--intent-hint", "ask", "--requested-by", "claude", "--client-message-id", "c-1",
            "--idempotency-key", "ik", "--stream", "--max-seconds", "12.5",
            "--compression-threshold-tokens", "100", "--compression-protect-first-n", "2",
            "--compression-protect-last-n", "3", "--relay-chain", "a,b",
            "--relay-deadline-epoch", "1000.5", "--requested-by-session", "rs",
            "--defer-thread-policy", "--json", "--use-agent-default",
        ]
    )
    known = {dest for dest, _flag, _kind in chat_serve_route.SEND_FLAGS}
    unaccounted = set(vars(full)) - known - chat_serve_route.NOT_FORWARDED
    assert not unaccounted, f"mission-chat message options the serve is never told: {unaccounted}"

    reparsed = parser.parse_args(chat_serve_route.send_argv(full))
    for dest in known:
        assert getattr(reparsed, dest) == getattr(full, dest), dest
    assert reparsed.in_process is False


def test_the_detached_dispatch_child_runs_its_own_turn():
    import sys

    from tools.agent_chat_dispatch.child import build_dispatch_argv

    argv = build_dispatch_argv(
        {"persona_id": "qa", "message": "m", "max_seconds": 60.0}, deadline_epoch=1.0
    )
    assert argv[0] == sys.executable
    parsed = _parser().parse_args(argv[3:])
    assert parsed.in_process is True


@pytest.fixture(autouse=True)
def _isolated(isolate_agent_runtime_root):
    return isolate_agent_runtime_root
