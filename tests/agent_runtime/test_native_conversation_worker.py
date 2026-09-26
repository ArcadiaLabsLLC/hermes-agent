"""Real selected-interpreter child, native protocol, and profile-local skill reader."""
from pathlib import Path

import pytest

from agent_runtime.conversations.worker import start_worker

pytestmark = pytest.mark.timeout(120)


def test_actual_native_worker_boot_and_profile_local_catalog(tmp_path, monkeypatch):
    home = tmp_path / "isolated-profile"
    skill = home / "skills" / "private-review" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text('---\nname: private-review\ndescription: Isolated review\n---\nReview this carefully.\n', encoding="utf-8")
    # No credentialed provider or configured MCP server is available in this profile.
    (home / "config.yaml").write_text('model:\n  default: test-model\n  provider: custom\n  base_url: http://127.0.0.1:1/v1\n', encoding="utf-8")
    events = []
    peer = start_worker(home, receive=events.append, lost=lambda: None)
    try:
        assert peer.alive
        reply = peer.call("session.create", {"cwd": str(tmp_path), "source": "eternia_intelligence"})
        session = reply["session_id"]
        assert reply["stored_session_id"]
        result = peer.call("eternia.skills.list", {"session_id": session})
        assert any(row["id"] == "private-review" for row in result["data"]["skills"])
        detail = peer.call("eternia.skills.detail", {"session_id": session, "skill_id": "private-review"})
        assert "Review this carefully." in str(detail["data"])
        assert Path(reply["info"]["cwd"]) == tmp_path
    finally:
        peer.close()
    assert not peer.execution_possible
