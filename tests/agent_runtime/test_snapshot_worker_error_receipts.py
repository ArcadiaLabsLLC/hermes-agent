import json
import logging
import pytest
from agent_runtime.snapshot_worker.child import SnapshotBuildFailed, handle_build, _reply_frame


def test_failed_build_preserves_receipts_and_redaction_safe_stack(monkeypatch):
    import agent_runtime.snapshot.build as build
    def fail():
        logging.getLogger("agent_runtime.probe").warning("build_phase before_failure")
        raise ValueError("private_token=must-never-cross-wire")
    monkeypatch.setattr(build, "_build_snapshot_uncoalesced", fail)
    with pytest.raises(SnapshotBuildFailed) as caught:
        handle_build({})
    diagnostics = caught.value.diagnostics
    assert diagnostics["error_type"] == "ValueError"
    assert any(":fail:" in frame for frame in diagnostics["frames"])
    assert any(row["message"] == "build_phase before_failure" for row in diagnostics["receipts"])
    wire = _reply_frame("request", code=5000, message="SnapshotBuildFailed", data=diagnostics)
    assert b"must-never-cross-wire" not in wire
    assert json.loads(wire)["error"]["data"] == diagnostics
