"""Restored rich-input rows keep the operator text and media, not injected turn context."""
import pytest

from agent_runtime.persona_chat_history.history_rows import _safe_recent_messages
from agent_runtime.runtime_hud import render_runtime_context_envelope, render_skill_preload_envelope
from tests.agent_runtime.test_persona_chat_history_curation import FakeSessionDB


@pytest.mark.parametrize("media", [
    "\n\n[Image attached at: C:\\qa\\operator_images\\photo.png]\n[screenshot]",
    "\n\n[Image attached at: /qa/photo.png]\n[Image attached at: /qa/second.png]\n[screenshot]\n[screenshot detail=high]",
    "\n\nMEDIA:/qa/photo.png",
])
def test_native_attachment_suffix_does_not_expose_envelopes(media):
    skill = render_skill_preload_envelope(skill_names=["qa-check"], skill_preload_content="private skill body")
    hud = render_runtime_context_envelope(context_id="ctx_qa", revision="hud_0123", delivery="snapshot",
                                         situational_hud_content="private runtime context")
    content = f"Read my attachment\n\n{skill}\n\n{hud}{media}"
    db = FakeSessionDB([{"role": "user", "content": content}])
    rows, status, unread = _safe_recent_messages(db, session_id="s1")
    assert status == "safe" and unread is None
    assert rows[0]["text"] == f"Read my attachment{media}"
    assert rows[0]["runtime_context"]["context_id"] == "ctx_qa"
    assert rows[0]["skill_preload"]["skills"] == ["qa-check"]
    assert db.get_messages("s1")[0]["content"] == content


def test_operator_prose_after_a_literal_envelope_stays_visible():
    hud = render_runtime_context_envelope(context_id="ctx_qa", revision="hud_0123", delivery="snapshot",
                                         situational_hud_content="quoted context")
    content = f"Explain this tag:\n\n{hud}\n\nThis is my example.\n[Image attached at: /qa/photo.png]\n[screenshot]"
    rows, _, _ = _safe_recent_messages(FakeSessionDB([{"role": "user", "content": content}]), session_id="s1")
    assert rows[0]["text"] == content
    assert "runtime_context" not in rows[0]
