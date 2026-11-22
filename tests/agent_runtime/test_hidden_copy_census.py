"""The hidden-copy census, and what happens to each kind of copy before the canonical predicate goes.

Row ``RT-HERMES-STOPS-MAKING-A-HIDDEN-COPY-OF-EVERY-AGENT`` (plan
``agent-template-vs-canonical-instance-2026-11-21`` §5(iii), §6; reviews w1118a.78 and .80). The adoption
row's holdings reader missed two kinds of copy that looked empty: (1) a copy holding a saved chat known
only from its transcript (no chat pointer, no ledger entry), archived per the owner's RULED cleanup with
its chats still listed under the agent; (2) a Work assignee with no instance pointer, in live use, so
adopted. The security gate: no unstamped ``personainst_<persona>`` row is left after a run.
"""

from __future__ import annotations

import json

import pytest

from agent_runtime import paths
from agent_runtime.default_scope import DEFAULT_WORKSPACE_ID, ensure_default_scope
from agent_runtime.models import CHAT_HEAD_KIND_PER_PROFILE, PersonaInstance
from agent_runtime.persona_assignments import PersonaInstanceStore, persona_instance_id_for
from agent_runtime.persona_instance_adoption import (
    adopt_global_rows,
    hold_unstamped_hidden_copies,
    unstamped_hidden_copies,
)
from agent_runtime.persona_instance_identity import reconcile_persona_instances
from agent_runtime.serde import to_jsonable
from agent_runtime.states import WorkerSessionState

pytestmark = pytest.mark.usefixtures("isolate_agent_runtime_root", "persisted_persona_samples")

PERSONA = "neko_supervisor"
COPY = persona_instance_id_for(PERSONA)
SAVED = f"persona_chat_{COPY}_0123456789ab"


def _seed(instance_id: str = COPY, *, persona_id: str = PERSONA, **fields) -> None:
    row = PersonaInstance(
        id=instance_id, persona_id=persona_id, role=persona_id, display_name="Neko", profile_id=None,
        runtime_root=str(paths.store_root()), state=WorkerSessionState.IDLE, mode="configured", **fields,
    )
    path = paths.persona_instance_path(instance_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(to_jsonable(row), indent=2, sort_keys=True), encoding="utf-8")


def _raw(instance_id: str = COPY) -> dict:
    return json.loads(paths.persona_instance_path(instance_id).read_text(encoding="utf-8"))


def _fates(report: list[dict]) -> dict[str, tuple]:
    return {item["persona_instance_id"]: (item["fate"], item.get("reason")) for item in report}


def _saved_chat(session_id: str = SAVED, *, persisted: str | None = None) -> None:
    """A saved chat in the process chat store that names its holder only by its transcript."""
    from agent_runtime.persona_chat_continuity import PERSONA_CHAT_SESSION_SOURCE
    from tests.agent_runtime.test_persona_chat_move import _db

    db = _db(session_id)
    config = {"persona_instance_id": persisted} if persisted else None
    db.create_session(session_id, PERSONA_CHAT_SESSION_SOURCE, model_config=config)
    db.append_message(session_id, "user", "written to the hidden copy")


@pytest.fixture
def work_assignees(monkeypatch):
    """The Work boards' assignees, as the census reads them (``_work_assignee_tokens``)."""
    import agent_runtime.persona_instance_adoption as adoption

    tokens: dict[str, frozenset[str] | None] = {"value": frozenset()}
    monkeypatch.setattr(adoption, "_work_assignee_tokens", lambda: tokens["value"])
    return tokens


def test_a_work_assignee_with_no_pointer_is_adopted(work_assignees):
    """Kind (2). Kill-mutation: drop the assignee test in ``canonical_row_holdings`` → archived, red."""
    ensure_default_scope(seed_active_pointers=False)
    _seed()
    work_assignees["value"] = frozenset({COPY})
    assert _fates(adopt_global_rows(apply=True)) == {COPY: ("adopted", None)}
    assert _raw()["workspace_id"] == DEFAULT_WORKSPACE_ID and _raw()["adopted_from_global"]


def test_a_copy_holding_only_transcript_chats_is_archived_and_its_chats_stay_listed(work_assignees):
    """Kind (1): the census counts the saved chats before the archive, and Chat history still lists the
    chat under the agent, flagged ``holder_retired``."""
    from agent_runtime.persona_chat_history import persona_chat_history_summary

    ensure_default_scope(seed_active_pointers=False)
    _seed()
    _saved_chat()
    _saved_chat(f"persona_chat_{persona_instance_id_for('qa')}_00000000000a", persisted=COPY)
    census = reconcile_persona_instances(apply=False)
    entry = next(item for item in census["adoption"] if item["persona_instance_id"] == COPY)
    assert (entry["fate"], entry["holds"], entry["saved_chats"]) == ("would_archive", [], 2)
    assert paths.persona_instance_path(COPY).exists()  # the census wrote nothing
    applied = reconcile_persona_instances(apply=True)
    assert _fates(applied["adoption"])[COPY] == ("archived", None)
    assert applied["unstamped_hidden_copies"] == []
    rows = persona_chat_history_summary(persona_instances=PersonaInstanceStore().list_all())
    row = next(item for item in rows if item["session_id"] == SAVED)
    assert (row["persona_id"], row["persona_instance_id"], row["holder_retired"]) == (PERSONA, COPY, True)


def test_a_per_profile_head_copy_is_flagged_in_the_census(work_assignees):
    ensure_default_scope(seed_active_pointers=False)
    _seed(chat_head_kind=CHAT_HEAD_KIND_PER_PROFILE)
    entry = adopt_global_rows(apply=False)[0]
    assert entry["fate"] == "would_archive" and entry["per_profile_head"] is True


def test_an_unreadable_work_board_archives_nothing(work_assignees):
    """Kill-mutation: drop the ``work_read`` test in ``_archive_or_hold`` → the copy is archived, red."""
    ensure_default_scope(seed_active_pointers=False)
    _seed()
    work_assignees["value"] = None
    assert _fates(adopt_global_rows(apply=True)) == {COPY: ("held_local", "work_unreadable")}
    assert _raw()["adopted_from_global"]


def test_a_profile_channel_is_held_never_archived(work_assignees):
    """A ``profile_<name>`` send still opens ``personainst_profile_<name>``; archiving it would refuse it."""
    channel = persona_instance_id_for("profile_alice")
    _seed(channel, persona_id="profile_alice")
    assert _fates(adopt_global_rows(apply=True)) == {channel: ("held_local", "profile_channel")}
    assert paths.persona_instance_path(channel).exists()


def test_a_row_the_adoption_cannot_place_is_held_machine_local(work_assignees):
    """The security gate: a row the adoption skipped is stamped, never left an ordinary unscoped row, and
    a stale stored pointer is cleared. Kill-mutation: skip the write in ``_hold_local`` → red."""
    _seed(default_chat_session_id=SAVED, workspace_id="ws_elsewhere")  # no Default workspace exists
    assert unstamped_hidden_copies() == [COPY]
    assert _fates(adopt_global_rows(apply=True)) == {COPY: ("held_local", "no_default_workspace")}
    raw = _raw()
    assert raw["adopted_from_global"] and raw.get("workspace_id") is None
    assert unstamped_hidden_copies() == []
    # Retried at the next run: once the Default workspace exists the held row is adopted.
    ensure_default_scope(seed_active_pointers=False)
    assert _fates(adopt_global_rows(apply=True)) == {COPY: ("adopted", None)}
    assert _raw()["workspace_id"] == DEFAULT_WORKSPACE_ID


def test_the_boot_fallback_holds_every_unstamped_copy():
    """When a run raises, the serve boot stamps every unstamped copy machine-local and nothing else."""
    _seed()
    _seed(persona_instance_id_for("qa"), persona_id="qa", workspace_id="ws_elsewhere")
    assert hold_unstamped_hidden_copies(today="2026-11-21") == [COPY, persona_instance_id_for("qa")]
    assert unstamped_hidden_copies() == []
    assert _raw(persona_instance_id_for("qa")).get("workspace_id") is None
