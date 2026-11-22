"""Old hidden copies that only hold saved chats are cleaned up, and their chats stay with the agent.

Row ``RT-OLD-HIDDEN-COPIES-THAT-ONLY-HOLD-SAVED-CHATS-ARE-CLEANED-UP-AND-THEIR-CHATS-STAY-WITH-THE-AGENT``
(owner RULED 2026-11-21, "Yes, that's it"): an adopted copy whose only content is saved chats from before
its adoption is retired through retire's archive; its chats stay in the agent's Chat history
(``holder_retired``); a copy in live use stays an ordinary placed agent; nothing is deleted, the
persona's profile and memory are untouched, and a second run does nothing.
"""

from __future__ import annotations

import json
from datetime import timedelta

import pytest

from agent_runtime import paths
from agent_runtime.default_scope import DEFAULT_WORKSPACE_ID, ensure_default_scope
from agent_runtime.models import PersonaInstance
from agent_runtime.persona_assignments import PersonaInstanceStore, persona_instance_id_for
from agent_runtime.persona_instance_identity import reconcile_persona_instances
from agent_runtime.serde import to_jsonable
from agent_runtime.states import WorkerSessionState
from hermes_time import now

pytestmark = pytest.mark.usefixtures("isolate_agent_runtime_root", "persisted_persona_samples")

TODAY = now().date()
ADOPTED_ON = (TODAY - timedelta(days=30)).isoformat()
CHAT_ONLY = persona_instance_id_for("dev")
IN_USE = persona_instance_id_for("qa")
RECENT = persona_instance_id_for("backend_dev")
SAVED = f"persona_chat_{CHAT_ONLY}_0123456789ab"


def _adopted(instance_id: str, persona_id: str, *, stamp: str = ADOPTED_ON, **fields) -> None:
    """A hidden copy the adoption placed in the Default workspace, stamped ``stamp``."""
    row = PersonaInstance(
        id=instance_id, persona_id=persona_id, role=persona_id, display_name=persona_id, profile_id=None,
        runtime_root=str(paths.store_root()), state=WorkerSessionState.IDLE, mode="configured",
        workspace_id=DEFAULT_WORKSPACE_ID, adopted_from_global=stamp, **fields,
    )
    path = paths.persona_instance_path(instance_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(to_jsonable(row), indent=2, sort_keys=True), encoding="utf-8")


def _saved_chat(session_id: str) -> None:
    from agent_runtime.persona_chat_continuity import PERSONA_CHAT_SESSION_SOURCE
    from tests.agent_runtime.test_persona_chat_move import _db

    db = _db(session_id)
    db.create_session(session_id, PERSONA_CHAT_SESSION_SOURCE)
    db.append_message(session_id, "user", "said to the hidden copy before it was adopted")


def _fates(report: list[dict]) -> dict[str, tuple]:
    return {item["persona_instance_id"]: (item["fate"], item.get("reason")) for item in report}


@pytest.fixture
def adopted_copies(monkeypatch):
    """Three adopted copies: one holding only an old saved chat, one with a goal, one chatted with lately."""
    import agent_runtime.mission_chat_turns.reads as turn_reads
    import agent_runtime.persona_instance_adoption as adoption

    monkeypatch.setattr(adoption, "_work_assignee_tokens", lambda: frozenset())
    old_start = (TODAY - timedelta(days=40)).isoformat()  # every seeded chat started long ago
    monkeypatch.setattr(adoption, "_chat_start_dates", lambda ids: dict.fromkeys(ids, old_start))
    monkeypatch.setattr(turn_reads, "last_turn_started_by_instance",
                        lambda: {CHAT_ONLY: f"{TODAY - timedelta(days=40)}T09:00:00.000000Z",
                                 RECENT: f"{TODAY - timedelta(days=3)}T09:00:00.000000Z"})
    ensure_default_scope(seed_active_pointers=False)
    _adopted(CHAT_ONLY, "dev", default_chat_session_id=SAVED)
    _saved_chat(SAVED)
    _adopted(IN_USE, "qa", default_chat_session_id=f"persona_chat_{IN_USE}_00000000000a", goal_id="goal_1")
    # Adopted by today's boot: its last turn predates the stamp, and is still recent.
    _adopted(RECENT, "backend_dev", stamp=TODAY.isoformat(),
             default_chat_session_id=f"persona_chat_{RECENT}_00000000000b")


def test_the_dry_run_names_each_adopted_copy_and_its_fate_and_writes_nothing(adopted_copies):
    census = reconcile_persona_instances(apply=False)
    assert _fates(census["cleanup"]) == {
        CHAT_ONLY: ("would_retire", None),
        IN_USE: ("kept", "in_use"),
        RECENT: ("kept", "recently_used"),
    }
    assert census["chat_only_copies_retired_count"] == 1
    assert paths.persona_instance_path(CHAT_ONLY).exists()


def test_a_chat_only_copy_is_retired_and_its_chats_stay_listed(adopted_copies):
    """Kill-mutation: skip the retire in ``clean_up_chat_only_copies`` → the copy is still live, red."""
    from agent_runtime.persona_chat_history import persona_chat_history_summary
    from hermes_cli.profiles import get_profile_dir

    memory = get_profile_dir("gpt-launcher") / "memories" / "MEMORY.md"
    memory.parent.mkdir(parents=True, exist_ok=True)
    memory.write_text("The owner likes short read-outs.", encoding="utf-8")

    applied = reconcile_persona_instances(apply=True)

    assert _fates(applied["cleanup"])[CHAT_ONLY] == ("retired", None)
    live = {row.id for row in PersonaInstanceStore().list_all()}
    assert CHAT_ONLY not in live and {IN_USE, RECENT} <= live
    assert list(paths.persona_instances_archive_dir().rglob(f"{CHAT_ONLY}.json"))  # archived, never deleted
    rows = persona_chat_history_summary(persona_instances=PersonaInstanceStore().list_all())
    row = next(item for item in rows if item["session_id"] == SAVED)
    assert (row["persona_id"], row["persona_instance_id"], row["holder_retired"]) == ("dev", CHAT_ONLY, True)
    assert memory.read_text(encoding="utf-8") == "The owner likes short read-outs."  # the agent's, untouched

    again = reconcile_persona_instances(apply=True)
    assert CHAT_ONLY not in _fates(again["cleanup"])
    assert again["chat_only_copies_retired_count"] == 0


def test_a_copy_chatted_with_recently_is_kept(adopted_copies):
    """Its last turn is before the adoption stamp but within the last two weeks: in use, kept. Kill-mutation:
    drop the recent-use test in ``clean_up_chat_only_copies`` → retired, red."""
    applied = reconcile_persona_instances(apply=True)
    assert _fates(applied["cleanup"])[RECENT] == ("kept", "recently_used")
    assert PersonaInstanceStore().get(RECENT).workspace_id == DEFAULT_WORKSPACE_ID


def test_a_copy_whose_chat_was_opened_today_is_kept(monkeypatch):
    """An operator chat opened on the copy today, no turn yet: in use. Kill-mutation: drop the chat-start
    test in ``clean_up_chat_only_copies`` → retired, red."""
    import agent_runtime.mission_chat_turns.reads as turn_reads
    import agent_runtime.persona_instance_adoption as adoption

    monkeypatch.setattr(adoption, "_work_assignee_tokens", lambda: frozenset())
    monkeypatch.setattr(turn_reads, "last_turn_started_by_instance", lambda: {})
    ensure_default_scope(seed_active_pointers=False)
    _adopted(CHAT_ONLY, "dev", default_chat_session_id=SAVED)
    _saved_chat(SAVED)  # started now, through the real chat store
    applied = reconcile_persona_instances(apply=True)
    assert _fates(applied["cleanup"])[CHAT_ONLY] == ("kept", "recently_used")

