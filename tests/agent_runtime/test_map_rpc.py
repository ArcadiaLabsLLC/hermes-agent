"""The METHOD lane's MAP CATALOGUE: ``runtime.map.list`` / ``.get`` / ``.set`` /
``.clear``.

The owner's 2026-09-22 report is the whole reason this family exists: one
workspace read ``flat grass test level v4 · yours`` on the Windows box and
``unnamed · yours`` on the Mac after a realm pull. The level DOCUMENT travelled;
the catalogue that names it did not, because the launcher resolves the caption's
display name from the level sidecar's ``SavedMapId`` against a
SharedPreferences store the second machine never held.

What this file pins is the adapter's whole contract, and three of its claims are
this family's rather than the level family's:

1. **``list`` is the catalogue question and it costs no document bytes.** A
   caption asks "what is this map called"; answering it must not ship a scene
   per entry. Every row carries ``name`` and ``sha256`` and no ``document``.

2. **An absent map is a REFUSAL on ``get``, not an honest empty.** A level's
   absence is normal because the WORKSPACE record still exists; a map has no
   record apart from its document, so "no document" and "no such map" are one
   fact, and a nameless row handed to the launcher is the ``unnamed`` caption
   this family exists to retire.

3. **``name`` is a validated fact, and uniqueness is asked on ONE side.** The
   level family reads two facts (UTF-8 JSON, a numeric ``version``); this one
   reads three, and the third is the defect itself — a catalogue entry with no
   name resolves to ``unnamed`` on arrival exactly as a missing entry does. On
   top of the shape gate, the two AUTHORING doors refuse a name another map
   already holds (``name_taken``), while the pull applier deliberately does not:
   refusing an arriving map over a label would delete a peer's catalogue entry,
   which is the defect wearing a validator's hat.

The reason strings ``name_invalid``, ``name_taken`` and ``document_too_large``
are lane LM's, pinned across the two repos: the launcher maps each to a typed
failure, so a spelling that drifted here would surface there as an untyped one.

Everything else is the level family's contract verbatim, including the one test
that tells the two hashes apart: the compare-and-set token is over the STORED
BYTES and never ``map_document_hash``, the semantic hash realm sync merges on.
"""

from __future__ import annotations

import hashlib
import json

from agent_runtime import paths, serve_rpc
from agent_runtime.map_sync import MapStore
from tests.agent_runtime.test_serve_rpc_office import (
    SHUTDOWN,
    _reply,
    _rpc,
    _run,
)

MAP_ID = "map_rpc_test"

#: Deliberately NOT canonically serialised — two spaces of indentation and keys
#: out of sorted order — so "stored verbatim" is a claim this fixture can
#: actually falsify.
DOCUMENT = '{\n  "version": 3,\n  "name": "flat grass test level v4",\n  "origin": "local",\n  "scene": {"tiles": [1, 2, 3]}\n}'


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _call(rid: str, method: str, params: dict) -> dict:
    return _reply(_run([_rpc(rid, method, params), SHUTDOWN]), rid)


def _seed(map_id: str = MAP_ID, *, document: str = DOCUMENT) -> str:
    MapStore().write(map_id, document.encode("utf-8"))
    return map_id


def _doc(**overrides) -> str:
    body = {"version": 1, "name": "seeded"}
    body.update(overrides)
    return json.dumps(body)


# ── list ────────────────────────────────────────────────────────────────────


def test_list_answers_an_empty_catalogue_with_an_empty_list():
    """An install that never saved a named map is the normal first state, and it
    is an empty catalogue rather than an error — the launcher binds its adapter
    before anything has been saved."""

    reply = _call("map-1", "runtime.map.list", {})

    assert reply["result"] == {"maps": [], "count": 0}


def test_list_carries_the_name_and_the_hash_and_never_the_document():
    """THE verb the defect needed, and the assertion that keeps it cheap.

    ``name`` is present because a caption is what the launcher is resolving;
    ``document`` is absent because shipping a scene per entry would make the
    catalogue read scale with the scenes instead of with the list."""

    _seed("map_alpha", document=_doc(name="alpha"))
    _seed("map_beta", document=_doc(name="beta"))

    reply = _call("map-2", "runtime.map.list", {})

    result = reply["result"]
    assert result["count"] == 2
    assert [row["map_id"] for row in result["maps"]] == ["map_alpha", "map_beta"]
    assert [row["name"] for row in result["maps"]] == ["alpha", "beta"]
    assert all("document" not in row for row in result["maps"])
    assert all(row["present"] is True and row["sha256"] for row in result["maps"])


# ── read ────────────────────────────────────────────────────────────────────


def test_get_refuses_a_map_the_catalogue_does_not_hold():
    """Claim 2, and the difference from ``runtime.level.get`` that matters.

    A level answers ``present: false`` for a workspace that never had one
    because the workspace RECORD still exists. There is no record behind a map,
    so an honest empty here would be a nameless row for the launcher to render —
    the ``unnamed`` caption itself, now produced by hermes."""

    assert not paths.map_path("map_never_saved").exists()

    reply = _call("map-3", "runtime.map.get", {"map_id": "map_never_saved"})

    assert reply["error"]["code"] == serve_rpc.ERR_NOT_FOUND
    assert reply["error"]["data"] == {
        "reason": "map_not_found",
        "map_id": "map_never_saved",
    }


def test_an_unknown_map_id_is_refused_by_get_and_never_authored_by_it():
    """A typo must not leave a file behind, and must not be answered.

    The write leg is the one worth asserting: ``set`` is how a map comes into
    existence, so it has no unknown-id arm at all — which makes "the read
    refused and nothing was written" the property, rather than "three verbs
    refuse" as in the level family."""

    reply = _call("map-4", "runtime.map.get", {"map_id": "map_typo_zzz"})

    assert reply["error"]["code"] == serve_rpc.ERR_NOT_FOUND
    assert not paths.map_path("map_typo_zzz").exists()
    assert MapStore().list_map_tokens() == []


def test_get_hands_back_the_stored_bytes_verbatim():
    """The round trip is the contract. Asserted on the RAW STRING, not on the
    parsed JSON: a parse-and-compare would pass against a hermes that had
    re-indented or re-keyed the document, which is the one thing this family
    promises never to do."""

    _seed()

    reply = _call("map-5", "runtime.map.get", {"map_id": MAP_ID})

    result = reply["result"]
    assert result["document"] == DOCUMENT
    assert result["present"] is True
    assert result["name"] == "flat grass test level v4"
    assert result["bytes"] == len(DOCUMENT.encode("utf-8"))
    assert result["sha256"] == _sha(DOCUMENT)
    assert result["version"] == 3


def test_a_missing_map_id_is_an_invalid_request_and_not_a_not_found():
    """A caller that sent no id has a bug in the REQUEST; answering ``not
    found`` would send it hunting a catalogue entry it never named."""

    reply = _call("map-6", "runtime.map.get", {})

    assert reply["error"]["code"] == serve_rpc.ERR_INVALID_PARAMS
    assert reply["error"]["data"]["reason"] == "map_id_required"


# ── write ───────────────────────────────────────────────────────────────────


def test_set_without_an_expectation_writes_unconditionally():
    reply = _call("map-7", "runtime.map.set", {"map_id": MAP_ID, "document": DOCUMENT})

    assert reply["result"]["changed"] is True
    assert reply["result"]["sha256"] == _sha(DOCUMENT)
    assert reply["result"]["name"] == "flat grass test level v4"
    assert MapStore().read(MAP_ID) == DOCUMENT.encode("utf-8")


def test_set_with_the_matching_sha_is_accepted():
    _seed()
    renamed = _doc(version=4, name="flat grass test level v5")

    reply = _call(
        "map-8",
        "runtime.map.set",
        {"map_id": MAP_ID, "document": renamed, "expect_sha256": _sha(DOCUMENT)},
    )

    assert reply["result"]["changed"] is True
    assert reply["result"]["name"] == "flat grass test level v5"
    assert MapStore().read(MAP_ID) == renamed.encode("utf-8")


def test_set_with_a_stale_sha_is_a_conflict_and_writes_nothing():
    """The lost-update refusal. The assertion that matters is the LAST one: a
    handler that answered the conflict after writing would look identical on the
    wire and would have destroyed the other author's catalogue entry."""

    _seed()
    stale = _sha(_doc(name="something else"))

    reply = _call(
        "map-9",
        "runtime.map.set",
        {"map_id": MAP_ID, "document": _doc(name="clobber"), "expect_sha256": stale},
    )

    assert reply["error"]["code"] == serve_rpc.ERR_CONFLICT
    assert reply["error"]["data"] == {
        "reason": "sha256_mismatch",
        "map_id": MAP_ID,
        "current_sha256": _sha(DOCUMENT),
    }
    assert MapStore().read(MAP_ID) == DOCUMENT.encode("utf-8")


def test_set_with_a_null_expectation_over_a_present_map_is_a_conflict():
    """``expect_sha256: null`` is a CLAIM — "I am minting this map id" — and it
    is the arm a lane that treated the key's absence and a null value as the
    same thing would lose entirely. Two machines saving a map under one id is
    exactly the race it catches."""

    _seed()

    reply = _call(
        "map-10",
        "runtime.map.set",
        {"map_id": MAP_ID, "document": _doc(name="clobber"), "expect_sha256": None},
    )

    assert reply["error"]["code"] == serve_rpc.ERR_CONFLICT
    assert reply["error"]["data"]["reason"] == "sha256_mismatch"
    assert MapStore().read(MAP_ID) == DOCUMENT.encode("utf-8")


def test_a_null_expectation_over_an_absent_map_is_the_first_write():
    """The other half of the same claim, and the reason the null arm is not just
    a refusal generator: a launcher saving a map for the first time has no sha to
    offer and must still be able to guard its write."""

    reply = _call(
        "map-11",
        "runtime.map.set",
        {"map_id": MAP_ID, "document": DOCUMENT, "expect_sha256": None},
    )

    assert reply["result"]["changed"] is True
    assert MapStore().read(MAP_ID) == DOCUMENT.encode("utf-8")


def test_a_reserialised_document_is_a_conflict_even_though_the_merge_would_converge():
    """The one test that tells the two hashes apart.

    ``map_document_hash`` (realm sync's merge key) parses and re-serialises
    canonically, so these two documents are the SAME to it. The compare-and-set
    token is over the stored BYTES, so a caller holding the re-indented copy has
    not read what is stored and must be refused. A handler wired to the semantic
    hash passes every other case in this file."""

    _seed()
    reindented = json.dumps(json.loads(DOCUMENT), indent=4, sort_keys=True)
    assert json.loads(reindented) == json.loads(DOCUMENT)

    reply = _call(
        "map-12",
        "runtime.map.set",
        {"map_id": MAP_ID, "document": _doc(name="clobber"), "expect_sha256": _sha(reindented)},
    )

    assert reply["error"]["code"] == serve_rpc.ERR_CONFLICT
    assert reply["error"]["data"]["reason"] == "sha256_mismatch"


def test_every_validator_arm_carries_the_store_doors_own_word():
    """Not a generic "rejected": the refusal codes are what let the launcher tell
    an operator WHICH fact failed, and they come from ``MapDocumentError.code``
    rather than a second reading of the document here.

    ``missing_name`` is the arm this family adds and the one that matters most —
    a catalogue entry with no name resolves to ``unnamed`` on arrival exactly as
    a missing entry does, so accepting one would publish the reported defect
    instead of fixing it."""

    cases = {
        "unreadable_document": "not json at all",
        "not_an_object": "[1, 2, 3]",
        "missing_version": json.dumps({"name": "island"}),
        "name_invalid": json.dumps({"version": 1}),
        "document_too_large": json.dumps({"version": 1, "name": "x" * (1024 * 1024)}),
    }

    for index, (code, document) in enumerate(sorted(cases.items())):
        reply = _call(f"map-13{index}", "runtime.map.set", {"map_id": MAP_ID, "document": document})
        assert reply["error"]["code"] == serve_rpc.ERR_INVALID_PARAMS, code
        assert reply["error"]["data"]["reason"] == code, code

    # A blank name is the name_invalid arm too: the caption it produces is
    # indistinguishable from an absent one, and lane LM maps one spelling.
    reply = _call(
        "map-14", "runtime.map.set", {"map_id": MAP_ID, "document": json.dumps({"version": 1, "name": "   "})}
    )
    assert reply["error"]["data"]["reason"] == "name_invalid"
    assert MapStore().list_map_tokens() == []


def test_a_name_another_map_already_holds_is_refused_as_name_taken():
    """Uniqueness, and it is NOT a document-shape fact: the bytes are fine and
    only the rest of the catalogue can answer it.

    Asked on this door because a set is AUTHORING — the launcher's picker is
    naming a map — and two entries called "island" make the catalogue useless
    for the one job it has."""

    _seed("map_island", document=_doc(name="island"))

    reply = _call(
        "map-18", "runtime.map.set", {"map_id": "map_other", "document": _doc(name="Island  ")}
    )

    assert reply["error"]["code"] == serve_rpc.ERR_INVALID_PARAMS
    assert reply["error"]["data"]["reason"] == "name_taken"
    assert reply["error"]["data"]["held_by"] == "map_island"
    assert MapStore().read("map_other") is None


def test_a_map_keeping_its_own_name_is_never_taken():
    """The arm that would break every scene edit if uniqueness were keyed on the
    name alone: re-saving a map under the name it already has is the normal
    write, not a collision with itself."""

    _seed("map_island", document=_doc(name="island"))

    reply = _call(
        "map-19",
        "runtime.map.set",
        {"map_id": "map_island", "document": _doc(name="island", version=2)},
    )

    assert reply["result"]["changed"] is True
    assert reply["result"]["name"] == "island"


def test_the_pull_door_is_not_gated_on_uniqueness():
    """The refusal above must not reach the applier.

    A realm can carry two same-named maps — two machines named a scene the same
    thing before they ever met — and refusing one on arrival would DELETE a
    peer's catalogue entry to enforce a label, which is the defect this whole
    family exists to close. ``validate_map_document`` is what the pull and the
    publish scan run, and it cannot raise ``name_taken`` because it never sees
    the catalogue."""

    from agent_runtime.map_sync import MapStore as _Store
    from agent_runtime.map_sync import validate_map_document

    _seed("map_island", document=_doc(name="island"))

    # The shape gate accepts the colliding document...
    assert validate_map_document(_doc(name="island").encode("utf-8"))["name"] == "island"
    # ...and the store door, which the applier writes through, stores it.
    _Store().write("map_island_from_peer", _doc(name="island").encode("utf-8"))
    assert _Store().read("map_island_from_peer") is not None


# ── clear ───────────────────────────────────────────────────────────────────


def test_clear_removes_a_present_map():
    _seed()

    reply = _call("map-15", "runtime.map.clear", {"map_id": MAP_ID})

    assert reply["result"] == {"map_id": MAP_ID, "cleared": True}
    assert MapStore().read(MAP_ID) is None


def test_clear_of_an_absent_map_is_an_accepted_no_op():
    """Absence is not an error HERE even though it is on ``get``: a clear states
    a desired end state and the end state already holds, which is what makes a
    retry converge instead of alternating between success and refusal."""

    reply = _call("map-16", "runtime.map.clear", {"map_id": "map_never_saved"})

    assert reply["result"] == {"map_id": "map_never_saved", "cleared": False}


def test_clear_with_a_stale_sha_is_a_conflict_and_removes_nothing():
    _seed()

    reply = _call(
        "map-17",
        "runtime.map.clear",
        {"map_id": MAP_ID, "expect_sha256": _sha(_doc(name="stale"))},
    )

    assert reply["error"]["code"] == serve_rpc.ERR_CONFLICT
    assert reply["error"]["data"]["current_sha256"] == _sha(DOCUMENT)
    assert MapStore().read(MAP_ID) == DOCUMENT.encode("utf-8")
