"""RT-PROVIDER-REQUEST-START (ruled 2026-10-21): "nothing left" is read off a per-attempt hooked fact.

The real hook (``install_transport_phase_trace``) on a real httpx client: a refused connection
is proven unsent, a request a local server received is sent, an unhooked attempt stays
ambiguous; and the classifier settles the not-submitted kind only on that proof.
"""

from __future__ import annotations

import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

import httpx
import pytest

from agent_runtime.mission_chat_outcome import (
    ChatErrorKind,
    ExecutionState,
    PROVIDER_UNAVAILABLE_REASON,
    classify_turn_failure,
)
from agent_runtime.transport_dispatch_evidence import (
    AttemptFact,
    TransportAttempts,
    begin_turn_attempts,
    open_attempt,
)
from agent_runtime.transport_phase_trace import install_transport_phase_trace


class _Ok(BaseHTTPRequestHandler):
    def do_POST(self) -> None:  # noqa: N802 - stdlib name
        self.rfile.read(int(self.headers.get("Content-Length") or 0))
        self.send_response(200)
        self.send_header("Content-Length", "2")
        self.end_headers()
        self.wfile.write(b"{}")

    def log_message(self, *args) -> None:
        return


@pytest.fixture()
def local_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Ok)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}/v1/chat"
    finally:
        server.shutdown()
        server.server_close()


def _refused_url() -> str:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    return f"http://127.0.0.1:{port}/v1/chat"  # bound then closed: nothing listens


def _turn():
    agent = SimpleNamespace()
    return agent, begin_turn_attempts(agent)


def _attempt(agent, url: str, *, hooked: bool = True) -> None:
    open_attempt(agent)
    sdk_client = SimpleNamespace(_client=httpx.Client(timeout=5))
    if hooked:
        install_transport_phase_trace(agent, sdk_client)
    try:
        sdk_client._client.post(url, content=b'{"model":"m"}')
    except httpx.HTTPError:
        pass
    finally:
        sdk_client._client.close()


def test_a_refused_connection_on_a_hooked_transport_is_proven_unsent():
    agent, ledger = _turn()
    _attempt(agent, _refused_url())
    assert ledger.proven_unsent() is True


def test_a_request_the_server_received_is_never_unsent(local_server):
    agent, ledger = _turn()
    _attempt(agent, local_server)
    assert ledger.proven_unsent() is False


def test_one_sent_attempt_on_a_retry_ladder_keeps_the_turn_sent(local_server):
    agent, ledger = _turn()
    _attempt(agent, local_server)
    _attempt(agent, _refused_url())
    assert ledger.proven_unsent() is False


def test_an_unhooked_attempt_stays_ambiguous_though_nothing_marked_sent():
    """The Bedrock / Codex app-server shape: no hook, so no ``request_sent`` can ever fire."""

    agent, ledger = _turn()
    _attempt(agent, _refused_url(), hooked=False)
    assert ledger.proven_unsent() is False
    agent, ledger = _turn()
    _attempt(agent, _refused_url())
    _attempt(agent, _refused_url(), hooked=False)
    assert ledger.proven_unsent() is False


def test_no_attempt_and_a_hooked_but_untraced_attempt_prove_nothing():
    assert TransportAttempts().proven_unsent() is False
    ledger = TransportAttempts()
    ledger.open()
    ledger.note(AttemptFact.HOOKED)
    assert ledger.proven_unsent() is False


def test_a_new_turn_on_a_resident_agent_starts_a_fresh_ledger():
    agent, first = _turn()
    _attempt(agent, _refused_url())
    second = begin_turn_attempts(agent)
    assert first.proven_unsent() is True and second.proven_unsent() is False


def test_the_classifier_settles_not_submitted_only_on_the_proof():
    exc = RuntimeError("connection refused")
    proven = classify_turn_failure(exc, provider_submitted=True, request_dispatched=False, request_unsent=True)
    assert (proven.execution_state, proven.error_kind) == (
        ExecutionState.FAILED, ChatErrorKind.CHAT_TURN_NOT_SUBMITTED)
    # Terminal in the journal (the refusal arm), hermes-authored, no turn-resolve.
    assert proven.provider_refusal is not None
    assert proven.provider_refusal.reason == PROVIDER_UNAVAILABLE_REASON

    absent_only = classify_turn_failure(exc, provider_submitted=True, request_dispatched=False)
    assert absent_only.error_kind is ChatErrorKind.CHAT_TURN_OUTCOME_UNKNOWN

    sent_wins = classify_turn_failure(exc, provider_submitted=True, request_dispatched=True, request_unsent=True)
    assert sent_wins.error_kind is ChatErrorKind.CHAT_TURN_OUTCOME_UNKNOWN
