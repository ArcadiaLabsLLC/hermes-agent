"""Constructing an agent under tests/agent never reaches the live model catalog.

Pins ``tests._downstream.agent_conftest._model_catalog_is_offline``. The control sits
where the catalog's transport actually runs: ``agent.model_metadata_http`` builds an
``httpx.Client`` and every request it sends passes ``httpx.HTTPTransport.handle_request``
(measured 2026-10-13: the ``openrouter-prewarm`` thread fetched the catalog with HTTP 200
while ``socket.create_connection`` and ``socket.socket.connect`` patches saw nothing, so a
socket-level control proves nothing here). Killing mutation: delete the fixture; both tests
red on ``attempted == []`` while ``fetch_model_metadata`` still answers (its own except).
"""

from __future__ import annotations

import threading
from unittest.mock import patch

import httpx
import pytest


@pytest.fixture
def _transport_attempts(monkeypatch):
    attempted: list[str] = []

    def _refuse(self, request):
        attempted.append(str(request.url))
        raise httpx.ConnectError("tests/agent reached the live transport", request=request)

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", _refuse)
    return attempted


def test_fetch_model_metadata_answers_without_the_transport(_transport_attempts):
    from agent import model_metadata

    assert model_metadata.fetch_model_metadata(force_refresh=True) == {}
    assert _transport_attempts == []


def test_an_openrouter_agent_prewarms_without_the_transport(_transport_attempts, tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    import run_agent as run_agent_module
    from agent import model_metadata
    from hermes_state import SessionDB
    from run_agent import AIAgent

    monkeypatch.setattr(model_metadata, "_model_metadata_cache", {})
    run_agent_module._openrouter_prewarm_done.clear()
    with patch.dict("os.environ", {"OPENROUTER_API_KEY": "test-key"}):
        agent = AIAgent(
            api_key="test-key", base_url="https://openrouter.ai/api/v1", model="test/model",
            quiet_mode=True, session_db=SessionDB(db_path=tmp_path / "state.db"),
            session_id="offline-catalog", platform="telegram",
            skip_context_files=True, skip_memory=True,
        )
    for thread in threading.enumerate():
        if thread.name == "openrouter-prewarm":
            thread.join(timeout=5)
    assert agent is not None
    assert model_metadata.fetch_model_metadata() == {}
    assert _transport_attempts == []
