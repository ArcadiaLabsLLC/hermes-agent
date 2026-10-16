"""CLI-to-serve route S3: ``harness serve settles rearm`` is a write the live serve does.

Plan: ``docs/agent-runtime-harness/archive/cli-serve-route-2026-10-15.md`` S3. With a live
serve the parsed verb hands ``serve settles rearm <ref>`` to it and never touches
the store itself; with no serve it re-arms locally; a live serve that fails the request
is a non-zero exit and still no local write.

Kill-mutation: delete the ``_relay_rearm`` hand-off in ``_cmd_serve_settles_rearm`` (call
``rearm_settle`` directly while a serve is live). The serve then receives nothing and
the local store write runs, and the first case reds.
"""

from __future__ import annotations

import argparse

import pytest

from agent_runtime.serve_socket import cli_route
from tests.agent_runtime.test_serve_socket_lane import running_serve


def _parse(*extra: str) -> argparse.Namespace:
    from hermes_cli.harness import build_parser

    parser = argparse.ArgumentParser()
    build_parser(parser.add_subparsers(dest="command"))
    return parser.parse_args(["harness", "serve", "settles", "rearm", "settle_abc", *extra])


@pytest.fixture
def local_writes(monkeypatch):
    calls: list[str] = []

    def rearm_settle(settle_id):
        from agent_runtime.chat_turn_settles import RearmResult

        calls.append(settle_id)
        return RearmResult.NOT_FOUND, None

    monkeypatch.setattr("agent_runtime.chat_turn_settles.rearm_settle", rearm_settle)
    monkeypatch.setattr("agent_runtime.chat_turn_settles.resolve_settle_ref",
                        lambda ref, session_id=None: ref)
    monkeypatch.setattr(cli_route, "_this_pid", lambda: -1)
    return calls


def test_with_a_live_serve_the_rearm_is_the_serves_write(local_writes):
    seen: list[list[str]] = []

    def dispatch(argv):
        seen.append(list(argv))
        print('{"ok": true, "answered_by": {"lane": "serve"}}')
        return 0

    args = _parse("--json")
    with running_serve(dispatch=dispatch):
        assert args.func(args) == 0
    assert seen == [["harness", "serve", "settles", "rearm", "settle_abc", "--json"]]
    assert local_writes == [], "the re-arm also ran in the asking process"


def test_with_no_live_serve_the_rearm_runs_here(local_writes):
    """Positive control: the write rule's one local arm."""

    args = _parse("--json")
    assert args.func(args) == 2  # NOT_FOUND from the stubbed store
    assert local_writes == ["settle_abc"]


def test_a_live_serve_that_fails_the_rearm_is_an_error_not_a_local_write(local_writes):
    def failing(argv):
        raise SystemExit(2)

    args = _parse()
    with running_serve(dispatch=failing):
        assert args.func(args) == 1
    # (The refusal JSON goes to stdout, which the in-thread serve under test owns.)
    assert local_writes == []


def test_inside_a_serve_request_the_rearm_never_dials(local_writes, monkeypatch):
    from hermes_cli.harness_parts.serve import frames as serve_frames

    monkeypatch.setattr(cli_route, "relay_argv", lambda *a, **k: pytest.fail("the serve's own re-arm dialled the serve"))
    token = serve_frames._request_id.set("req-inside-serve")
    try:
        args = _parse()
        assert args.func(args) == 2
    finally:
        serve_frames._request_id.reset(token)
    assert local_writes == ["settle_abc"]
