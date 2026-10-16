"""The work RPC preserves the dispatch owner's cancellation verdict."""

from types import SimpleNamespace

import pytest

from agent_runtime import serve_rpc
from agent_runtime.running_work import surface


@pytest.mark.parametrize("outcome", [
    "stopping", "cancelled", "cancel_requested", "already_finished", "not_running",
    "not_owned_here", "peer_unreachable",
])
def test_dispatch_cancellation_reaches_rpc_with_its_native_outcome(monkeypatch, outcome):
    row = {"work_id": "dispatch:job", "kind": "dispatch",
           "started_at": "2026-10-14T00:00:00Z"}
    monkeypatch.setattr(surface, "build_running_work", lambda: {"rows": [row]})
    calls = []

    def request_cancel(job_id, *, reason):
        calls.append((job_id, reason))
        return {"outcome": outcome, "state": "fixture-state", "poll_seconds": 1}

    monkeypatch.setattr(surface, "_module", lambda name: SimpleNamespace(request_cancel=request_cancel))
    response = serve_rpc.handle_request({
        "jsonrpc": "2.0", "id": "cancel", "method": "runtime.work.cancel",
        "params": {"work_id": "dispatch:job", "reason": "operator_cancel",
                   "issued_at": "2026-10-14T00:00:01Z"},
    })
    assert calls == [("job", "operator_cancel")]
    if outcome in {"not_owned_here", "peer_unreachable"}:
        assert response["error"]["data"]["reason"] == outcome
        assert "result" not in response
    else:
        assert "error" not in response
        result = response["result"]
        assert result["outcome"] == outcome
        assert result["state"] == "fixture-state"
        assert result["work_id"] == "dispatch:job"
        assert result["status"] == "ok"
