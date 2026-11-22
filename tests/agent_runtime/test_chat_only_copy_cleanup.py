"""Old hidden copies that only hold saved chats are cleaned up, and their chats stay with the agent.

Row ``RT-OLD-HIDDEN-COPIES-THAT-ONLY-HOLD-SAVED-CHATS-ARE-CLEANED-UP-AND-THEIR-CHATS-STAY-WITH-THE-AGENT``
(owner RULED 2026-11-21, "Yes, that's it"): an adopted copy with no chat pointer whose only content is saved
chats in the move ledger is retired through retire's archive, and its chats stay in the agent's Chat history
(``holder_retired``); a copy whose chat pointer names its live chat is in live use
(``RT-FU-A-HIDDEN-COPY-IS-IN-LIVE-USE-WHEN-IT-HOLDS-A-LIVE-CHAT-NOT-BY-A-14-DAY-WINDOW``, no date window);
a copy in live use stays an ordinary placed agent; nothing is deleted, the
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
from agent_runtime.persona_assignments.chat_moves import record_chat_move
from agent_runtime.persona_instance_identity import reconcile_persona_instances
from agent_runtime.serde import to_jsonable
from agent_runtime.states import WorkerSessionState
from hermes_time import now

pytestmark = pytest.mark.usefixtures("isolate_agent_runtime_root", "persisted_persona_samples")

ADOPTED_ON = (now().date() - timedelta(days=30)).isoformat()
CHAT_ONLY = persona_instance_id_for("dev")
IN_USE = persona_instance_id_for("qa")
LIVE = persona_instance_id_for("backend_dev")
# Minted for another copy and moved onto this one: the move ledger lists it, the copy's pointer does not.
SAVED = f"persona_chat_{persona_instance_id_for('designer')}_0123456789ab"
LIVE_CHAT = f"persona_chat_{LIVE}_00000000000b"


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
    """Three adopted copies: one with no chat pointer holding only a saved chat in the move ledger, one with
    a goal, one whose chat pointer names its live chat (adopted by today's boot, no turn on record)."""
    import agent_runtime.persona_instance_adoption as adoption

    monkeypatch.setattr(adoption, "_work_assignee_tokens", lambda: frozenset())
    ensure_default_scope(seed_active_pointers=False)
    _adopted(CHAT_ONLY, "dev")
    _saved_chat(SAVED)
    record_chat_move(SAVED, CHAT_ONLY)
    _adopted(IN_USE, "qa", default_chat_session_id=f"persona_chat_{IN_USE}_00000000000a", goal_id="goal_1")
    _adopted(LIVE, "backend_dev", stamp=now().date().isoformat(), default_chat_session_id=LIVE_CHAT)


def test_the_dry_run_names_each_adopted_copy_and_its_fate_and_writes_nothing(adopted_copies):
    census = reconcile_persona_instances(apply=False)
    assert _fates(census["cleanup"]) == {
        CHAT_ONLY: ("would_retire", None),
        IN_USE: ("kept", "in_use"),
        LIVE: ("kept", "live_chat"),
    }
    assert census["chat_only_copies_retired_count"] == 1
    assert paths.persona_instance_path(CHAT_ONLY).exists()


def test_a_chat_only_copy_is_retired_and_its_chats_stay_listed(adopted_copies):
    """No chat pointer, only a saved chat in the move ledger: retired. Kill-mutations: skip the retire in
    ``clean_up_chat_only_copies`` → the copy is still live, red; test ``_row_chats`` (ledger chats too) in
    place of the pointer → kept as ``live_chat``, red."""
    from agent_runtime.persona_chat_history import persona_chat_history_summary
    from hermes_cli.profiles import get_profile_dir

    memory = get_profile_dir("gpt-launcher") / "memories" / "MEMORY.md"
    memory.parent.mkdir(parents=True, exist_ok=True)
    memory.write_text("The owner likes short read-outs.", encoding="utf-8")

    applied = reconcile_persona_instances(apply=True)

    assert _fates(applied["cleanup"])[CHAT_ONLY] == ("retired", None)
    live = {row.id for row in PersonaInstanceStore().list_all()}
    assert CHAT_ONLY not in live and {IN_USE, LIVE} <= live
    assert list(paths.persona_instances_archive_dir().rglob(f"{CHAT_ONLY}.json"))  # archived, never deleted
    rows = persona_chat_history_summary(persona_instances=PersonaInstanceStore().list_all())
    row = next(item for item in rows if item["session_id"] == SAVED)
    assert (row["persona_id"], row["persona_instance_id"], row["holder_retired"]) == ("dev", CHAT_ONLY, True)
    assert memory.read_text(encoding="utf-8") == "The owner likes short read-outs."  # the agent's, untouched

    again = reconcile_persona_instances(apply=True)
    assert CHAT_ONLY not in _fates(again["cleanup"])
    assert again["chat_only_copies_retired_count"] == 0


def test_a_copy_with_a_live_chat_is_kept(adopted_copies):
    """Its chat pointer names its live chat; it holds nothing else and no date is read. Kill-mutation: drop
    the pointer test in ``clean_up_chat_only_copies`` → retired, red."""
    applied = reconcile_persona_instances(apply=True)
    assert _fates(applied["cleanup"])[LIVE] == ("kept", "live_chat")
    assert PersonaInstanceStore().get(LIVE).workspace_id == DEFAULT_WORKSPACE_ID


def test_a_hidden_copy_with_a_live_chat_survives_adoption_and_cleanup_in_one_run(monkeypatch):
    """The owner's daily copy on the first boot: an UNSTAMPED hidden copy whose pointer names its live chat
    is adopted and then cleaned up in one applied run, and stays placed. Kill-mutation: drop the pointer
    test in ``clean_up_chat_only_copies`` → retired by the same run, red."""
    import agent_runtime.persona_instance_adoption as adoption

    monkeypatch.setattr(adoption, "_work_assignee_tokens", lambda: frozenset())
    ensure_default_scope(seed_active_pointers=False)
    row = PersonaInstance(
        id=LIVE, persona_id="backend_dev", role="backend_dev", display_name="backend_dev", profile_id=None,
        runtime_root=str(paths.store_root()), state=WorkerSessionState.IDLE, mode="configured",
        default_chat_session_id=LIVE_CHAT,
    )
    path = paths.persona_instance_path(LIVE)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(to_jsonable(row), indent=2, sort_keys=True), encoding="utf-8")
    _saved_chat(LIVE_CHAT)

    applied = reconcile_persona_instances(apply=True)

    assert {item["persona_instance_id"]: item["fate"] for item in applied["adoption"]}[LIVE] == "adopted"
    assert _fates(applied["cleanup"])[LIVE] == ("kept", "live_chat")
    kept = PersonaInstanceStore().get(LIVE)
    assert (kept.workspace_id, kept.default_chat_session_id) == (DEFAULT_WORKSPACE_ID, LIVE_CHAT)
