"""Fork-owned half of ``tests/agent/test_compression_feasibility.py``.

The fork's ``local-llama-hermes`` same-model aux floor exemption
(``agent.conversation_compression``). Upstream's autouse
``_stable_aux_provider_config`` and ``_make_agent`` are imported by name.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from tests.agent.test_compression_feasibility import (  # noqa: F401 — upstream names the moved tests use
    _make_agent,
    _stable_aux_provider_config,
)


@patch("agent.model_metadata.get_model_context_length", return_value=8192)
@patch("agent.auxiliary_client.get_text_auxiliary_client")
def test_managed_local_compression_honors_verified_small_context(mock_get_client, mock_ctx_len):
    agent = _make_agent(main_context=8192)
    agent.requested_provider = "local-llama-hermes"
    agent.provider = "custom"
    agent._emit_status = lambda msg: None
    agent.base_url = "http://127.0.0.1:49152/v1"
    client = MagicMock()
    client.base_url = agent.base_url
    mock_get_client.return_value = (client, agent.model)
    agent._check_compression_model_feasibility()
    assert agent.context_compressor.threshold_tokens == 4096
    client.base_url = "http://127.0.0.1:49153/v1"
    with pytest.raises(ValueError, match="below the minimum"):
        agent._check_compression_model_feasibility()
    mock_get_client.return_value = (MagicMock(), "different-auxiliary-model")
    with pytest.raises(ValueError, match="below the minimum"):
        agent._check_compression_model_feasibility()
