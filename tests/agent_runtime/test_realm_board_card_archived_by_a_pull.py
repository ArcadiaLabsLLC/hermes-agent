"""A teammate deletes a shared board card and brings it back: a member gets it back, and only pulling
never reads as an unpublished change.

RT-REALM-BOARD-CARD-ARCHIVED-BY-A-PULL-BLOCKS-IT-COMING-BACK, the board twin of
RT-REALM-MEMBER-DESK-ARCHIVED-BY-A-PULL-BLOCKS-THE-AGENT-COMING-BACK. Read in code at filing; reproduced
here on two simulated computers (``_Team``) before the fix: after the restore's pull the card stayed gone
on the member's machine and the board read as an unpublished change — the delete's pull had entered the
teammate's tombstone in the member's ledger as the member's own, and the board's plain ledger union kept
it after the realm dropped it.

The fix is the office's: ONE who-archived record (``agent_runtime.realm_held``) used by the office and
board stores alike, the by-origin merge (``sync_merge.merge_archived_ledgers_by_origin``) in
``adopt_remote_board``, ``BoardStore.own_archived_card_ids`` as the only ``locally_archived`` answer the
board pull reads, and no own tombstone from the pull's remote-removal arm. Killing mutations are named
per test.
"""
from __future__ import annotations

import pytest

from agent_runtime import board_models, serve_rpc
from agent_runtime.board_store import BoardStore
from agent_runtime.realm_sync import publish_realm_sync, pull_realm_sync
from agent_runtime.store import WorkspaceStore
from tests.agent_runtime.test_workspace_move_out_of_server_realm import _Team


@pytest.fixture
def team(tmp_path, monkeypatch):
    return _Team(tmp_path, monkeypatch)


def _unpublished(realm_id: str) -> tuple[bool, list[tuple]]:
    """``(unpublished_changes, [(family, item, kind)])`` as the realm card reads them."""
    reply = serve_rpc.handle_request(
        {"jsonrpc": "2.0", "id": "st", "method": "runtime.realm.sync.status", "params": {"realm_id": realm_id}})
    status = reply["result"]
    return status["unpublished_changes"], [
        (str(item["family"]), item["item_key"], item["kind"]) for item in status["store_drift"]["items"]]


def _titles(workspace_id: str) -> list[str]:
    board_id = board_models.default_board_id(workspace_id)
    return [card.title for card in BoardStore().list_cards(board_id)] if BoardStore().exists(board_id) else []


def _shared_card(team: _Team):
    """Alice's realm: one workspace with one board card, published; Bob joins and pulls."""
    shared = team.found("alice", "Team Realm", "srv_team")
    workspace = WorkspaceStore().create(name="Roadmap", realm_id=shared.id)
    card = BoardStore().add_card(workspace_id=workspace.id, title="Ship it", description="seeded")
    publish_realm_sync(shared.id)
    team.join("bob", shared)
    assert _titles(workspace.id) == ["Ship it"]
    assert _unpublished(shared.id) == (False, [])
    return shared, workspace, card


def _alice(team: _Team, shared, verb, card) -> None:
    team.be("alice")
    verb(card.card_id, board_id=card.board_id)
    publish_realm_sync(shared.id)


def test_a_teammates_delete_then_restore_brings_the_card_back_and_nothing_reads_unpublished(team):
    """Delete, pull, restore, pull — on the member's machine.

    Mutations, one at a time: in ``board_sync``'s ARCHIVE_LOCAL arm record the tombstone again (drop
    ``record_tombstone=False``) -> the restore's pull leaves the card gone, red at the second ``_titles``;
    in ``apply_board_pull`` read ``local_board.archived_card_ids`` instead of ``own_archived_card_ids`` ->
    the same red; in ``adopt_remote_board`` go back to the plain ``merge_archived_ledgers`` -> the same red
    (the realm's key outlives the realm); in ``adopt_remote_board`` pass an empty realm-held set -> the
    restore's pull reads the board ``changed``, red at the second ``_unpublished``; in
    ``realm_held.own_archived`` ignore the realm-held record -> ``(0, 1)``, red (the office twin's test
    reddens too)."""
    shared, workspace, card = _shared_card(team)
    _alice(team, shared, BoardStore().archive_card, card)

    team.be("bob")
    pulled = pull_realm_sync(shared.id)
    assert pulled["board_sync"]["archived"] == 1
    assert _titles(workspace.id) == []
    assert _unpublished(shared.id) == (False, [])

    _alice(team, shared, BoardStore().restore_card, card)
    team.be("bob")
    pulled = pull_realm_sync(shared.id)
    assert (pulled["board_sync"]["adopted"], pulled["board_sync"]["conflicts"]) == (1, 0)
    assert _titles(workspace.id) == ["Ship it"]
    assert _unpublished(shared.id) == (False, [])

    pull_realm_sync(shared.id)
    assert _titles(workspace.id) == ["Ship it"]
    assert _unpublished(shared.id) == (False, [])


def test_a_card_the_member_deleted_himself_stays_deleted_when_the_teammate_restores_it(team):
    """The hand archive wins: Bob deleted the card on his machine, Alice deleted and then restored it.
    Bob's own delete is his own change, so it is still what Bob has after the restore's pull.

    Mutation: in ``board_store.files.archive_card_locked`` skip ``realm_held.forget`` (Bob's own delete of a
    card id the realm already held stays the realm's) -> the restore's pull brings the card back, red; the
    same red with ``realm_held.forget`` made a no-op."""
    shared, workspace, card = _shared_card(team)
    _alice(team, shared, BoardStore().archive_card, card)
    team.be("bob")
    pull_realm_sync(shared.id)
    assert _titles(workspace.id) == []
    # Bob now deletes it himself as well (a restore then his own delete), before Alice brings it back.
    BoardStore().restore_card(card.card_id, board_id=card.board_id)
    BoardStore().archive_card(card.card_id, board_id=card.board_id)

    _alice(team, shared, BoardStore().restore_card, card)
    team.be("bob")
    pull_realm_sync(shared.id)
    assert _titles(workspace.id) == []
    assert card.card_id in BoardStore().own_archived_card_ids(card.board_id)
