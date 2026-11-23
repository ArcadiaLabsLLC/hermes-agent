"""A chat's stored rows are scrubbed, parsed and journal-read once, not again on every read.

RT-FU-EVERY-NEKO-REPLY-RE-READS-THE-WHOLE-LIVE-CHAT-BEFORE-ETERNIA-SHOWS-IT: a chat opened in
Eternia is read through ``runtime.persona.chat.history``, which curates the whole chat; on the
owner's Neko chat (878 rows, 2026-11-23) that read took 4.8 s, 1.9 s of it the secret scrubber
over rows it had scrubbed on the read before, and 1.8 s re-parsing the turn journal once per
turn with no record. Measured on a copy: 0.6 s once the chat has been read.
"""

from __future__ import annotations

from agent.redact import clear_vault_redaction_values, register_vault_redaction_value
from agent_runtime import redaction
from agent_runtime.mission_chat_turns import persist_mission_chat_turn, reads
from agent_runtime.persona_chat_history import operator_envelopes
from agent_runtime.persona_chat_history.curation import CurationState
from agent_runtime.runtime_hud.envelopes import render_runtime_context_envelope

_KEY = "ghp_" + "Ab3" * 12


def test_a_stored_rows_text_is_scrubbed_once_across_reads(monkeypatch):
    """MUTATION (red recorded 2026-11-23): return ``_redact_upstream(text)`` from
    ``mask_known_key_shapes`` -> two scrubs, not one."""

    redaction._MASK_MEMO.clear()
    scrubbed: list[str] = []
    real = redaction._redact_upstream

    def counting(text):
        scrubbed.append(text)
        return real(text)

    monkeypatch.setattr(redaction, "_redact_upstream", counting)
    text = f"Pushed with {_KEY} today."

    first = redaction.mask_known_key_shapes(text)
    second = redaction.mask_known_key_shapes(text)

    assert first == second
    assert _KEY not in second and "«redacted:ghp_…»" in second
    assert scrubbed == [text]


def test_a_vault_value_registered_after_the_first_scrub_is_hidden_on_the_next():
    """MUTATION (red recorded 2026-11-23): return the kept answer unpassed in
    ``_MaskMemo.mask`` -> the vault value shows on the second read."""

    redaction._MASK_MEMO.clear()
    secret = "correct-horse-battery-staple"
    text = f"The vault answer is {secret}."
    try:
        assert secret in redaction.mask_known_key_shapes(text)
        register_vault_redaction_value(secret)
        assert secret not in redaction.mask_known_key_shapes(text)
    finally:
        clear_vault_redaction_values()


def test_an_operator_rows_envelopes_are_parsed_once_and_each_reader_gets_its_own_copy(monkeypatch):
    """MUTATION (red recorded 2026-11-23): drop ``functools.lru_cache`` from
    ``operator_envelopes._stripped`` -> two parses, not one."""

    getattr(operator_envelopes._stripped, "cache_clear", lambda: None)()
    parsed: list[str] = []
    real = operator_envelopes.extract_runtime_context_envelope

    def counting(text):
        parsed.append(text)
        return real(text)

    monkeypatch.setattr(operator_envelopes, "extract_runtime_context_envelope", counting)
    row = "Ship it.\n\n" + render_runtime_context_envelope(
        context_id="ctx_1", revision="hud_0123456789abcdef", delivery="unchanged",
        situational_hud_content=None)

    first = operator_envelopes.strip_operator_envelopes(row)
    second = operator_envelopes.strip_operator_envelopes(row)

    assert first[0] == second[0] == "Ship it."
    assert first[1] == second[1] and first[1] is not None
    assert first[1] is not second[1]
    assert len(parsed) == 1


def test_turns_with_no_record_read_the_chats_journal_once(isolate_agent_runtime_root, monkeypatch):
    """MUTATION (red recorded 2026-11-23): call ``mission_chat_turn_elements`` per turn in
    ``CurationState.turn_elements_for`` -> one journal read per turn."""

    for turn in (1, 2, 3):
        persist_mission_chat_turn(
            session_id="s1", client_message_id=f"client_{turn}", turn_id=f"turn_{turn}",
            elements=[{"kind": "segment", "id": f"seg_{turn}", "turn_id": f"turn_{turn}", "seq": 1,
                       "seg_type": "answer", "text": f"Answer {turn}."}],
        )
    expected = [reads.mission_chat_turn_elements(session_id="s1", client_message_id=f"client_{turn}")
                for turn in (1, 2, 3)]
    calls: list[str] = []
    real = reads._read_session

    def counting(session_key):
        calls.append(session_key)
        return real(session_key)

    monkeypatch.setattr(reads, "_read_session", counting)
    # No records in hand: every turn falls through to the journal.
    state = CurationState(session_id="s1", turn_records=[], turn_records_by_message={})

    got = [state.turn_elements_for(f"client_{turn}") for turn in (1, 2, 3)]

    assert got == expected and all(got)
    assert calls == ["s1"]
