"""w1-sendprep: a chat turn hashes its native revision from the lineage it already read.

``TurnCommit._build_context`` reads the root's tip and its ancestor-inclusive history once
(timed as ``context_native_history_ms``). It used to compute ``native_revision_before``
through ``_persona_chat_native_revision``, which resolves the tip and reads the whole
lineage a second time, untimed, inside ``context_built``. On the Dev persona the first read
is 17–29 ms per warm turn and grows with the transcript; the second cost the same again.

It also hashed ``safe_native_history`` of that lineage a second time, although the fed
history is exactly that list whenever the journal's abandoned filter drops nothing.

*Killing mutations:* restore ``_persona_chat_native_revision(session_db, session_id)`` in
``_build_context`` -> lineage reads 1 -> 2, red; drop the ``safe_history=`` hand-off ->
``safe_native_history`` passes 1 -> 2 on the unfiltered case, red.
"""

from __future__ import annotations

import types

import pytest

from agent_runtime.persona_chat_continuity.wire import (
    native_history_revision,
    native_history_revision_of,
)
from agent_runtime.persona_chat_session import (
    _persona_chat_native_revision,
    _persona_chat_native_revision_of_read,
)

ROOT = "persona_chat_personainst_dev_agent_root"
TIP = "persona_chat_personainst_dev_agent_root_child"

HISTORY = [
    {"role": "user", "content": "first", "client_message_id": "c1", "platform_message_id": "c1"},
    {"role": "assistant", "content": "reply", "client_message_id": "c1:assistant:0"},
    # a byte-identical duplicate of one logical row, as a compression child folds it
    {"role": "user", "content": "first", "client_message_id": "c1", "platform_message_id": "c1"},
    {"role": "user", "content": "gone", "client_message_id": "c2", "abandoned": True},
    {"role": "user", "content": "second", "client_message_id": "c3", "platform_message_id": "c3"},
    {"role": "tool", "content": "{}", "tool_call_id": "t1"},
]


class _CountingSessionDB:
    def __init__(self, history):
        self._history = history
        self.lineage_reads = 0
        self.tip_resolves = 0

    def resolve_resume_session_id(self, root):
        self.tip_resolves += 1
        return TIP if root == ROOT else root

    def get_messages_as_conversation(self, session_id, include_ancestors=False, repair_alternation=False):
        assert session_id == TIP and include_ancestors
        self.lineage_reads += 1
        return [dict(row) for row in self._history]

    def get_session(self, session_id):
        return {}


def test_revision_of_a_read_equals_the_fresh_read_revision():
    db = _CountingSessionDB(HISTORY)
    fresh = native_history_revision(db, ROOT)
    assert native_history_revision_of(TIP, db.get_messages_as_conversation(TIP, True)) == fresh
    assert native_history_revision_of(TIP, None) == native_history_revision(_CountingSessionDB([]), ROOT)


def test_session_helper_hashes_the_read_without_reading_again():
    db = _CountingSessionDB(HISTORY)
    expected = _persona_chat_native_revision(_CountingSessionDB(HISTORY), ROOT)
    history = db.get_messages_as_conversation(TIP, include_ancestors=True)
    reads = db.lineage_reads
    assert _persona_chat_native_revision_of_read(db, ROOT, TIP, history) == expected
    assert db.lineage_reads == reads and db.tip_resolves == 0


def test_a_store_without_the_native_readers_takes_the_fresh_read_path():
    legacy = types.SimpleNamespace(get_messages=lambda session_id: [dict(row) for row in HISTORY])
    assert _persona_chat_native_revision_of_read(legacy, ROOT, ROOT, list(HISTORY)) == (
        _persona_chat_native_revision(legacy, ROOT)
    )


@pytest.mark.parametrize(
    ("journal_abandoned", "fed", "safe_passes"),
    [
        (set(), ["first", "reply", "second"], 1),
        # a journal-abandoned row leaves the fed history but never the revision
        ({"c3"}, ["first", "reply"], 2),
    ],
)
def test_build_context_reads_the_lineage_once_and_keeps_the_revision(
    monkeypatch, journal_abandoned, fed, safe_passes
):
    import agent_runtime.mission_chat_turn_context as turn_context_module
    from agent_runtime.persona_chat_continuity import wire as wire_module
    from hermes_cli.harness_parts.persona.chat_turn_commit import run as run_module

    monkeypatch.setattr(run_module, "abandoned_mission_chat_message_ids", lambda session_id: journal_abandoned)
    monkeypatch.setattr(run_module, "is_abandoned_mission_chat_message", lambda pid, ids: pid in ids)
    monkeypatch.setattr(run_module, "persona_chat_runtime_registry", lambda: None)
    monkeypatch.setattr(run_module, "_resolve_relay_sender_marker", lambda *a, **k: None)
    monkeypatch.setattr(run_module, "_session_model_config", lambda db, sid: {})
    monkeypatch.setattr(run_module, "resolve_mission_chat_max_seconds", lambda value: 240)
    expected = native_history_revision(_CountingSessionDB(HISTORY), ROOT)
    passes = []
    real_safe = wire_module.safe_native_history

    def _counting_safe(messages):
        passes.append(len(messages))
        return real_safe(messages)

    monkeypatch.setattr(run_module, "safe_native_history", _counting_safe)
    monkeypatch.setattr(wire_module, "safe_native_history", _counting_safe)
    built = {}

    def _fake_builder(**kwargs):
        built.update(kwargs)
        return types.SimpleNamespace()

    monkeypatch.setattr(turn_context_module, "build_mission_chat_turn_context", _fake_builder)

    marks = []
    db = _CountingSessionDB(HISTORY)
    commit = types.SimpleNamespace(
        args=types.SimpleNamespace(),
        session_db=db,
        session_id=ROOT,
        pre_admit_timings={},
        instance_store=None,
        relay_chain_in=None,
        persona=None,
        instance=None,
        cfg=None,
        model_selection={},
        relay_deadline=None,
        turn_relay_chain=(),
        message="hello",
        turn_phases=types.SimpleNamespace(mark=marks.append),
    )

    run_module._RunPhases._build_context(commit)

    assert db.lineage_reads == 1 and db.tip_resolves == 1
    assert len(passes) == safe_passes
    assert commit.native_revision_before == expected
    assert commit.active_session_id == TIP
    assert [row.get("content") for row in built["native_history"]] == fed
    assert "context_native_history_ms" in commit.pre_admit_timings
    assert marks == ["context_built"]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
