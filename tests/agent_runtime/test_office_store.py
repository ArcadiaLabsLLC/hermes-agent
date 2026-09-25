"""OfficeStore tests (office plan W-H1): event-per-mutation, actor-key
canonicalization at the store boundary, filename truncation collision-proofing,
write-time secret rejection of display names, archive ledger + restore,
revision guard, the prune-lane hook, and the snapshot offices projection.
Autouse conftest fixtures isolate the runtime root.
"""

from __future__ import annotations

import pytest

from agent_runtime import office_models, paths, sync_merge
from agent_runtime.errors import (
    ActorsUnreadable,
    ArchiveUnreadable,
    NotFound,
    StaleRevision,
    SyncConflict,
    WorkspaceUnresolved,
)
from agent_runtime.events import EventLog
from agent_runtime.office_store import (
    ARCHIVED_LEDGER_CAP,
    OfficeStore,
)
from agent_runtime.snapshot import SNAPSHOT_CONTRACT_VERSION, build_snapshot
from agent_runtime.store import WorkspaceStore


def _event_types() -> list[str]:
    return [evt.type for _, evt in EventLog().iter_from_offset(0)]


def _make_workspace(name: str = "Default") -> str:
    ws = WorkspaceStore().create(name=name)
    WorkspaceStore().set_active(ws.id)
    return ws.id


def _actor_payload(persona_id: str = "dev", **overrides) -> dict:
    payload = {
        "persona_id": persona_id,
        "items": [
            {"item_id": persona_id, "persona_id": persona_id, "kind": "agent", "position": [1.5, 2.0], "folder": "Agents"},
            {"item_id": f"desk-{persona_id}", "persona_id": persona_id, "kind": "desk", "position": [1.5, 3.6], "folder": "Desks"},
        ],
    }
    payload.update(overrides)
    return payload


# ── event per mutation + round trip ───────────────────────────────────────


def test_upsert_remove_restore_round_trip_emits_event_per_mutation():
    ws = _make_workspace()
    store = OfficeStore()
    actor = store.upsert_actor(ws, _actor_payload("dev"))
    assert actor.actor_key == "dev"
    assert len(actor.items) == 2
    removed = store.remove_actor(ws, "dev")
    assert removed.state == "archived"
    restored = store.restore_actor(ws, "dev")
    assert restored.state == "active"
    store.update_surface(ws, folders=["West Wing"])

    types = _event_types()
    for expected in (
        "office.surface.created",
        "office.actor.upserted",
        "office.actor.removed",
        "office.actor.restored",
        "office.surface.updated",
    ):
        assert expected in types, (expected, types)


def test_surface_created_once_and_deterministic():
    ws = _make_workspace()
    store = OfficeStore()
    first = store.ensure_surface(ws)
    second = store.ensure_surface(ws)
    assert _event_types().count("office.surface.created") == 1
    assert office_models.office_content_hash(first) == office_models.office_content_hash(second)
    assert list(first.folders) == list(office_models.DEFAULT_FOLDERS)


# ── identity: canonicalization at the boundary (plan §4.3) ────────────────


def test_actor_key_canonicalizes_drifted_instance_id():
    ws = _make_workspace()
    store = OfficeStore()
    actor = store.upsert_actor(
        ws,
        _actor_payload("dev", persona_instance_id="persona_personainst_goal1_dev"),
    )
    # persona_personainst_* actor-token drift collapses at the store boundary.
    assert actor.actor_key == "personainst_goal1_dev"
    assert actor.persona_instance_id == "personainst_goal1_dev"
    assert paths.office_actor_path(ws, "personainst_goal1_dev").exists()


def test_actor_key_falls_back_to_persona_id_and_normalizes_case():
    ws = _make_workspace()
    store = OfficeStore()
    actor = store.upsert_actor(ws, _actor_payload("Backend_Dev"))
    assert actor.actor_key == "backend_dev"
    assert actor.persona_id == "backend_dev"


def test_long_actor_keys_truncate_without_colliding():
    shared_prefix = "p" * 70
    token_a = office_models.actor_file_token(shared_prefix + "alpha")
    token_b = office_models.actor_file_token(shared_prefix + "beta")
    assert token_a != token_b, "truncated filenames must stay collision-proof (hash suffix)"
    assert len(token_a) <= 64 + 11
    # Deterministic: same key, same token, every machine.
    assert token_a == office_models.actor_file_token(shared_prefix + "alpha")


# ── write-time secret rejection (plan §4.2) ───────────────────────────────


def test_secret_shaped_display_name_rejected_at_write():
    ws = _make_workspace()
    store = OfficeStore()
    payload = _actor_payload("dev")
    payload["items"][0]["display_name"] = "token: abcdefgh12345678"
    with pytest.raises(ValueError):
        store.upsert_actor(ws, payload)
    # Nothing was written; the surface may exist but no actor file does.
    assert not store.actor_exists(ws, "dev")


# ── validation + revision guard ────────────────────────────────────────────


def test_invalid_payloads_rejected():
    ws = _make_workspace()
    store = OfficeStore()
    with pytest.raises(ValueError):
        store.upsert_actor(ws, {"persona_id": "dev", "items": []})
    with pytest.raises(ValueError):
        store.upsert_actor(ws, _actor_payload("dev", items=[{"item_id": "dev", "position": ["nan", 0]}]))
    with pytest.raises(ValueError):
        store.upsert_actor(ws, {"items": [{"item_id": "x", "position": [0, 0]}]})


def test_stale_revision_guard():
    ws = _make_workspace()
    store = OfficeStore()
    actor = store.upsert_actor(ws, _actor_payload("dev"))
    with pytest.raises(StaleRevision):
        store.upsert_actor(ws, _actor_payload("dev"), expect_revision=actor.revision + 5)
    updated = store.upsert_actor(ws, _actor_payload("dev"), expect_revision=actor.revision)
    assert updated.revision == actor.revision + 1


def test_scale_clamped_defensively():
    ws = _make_workspace()
    store = OfficeStore()
    payload = _actor_payload("dev")
    payload["items"][0]["scale"] = 99.0
    actor = store.upsert_actor(ws, payload)
    assert actor.items[0].scale == office_models.SCALE_MAX


# ── archive ledger + restore + re-add ─────────────────────────────────────


def test_remove_records_ledger_and_blocks_nothing_else():
    ws = _make_workspace()
    store = OfficeStore()
    store.upsert_actor(ws, _actor_payload("dev"))
    store.remove_actor(ws, "dev", reason="operator")
    surface = store.get_surface(ws)
    assert "dev" in surface.archived_actor_keys
    assert not store.actor_exists(ws, "dev")
    assert paths.office_archived_actor_path(ws, "dev").exists()
    # Idempotent remove returns the archived copy.
    again = store.remove_actor(ws, "dev")
    assert again.state == "archived"


def test_upsert_after_archive_clears_ledger():
    """The store's re-add contract, now behind the class-key fence's consent.

    "An explicit upsert of an archived key is intent to re-add, so clear the
    resurrection ledger" is still the contract — but since EG-6.6 the fence that
    used to sit at four callers sits in ``upsert_actor`` itself, and a CLASS-keyed
    re-add of an archived key is the exact write it refuses
    (``resurrects_archived_class_key``). Every production caller already refused
    this before the hoist; what changed is that the store no longer takes the
    intent on faith from whoever called it.

    So the intent is spelled: ``allow_class_key=True`` is the sanctioned override
    (``harness office actor-upsert --allow-class-key``, and the reason
    ``restore_actor`` exists). The refusal WITHOUT it is pinned in
    ``test_office_class_key_one_fence.py``; what this test still owns is that
    consent really does clear the ledger and the archive copy.

    D1 adds a SECOND consent to this write, and the two are not the same
    question: ``allow_class_key`` says the key shape is deliberate, ``resurrect``
    says raising a deleted key is. This write is both, so it spells both.
    """

    ws = _make_workspace()
    store = OfficeStore()
    store.upsert_actor(ws, _actor_payload("dev"))
    store.remove_actor(ws, "dev")
    readded = store.upsert_actor(
        ws, _actor_payload("dev"), allow_class_key=True, resurrect=True
    )
    assert readded.state == "active"
    surface = store.get_surface(ws)
    assert "dev" not in surface.archived_actor_keys
    assert not paths.office_archived_actor_path(ws, "dev").exists()


def test_restore_missing_raises():
    ws = _make_workspace()
    store = OfficeStore()
    with pytest.raises(NotFound):
        store.restore_actor(ws, "ghost")


# ── EG-1.5 / RD-H4: the scan counts what it could not read ─────────────────


@pytest.mark.parametrize("corrupt_count", [1, 2])
def test_a_corrupt_actor_file_is_counted_not_vanished(corrupt_count, caplog):
    """``continue`` alone made a shortened office indistinguishable from a
    smaller one.

    ``read_actor_dir`` has always skipped an actor file it could not decode, and
    the skip has to stay — a whole office must not vanish because one file is
    mid-write or held by an AV scanner. What could not stay is the SILENCE: every
    reader downstream got a shorter list that described itself as complete.

    **Anti-vacuity.** Restoring the bare ``continue`` is the mutation. The count
    is driven to TWO distinct values by this parametrize, so a mutant reporting a
    constant matches at most one; a mutant that skips silently reports 0 and
    matches neither. The readable actors are asserted in the same breath, which
    is what stops the opposite over-correction (refusing the whole scan) from
    passing.
    """

    ws = _make_workspace()
    store = OfficeStore()
    store.upsert_actor(ws, _actor_payload("dev"))
    store.upsert_actor(ws, _actor_payload("qa"))
    for index in range(corrupt_count):
        # A file the glob finds and the decoder cannot use — the shape an
        # interrupted write or a partially-scanned file arrives in.
        (paths.office_actors_dir(ws) / f"broken{index}.json").write_text(
            "{not json", encoding="utf-8"
        )

    with caplog.at_level("WARNING"):
        scan = store.scan_actors(ws)

    assert scan.unreadable == corrupt_count
    assert [actor.actor_key for actor in scan.actors] == ["dev", "qa"]
    # ONE line for that ONE scan, naming the exception CLASS — never one line per
    # file (a directory of stale files would flood the log on every office read)
    # and never the decoder's message. Read before the second scan below, which
    # would legitimately add its own line.
    unreadable_lines = [
        record.getMessage()
        for record in caplog.records
        if "office actor files unreadable" in record.getMessage()
    ]
    assert len(unreadable_lines) == 1
    assert f": {corrupt_count} (" in unreadable_lines[0]
    assert "JSONDecodeError" in unreadable_lines[0]
    # ``.actors`` still answers exactly what it always did; AX5 removed the thin
    # view, not the rows.
    assert [actor.actor_key for actor in store.scan_actors(ws).actors] == ["dev", "qa"]


def test_an_unreadable_archive_refuses_the_re_add_instead_of_minting_revision_1():
    """The revision guard is only as honest as the token it spends.

    ``upsert_actor`` bases a re-added key's revision on the ARCHIVED copy on
    purpose: a key that left and came back carries its history forward, so the
    number a peer holds stays meaningful. The swallow turned an unreadable
    archive into ``archived = None`` → base 0 → **revision 1**, a token below the
    one every launcher read model and every peer already holds. The next guarded
    write then reads as a stale prediction against a server that silently
    rewound — and RD-L2/EG-5.1 arms exactly that comparison.

    **Anti-vacuity.** Falling through to base 0 is the mutation. *Probed fields:*
    the typed refusal class, AND that the archive file is still on disk with no
    new actor file beside it — the mutant returns an actor at revision 1 and
    writes it, and a store that merely raised something untyped could not satisfy
    the first probe.

    The two consents on the re-add are not incidental: since EG-6.6 the
    class-key fence runs FIRST inside ``upsert_actor``, and since D1 the
    tombstone fence runs before the archive is read at all, so BOTH are what get
    this write as far as the archive read — and the point of the test is that
    consenting to the resurrection does NOT also consent to inventing the
    revision token. Three fences, three decisions.
    """

    ws = _make_workspace()
    store = OfficeStore()
    actor = store.upsert_actor(ws, _actor_payload("dev"))
    for _ in range(6):
        actor = store.upsert_actor(ws, _actor_payload("dev"))
    assert actor.revision == 7
    store.remove_actor(ws, "dev")
    archived_path = paths.office_archived_actor_path(ws, "dev")
    assert archived_path.exists()
    archived_path.write_text("{truncated", encoding="utf-8")

    with pytest.raises(ArchiveUnreadable):
        store.upsert_actor(
            ws, _actor_payload("dev"), allow_class_key=True, resurrect=True
        )

    # Nothing was written on the refusal path: no revision-1 actor file, and the
    # archive copy is left exactly as found for an operator to repair.
    assert not paths.office_actor_path(ws, "dev").exists()
    assert archived_path.read_text(encoding="utf-8") == "{truncated"


def test_an_already_archived_remove_over_an_unreadable_archive_refuses_typed():
    """The idempotent remove branch reads the same token, so it refuses the same
    way.

    That branch exists to make a repeated delete gesture harmless, and its ack
    carries the POST-archive revision — the token a later guarded write on this
    key must present. An undecodable archive there used to surface as whatever
    the JSON decoder happened to raise, which the RPC lane could only report as
    an untyped handler crash. One condition, one reason string, on both verbs.
    """

    ws = _make_workspace()
    store = OfficeStore()
    store.upsert_actor(ws, _actor_payload("dev"))
    store.remove_actor(ws, "dev")
    paths.office_archived_actor_path(ws, "dev").write_text("{truncated", encoding="utf-8")

    with pytest.raises(ArchiveUnreadable):
        store.remove_actor(ws, "dev")


# ── conflict guard ─────────────────────────────────────────────────────────


def test_conflict_sidecar_blocks_upsert_until_resolved():
    ws = _make_workspace()
    store = OfficeStore()
    store.upsert_actor(ws, _actor_payload("dev"))
    sidecar = paths.office_conflict_path(ws, "dev")
    sidecar.parent.mkdir(parents=True, exist_ok=True)
    sidecar.write_text('{"actor_key": "dev", "kind": "both_changed", "remote_actor": null}', encoding="utf-8")
    with pytest.raises(SyncConflict):
        store.upsert_actor(ws, _actor_payload("dev"))
    resolved = store.resolve_conflict(ws, "dev", take="local")
    assert resolved is not None and resolved.actor_key == "dev"
    assert "office.actor.conflict_resolved" in _event_types()
    # Resolution archives the sidecar; writes flow again.
    assert not sidecar.exists()
    store.upsert_actor(ws, _actor_payload("dev"))


# ── the generic desk: furniture, unlimited, owned by nobody (2026-09-18) ──
#
# The one-desk-per-persona fence (D6) lived here — a refusal, two acceptances,
# a dry-run pin, an unreadable-directory pin, an id-vs-row narrowing, and a CLI
# exit-code translation. All of it is deleted with the fence, not rewritten:
# every one of those tests asserted a REFUSAL of a write that is now correct,
# and a test of deleted behaviour rewritten into "the write succeeds" would be
# a tautology over the whole store rather than a pin on anything.
#
# What replaces them are the three properties the ruling actually creates. The
# owner, 2026-09-18: *"i want desks to just be one type all agents can use, no
# more per persona desk, just one single desk object."*
#
# The launcher mints a generic desk under its OWN synthetic id
# (``desk_<8 base36>``) and uses that id as the item's ``persona_id`` too, so a
# desk is its own actor file. These fixtures spell exactly that shape.


def _generic_desk_payload(desk_id: str, position=(0.0, 0.0)) -> dict:
    """A generic desk: one item, addressed by its own synthetic id.

    ``persona_id`` at BOTH levels is the desk's own id, which is the whole shape
    the ruling creates — the actor key is the desk id, the item's address is the
    desk id, and no persona appears anywhere. Hand-spelled here rather than
    imported from the launcher because hermes has no minter and needs none: the
    store's contract is that it does not know what an id MEANS.
    """

    return {
        "persona_id": desk_id,
        "items": [
            {
                "item_id": desk_id,
                "persona_id": desk_id,
                "kind": "desk",
                "position": [float(position[0]), float(position[1])],
                "folder": "Desks",
            }
        ],
    }


def test_two_generic_desks_in_one_workspace_both_persist_and_both_emit():
    """THE ruling, at the store: two desks, two actor files, two events.

    HONEST ABOUT WHAT THIS DOES AND DOES NOT PROVE, because the red-first pass
    corrected the claim it was first written with. The deleted fence was keyed
    on the ITEM's persona, and two generic desks carry two DIFFERENT synthetic
    personas — so the old fence would have accepted this pair too. Restoring it
    leaves this test green, which was measured rather than assumed
    (2026-09-18). The test that the restoration actually kills is the LEGACY one
    below, where both desks name persona ``dev``.

    So what this pins is not the fence's absence. It is the generic-desk SHAPE
    reaching disk intact through the whole write path — a desk whose actor key,
    item id and ``persona_id`` are one synthetic token and whose actor names no
    instance — which is the shape slice 2 of the launcher plan starts minting
    and which nothing in this store had ever been asked to hold before. A guard
    that grew an opinion about an id it does not recognise reds here.

    Both halves are asserted, because a store that took the write and then lost
    it would satisfy the return values alone: the actor set is re-read off disk,
    and the EventLog is counted — office store mutations MUST keep emitting, and
    a fence deletion is exactly the kind of change that can silently cost an
    emission if it took the wrong line with it.
    """

    ws = _make_workspace()
    store = OfficeStore()

    first = store.upsert_actor(ws, _generic_desk_payload("desk_aaaaaaaa", (1.0, 1.0)))
    second = store.upsert_actor(ws, _generic_desk_payload("desk_bbbbbbbb", (2.0, 2.0)))

    assert first.actor_key == "desk_aaaaaaaa"
    assert second.actor_key == "desk_bbbbbbbb"

    # Read back off disk, not off the return values.
    on_disk = {a.actor_key: a for a in store.scan_actors(ws).actors}
    assert set(on_disk) == {"desk_aaaaaaaa", "desk_bbbbbbbb"}
    assert [i.kind for i in on_disk["desk_aaaaaaaa"].items] == ["desk"]
    assert [i.kind for i in on_disk["desk_bbbbbbbb"].items] == ["desk"]
    assert [list(i.position) for i in on_disk["desk_bbbbbbbb"].items] == [[2.0, 2.0]]

    # One event per mutation, for EACH desk. Not ">= 1": a fence deletion that
    # also dropped an emission would pass a floor check.
    assert _event_types().count("office.actor.upserted") == 2


def test_a_third_and_fourth_desk_are_not_a_cap_either():
    """Unlimited means unlimited, and the boundary is worth one test.

    A fence rewritten as "at most two" — or a predicate that only ever compared
    the incoming payload against ONE existing holder — would pass the test above
    and fail here. Cheap, and it pins the word the ruling actually used.
    """

    ws = _make_workspace()
    store = OfficeStore()
    for token in ("desk_aaaaaaaa", "desk_bbbbbbbb", "desk_cccccccc", "desk_dddddddd"):
        store.upsert_actor(ws, _generic_desk_payload(token))

    assert len(store.scan_actors(ws).actors) == 4
    assert _event_types().count("office.actor.upserted") == 4


def test_two_desks_under_one_legacy_persona_key_are_no_longer_refused():
    """The LEGACY shape, and the launcher owns cleaning it up — not this store.

    A pre-ruling desk carries a persona's id as its address
    (``<persona>_desk`` / ``desk-<persona>``), and two of them for one persona
    is precisely what the deleted fence existed to refuse. It is accepted now,
    because this store never knew what an id meant and the invariant that gave
    the id meaning is gone.

    That acceptance is NOT a migration path and must not be read as one. Old
    per-persona desks are dropped-and-reported at the LAUNCHER's one load
    chokepoint (``MissionOfficeLayout.fromJson``), by the owner's ruling that
    old schema is reported so it can be deleted and replaced rather than kept
    alive by a compatibility path. Hermes holds no migration and needs none.

    KILLING MUTATION, applied and recorded red 2026-09-18: restore a
    persona-keyed desk fence in ``upsert_actor``. This reds on the second write
    (``duplicate_desk: dev already holds a desk``) while EVERY generic-desk test
    beside it stays green — which is the measurement that makes this the ONLY
    witness to the fence's deletion in this file. Two generic desks carry two
    different synthetic personas and were never what the fence refused; a
    legacy pair for one persona is.
    """

    ws = _make_workspace()
    store = OfficeStore()

    legacy_one = {
        "persona_id": "dev",
        "items": [
            {"item_id": "dev_desk", "persona_id": "dev", "kind": "desk", "position": [0.0, 0.0]}
        ],
    }
    legacy_two = {
        "persona_id": "dev",
        "persona_instance_id": "personainst_dev_agent_1",
        "items": [
            {"item_id": "desk-dev", "persona_id": "dev", "kind": "desk", "position": [3.0, 0.0]}
        ],
    }

    store.upsert_actor(ws, legacy_one)
    store.upsert_actor(ws, legacy_two)

    held = {
        item.item_id
        for actor in store.scan_actors(ws).actors
        for item in actor.items
        if item.kind == "desk"
    }
    assert held == {"dev_desk", "desk-dev"}
    assert _event_types().count("office.actor.upserted") == 2


def test_a_generic_desk_write_pays_the_CLASS_KEY_scan_and_only_that_one():
    """The cost claim, stated accurately rather than optimistically.

    MEASURED, not assumed, and the measurement corrected the claim this test was
    first written to make. A generic desk actor carries no
    ``persona_instance_id`` — a desk has no instance to name — so from the
    store's point of view it is a CLASS-KEYED payload, and
    ``_guard_class_keyed_write`` scans the actor directory for it. That fence
    refuses ``ActorsUnreadable`` over a directory it could only partly read, for
    its own reasons (EG-6.6), and it is untouched by the desk fence's deletion.

    So the honest accounting is: a desk write used to pay TWO full
    ``scan_actors`` calls — the class-key fence's and the desk fence's — and now
    pays ONE. It does not pay zero, and a reader who took "the fence cost a scan
    per desk write" as "desk writes no longer scan" would be wrong.

    The refusal below is the class-key fence's, identified by its own SENTENCE
    rather than by the exception type: both fences raised ``ActorsUnreadable``,
    so a type-only assertion would have passed against the deleted one and this
    test would have been pinning a ghost.

    KILLING MUTATION: drop the ``scan.unreadable`` arm from
    ``office_class_key_guard.class_key_collision`` — the write then succeeds and
    the ``raises`` reds. That is the correct killing mutation because it is the
    fence that actually answers here.
    """

    ws = _make_workspace()
    store = OfficeStore()
    store.ensure_surface(ws, created_by="seed")
    actors_dir = paths.office_actors_dir(ws)
    actors_dir.mkdir(parents=True, exist_ok=True)
    (actors_dir / "broken.json").write_text("{not json", encoding="utf-8")

    with pytest.raises(ActorsUnreadable) as excinfo:
        store.upsert_actor(ws, _generic_desk_payload("desk_aaaaaaaa"))

    assert "the class-key fence cannot prove" in str(excinfo.value), (
        "the refusal did not come from the class-key fence — if it came from a "
        "restored desk fence this test is measuring the wrong thing"
    )


def test_an_instance_keyed_placement_still_never_pays_for_the_scan():
    """The twin, and the boundary: an INSTANCE-keyed write scans nothing.

    This is the old ``test_a_desk_free_payload_never_pays_for_the_scan`` under a
    name that says what actually decides it. It never was the desk-freeness: the
    class-key fence skips an instance-keyed payload ("an instance-keyed write IS
    the migration's shape"), and the desk fence skipped a desk-free one. With
    the desk fence gone only the first clause remains, and it is what keeps the
    launcher's drop and ``agent create``'s placement leg — both instance-keyed —
    off the directory scan even on a store holding one stale file.

    Kept beside the test above so the pair is a boundary rather than one
    assertion twice: same fixture, same unreadable file, opposite outcomes,
    decided by the presence of ``persona_instance_id`` alone."""

    ws = _make_workspace()
    store = OfficeStore()
    store.ensure_surface(ws, created_by="seed")
    actors_dir = paths.office_actors_dir(ws)
    actors_dir.mkdir(parents=True, exist_ok=True)
    (actors_dir / "broken.json").write_text("{not json", encoding="utf-8")

    placed = store.upsert_actor(
        ws,
        {
            "persona_id": "dev",
            "persona_instance_id": "personainst_dev_agent_1",
            "items": [
                {"item_id": "personainst_dev_agent_1", "kind": "agent", "position": [1.0, 2.0]}
            ],
        },
    )
    assert placed.actor_key == "personainst_dev_agent_1"


def test_a_retire_does_not_take_a_neighbouring_generic_desk():
    """The second property the ruling depends on, VERIFIED rather than assumed.

    ``archive_actors_for_instance`` selects on ``_instance_bound_actor``, which
    answers ``False`` for an actor carrying no ``persona_instance_id``. A
    generic desk actor names no instance — its key is ``desk_<8 base36>`` — so
    a retire of an agent standing beside it cannot reach it. The audit ASSERTED
    this; this proves it, which is the difference the task asked for.

    POSITIVE CONTROL, and it is the load-bearing half: the agent's OWN actor IS
    archived by the same call. Without it, "the desk survived" is satisfied by a
    retire that archived nothing at all — a prune that silently matched no rows
    would look identical to a prune that correctly spared one.

    KILLING MUTATION, applied and recorded red 2026-09-18: make
    ``_instance_bound_actor`` answer ``True`` for an unbound actor
    (``if not bound: return True``), which is the code shape of "put the desk's
    key into the retire archive set". Observed:
    ``assert ['desk_aaaaaaaa', 'personainst_goal9_qa'] == ['personainst_goal9_qa']``
    — the desk joined the archive list, and the control's own key is still in
    it, which is what says the retire ran rather than that it matched nothing.
    """

    ws = _make_workspace()
    store = OfficeStore()

    store.upsert_actor(ws, _generic_desk_payload("desk_aaaaaaaa"))
    store.upsert_actor(
        ws,
        {
            "persona_id": "qa",
            "persona_instance_id": "personainst_goal9_qa",
            "items": [
                {
                    "item_id": "personainst_goal9_qa",
                    "kind": "agent",
                    "position": [5.0, 5.0],
                    "folder": "Agents",
                }
            ],
        },
    )

    result = store.archive_actors_for_instance("persona_personainst_goal9_qa")

    # POSITIVE CONTROL: the retire DID run and DID take the agent's actor.
    assert result["archived_actor_keys"] == ["personainst_goal9_qa"]
    assert result["failed"] == 0
    assert not store.actor_exists(ws, "personainst_goal9_qa")

    # And the desk beside it is untouched — still live, still a desk, not merely
    # still named somewhere.
    assert store.actor_exists(ws, "desk_aaaaaaaa")
    survivor = store.get_actor(ws, "desk_aaaaaaaa")
    assert [i.kind for i in survivor.items] == ["desk"]
    assert "desk_aaaaaaaa" not in store.get_surface(ws).archived_actor_keys


# ── prune lane (plan §4.3) ─────────────────────────────────────────────────


def test_archive_actors_for_instance_archives_only_instance_bound():
    ws = _make_workspace()
    store = OfficeStore()
    store.upsert_actor(ws, _actor_payload("dev"))  # persona-keyed: survives
    store.upsert_actor(ws, _actor_payload("qa", persona_instance_id="personainst_goal9_qa"))
    result = store.archive_actors_for_instance("persona_personainst_goal9_qa")
    # The IDENTITIES leave with the counts (plan D7): ``agent retire``'s ack
    # names every actor it took off the level, and a count cannot be named.
    assert result == {
        "archived": 1,
        "failed": 0,
        "archived_actor_keys": ["personainst_goal9_qa"],
        "failures": [],
    }
    assert store.actor_exists(ws, "dev")
    assert not store.actor_exists(ws, "personainst_goal9_qa")
    surface = store.get_surface(ws)
    assert "personainst_goal9_qa" in surface.archived_actor_keys


def test_a_prune_that_could_not_archive_its_match_says_so_instead_of_zero(monkeypatch):
    """``0`` used to mean two opposite things: nothing matched, and every match
    failed.

    The per-actor swallow STAYS — a prune must not die on one bad file, and the
    persona-instance retirement it serves is authoritative with or without the
    office projection — so the honest repair is a failure count, not a raise. The
    archive call is made to fail directly (a share violation is what this
    platform actually raises here) because the subject is the LOOP's accounting,
    not any one cause of failure.

    *Probed fields:* ``archived == 0`` AND ``failed == 1``, together. The old
    bare-int return could express only the first, and that is the very same
    answer "nothing matched" gives.
    """

    ws = _make_workspace()
    store = OfficeStore()
    store.upsert_actor(ws, _actor_payload("qa", persona_instance_id="personainst_goal9_qa"))

    def _refuse(*_args, **_kwargs):
        raise OSError("share violation")

    monkeypatch.setattr(store, "remove_actor", _refuse)

    result = store.archive_actors_for_instance("persona_personainst_goal9_qa")

    assert result["archived"] == 0
    assert result["failed"] == 1
    assert result["archived_actor_keys"] == []
    # And WHICH actor, and WHY — the half `agent retire` puts on its ack as
    # ``office_archive_failures``. A count answers "something is still on the
    # canvas"; only the key answers "that one is".
    assert result["failures"] == [
        {
            "actor_key": "personainst_goal9_qa",
            "workspace_id": ws,
            "error": "OSError: share violation",
        }
    ]
    # The loop survived the failure rather than propagating it, so the placement
    # is still there for an operator to prune again.
    assert store.actor_exists(ws, "personainst_goal9_qa")


# ── snapshot projection (W-H3) ─────────────────────────────────────────────


def test_snapshot_offices_section_and_conflict_parity_warning():
    ws = _make_workspace()
    store = OfficeStore()
    store.upsert_actor(ws, _actor_payload("dev"))
    sidecar = paths.office_conflict_path(ws, "dev")
    sidecar.parent.mkdir(parents=True, exist_ok=True)
    sidecar.write_text('{"actor_key": "dev", "kind": "both_changed", "remote_actor": null}', encoding="utf-8")

    snap = build_snapshot(event_log=EventLog())
    offices = snap["offices"]
    assert ws in offices
    row = offices[ws]
    assert row["actor_count"] == 1
    assert row["actors"][0]["actor_key"] == "dev"
    assert row["actors"][0]["items"][0]["position"] == [1.5, 2.0]
    assert row["conflict_actor_keys"] == ["dev"]
    assert row["orphaned"] is False
    codes = {w.get("code") for w in snap["parity"]["warnings"]}
    assert "office_actor_conflict" in codes
    assert snap["parity"]["contract_version"] == SNAPSHOT_CONTRACT_VERSION


# ── dry-run: full validation, zero writes, zero events (mutation-arg trap) ──
#
# The Stage-42 mutation scaffolding auto-registers ``--dry-run`` on every office
# verb; each MUST actually honor it. A dry-run performs full validation incl. the
# revision guard, returns the WOULD-BE result, and leaves the store byte-identical
# with no EventLog event (dry-runs are not mutations). Each test asserts the actor
# / surface file is byte-identical across the dry-run AND that no event was
# appended, then that the real run mutates + emits.


def _office_event_count() -> int:
    return sum(1 for _ in EventLog().iter_from_offset(0))


def test_upsert_dry_run_is_byte_identical_and_eventless():
    ws = _make_workspace()
    store = OfficeStore()
    store.upsert_actor(ws, _actor_payload("dev"))
    path = paths.office_actor_path(ws, "dev")
    before_bytes = path.read_bytes()
    before_events = _office_event_count()

    would_be = store.upsert_actor(ws, _actor_payload("dev"), dry_run=True)
    assert would_be.revision == 2, "dry-run must report the would-be (bumped) revision"
    assert path.read_bytes() == before_bytes, "dry-run must not rewrite the actor file"
    assert _office_event_count() == before_events, "dry-run must emit no event"

    # The real run mutates + emits. TWO events, not one: the S7-A office leg
    # pairs every actor-only upsert with an ``office_actor`` ``state.patched``
    # from inside the same lock (``OfficeStore._emit_actor_patch``). Asserted by
    # TYPE rather than as ``+2`` so the pairing is the thing under test — a bare
    # count would go green again if either half were replaced by an unrelated
    # event.
    real = store.upsert_actor(ws, _actor_payload("dev"))
    assert real.revision == 2
    assert path.read_bytes() != before_bytes
    emitted = [event.type for _, event in EventLog().iter_from_offset(0)][before_events:]
    assert emitted == ["state.patched", "office.actor.upserted"]


def test_upsert_dry_run_on_fresh_office_creates_nothing():
    ws = _make_workspace()
    store = OfficeStore()
    before_events = _office_event_count()
    would_be = store.upsert_actor(ws, _actor_payload("dev"), dry_run=True)
    assert would_be.actor_key == "dev"
    assert not store.actor_exists(ws, "dev"), "dry-run created an actor file"
    assert not store.surface_exists(ws), "dry-run lazily created the surface"
    assert _office_event_count() == before_events, "dry-run must emit no event"


def test_upsert_dry_run_still_enforces_revision_guard_and_validation():
    ws = _make_workspace()
    store = OfficeStore()
    actor = store.upsert_actor(ws, _actor_payload("dev"))
    with pytest.raises(StaleRevision):
        store.upsert_actor(ws, _actor_payload("dev"), expect_revision=actor.revision + 5, dry_run=True)
    with pytest.raises(ValueError):
        store.upsert_actor(ws, {"persona_id": "dev", "items": []}, dry_run=True)


def test_remove_dry_run_is_byte_identical_and_eventless():
    ws = _make_workspace()
    store = OfficeStore()
    created = store.upsert_actor(ws, _actor_payload("dev"))
    path = paths.office_actor_path(ws, "dev")
    before_bytes = path.read_bytes()
    before_events = _office_event_count()

    would_be = store.remove_actor(ws, "dev", dry_run=True)
    assert would_be.state == "archived"
    assert would_be.revision == created.revision + 1
    assert store.actor_exists(ws, "dev"), "dry-run archived the actor for real"
    assert not paths.office_archived_actor_path(ws, "dev").exists()
    assert path.read_bytes() == before_bytes
    assert _office_event_count() == before_events

    # The real run archives + emits. TWO events since 2026-08-16, for exactly
    # the reason the sibling upsert test above states: an archive is now PAIRED
    # with an ``office_actor`` ``state.patched`` (op ``remove``) from inside the
    # same lock, so ``office.actor.removed`` can be covered without shipping a
    # promoted frame whose office row never arrives (office fold-promotion plan
    # §V2/O-H1). Asserted by TYPE rather than as ``+2``, matching the upsert
    # test: a bare count goes green again if either half is replaced by an
    # unrelated event.
    removed = store.remove_actor(ws, "dev")
    assert removed.state == "archived"
    assert not store.actor_exists(ws, "dev")
    emitted = [event.type for _, event in EventLog().iter_from_offset(0)][before_events:]
    assert emitted == ["state.patched", "office.actor.removed"]


def test_restore_dry_run_is_byte_identical_and_eventless():
    ws = _make_workspace()
    store = OfficeStore()
    store.upsert_actor(ws, _actor_payload("dev"))
    store.remove_actor(ws, "dev")
    archive_path = paths.office_archived_actor_path(ws, "dev")
    before_bytes = archive_path.read_bytes()
    before_events = _office_event_count()

    would_be = store.restore_actor(ws, "dev", dry_run=True)
    assert would_be.state == "active"
    assert archive_path.exists(), "dry-run consumed the archive copy"
    assert not store.actor_exists(ws, "dev"), "dry-run restored the actor for real"
    assert archive_path.read_bytes() == before_bytes
    assert _office_event_count() == before_events

    restored = store.restore_actor(ws, "dev")
    assert restored.state == "active"
    assert store.actor_exists(ws, "dev")
    assert _office_event_count() == before_events + 1


def test_set_folders_dry_run_is_byte_identical_and_eventless():
    ws = _make_workspace()
    store = OfficeStore()
    store.ensure_surface(ws)
    surface_path = paths.office_surface_path(ws)
    before_bytes = surface_path.read_bytes()
    before_events = _office_event_count()
    before_revision = store.get_surface(ws).revision

    would_be = store.update_surface(ws, folders=["West Wing"], dry_run=True)
    assert "West Wing" in would_be.folders, "dry-run must report the would-be folders"
    assert would_be.revision == before_revision + 1
    assert surface_path.read_bytes() == before_bytes
    assert _office_event_count() == before_events
    assert store.get_surface(ws).revision == before_revision

    updated = store.update_surface(ws, folders=["West Wing"])
    assert "West Wing" in updated.folders
    assert surface_path.read_bytes() != before_bytes
    # TWO events, not one, since WV-H3 (2026-08-16): the ``office_surface``
    # ``state.patched`` row rides inside the lock beside its domain event, which
    # is what lets a folder-change batch be promoted instead of demoting the
    # whole thing to a full core. The DRY RUN's count above is the assertion
    # this test is about, and it is unchanged — a preview that logged either of
    # them would be claiming a revision the store does not hold.
    assert _office_event_count() == before_events + 2


def test_resolve_conflict_dry_run_leaves_sidecar_and_is_eventless():
    ws = _make_workspace()
    store = OfficeStore()
    store.upsert_actor(ws, _actor_payload("dev"))
    sidecar = paths.office_conflict_path(ws, "dev")
    sidecar.parent.mkdir(parents=True, exist_ok=True)
    sidecar.write_text('{"actor_key": "dev", "kind": "both_changed", "remote_actor": null}', encoding="utf-8")
    actor_path = paths.office_actor_path(ws, "dev")
    before_actor_bytes = actor_path.read_bytes()
    before_events = _office_event_count()

    would_be = store.resolve_conflict(ws, "dev", take="local", dry_run=True)
    assert would_be is not None and would_be.actor_key == "dev"
    assert sidecar.exists(), "dry-run archived the conflict sidecar for real"
    assert actor_path.read_bytes() == before_actor_bytes
    assert _office_event_count() == before_events
    # A dry-run does not unblock writes: the sidecar still guards upserts.
    with pytest.raises(SyncConflict):
        store.upsert_actor(ws, _actor_payload("dev"))

    resolved = store.resolve_conflict(ws, "dev", take="local")
    assert resolved is not None
    assert not sidecar.exists()
    # TWO since w12/l3 (2026-09-04): the domain event, and the ``office_conflict``
    # ``state.patched`` that carries the key leaving ``conflict_actor_keys``.
    # ``take="local"`` writes no actor, so the ledger row is the whole of what
    # this arm puts on the wire — which is exactly why it exists.
    assert _office_event_count() == before_events + 2


# --------------------------------------------------------------------------- #
# MC-8 / P10 — an office is not minted for a workspace no record resolves
# --------------------------------------------------------------------------- #
#
# ``ensure_surface`` authored a default surface for ANY id that passed
# ``_safe_id``. The measured consequence (EG-0.1): a leaked test context minted a
# LIVE office in the operator's runtime root — 135 events, a ``revision 67``
# actor file — for a workspace id no verb ever authorised. The parity warning
# describes that afterwards; these cases are the door.


def test_ensure_surface_refuses_an_id_no_workspace_record_resolves():
    """Refused, and refused BEFORE anything happened.

    Three separate claims, because "it refused" and "it refused before doing
    anything" are different statements and only the second makes it safe:

    *Kills, one per claim (C30):*

    * A — restore the lazy mint (delete the ``workspace_resolves`` guard): the
      ``pytest.raises`` reds, because nothing refuses at all;
    * B — raise AFTER ``_write_surface``: the raises still passes and the
      DIRECTORY assertion reds;
    * C — raise after ``self._emit``: the raises and the directory both pass and
      the EVENT assertion reds.
    """

    store = OfficeStore()
    before = _event_types()

    with pytest.raises(WorkspaceUnresolved) as excinfo:
        store.ensure_surface("ws_nope")

    assert excinfo.value.code == "workspace_unresolved", (
        "the refusal carries no machine reason, so every envelope that maps it "
        "falls back to internal_error — an operator refusal reported as a crash"
    )
    assert excinfo.value.safe_details.get("workspace_id") == "ws_nope", (
        "the refusal does not name the id it refused, so an operator holding a "
        "typo cannot tell which of their ids was rejected"
    )
    assert not paths.office_dir("ws_nope").exists(), (
        "the refusal left an office directory on disk. A refused write that "
        "still authored the surface is the defect wearing an exception."
    )
    assert _event_types() == before, (
        "the refusal emitted an event. An office.surface.created for a surface "
        "that does not exist is worse than the silent mint it replaced: every "
        "watermark-gated consumer folds a create for a workspace nobody has."
    )


def test_a_resolving_workspace_is_unaffected_archived_included():
    """The refusal must not touch the ordinary path, and archived still resolves.

    An archived workspace is a REAL record. Its office is not an orphan and
    refusing it would break the surface of a workspace the operator can restore.

    *Kill:* derive the predicate with ``list_all()`` instead of
    ``list_all(include_archived=True)`` in ``workspace_resolves``. The live case
    stays green and the archived one reds — which is why both are driven here
    rather than only the obvious one.
    """

    live = _make_workspace("Live Workspace")
    archived = WorkspaceStore().create(name="Archived Workspace")
    WorkspaceStore().archive(archived.id)

    store = OfficeStore()
    assert store.ensure_surface(live).workspace_id == live
    assert store.ensure_surface(archived.id).workspace_id == archived.id, (
        "an ARCHIVED workspace stopped resolving, so its office can no longer be "
        "authored or read; archiving is the reversible path and this makes it "
        "quietly destructive"
    )


def test_an_existing_surface_is_still_returned_after_its_workspace_disappears():
    """THE MUTATION MOST LIKELY TO BE MISSED, and the one that breaks the live store.

    The refusal guards CREATION, never reading. An office whose workspace record
    has since gone must still be returned: the projection, the ``orphaned_office``
    parity warning and ``archive_orphaned_surface`` all read through
    ``ensure_surface``, and that verb's entire precondition is
    ``workspace_resolves() is False``. A refusal placed above the
    ``surface_exists`` short-circuit would make the live orphan UNARCHIVABLE by
    the one verb that exists to archive it — the operator's only exit, closed by
    the fix meant to protect them.

    *Kill:* move the ``workspace_resolves`` refusal above the ``surface_exists``
    short-circuit. This reds; the refusal case above stays green, which is
    exactly why it cannot stand in for this one.
    """

    ws = _make_workspace("Doomed Workspace")
    store = OfficeStore()
    store.ensure_surface(ws)
    store.upsert_actor(ws, _actor_payload("dev"))
    paths.workspace_path(ws).unlink()
    assert not store.workspace_resolves(ws), "the fixture did not orphan the office"

    surface = store.ensure_surface(ws)
    assert surface.workspace_id == ws, (
        "an EXISTING office surface stopped being readable once its workspace "
        "record went away, so an operator cannot project, warn about or archive "
        "the orphan they already have"
    )
    assert store.archive_orphaned_surface(ws, dry_run=True)["workspace_id"] == ws, (
        "the archive verb — whose precondition is that the workspace does NOT "
        "resolve — can no longer preview the surface it exists to move"
    )


def test_the_template_clone_is_unaffected_because_it_creates_the_record_first():
    """The one caller worth reading rather than assuming.

    ``workspace_template._copy_office`` calls ``ensure_surface`` on the
    DESTINATION, so a clone into a workspace whose record did not yet exist would
    now refuse. It does not: the CLI create verb creates the workspace record and
    only then copies content ("Office/board content copies AFTER the workspace
    exists", ``hermes_cli/harness.py``). Both directions are driven so the pin
    states the behaviour rather than only the happy half.

    *Kill:* the ordering change this depends on — copy into a destination whose
    record does not exist yet. That is the second half below, and it is asserted
    as a REFUSAL rather than left undefined, so a future caller that clones
    before creating gets a named failure instead of a silent orphan.
    """

    from agent_runtime.workspace_template import copy_workspace_content

    source = _make_workspace("Template Source")
    OfficeStore().upsert_actor(source, _actor_payload("dev"))

    dest = WorkspaceStore().create(name="Template Destination")
    outcome = copy_workspace_content(source, dest.id, scopes=("office",))
    assert outcome["copied"]["office_actors"] >= 1, outcome
    assert OfficeStore().surface_exists(dest.id)

    with pytest.raises(WorkspaceUnresolved):
        copy_workspace_content(source, "ws_unrecorded_destination", scopes=("office",))
    assert not paths.office_dir("ws_unrecorded_destination").exists(), (
        "a clone into an unrecorded destination authored the office anyway"
    )


def test_the_refusal_reaches_the_operator_typed_and_not_as_an_internal_error():
    """What an operator actually sees, on the lane that can actually reach this.

    WHERE IT SURFACES, established rather than assumed. The RPC office arms
    (``runtime.office.upsert`` / ``…surface_update``) CANNOT reach this refusal:
    each pre-checks ``store.surface_exists`` and returns ``ERR_NOT_FOUND`` with
    ``reason=workspace_not_found`` before the store is asked to author anything.
    A ``WorkspaceUnresolved`` handler on those arms would be a catch that can
    never fire, so none was added — an always-green production branch is the same
    defect as an always-green test. The reachable lane is the CLI/argv one, and
    that is what this pins.

    Two claims, two kills:

    * the verb PROPAGATES the refusal to the harness dispatch boundary — it is
      not swallowed and not converted to a generic failure. ``hermes_cli.main``
      forks every exception out of a ``harness`` command into
      ``emit_harness_error`` rather than letting a traceback be the response, so
      reaching that boundary is what makes the envelope below the operator's
      view. *Kill:* wrap the store call in ``except Exception: return 1`` in
      ``harness_parts/office.py`` — the raises reds;
    * the taxonomy renders it TYPED. *Kill:* delete the ``WorkspaceUnresolved``
      row from ``_error_code_for_exception``. The exception is an
      ``AgentRuntimeError``, so it falls through to the catch-all and the
      envelope reads ``internal_error`` at exit 1 — an operator refusal reported
      as a harness crash, which is the exact defect that row's neighbour
      (``ArchiveUnreadable``) was added to fix. Both assertions below red.
    """

    import argparse
    import json as _json

    from hermes_cli.harness import build_parser
    from hermes_cli.harness_support import ERROR_EXIT_CODES, emit_harness_error

    parser = argparse.ArgumentParser()
    build_parser(parser.add_subparsers(dest="command"))
    args = parser.parse_args([
        "harness", "office", "actor-upsert",
        "--workspace", "ws_typo_here",
        "--actor-json", _json.dumps(
            {"persona_id": "qa", "items": [{"item_id": "qa", "kind": "agent", "position": [1, 1]}]}
        ),
        "--json",
    ])

    with pytest.raises(WorkspaceUnresolved) as excinfo:
        args.func(args)

    exit_code = emit_harness_error(excinfo.value, args=args)
    assert exit_code == ERROR_EXIT_CODES["workspace_unresolved"] == 3, (
        f"the refusal exits {exit_code}. Without its taxonomy row it falls to "
        "the AgentRuntimeError catch-all and exits 1 as internal_error — a "
        "refusal an operator caused, reported as a harness crash."
    )
    assert not paths.office_dir("ws_typo_here").exists(), (
        "the CLI write authored the office it was refusing"
    )


def merge_archived_ledgers(peer_keys, local_keys):
    """The union adopt_remote_surface spends: sync_merge's rule at the office cap."""
    return sync_merge.merge_archived_ledgers(peer_keys, local_keys, cap=ARCHIVED_LEDGER_CAP)


# ── C1: the archived-ledger union (M4) ─────────────────────────────────────


def test_the_ledger_union_leads_with_the_peer_so_a_subset_rehashes_identically():
    """C1's hash-neutrality property, at the level it lives at. When the local
    ledger is a SUBSET of the peer's, the union must BE the peer's list — same
    members, same order — or ``office_content_hash`` disagrees with the remote
    and every converged surface adopts into a permanent phantom local edit."""

    peer = ["a", "b", "c"]
    assert merge_archived_ledgers(peer, ["b"]) == peer
    assert merge_archived_ledgers(peer, []) == peer
    assert merge_archived_ledgers(peer, list(peer)) == peer


def test_local_only_keys_land_on_the_cap_surviving_tail():
    """The cap keeps the TAIL (``[-ARCHIVED_LEDGER_CAP:]``, the idiom
    ``_archive_actor_locked`` spends), so the union must put local-only keys
    there: this store is the only witness to a resurrection it alone archived,
    while a key the peer holds is guarded on the peer too."""

    assert merge_archived_ledgers(["a", "b"], ["z"]) == ["a", "b", "z"]

    over_cap = merge_archived_ledgers(
        [f"peer{i}" for i in range(ARCHIVED_LEDGER_CAP)], ["local_only"]
    )
    assert len(over_cap) == ARCHIVED_LEDGER_CAP
    assert over_cap[-1] == "local_only"
    assert "peer0" not in over_cap


def test_the_union_deduplicates_on_first_occurrence():
    """A repeat cannot be minted locally (``_archive_actor_locked`` guards it),
    so one can only have arrived from a peer — and carrying it forward would
    spend cap budget on a key already guarded."""

    assert merge_archived_ledgers(["a", "a", "b"], ["b", "c", "c"]) == ["a", "b", "c"]


# ── C4: the retire lane's reads join the completeness discipline (M8) ───────


def test_a_prune_over_an_unreadable_directory_reports_the_shortfall():
    """C4 (M8). The prune walked the actor ROWS alone, which drop what could not
    decode and reports the remainder as complete — so a bound desk whose file
    would not open was neither archived nor counted, and ``failures: []`` claimed
    every bound actor was off the level. That empty list is the retire ack's
    positive claim (``agent_retire``'s own docstring), and it was a false one.

    The loop still survives: the readable bound desk is archived in the same
    call, which is what stops the opposite over-correction (refusing the whole
    prune) from passing here.
    """

    ws = _make_workspace()
    store = OfficeStore()
    store.upsert_actor(ws, _actor_payload("qa", persona_instance_id="personainst_c4_qa"))
    (paths.office_actors_dir(ws) / "broken.json").write_text("{not json", encoding="utf-8")

    result = store.archive_actors_for_instance("persona_personainst_c4_qa")

    assert result["archived"] == 1
    assert result["archived_actor_keys"] == ["personainst_c4_qa"]
    assert not store.actor_exists(ws, "personainst_c4_qa")
    # ``actor_key: None`` — the key of the file that would not decode is exactly
    # what could not be decoded, so naming one would be inventing it. The FILE
    # can be named, and now is: the scan carries the paths it skipped, so the
    # row an operator reads points at something they can open.
    assert result["failures"] == [
        {
            "actor_key": None,
            "workspace_id": ws,
            "error": "ActorsUnreadable: 1 (actors/broken.json)",
        }
    ]
    assert result["failed"] == 1


def test_the_replays_evidence_read_refuses_a_short_answer():
    """C4 (M8), the read-only half. ``archived_actor_keys_for_instance`` is the
    replay's EVIDENCE — the answer to "which desks are off the level" — and it
    was built from the actor ROWS alone. A bound desk whose archive copy will not
    decode came back as "not archived by this instance", which is the one thing
    an empty list is supposed to rule out. A short list here is not a smaller
    truth, it is a different claim."""

    ws = _make_workspace()
    store = OfficeStore()
    store.upsert_actor(ws, _actor_payload("qa", persona_instance_id="personainst_c4_ev"))
    store.remove_actor(ws, "personainst_c4_ev")
    assert store.archived_actor_keys_for_instance("persona_personainst_c4_ev") == [
        "personainst_c4_ev"
    ]

    (paths.office_archive_dir(ws) / "broken.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(ActorsUnreadable):
        store.archived_actor_keys_for_instance("persona_personainst_c4_ev")


# ── H-H12: the store records what an item was minted as ──────────────────────


def _one_item(persona_id: str, item_id: str, kind: str) -> dict:
    return {
        "persona_id": persona_id,
        "items": [
            {
                "item_id": item_id,
                "persona_id": persona_id,
                "kind": kind,
                "position": [1.0, 2.0],
            }
        ],
    }


def test_the_minted_kind_is_stamped_once_and_never_moves_again():
    """H-H12. ``kind`` is mutable; what an item was MINTED as is not.

    Every upsert re-sends the whole item list, so any later write may re-spell
    an agent's item as a desk and the store accepts it — which left "was this
    really an agent?" a question with no stored answer, and the doctor's
    desk-litter classifier asking the ``item_id`` STRING for launcher naming
    conventions that nothing enforces.

    RED-FIRST against the arm this replaces: before it, ``minted_kind`` did not
    exist and this reds on the attribute.

    ANTI-VACUITY: the re-kinding write is a REAL store write, and ``kind`` is
    asserted to have actually moved. A stamp that simply copied ``kind`` every
    time would satisfy the first assertion and fail the second pair — which is
    the whole difference between recording a mint and echoing the last write.

    KILLING MUTATION: stamp from ``item.kind`` unconditionally (drop the
    ``on_record`` lookup in ``_stamp_minted_kinds``) and the third assertion
    reds.
    """

    ws = _make_workspace()
    store = OfficeStore()

    minted = store.upsert_actor(ws, _one_item("dev", "dev_thing", "agent"))
    assert [(i.kind, i.minted_kind) for i in minted.items] == [("agent", "agent")]

    rekinded = store.upsert_actor(ws, _one_item("dev", "dev_thing", "desk"))
    assert rekinded.items[0].kind == "desk", "the re-kinding write did not land"
    assert rekinded.items[0].minted_kind == "agent"
    # And it is DURABLE, not an in-memory artefact of the returned object.
    assert store.get_actor(ws, "dev").items[0].minted_kind == "agent"


def test_a_new_item_id_is_minted_fresh_beside_a_sticky_one():
    """Stickiness is per ITEM ID, not per actor.

    An actor gains and loses items over its life. Carrying one item's recorded
    mint onto another — or refusing to stamp a genuinely new item because the
    actor already existed — would both be wrong, and the second is the easier
    mistake to write.

    KILLING MUTATION: key ``on_record`` on anything but ``item_id`` (the actor,
    the kind, the index) and one of the two rows below reds.
    """

    ws = _make_workspace()
    store = OfficeStore()
    # Minted a DESK, so the two rows below cannot both be explained by one rule.
    store.upsert_actor(ws, _one_item("dev", "dev_thing", "desk"))

    grown = store.upsert_actor(
        ws,
        {
            "persona_id": "dev",
            "items": [
                # Re-kinded: sticky, so it must still read ``desk``.
                {
                    "item_id": "dev_thing",
                    "persona_id": "dev",
                    "kind": "agent",
                    "position": [1.0, 2.0],
                },
                # Never seen before: stamped from the kind it arrives with.
                {
                    "item_id": "dev_newcomer",
                    "persona_id": "dev",
                    "kind": "agent",
                    "position": [3.0, 4.0],
                },
            ],
        },
    )

    assert {i.item_id: i.minted_kind for i in grown.items} == {
        "dev_thing": "desk",
        "dev_newcomer": "agent",
    }


def test_a_client_cannot_declare_what_its_item_was_minted_as():
    """The field is the STORE's record, never the caller's assertion.

    A ``minted_kind`` a payload could set would be exactly the self-declaration
    this field replaced an id-spelling with — the classifier would be right back
    to trusting something the writer controls. ``_normalize_item`` does not read
    the key, so it cannot ride in.

    KILLING MUTATION: read ``minted_kind`` off ``raw`` in ``_normalize_item``
    and this reds.
    """

    ws = _make_workspace()
    store = OfficeStore()
    payload = _one_item("dev", "dev_thing", "desk")
    payload["items"][0]["minted_kind"] = "agent"

    actor = store.upsert_actor(ws, payload)

    assert actor.items[0].minted_kind == "desk"


def test_a_re_added_key_carries_its_recorded_mint_forward_from_the_archive():
    """A resurrection is the same item, not a second one.

    The same precedence ``base_revision`` uses one line down, and for the same
    reason: an actor re-added after a removal carries its history forward rather
    than starting a fresh one. A mint that reset here would hand an operator a
    clean-looking desk whose agent origin the store had just forgotten.

    KILLING MUTATION: pass only ``existing`` to ``_stamp_minted_kinds`` and this
    reds — ``existing`` is ``None`` on the re-add, which is precisely the arm
    ``archived`` exists for.
    """

    ws = _make_workspace()
    store = OfficeStore()
    # Instance-keyed, so the class-key fence (a separate consent, deliberately
    # not implied by ``resurrect``) is not what this test is about.
    minted = _one_item("dev", "dev_thing", "agent")
    minted["persona_instance_id"] = "personainst_dev_mint"
    store.upsert_actor(ws, minted)
    store.remove_actor(ws, "personainst_dev_mint")

    re_added = _one_item("dev", "dev_thing", "desk")
    re_added["persona_instance_id"] = "personainst_dev_mint"
    restored = store.upsert_actor(ws, re_added, resurrect=True)

    assert restored.items[0].minted_kind == "agent"


def test_the_recorded_mint_is_not_content_and_never_moves_the_sync_hash():
    """H-H12's blip, closed instead of accepted.

    ``office_content_hash`` is what the realm-sync lane compares to decide that
    an actor changed. ``minted_kind`` lives inside ``items``, which
    ``_HASH_EXCLUDE`` cannot reach, so on the first write after the upgrade
    every actor's hash would have moved once with nothing observable behind it —
    an unmeasured drift spike on the one lane whose whole job is detecting real
    drift — and any peer still decoding the field away would have disagreed with
    this install for as long as it stayed unupgraded.

    ANTI-VACUITY: the hash is asserted against the pre-field payload computed
    HERE, from the same encoder, with the key absent — not against a golden
    string that would rot, and not merely against itself. And ``kind`` is
    asserted to still move it, so the exclusion is proved narrow: it hides the
    provenance, never the content.

    KILLING MUTATION: drop the ``items`` re-filter from ``office_content_hash``
    and the first assertion reds.
    """

    import hashlib
    import json

    from agent_runtime.serde import to_jsonable

    ws = _make_workspace()
    store = OfficeStore()
    stamped = store.upsert_actor(ws, _one_item("dev", "dev_thing", "agent"))
    assert stamped.items[0].minted_kind == "agent", "fixture did not stamp"

    # What this function encoded before the field existed: the same payload with
    # the key simply absent.
    payload = {
        key: value
        for key, value in to_jsonable(stamped).items()
        if key not in office_models._HASH_EXCLUDE
    }
    payload["items"] = [
        {k: v for k, v in item.items() if k != "minted_kind"} for item in payload["items"]
    ]
    pre_field = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
            "utf-8"
        )
    ).hexdigest()

    assert office_models.office_content_hash(stamped) == pre_field, (
        "stamping the mint moved the sync hash: every actor reports as a local edit once"
    )

    # ...and the exclusion is NARROW: ``kind`` is content and still moves it.
    rekinded = store.upsert_actor(ws, _one_item("dev", "dev_thing", "desk"))
    assert rekinded.items[0].minted_kind == "agent"
    assert office_models.office_content_hash(rekinded) != pre_field


# ── the unaimed placement's slot, resolved under the lock (H-H10 / M10) ──────


def _unaimed_payload(persona_id: str, *, instance: str, folder: str = "Agents") -> dict:
    """A payload with NO ``position`` key — the shape ``placement_actor_payload``
    builds when the client did not aim."""

    return {
        "persona_id": persona_id,
        "persona_instance_id": instance,
        "items": [
            {
                "item_id": instance,
                "persona_id": persona_id,
                "kind": "agent",
                "folder": folder,
            }
        ],
    }


def test_a_positionless_item_is_refused_when_no_policy_came_with_it():
    """The pairing is enforced by the STORE, not by convention at the caller.

    ``placement_actor_payload`` omits the key rather than inventing an origin,
    so this refusal is the only thing standing between "the caller forgot the
    policy" and an agent silently placed at (0, 0) forever.

    *Mutation:* default the missing point to ``(0.0, 0.0)`` inside
    ``_item_point``. The mutant writes the actor and this raises nothing.
    """

    ws = _make_workspace()
    store = OfficeStore()
    with pytest.raises(ValueError, match="item position must be"):
        store.upsert_actor(ws, _unaimed_payload("qa", instance="personainst_m10_a"))
    assert store.scan_actors(ws).actors == []


def test_the_policy_answers_from_inside_the_lock_and_its_point_is_what_is_written():
    """The hook's answer reaches the FILE, and it reaches it having seen the
    floor the write lands beside.

    *Mutation:* ignore ``position_policy`` and read ``raw.get("position")``
    anyway — the write then refuses (no key), so the surviving mutant is the
    subtler one: call the policy but discard its answer. Both are caught by the
    stored coordinates, which is why this asserts the file rather than the
    return value.
    """

    ws = _make_workspace()
    store = OfficeStore()
    seen: list = []

    def _policy(scan):
        seen.append(scan)
        return (7.25, -3.5)

    actor = store.upsert_actor(
        ws,
        _unaimed_payload("qa", instance="personainst_m10_b"),
        position_policy=_policy,
    )
    assert [float(v) for v in actor.items[0].position] == [7.25, -3.5]
    stored = store.get_actor(ws, actor.actor_key)
    assert [float(v) for v in stored.items[0].position] == [7.25, -3.5]
    assert len(seen) == 1


def test_the_policy_is_handed_the_scan_and_not_a_bare_list():
    """The completeness question stays ASKABLE at the seam that can answer it.

    A store that unwrapped ``scan.actors`` here would drop the unreadable count
    on the floor at exactly the boundary the whole ``ActorScan`` shape exists to
    stop dropping it at — the policy could then never tell a floor it read whole
    from one it read half of.

    *Mutation:* pass ``self.scan_actors(wsid).actors``. ``scan.unreadable``
    raises ``AttributeError`` on a list and the mutant convicts.
    """

    ws = _make_workspace()
    store = OfficeStore()
    store.upsert_actor(ws, _actor_payload("dev"))
    (paths.office_actors_dir(ws) / "broken.json").write_text("{not json", encoding="utf-8")
    seen: list = []

    def _policy(scan):
        seen.append((len(scan.actors), scan.unreadable))
        return (0.0, 0.0)

    store.upsert_actor(
        ws,
        _unaimed_payload("qa", instance="personainst_m10_c"),
        position_policy=_policy,
    )
    assert seen == [(1, 1)]


def test_the_policy_sees_the_actor_set_the_write_lands_beside(monkeypatch):
    """M10's property, at the level it lives at: the scan the policy reads and
    the write that follows it are under ONE ``office_lock`` acquisition, so
    nothing can land in between.

    Proved by contending FROM INSIDE the policy: a second writer attempted while
    the hook is running must not be able to take the lock. Before H-H10 the
    equivalent read ran with the lock unheld, and that second writer landed —
    which is exactly how two unaimed creates came to share a slot.

    The deadline is shortened because the claim is "it could not get in", and
    the configured 15 s of proving that is 15 s of nothing happening. It also
    only refuses at all because H-H6 made the POSIX deadline reachable; on the
    old blocking ``flock`` this test would have deadlocked rather than passed
    or failed, which is why the two stages ship in that order.

    *Mutation:* resolve the policy BEFORE ``with office_lock(wsid)``. The
    contending write then succeeds inside the hook and ``blocked`` is False.
    """

    from agent_runtime import locks
    from agent_runtime.locks import HarnessLockUnavailable

    monkeypatch.setattr(locks, "_lock_timeout_seconds", lambda value: 0.2)

    ws = _make_workspace()
    store = OfficeStore()
    blocked: list = []

    def _policy(scan):
        try:
            OfficeStore().upsert_actor(
                ws,
                _actor_payload("rival", persona_instance_id="personainst_m10_rival"),
            )
            blocked.append(False)
        except HarnessLockUnavailable:
            blocked.append(True)
        return (1.0, 1.0)

    store.upsert_actor(
        ws,
        _unaimed_payload("qa", instance="personainst_m10_d"),
        position_policy=_policy,
    )
    assert blocked == [True], "a concurrent write reached the store mid-policy"


def test_a_multi_item_payload_is_refused_rather_than_guessed_at():
    """One point cannot answer for several items, and a store that picked one of
    them would be inventing a rule its caller never stated. Refused BEFORE
    ``ensure_surface``, so a refused call leaves the store as it found it.

    *Mutation:* apply the resolved point to ``raw_items[0]`` and leave the rest
    to their own keys. The mutant accepts a payload whose placement is half
    policy-chosen and half caller-chosen, with nothing saying which.
    """

    ws = _make_workspace()
    store = OfficeStore()
    payload = _unaimed_payload("qa", instance="personainst_m10_e")
    payload["items"].append(
        {"item_id": "second", "persona_id": "qa", "kind": "agent", "folder": "Agents"}
    )
    with pytest.raises(ValueError, match="position_policy resolves ONE item"):
        store.upsert_actor(ws, payload, position_policy=lambda scan: (0.0, 0.0))
    assert store.scan_actors(ws).actors == []


# ── typed per-key outcomes at the best-effort loops (H-H3) ──────────────────


def test_a_conflict_sidecar_that_would_not_decode_is_named_as_a_guess():
    """H-H3. The substitution stays; the silence goes.

    ``conflict_actor_keys`` answered a decode failure with ``path.stem`` and
    said nothing. The stem is ``actor_file_token(actor_key)`` — sanitised and,
    past 64 characters, truncated with a hash suffix — so for a long key it is
    not the actor key, and ``office resolve-conflict --actor <it>`` finds
    nothing. Both readers present these to an operator as keys to act on.

    *Mutation:* mint ``conflict_read`` in the ``except`` arm too. Every entry
    then claims to have been read out of a payload and ``unreadable`` answers 0.
    """

    ws = _make_workspace()
    store = OfficeStore()
    paths.office_conflict_path(ws, "dev").parent.mkdir(parents=True, exist_ok=True)
    paths.office_conflict_path(ws, "dev").write_text(
        '{"actor_key": "dev"}', encoding="utf-8"
    )
    (paths.office_conflicts_dir(ws) / "broken.json").write_text("{not json", encoding="utf-8")

    scan = store.scan_conflicts(ws)
    assert scan.keys == ["broken", "dev"]
    assert scan.unreadable == 1
    guessed = [o for o in scan.outcomes if not o.succeeded]
    assert [o.actor_key for o in guessed] == ["broken"]
    assert guessed[0].outcome.startswith("conflict_unreadable:")
    # The CLASS, never the message, in the token a program branches on.
    assert ":" in guessed[0].outcome and " " not in guessed[0].outcome


def test_a_readable_sidecar_with_no_actor_key_is_the_same_guess():
    """A payload that decoded fine and simply did not say is still a filename
    guess, and must not pass for a read key just because the JSON parsed.

    *Mutation:* fall through to ``conflict_read(workspace_id, key or path.stem)``.
    The keys list is identical, so only the outcome convicts — which is the
    point of having one.
    """

    ws = _make_workspace()
    store = OfficeStore()
    paths.office_conflicts_dir(ws).mkdir(parents=True, exist_ok=True)
    (paths.office_conflicts_dir(ws) / "silent.json").write_text("{}", encoding="utf-8")

    scan = store.scan_conflicts(ws)
    assert scan.keys == ["silent"]
    assert scan.unreadable == 1


def test_a_resolved_sidecar_is_not_a_conflict_and_is_never_read():
    """The skip is before the read, so a resolved sidecar cannot contribute an
    outcome of any kind — including a failure if it happened to be corrupt.

    *Mutation:* drop the ``.resolved.json`` skip. The resolved record shows up
    as a live conflict and the parity warning fires for work already done.
    """

    ws = _make_workspace()
    store = OfficeStore()
    paths.office_conflicts_dir(ws).mkdir(parents=True, exist_ok=True)
    (paths.office_conflicts_dir(ws) / "dev.resolved.json").write_text(
        "{not json", encoding="utf-8"
    )
    assert store.scan_conflicts(ws) == ([], [])


def test_the_prunes_ack_is_derived_from_its_outcomes_and_cannot_disagree():
    """H-H3. The four ack keys were two lists and two tallies kept in parallel;
    any one of them could drift from the others in silence. They are one typed
    list's projections now, and the counts are its lengths.

    Both arms in one workspace so the derivation is exercised across a mixed
    outcome set, which is the case a per-arm tally gets wrong.

    *Mutation:* return a hand-kept ``"archived": len(outcomes)``. The
    unreadable-scan row is not an archive, so the count over-reports by one.
    """

    ws = _make_workspace()
    store = OfficeStore()
    store.upsert_actor(ws, _actor_payload("qa", persona_instance_id="personainst_hh3_a"))
    (paths.office_actors_dir(ws) / "broken.json").write_text("{not json", encoding="utf-8")

    result = store.archive_actors_for_instance("persona_personainst_hh3_a")

    assert result["archived"] == len(result["archived_actor_keys"]) == 1
    assert result["failed"] == len(result["failures"]) == 1
    assert result["archived_actor_keys"] == ["personainst_hh3_a"]
    assert result["failures"] == [
        {
            "actor_key": None,
            "workspace_id": ws,
            "error": "ActorsUnreadable: 1 (actors/broken.json)",
        }
    ]


# ── the blank folder is filled at the WRITE boundary (H-H9 / M9) ────────────


@pytest.mark.parametrize(
    "kind,expected", [("agent", "Agents"), ("desk", "Desks"), (None, "Agents")]
)
def test_a_blank_folder_is_filled_with_the_kinds_default_when_it_is_written(kind, expected):
    """M9. One stored row means one thing.

    ``folder: ""`` persisted, and three readers then compensated for it
    independently — the layout policy before scanning, the launcher's decoder at
    decode, and a third reader again. "Which folder is this item in" had three
    answers derived three ways from a value that said nothing.

    The unknown-kind case is in the table on purpose: ``normalize_item_kind``
    maps every unrecognised spelling to ``agent``, so the folder must follow it
    rather than inventing a fourth folder at write time.

    *Mutation:* drop the ``or folder_for_kind(kind)`` fallback. The stored
    folder is ``""`` again and every arm of the table fails.
    """

    ws = _make_workspace()
    store = OfficeStore()
    item = {"item_id": "solo", "persona_id": "qa", "position": [1.0, 2.0]}
    if kind is not None:
        item["kind"] = kind
    actor = store.upsert_actor(
        ws, {"persona_id": "qa", "persona_instance_id": "personainst_hh9", "items": [item]}
    )
    assert actor.items[0].folder == expected
    # From the FILE, not the returned object: the claim is about what was
    # persisted, and a fill applied only on the way out would leave the disk
    # ambiguous exactly as before.
    assert store.get_actor(ws, actor.actor_key).items[0].folder == expected


def test_an_explicit_folder_is_never_overwritten_by_the_default():
    """The fill is for ABSENCE only. An operator who filed an agent under "Ops"
    must not have it silently re-filed under "Agents".

    *Mutation:* fill unconditionally (``folder = folder_for_kind(kind)``). Every
    non-default folder in the store collapses into two.
    """

    ws = _make_workspace()
    store = OfficeStore()
    actor = store.upsert_actor(
        ws,
        {
            "persona_id": "qa",
            "persona_instance_id": "personainst_hh9_ops",
            "items": [
                {
                    "item_id": "solo",
                    "persona_id": "qa",
                    "kind": "agent",
                    "position": [1.0, 2.0],
                    "folder": "Ops",
                }
            ],
        },
    )
    assert actor.items[0].folder == "Ops"


def test_the_written_folder_is_the_one_the_layout_policy_would_have_inferred():
    """The fill and the scan's fallback are the SAME authority, so a row this
    store writes and a row the policy compensates for cannot land in different
    folders.

    *Mutation:* spell the pair locally (``"Desks" if kind == "desk" else
    "Agents"``). Green today and free to drift the moment either side's
    vocabulary moves — which is why the assertion is against
    ``folder_for_kind`` itself rather than against the literals.
    """

    from agent_runtime.office_layout_policy import folder_for_kind, item_folder

    ws = _make_workspace()
    store = OfficeStore()
    for kind in ("agent", "desk"):
        actor = store.upsert_actor(
            ws,
            {
                "persona_id": kind,
                "persona_instance_id": f"personainst_hh9_{kind}",
                "items": [
                    {"item_id": kind, "persona_id": kind, "kind": kind, "position": [0.0, 0.0]}
                ],
            },
        )
        written = actor.items[0]
        assert written.folder == folder_for_kind(kind)
        # And the scan's own fallback agrees about the filled row, which is the
        # property that makes the read-side compensation harmless rather than a
        # second opinion.
        assert item_folder(written) == written.folder


# ── WHICH conflict keys are guesses reaches the operator (RD-5) ─────────────


def test_the_scan_separates_guessed_conflict_keys_from_read_ones():
    """RD-5. ``keys`` was complete and ``outcomes`` already said which entries
    were invented from a filename — but every reader took ``.keys`` alone, so
    the provenance existed and reached nobody.

    ``guessed_keys`` is that projection, derived from ``outcomes`` rather than
    tallied beside them (two parallel lists are two things free to drift), and
    it is what both readers now carry.

    *Mutation:* return ``self.keys``. Every key reads as a guess, and the
    surfaces that mark guesses mark all of them — the mirror image of the
    silence this replaces, and just as wrong.
    """

    ws = _make_workspace()
    store = OfficeStore()
    paths.office_conflict_path(ws, "dev").parent.mkdir(parents=True, exist_ok=True)
    paths.office_conflict_path(ws, "dev").write_text(
        '{"actor_key": "dev"}', encoding="utf-8"
    )
    # Both routes to a guess: a sidecar that would not decode, and one that
    # decoded and did not say. They must land in the same list.
    (paths.office_conflicts_dir(ws) / "broken.json").write_text("{not json", encoding="utf-8")
    (paths.office_conflicts_dir(ws) / "silent.json").write_text("{}", encoding="utf-8")

    scan = store.scan_conflicts(ws)
    assert scan.keys == ["broken", "dev", "silent"]
    # NOT the key that came out of a payload, which is the whole distinction.
    assert scan.guessed_keys == ["broken", "silent"]
    # The two projections of one outcome list cannot disagree about how many.
    assert len(scan.guessed_keys) == scan.unreadable


def test_the_snapshot_office_row_and_its_warning_mark_a_guessed_conflict_key():
    """The point of the separation: an operator is never handed a token
    ``office resolve-conflict --actor <it>`` cannot find without being told so.

    Both keys ride ONE row and ONE warning code — the discrimination is a field
    and a sentence, never a second code, or every existing census of
    ``office_actor_conflict`` zeroes.

    *Mutation:* pass ``conflict_guessed_keys=()`` at the snapshot call site (or
    drop the marking arm). The row is silent again and both keys read as
    actionable.
    """

    ws = _make_workspace()
    store = OfficeStore()
    store.upsert_actor(ws, _actor_payload("dev"))
    sidecar = paths.office_conflict_path(ws, "dev")
    sidecar.parent.mkdir(parents=True, exist_ok=True)
    sidecar.write_text(
        '{"actor_key": "dev", "kind": "both_changed", "remote_actor": null}',
        encoding="utf-8",
    )
    (paths.office_conflicts_dir(ws) / "broken.json").write_text("{not json", encoding="utf-8")

    snap = build_snapshot(event_log=EventLog())
    row = snap["offices"][ws]
    assert row["conflict_actor_keys"] == ["broken", "dev"]
    assert row["conflict_guessed_keys"] == ["broken"]

    conflicts = {
        w["entity_id"]: w
        for w in snap["parity"]["warnings"]
        if w.get("code") == "office_actor_conflict"
    }
    assert set(conflicts) == {"broken", "dev"}
    assert conflicts["broken"]["guessed"] is True
    assert "filename guess" in conflicts["broken"]["detail"]
    # The real key keeps the unqualified sentence: a warning that hedged on
    # every key would teach an operator to ignore the hedge.
    assert conflicts["dev"]["guessed"] is False
    assert "filename guess" not in conflicts["dev"]["detail"]


def test_an_office_row_with_no_guess_list_still_warns_and_claims_nothing():
    """Additive means additive. ``conflict_guessed_keys`` is absent from every
    office row a core built before RD-5 landed, and from any caller that built
    the row without it, so the warning builder reads its absence as "this row
    cannot say" — it neither raises nor marks everything.

    *Mutation:* index ``office["conflict_guessed_keys"]``. A folded older core
    then takes the whole parity section down with a ``KeyError`` at the one
    place whose job is to report trouble.
    """

    from agent_runtime.snapshot import _office_parity_warnings

    warnings = _office_parity_warnings(
        {"offices": {"w1": {"workspace_id": "w1", "conflict_actor_keys": ["a1"]}}}
    )
    assert [w["code"] for w in warnings] == ["office_actor_conflict"]
    assert warnings[0]["guessed"] is False
    assert "filename guess" not in warnings[0]["detail"]


def test_the_row_builder_refuses_to_default_the_guess_list():
    """The same "never silently zero" rule ``actors_unreadable`` is declared
    under, applied to the list beside it: a caller that genuinely holds no
    conflict scan has to say ``conflict_guessed_keys=()`` out loud.

    *Mutation:* give the parameter a ``()`` default. Every caller that forgets
    it then silently claims none of its keys are guesses — which is precisely
    the claim the bare ``.keys`` list used to make, back where it belongs and
    impossible to notice.
    """

    import inspect

    from agent_runtime.snapshot import office_summary_row

    param = inspect.signature(office_summary_row).parameters["conflict_guessed_keys"]
    assert param.kind is inspect.Parameter.KEYWORD_ONLY
    assert param.default is inspect.Parameter.empty
    with pytest.raises(TypeError):
        office_summary_row(object(), [], actors_unreadable=0)


# ── a refused upsert authors nothing (the ensure_surface/office_lock order) ──


def test_a_refused_upsert_leaves_no_office_behind_on_a_surfaceless_workspace():
    """The surface is authored by a placement that HAPPENS, not by one attempted.

    ``upsert_actor`` called ``ensure_surface`` above ``office_lock`` — before a
    single fence had run — so every refusal in the verb had the same side effect:
    a workspace that had no office came out of the refused call holding a default
    ``office.json``, at revision 1, created_by the operator who was just told no.
    That is a write nobody asked for and nobody is told about, and it is shared by
    every guard: the class-key fence, the desk fence, the tombstone fence, the
    conflict guard and the revision check all refuse AFTER the office exists.

    Driven through the revision guard because it is the one refusal reachable on
    a workspace with no state at all — no migration, no archive, no sibling desk —
    which is exactly the case where the leftover office is most visible.

    ANTI-VACUITY, and it is the assertion that matters: an accepted upsert on the
    same workspace still authors the surface. A store that had simply stopped
    creating offices would satisfy the first half and fail here.
    """

    ws = _make_workspace()
    store = OfficeStore()
    assert not store.surface_exists(ws), "fixture already has an office"

    with pytest.raises(StaleRevision):
        store.upsert_actor(ws, _actor_payload("dev"), expect_revision=7)

    assert not store.surface_exists(ws), (
        "a refused upsert authored an office for a workspace that had none — the "
        "surface is being created by the ATTEMPT rather than by the placement"
    )
    assert not paths.office_surface_path(ws).exists()
    assert "office.surface.created" not in _event_types()

    store.upsert_actor(ws, _actor_payload("dev"))
    assert store.surface_exists(ws)
    assert "office.surface.created" in _event_types()


def test_a_fence_refusal_authors_no_office_either(monkeypatch):
    """The same property, asked of the FENCE lane rather than the revision check.

    The revision guard and the fences sit on either side of the position-policy
    hook and the archive read, so proving one says nothing about the other. It
    drives a fence by making it refuse on a FRESH workspace, which is what any
    fence looks like from the store's point of view when there is nothing on the
    canvas yet to collide with.

    This used to drive the DESK fence, which was deleted 2026-09-18 with the
    invariant it enforced. It is repointed at the class-key fence rather than
    deleted, because the property under test is the store's WRITE ORDER — the
    office is authored under the lock, after the fences, never by the attempt —
    and that property is about the order, not about which fence occupies a slot
    in it. ``_guard_class_keyed_write`` is the FIRST fence inside the lock, so a
    refusal from it is the earliest one this ordering has to survive.
    """

    from agent_runtime.office_class_key_guard import ClassKeyedPlacementRefused
    from agent_runtime.office_store import OfficeStore as _Store

    ws = _make_workspace()
    store = OfficeStore()

    def _always_refuses(self, workspace_id, payload, *, allow_class_key):
        raise ClassKeyedPlacementRefused(
            "class_key_collision", safe_details={"workspace_id": workspace_id}
        )

    monkeypatch.setattr(_Store, "_guard_class_keyed_write", _always_refuses)

    with pytest.raises(ClassKeyedPlacementRefused):
        store.upsert_actor(ws, _actor_payload("dev"))

    assert not store.surface_exists(ws), (
        "a fence refused and the store still authored the office the "
        "refused placement would have gone into"
    )


def test_an_unresolvable_workspace_is_still_refused_before_any_fence():
    """The refusal that had to KEEP its position when the creation moved.

    ``ensure_surface``'s workspace-record refusal (MC-8) ran before the lock and
    therefore before every fence. Moving the surface CREATION under the lock must
    not take the refusal with it: an id no workspace record resolves has no
    business hearing a class-key or desk sentence about a placement it can never
    make, and the store must not go near its actor directory to find that out.
    """

    store = OfficeStore()
    with pytest.raises(WorkspaceUnresolved):
        store.upsert_actor("ws_no_such_record", _actor_payload("dev"))
    assert not store.surface_exists("ws_no_such_record")


# ── the scan NAMES what it could not read ───────────────────────────────────


def test_the_scan_names_the_files_it_could_not_read_and_bounds_the_list():
    """``ActorScan`` carried a COUNT while the reader was standing on the paths.

    "3 actor files here would not open" tells an operator something is wrong and
    nothing about what to do next; ``actors/broken.json`` tells them which file to
    open. The names travel now — bounded, because a store holding a pathological
    number of undecodable files must not turn every scan into an unbounded list,
    and with the remainder spelled ``+N more`` rather than trimmed away, since a
    truncated list that describes itself as whole is the exact defect ``ActorScan``
    exists to close one layer down.

    ``unreadable`` is asserted to be the EXACT total past the cap: the count is
    not ``len(names)``, which is why the elision has to be visible.
    """

    from agent_runtime.office_store import MAX_UNREADABLE_ACTOR_FILE_NAMES

    ws = _make_workspace()
    store = OfficeStore()
    store.upsert_actor(ws, _actor_payload("dev"))
    (paths.office_actors_dir(ws) / "broken.json").write_text("{not json", encoding="utf-8")

    scan = store.scan_actors(ws)
    assert [a.actor_key for a in scan.actors] == ["dev"]
    assert scan.unreadable == 1
    assert scan.unreadable_files.names == ("actors/broken.json",)
    assert scan.unreadable_files.describe() == "actors/broken.json"

    overflow = MAX_UNREADABLE_ACTOR_FILE_NAMES + 3
    for index in range(overflow - 1):
        (paths.office_actors_dir(ws) / f"broken{index:02d}.json").write_text(
            "{not json", encoding="utf-8"
        )

    scan = store.scan_actors(ws)
    assert scan.unreadable == overflow, "the COUNT is capped by nothing"
    assert len(scan.unreadable_files.names) == MAX_UNREADABLE_ACTOR_FILE_NAMES
    assert scan.unreadable_files.describe().endswith("+3 more"), (
        "the elided remainder is silent, so the list reads as the whole story"
    )


def test_the_archived_directorys_shortfall_is_distinguishable_from_the_live_ones():
    """A merged scan says WHICH directory each unreadable file was in.

    ``scan_actors(include_archived=True)`` reads two directories, and an actor
    file and its archive copy share a filename token. A bare ``broken.json`` in
    the merged list would be a name an operator cannot act on — the whole reason
    the count was not enough in the first place.
    """

    ws = _make_workspace()
    store = OfficeStore()
    store.upsert_actor(ws, _actor_payload("dev"))
    (paths.office_actors_dir(ws) / "broken.json").write_text("{not json", encoding="utf-8")
    archive_dir = paths.office_archive_dir(ws)
    archive_dir.mkdir(parents=True, exist_ok=True)
    (archive_dir / "broken.json").write_text("{not json", encoding="utf-8")

    scan = store.scan_actors(ws, include_archived=True)
    assert scan.unreadable == 2
    assert set(scan.unreadable_files.names) == {"actors/broken.json", "archive/broken.json"}
