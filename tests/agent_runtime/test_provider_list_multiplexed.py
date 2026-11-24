"""``runtime.provider.*`` on a serve that multiplexes (RT-FU-A-MULTIPLEXED-SERVE-ANSWERS-YOUR-PROVIDER-LIST).

Live 2026-11-23 on the owner's account serve: once the serve hosted a turn on another profile's store
it multiplexed, every unscoped ``get_secret`` raised ``UnscopedSecretError``, and ``runtime.provider.list``
answered ``handler_failed`` with nothing in errors.log, so Eternia's Connections listed no provider and
the console's Provider tile opened nothing. Each test names its killing mutation.
"""

from __future__ import annotations

import logging

from agent.secret_scope import reset_multiplex_context, set_multiplex_context
from agent_runtime.serve_rpc.dispatch import handle_request


def _list() -> dict:
    return handle_request({"jsonrpc": "2.0", "id": 1, "method": "runtime.provider.list", "params": {}})


def test_provider_list_answers_on_a_multiplexed_serve():
    """Killing mutation: call ``work()`` outside ``profile_secret_fallback`` in ``_answer`` -> the pool's
    base-URL read raises ``UnscopedSecretError`` and the frame is ``handler_failed``, red."""
    token = set_multiplex_context(True)
    try:
        frame = _list()
    finally:
        reset_multiplex_context(token)
    assert "error" not in frame, frame
    assert {row["id"] for row in frame["result"]["catalog"]} >= {"anthropic", "openai-codex"}


def test_provider_handler_failed_logs_its_traceback(monkeypatch, caplog):
    """Killing mutation: drop the ``logger.error`` in ``_failed`` -> no record, red."""
    from hermes_cli.harness_parts import provider_visibility

    detail = "-".join(["provider", "visibility", "exploded"])  # a runtime value, not source text

    def boom():
        raise RuntimeError(detail)

    monkeypatch.setattr(provider_visibility, "build_provider_visibility", boom)
    with caplog.at_level(logging.ERROR, logger="agent_runtime.serve_rpc.provider"):
        frame = _list()
    assert frame["error"]["data"]["reason"] == "handler_failed"
    assert detail not in str(frame)
    record = next(r for r in caplog.records if "provider_handler_failed" in r.getMessage())
    assert "runtime.provider.list" in record.getMessage()
    message = record.getMessage()
    assert "error_class=RuntimeError" in message and "in boom" in message
    assert detail not in caplog.text
