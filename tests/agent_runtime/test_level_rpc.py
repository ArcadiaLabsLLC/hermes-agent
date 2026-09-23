"""The METHOD lane's LEVEL family: ``runtime.level.get`` / ``.set`` / ``.clear``.

The 2026-09-22 ruling made hermes the STORE of a workspace's level for every
workspace, not just the transport for a realm's default one. These three verbs
are what the launcher's office ``SceneStore`` becomes an adapter over, so what
this file pins is the adapter's whole contract:

1. **Absence is an honest empty, a typo is a REFUSAL.** ``present: false`` for a
   workspace that never had a level; ``workspace_not_found`` for an id no record
   resolves. A read leg that answered a blank for a typo would have the launcher
   draw an empty environment over a workspace that does not exist — the same
   defect ``runtime.office.get`` refuses, one family over.

2. **The bytes survive.** hermes stores the launcher's serializer output
   verbatim, so the ``document`` a get hands back is byte-identical to the one a
   set was given, INCLUDING the indentation and key order hermes has an opinion
   about everywhere else.

3. **``expect_sha256`` is three states, not two.** Omitted is unconditional,
   ``null`` means "there must be nothing stored", a hex string must equal the
   stored bytes' hash. The second is the arm that catches two machines authoring
   one workspace's level at once, and it is the one a lane that folded the
   parameter into a nullable string would silently lose.

The sha is over the STORED BYTES and never the semantic hash realm sync merges
on: the semantic hash calls a re-serialisation a no-op, which is exactly the
lost update a compare-and-set exists to refuse. ``test_a_reserialised_document
_is_a_conflict_even_though_the_merge_would_converge`` is the test that says so,
and it would go green against the wrong hash with every other case here passing.
"""

from __future__ import annotations

import hashlib
import json

from agent_runtime import paths, serve_rpc
from agent_runtime.level_sync import LevelStore
from tests.agent_runtime.office_seed import seed_workspace_record
from tests.agent_runtime.test_serve_rpc_office import (
    SHUTDOWN,
    _reply,
    _rpc,
    _run,
)

WORKSPACE = "ws_rpc_level_test"

#: Deliberately NOT canonically serialised — two spaces of indentation and keys
#: out of sorted order — so "stored verbatim" is a claim this fixture can
#: actually falsify.
DOCUMENT = '{\n  "version": 3,\n  "name": "island",\n  "tiles": [1, 2, 3]\n}'


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _call(rid: str, method: str, params: dict) -> dict:
    return _reply(_run([_rpc(rid, method, params), SHUTDOWN]), rid)


def _seed(workspace_id: str = WORKSPACE, *, document: str | None = None):
    seed_workspace_record(workspace_id)
    if document is not None:
        LevelStore().write(workspace_id, document.encode("utf-8"))
    return workspace_id


# ── read ────────────────────────────────────────────────────────────────────


def test_get_answers_an_unauthored_workspace_with_an_honest_empty():
    _seed()

    reply = _call("lvl-1", "runtime.level.get", {"workspace_id": WORKSPACE})

    assert reply["result"] == {
        "workspace_id": WORKSPACE,
        "workspace_token": paths.safe_path_token(WORKSPACE),
        "present": False,
        "bytes": 0,
        "sha256": None,
        "version": None,
        "document": None,
    }


def test_get_hands_back_the_stored_bytes_verbatim():
    """The round trip is the contract. Asserted on the RAW STRING, not on the
    parsed JSON: a parse-and-compare would pass against a hermes that had
    re-indented or re-keyed the document, which is the one thing this family
    promises never to do."""

    _seed(document=DOCUMENT)

    reply = _call("lvl-2", "runtime.level.get", {"workspace_id": WORKSPACE})

    result = reply["result"]
    assert result["document"] == DOCUMENT
    assert result["present"] is True
    assert result["bytes"] == len(DOCUMENT.encode("utf-8"))
    assert result["sha256"] == _sha(DOCUMENT)
    assert result["version"] == 3


def test_an_unknown_workspace_is_refused_by_every_verb_rather_than_answered():
    """One typo, three verbs, one refusal — and the WRITES must refuse too.

    A set that authored a level for an unresolvable id would leave an
    environment on disk forever for a workspace nothing can name, while the read
    leg refused the same string: the incoherent pair ``runtime.office.surface
    .update``'s docstring argues at length, reached here from the same side."""

    missing = "ws_level_does_not_exist"
    assert not paths.workspace_path(missing).is_file()

    for rid, method, extra in (
        ("lvl-3a", "runtime.level.get", {}),
        ("lvl-3b", "runtime.level.set", {"document": DOCUMENT}),
        ("lvl-3c", "runtime.level.clear", {}),
    ):
        reply = _call(rid, method, {"workspace_id": missing, **extra})
        assert reply["error"]["code"] == serve_rpc.ERR_NOT_FOUND, method
        assert reply["error"]["data"]["reason"] == "workspace_not_found", method

    assert not paths.level_path(missing).exists()


# ── write ───────────────────────────────────────────────────────────────────


def test_set_without_an_expectation_writes_unconditionally():
    _seed()

    reply = _call(
        "lvl-4", "runtime.level.set", {"workspace_id": WORKSPACE, "document": DOCUMENT}
    )

    assert reply["result"]["changed"] is True
    assert reply["result"]["sha256"] == _sha(DOCUMENT)
    assert LevelStore().read(WORKSPACE) == DOCUMENT.encode("utf-8")


def test_set_with_the_matching_sha_is_accepted():
    _seed(document=DOCUMENT)
    updated = json.dumps({"version": 4, "name": "island"})

    reply = _call(
        "lvl-5",
        "runtime.level.set",
        {
            "workspace_id": WORKSPACE,
            "document": updated,
            "expect_sha256": _sha(DOCUMENT),
        },
    )

    assert reply["result"]["changed"] is True
    assert LevelStore().read(WORKSPACE) == updated.encode("utf-8")


def test_set_with_a_stale_sha_is_a_conflict_and_writes_nothing():
    """The lost-update refusal. The assertion that matters is the LAST one: a
    handler that answered the conflict after writing would look identical on the
    wire and would have destroyed the other author's environment."""

    _seed(document=DOCUMENT)
    stale = _sha('{"version": 1}')

    reply = _call(
        "lvl-6",
        "runtime.level.set",
        {
            "workspace_id": WORKSPACE,
            "document": json.dumps({"version": 9}),
            "expect_sha256": stale,
        },
    )

    assert reply["error"]["code"] == serve_rpc.ERR_CONFLICT
    assert reply["error"]["data"] == {
        "reason": "sha256_mismatch",
        "workspace_id": WORKSPACE,
        "current_sha256": _sha(DOCUMENT),
    }
    assert LevelStore().read(WORKSPACE) == DOCUMENT.encode("utf-8")


def test_set_with_a_null_expectation_over_a_present_level_is_a_conflict():
    """``expect_sha256: null`` is a CLAIM — "I am the first author of this
    workspace's level" — and it is the arm a lane that treated the key's absence
    and a null value as the same thing would lose entirely. Two launchers
    applying an island to one fresh workspace is exactly the race it catches."""

    _seed(document=DOCUMENT)

    reply = _call(
        "lvl-7",
        "runtime.level.set",
        {
            "workspace_id": WORKSPACE,
            "document": json.dumps({"version": 9}),
            "expect_sha256": None,
        },
    )

    assert reply["error"]["code"] == serve_rpc.ERR_CONFLICT
    assert reply["error"]["data"]["reason"] == "sha256_mismatch"
    assert LevelStore().read(WORKSPACE) == DOCUMENT.encode("utf-8")


def test_a_null_expectation_over_an_absent_level_is_the_first_write():
    """The other half of the same claim, and the reason the null arm is not just
    a refusal generator: a launcher authoring a level for the first time has no
    sha to offer and must still be able to guard its write."""

    _seed()

    reply = _call(
        "lvl-8",
        "runtime.level.set",
        {"workspace_id": WORKSPACE, "document": DOCUMENT, "expect_sha256": None},
    )

    assert reply["result"]["changed"] is True
    assert LevelStore().read(WORKSPACE) == DOCUMENT.encode("utf-8")


def test_a_reserialised_document_is_a_conflict_even_though_the_merge_would_converge():
    """The one test that tells the two hashes apart.

    ``level_document_hash`` (realm sync's merge key) parses and re-serialises
    canonically, so these two documents are the SAME to it. The compare-and-set
    token is over the stored BYTES, so a caller holding the re-indented copy has
    not read what is stored and must be refused. A handler wired to the semantic
    hash passes every other case in this file."""

    _seed(document=DOCUMENT)
    reindented = json.dumps(json.loads(DOCUMENT), indent=4, sort_keys=True)
    assert json.loads(reindented) == json.loads(DOCUMENT)

    reply = _call(
        "lvl-9",
        "runtime.level.set",
        {
            "workspace_id": WORKSPACE,
            "document": json.dumps({"version": 9}),
            "expect_sha256": _sha(reindented),
        },
    )

    assert reply["error"]["code"] == serve_rpc.ERR_CONFLICT
    assert reply["error"]["data"]["reason"] == "sha256_mismatch"


def test_a_refused_document_carries_the_store_doors_own_word():
    """Not a generic "rejected": the four refusal codes are what let the
    launcher tell an operator WHICH fact failed, and they come from
    ``LevelDocumentError.code`` rather than a second reading of the document
    here."""

    _seed()

    versionless = _call(
        "lvl-10a",
        "runtime.level.set",
        {"workspace_id": WORKSPACE, "document": json.dumps({"name": "island"})},
    )
    assert versionless["error"]["code"] == serve_rpc.ERR_INVALID_PARAMS
    assert versionless["error"]["data"]["reason"] == "missing_version"

    not_json = _call(
        "lvl-10b",
        "runtime.level.set",
        {"workspace_id": WORKSPACE, "document": "not a document"},
    )
    assert not_json["error"]["data"]["reason"] == "unreadable_document"

    assert LevelStore().read(WORKSPACE) is None


def test_a_refused_document_is_refused_before_the_expectation_is_consulted():
    """Order matters to the operator: a document this runtime will not store is
    a client bug whatever is on disk, and reporting it as a conflict would send
    the launcher to re-read a level that was never the problem."""

    _seed(document=DOCUMENT)

    reply = _call(
        "lvl-11",
        "runtime.level.set",
        {
            "workspace_id": WORKSPACE,
            "document": "not a document",
            "expect_sha256": _sha("something else entirely" + "0" * 8),
        },
    )

    assert reply["error"]["code"] == serve_rpc.ERR_INVALID_PARAMS
    assert reply["error"]["data"]["reason"] == "unreadable_document"


def test_a_malformed_expectation_is_an_invalid_request_not_a_conflict():
    """A typo'd token can only ever mismatch, and a mismatch reported as a
    conflict would tell a client that somebody else had written its level."""

    _seed(document=DOCUMENT)

    reply = _call(
        "lvl-12",
        "runtime.level.set",
        {"workspace_id": WORKSPACE, "document": DOCUMENT, "expect_sha256": "deadbeef"},
    )

    assert reply["error"]["code"] == serve_rpc.ERR_INVALID_PARAMS
    assert reply["error"]["data"]["reason"] == "expect_sha256_invalid"


# ── clear ───────────────────────────────────────────────────────────────────


def test_clear_removes_a_present_level():
    _seed(document=DOCUMENT)

    reply = _call("lvl-13", "runtime.level.clear", {"workspace_id": WORKSPACE})

    assert reply["result"] == {"workspace_id": WORKSPACE, "cleared": True}
    assert LevelStore().read(WORKSPACE) is None
    assert not paths.level_path(WORKSPACE).exists()


def test_clear_over_an_absent_level_is_an_accepted_no_op():
    """``cleared: false`` and not an error — which is what makes a transport
    retry converge instead of turning a delivered clear into a failure."""

    _seed()

    reply = _call("lvl-14", "runtime.level.clear", {"workspace_id": WORKSPACE})

    assert reply["result"] == {"workspace_id": WORKSPACE, "cleared": False}


def test_clear_honours_the_same_expectation_as_set():
    _seed(document=DOCUMENT)

    stale = _call(
        "lvl-15",
        "runtime.level.clear",
        {"workspace_id": WORKSPACE, "expect_sha256": _sha('{"version": 1}')},
    )
    assert stale["error"]["code"] == serve_rpc.ERR_CONFLICT
    assert stale["error"]["data"]["current_sha256"] == _sha(DOCUMENT)
    assert LevelStore().read(WORKSPACE) == DOCUMENT.encode("utf-8")

    matched = _call(
        "lvl-16",
        "runtime.level.clear",
        {"workspace_id": WORKSPACE, "expect_sha256": _sha(DOCUMENT)},
    )
    assert matched["result"]["cleared"] is True


# ── params, tiers and receipts ──────────────────────────────────────────────


def test_a_missing_workspace_id_is_the_one_reason_every_verb_spends():
    for rid, method in (
        ("lvl-17a", "runtime.level.get"),
        ("lvl-17b", "runtime.level.set"),
        ("lvl-17c", "runtime.level.clear"),
    ):
        reply = _call(rid, method, {})
        assert reply["error"]["code"] == serve_rpc.ERR_INVALID_PARAMS, method
        assert reply["error"]["data"]["reason"] == "workspace_id_required", method


def test_a_non_string_document_is_refused_before_anything_is_read():
    _seed()

    reply = _call(
        "lvl-18", "runtime.level.set", {"workspace_id": WORKSPACE, "document": {"version": 1}}
    )

    assert reply["error"]["data"]["reason"] == "document_required"


def test_every_write_logs_a_receipt_on_the_office_write_line(caplog):
    """Observability lands as LOG RECEIPTS, never as new keys on the envelope.
    Shaped like ``log_office_write``'s other callers so an operator greps one
    format, with ``op`` naming the method."""

    _seed()
    with caplog.at_level("INFO", logger="agent_runtime.serve_rpc"):
        _call(
            "lvl-19a",
            "runtime.level.set",
            {"workspace_id": WORKSPACE, "document": DOCUMENT, "correlation_id": "gesture-1"},
        )
        _call("lvl-19b", "runtime.level.clear", {"workspace_id": WORKSPACE})

    lines = [record.getMessage() for record in caplog.records]
    assert any(
        "office_write op=runtime.level.set corr=gesture-1" in line for line in lines
    ), lines
    assert any(
        "office_write op=runtime.level.clear corr=-" in line for line in lines
    ), lines


def test_the_family_is_registered_and_declares_its_tier():
    from agent_runtime.call_authorization import TIER_CONSOLE

    for name in ("runtime.level.get", "runtime.level.set", "runtime.level.clear"):
        assert name in serve_rpc.method_names()
        assert serve_rpc.method_tiers()[name] == TIER_CONSOLE
