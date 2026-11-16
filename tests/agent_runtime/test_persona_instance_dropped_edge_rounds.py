"""A pulled agent whose steering parent is absent here is not a local change: pull, Revert all, pull.

RT-REALM-PULL-SHOWS-AN-UNTOUCHED-AGENT-AS-CHANGED. The owner, 2026-11-16, on a member's machine: after a
pull the realm card read "1 agent changed" (``personainst_dev_agent_8b319ebf``), Revert all answered
``reverted_to_upstream``, and the next pull brought it back — round after round. Reproduced in a scratch
home the same day: a pulled agent whose ``steered_by`` names a parent this machine does not hold mints
with the edge dropped (``parent_absent``), the pull settles the baseline at the REMOTE hash, and the drift
walk compared the edge-less replica with it; Revert realigned the baseline to the LOCAL hash, so the next
pull took the body again (``adopted``) and reset it.

The fix: the pull's dropped-steering ledger (its one owner of what was dropped) records the body as
minted and the realm's steering, and the drift walk, the publish projection and the revert all read it
(``persona_instance_sync.pull.body_as_pulled``). Killing mutations are named per test.
"""
from __future__ import annotations

from agent_runtime.persona_assignments import PersonaInstanceStore
from agent_runtime.persona_instance_sync import (
    apply_persona_instance_pull,
    instance_baseline_key,
    persona_instance_def_hash,
    read_dropped_steering_ledger,
    read_persona_instance_baseline,
    write_dropped_steering_ledger,
    write_persona_instance_baseline,
)
from agent_runtime.realm_revert import revert_realm_sync
from agent_runtime.realm_sync import DRIFT_FAMILY_PERSONA_INSTANCE, DRIFT_KIND_CHANGED
from tests.agent_runtime.test_persona_instance_drift import (
    INSTANCE_ID,
    _body,
    _drift,
    _realm_workspace,
    _subtree,
    _write_remote,
)

#: A steering parent the member's machine does not hold: in the owner's realm a canonical channel, which
#: publish never ships.
ABSENT_PARENT = "personainst_profile_base"


def _member_with_a_steered_replica(tmp_path):
    realm_id, ws = _realm_workspace(tmp_path / "sync_repo")
    subtree = _subtree(realm_id, tmp_path)
    remote = _body(ws, steered_by=[ABSENT_PARENT])
    _write_remote(subtree, remote)
    return realm_id, ws, subtree, remote


def _baseline(realm_id: str) -> str | None:
    return read_persona_instance_baseline(realm_id).get(instance_baseline_key(INSTANCE_ID))


def _local_hash() -> str:
    from agent_runtime.persona_instance_sync import project_persona_instance

    return persona_instance_def_hash(project_persona_instance(PersonaInstanceStore().get(INSTANCE_ID)))


def test_the_owners_three_rounds_pull_revert_all_pull_never_show_the_agent_changed(tmp_path):
    """Three rounds of the owner's loop. Each pull drops the edge (the parent is still absent), and the
    agent is never a local change: not after the pull, not after Revert all, not after the next pull —
    and no pull after the first takes the body again.

    Mutations: in ``_persona_instance_store_drift_items`` drop the ``body_as_pulled`` read -> round one
    reads ``changed``, red (the owner's screenshot); in ``PullPass._record_still_absent`` stop recording
    ``minted_hash`` -> the same, red."""
    realm_id, ws, subtree, remote = _member_with_a_steered_replica(tmp_path)

    for round_no in range(3):
        summary = apply_persona_instance_pull(realm_id, subtree)
        assert summary.steering_dropped == [
            {"key": INSTANCE_ID, "parent": ABSENT_PARENT, "reason": "parent_absent"}], round_no
        assert summary.adopted == [], f"round {round_no}: the pull took an unmoved body again"
        if round_no == 0:
            assert summary.replicated == [INSTANCE_ID]
        assert _drift(realm_id, ws) == [], f"round {round_no}: the untouched agent reads as changed"

        reverted = revert_realm_sync(realm_id, revert_all=True)
        assert [row for row in reverted["items"] if row["family"] == DRIFT_FAMILY_PERSONA_INSTANCE] == []
        assert _drift(realm_id, ws) == []
        assert _baseline(realm_id) == persona_instance_def_hash(remote)


def test_a_real_edit_reverted_leaves_the_baseline_the_next_pull_agrees_with(tmp_path):
    """The member DID rename the agent: that is drift, Revert puts the realm's body back (its absent edge
    still dropped), and the baseline it leaves is the realm's hash — so the next pull keeps the row
    (``kept_local`` through the heal check) instead of taking the body again (``adopted``).

    Mutation: in the instance arm's baseline hash (``realm_revert_writes.instance_baseline_after_revert``)
    answer the local hash -> the baseline is the edge-less hash and the next pull adopts, red."""
    realm_id, ws, subtree, remote = _member_with_a_steered_replica(tmp_path)
    apply_persona_instance_pull(realm_id, subtree)

    instance = PersonaInstanceStore().get(INSTANCE_ID)
    instance.display_name = "Locally renamed"
    PersonaInstanceStore()._write(instance)
    assert [(item.item_key, item.kind) for item in _drift(realm_id, ws)] == [(INSTANCE_ID, DRIFT_KIND_CHANGED)]

    result = revert_realm_sync(realm_id, item_specs=[f"{DRIFT_FAMILY_PERSONA_INSTANCE}:{ws}:{INSTANCE_ID}"])
    assert [row["outcome"] for row in result["items"]] == ["reverted_to_upstream"]
    assert PersonaInstanceStore().get(INSTANCE_ID).display_name == "Neko"
    assert _drift(realm_id, ws) == []
    assert _baseline(realm_id) == persona_instance_def_hash(remote)

    after = apply_persona_instance_pull(realm_id, subtree)
    assert after.adopted == [] and after.kept_local == [INSTANCE_ID]
    assert _drift(realm_id, ws) == []


def test_a_member_already_in_the_loop_leaves_it_on_one_pull(tmp_path):
    """A machine the old revert left with the baseline at the edge-less hash and a ledger without the
    minted body: the next pull takes the body once, records it, and from then on the agent is clean."""
    realm_id, ws, subtree, remote = _member_with_a_steered_replica(tmp_path)
    apply_persona_instance_pull(realm_id, subtree)
    write_persona_instance_baseline(realm_id, {instance_baseline_key(INSTANCE_ID): _local_hash()})
    write_dropped_steering_ledger(realm_id, {
        INSTANCE_ID: {"parents": [ABSENT_PARENT], "remote_hash": persona_instance_def_hash(remote)}})

    assert apply_persona_instance_pull(realm_id, subtree).adopted == [INSTANCE_ID]
    assert _drift(realm_id, ws) == []
    assert read_dropped_steering_ledger(realm_id)[INSTANCE_ID]["minted_hash"] == _local_hash()
    assert apply_persona_instance_pull(realm_id, subtree).adopted == []
    assert _drift(realm_id, ws) == []


def test_a_re_steer_on_top_of_a_dropped_edge_is_still_a_local_change(tmp_path):
    """The ledger explains exactly the body the pull minted, nothing more: a member who then re-steers the
    agent changed it, and it reads ``changed``.

    Mutation: in ``body_as_pulled`` skip the ``minted_hash`` check -> the re-steer is hidden, red."""
    realm_id, ws, subtree, _remote = _member_with_a_steered_replica(tmp_path)
    other = "personainst_dev_agent_0000beef"
    _write_remote(subtree, _body(ws, steered_by=[ABSENT_PARENT]), _body(ws, other))
    apply_persona_instance_pull(realm_id, subtree)
    assert _drift(realm_id, ws) == []

    instance = PersonaInstanceStore().get(INSTANCE_ID)
    instance.steered_by = [other]
    PersonaInstanceStore()._write(instance)
    assert [(item.item_key, item.kind) for item in _drift(realm_id, ws)] == [(INSTANCE_ID, DRIFT_KIND_CHANGED)]


def test_the_members_publish_carries_the_realms_steering_back_out(tmp_path):
    """What the member's publish would write for the untouched agent is the realm's body, edge and all —
    so the publish compare (the status flag) sees nothing waiting, and a publish never strips the edge
    from the team's copy.

    Mutation: in ``artifacts._with_pulled_steering`` drop the ``body_as_pulled`` read -> the projected
    body is the edge-less one, red."""
    from agent_runtime.realm_sync.artifacts import _persona_instance_projection, _with_pulled_steering

    realm_id, _ws, subtree, remote = _member_with_a_steered_replica(tmp_path)
    apply_persona_instance_pull(realm_id, subtree)
    projection = _with_pulled_steering(_persona_instance_projection([INSTANCE_ID])[0], realm_id)
    assert projection.hashes() == {INSTANCE_ID: persona_instance_def_hash(remote)}
