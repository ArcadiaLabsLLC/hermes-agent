"""The written description of a chat turn says what the code does (RT-CHAT-TURN-NOTES-CONTRADICT-THE-CODE).

Two notes had drifted: ``persona_runtime.py`` said the Mission Control caller passes ``session_id=None``
with the transcript "baked into the message", while ``chat_turn_commit/run.py`` passes the chat's native
tip and the transcript as structured ``conversation_history``; and the canon doc's opening sentence had
two ``###`` sections spliced into the middle of it.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _text(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_the_runtime_notes_describe_the_session_id_and_history_the_caller_passes():
    """Killing mutation: restore "passes ``session_id=None``" / "baked into the message" in either file -> red."""

    caller = _text("hermes_cli/harness_parts/persona/chat_turn_commit/run.py")
    assert "session_id=self.active_session_id," in caller and "conversation_history=self.native_history," in caller
    for relative in ("agent_runtime/persona_runtime.py", "agent_runtime/profile_runner/models.py"):
        notes = _text(relative)
        assert "session_id=None" not in notes, relative
        assert "baked into the" not in notes and "baked in by" not in notes, relative


def test_the_canon_docs_opening_sentence_is_whole():
    """Killing mutation: move a ``###`` section back between "sits under" and "## Open rows" -> red."""

    doc = _text("docs/agent-runtime-harness/05-chat-turn-lane.md")
    assert "sits under `## Open rows`, `## Unverified carry-forward`, or is gone." in doc
    opening = doc.split("\n## ", 1)[0]
    assert "\n### " not in opening
    # The two sections the splice carried are still in the doc, once each.
    assert doc.count("### Durable provider-refusal transcript marker") == 1
    assert doc.count("### Known setup refusal before provider dispatch") == 1
