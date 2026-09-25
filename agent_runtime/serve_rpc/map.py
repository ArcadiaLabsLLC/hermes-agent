"""``runtime.map.list`` / ``get`` / ``set`` / ``clear`` — the map document verbs.
"""

from __future__ import annotations

from typing import Any

from agent_runtime.call_authorization import TIER_CONSOLE

from agent_runtime.serve_rpc.protocol import (
    ERR_CONFLICT,
    ERR_HANDLER_FAILED,
    ERR_INVALID_PARAMS,
    ERR_NOT_FOUND,
    RpcContext,
    err,
    ok,
)
from agent_runtime.serve_rpc.reasons import RpcRefusal
from agent_runtime.serve_rpc.registry import method
from agent_runtime.serve_rpc.params import (
    ParamRefused,
    _correlation_id_param,
    _map_expect_param,
    _map_id_or_error,
)
from agent_runtime.serve_rpc.office_read import log_office_write

__layer__ = "lanes"

__all__ = [
    "MAP_SHA256_MISMATCH_REASON",
    "_runtime_map_clear",
    "_runtime_map_get",
    "_runtime_map_list",
    "_runtime_map_set",
]


# ── runtime.map.* ────────────────────────────────────────────────────────────
#
# The MAP CATALOGUE over the method lane — the level family's sibling, keyed by
# MAP ID instead of workspace. The owner's 2026-09-22 report is the whole
# argument: one workspace read ``flat grass test level v4 · yours`` on Windows
# and ``unnamed · yours`` on the Mac after a realm pull, because the launcher
# resolves the caption's display name from the level sidecar's ``SavedMapId``
# against a SharedPreferences catalogue that the second machine never held. The
# document travelled; the catalogue that names it did not. These four verbs are
# what ``LocalLevelCatalog`` becomes an adapter over, so the catalogue travels
# with the realm exactly as the level does.
#
# Everything below writes through ``MapStore`` — the same door realm sync's pull
# applier uses — and hands back ``map_document_row``, the same row the CLI's
# ``map show`` prints, because the launcher compares the ``sha256`` it read on
# one lane against the one it is handed on the other.

#: The ``data.reason`` both writes spend when ``expect_sha256`` does not match.
MAP_SHA256_MISMATCH_REASON = RpcRefusal.SHA256_MISMATCH


@method("runtime.map.list", tier=TIER_CONSOLE)
def _runtime_map_list(rid: Any, params: dict, context: RpcContext | None = None) -> dict:
    """The catalogue: every named map this install holds, WITHOUT the bytes.

    Params: none.

    Result: ``{maps: [{map_id, map_token, present, bytes, sha256, version,
    name}, ...], count}`` — descriptor rows, sorted by token. No ``document``
    key on any of them, and that is the verb's reason for existing: the launcher
    needs the NAME for a caption and the sha for a compare-and-set, and shipping
    a megabyte of scene per entry to answer "what is this map called" would make
    the catalogue read cost scale with the scenes rather than with the list.

    ``map_id`` is reported as the stored TOKEN. hermes never parsed an id out of
    the document — the filename is the address — so the token is the only id
    this lane can honestly hand back, and it is a pure function of the id the
    launcher minted.

    **Tier: ``console``**, matching ``runtime.level.get`` rather than the
    one-line rule. A row carries no document bytes, but the catalogue is the
    complete list of named environments on this machine; the read tier is
    deliberately open to ``unknown``, a caller the transport authenticated and
    could not place, and that caller is not entitled to the inventory.
    """

    from agent_runtime.map_sync import MapStore, map_document_row

    store = MapStore()
    rows = [map_document_row(token, store.read(token), full=False) for token in store.list_map_tokens()]
    return ok(rid, {"maps": rows, "count": len(rows)})


@method("runtime.map.get", tier=TIER_CONSOLE)
def _runtime_map_get(rid: Any, params: dict, context: RpcContext | None = None) -> dict:
    """ONE catalogue map's document, byte for byte as stored.

    Params: ``map_id`` (required).

    Result: the ``.list`` row plus ``document`` — the stored bytes as a string.

    Errors: ``-32602`` ``map_id_required``; ``4001`` ``map_not_found``.

    **An absent map is a REFUSAL here, and that is the one place this family
    parts from the level family's shape.** ``runtime.level.get`` answers
    ``present: false`` because a workspace RECORD exists and most workspaces
    never had a level applied — absence is the normal case for a thing that
    demonstrably exists. A map has no record apart from its document: the
    document IS the catalogue entry, so "no document" and "no such map" are one
    fact and reporting it as an honest empty would hand the launcher a nameless
    row to render, which is the ``unnamed`` caption this family exists to
    retire. ``.list`` is how a caller asks what exists without guessing.

    ``sha256`` is over the STORED BYTES and is the token the two writes guard
    on; it is deliberately NOT ``map_document_hash``, the semantic hash realm
    sync merges on, which cannot answer "did my document survive the round trip".
    """

    from agent_runtime.map_sync import MapStore, map_document_row

    map_id, refusal = _map_id_or_error(rid, params)
    if refusal is not None:
        return refusal
    assert map_id is not None
    raw = MapStore().read(map_id)
    if raw is None:
        return err(
            rid,
            ERR_NOT_FOUND,
            f"unknown map: {map_id}",
            {"reason": "map_not_found", "map_id": map_id},
        )
    return ok(rid, map_document_row(map_id, raw, full=True))


@method("runtime.map.set", tier=TIER_CONSOLE)
def _runtime_map_set(rid: Any, params: dict, context: RpcContext | None = None) -> dict:
    """Store one catalogue map VERBATIM, optionally compare-and-set.

    Params: ``map_id`` (required), ``document`` (required string — the
    descriptor and its scene as the launcher serialises them), ``expect_sha256``
    (optional: hex of the bytes the caller read, ``null`` for "there must be
    nothing stored", omitted for unconditional), ``correlation_id`` (optional).

    Result: the ``.list`` row plus ``changed``. ``changed: false`` means the
    stored bytes were already identical — an accepted write, not a refusal.

    Errors: ``-32602`` ``map_id_required`` / ``document_required`` /
    ``expect_sha256_invalid``, and ``-32602`` with ``data.reason =
    MapDocumentError.code`` for a document this runtime will not store (the
    store door's own five words carried through rather than re-derived, so a
    client can say WHICH refusal it was — including ``missing_name``, the arm
    this family adds and the one that keeps a nameless entry from being
    published as a fix); ``4090`` ``{reason: "sha256_mismatch",
    current_sha256}``.

    There is no ``map_not_found`` arm: a set is how a map comes into existence,
    which is exactly why ``expect_sha256: null`` is worth spelling — it is how a
    first write says *I believe I am minting this id*, and it is the arm that
    catches two machines minting one id at once.

    This does NOT publish. hermes counts unpublished maps in realm status and the
    ordinary publish carries them; an auto-publish here would put a half-saved
    catalogue into a git repo, where the cost is permanent.
    """

    from agent_runtime.map_sync import (
        MapDocumentError,
        MapStore,
        map_document_row,
        map_expectation_matches,
        map_name_holder,
        stored_map_sha256,
        validate_map_document,
    )
    from agent_runtime.map_sync import REFUSAL_NAME_TAKEN

    map_id, refusal = _map_id_or_error(rid, params)
    if refusal is not None:
        return refusal
    assert map_id is not None

    document = params.get("document")
    if not isinstance(document, str):
        return err(
            rid,
            ERR_INVALID_PARAMS,
            "invalid params: document must be a string",
            {"reason": "document_required", "map_id": map_id},
        )

    try:
        expect_provided, expect_sha256 = _map_expect_param(params)
    except ParamRefused as bad:
        return bad.frame(rid, map_id=map_id)

    try:
        correlation_id = _correlation_id_param(params)
    except ParamRefused as bad:
        return bad.frame(rid, map_id=map_id)

    raw = document.encode("utf-8")
    # Validated BEFORE the expectation is checked, for the level lane's reason: a
    # document this runtime refuses is a client bug whatever the store holds, and
    # reporting it as a conflict would send the launcher to re-read a map that
    # was never the problem.
    try:
        validate_map_document(raw)
    except MapDocumentError as refused_doc:
        return err(
            rid,
            ERR_INVALID_PARAMS,
            str(refused_doc),
            {"reason": refused_doc.code, "map_id": map_id},
        )

    # Uniqueness, asked HERE and nowhere near the pull applier. This is an
    # AUTHORING door — the launcher's picker is naming a map — and two entries
    # called "island" make the catalogue useless for the one job it has. The
    # pull deliberately does not ask: refusing an arriving map over a label
    # would delete a peer's catalogue entry, which is the defect this family
    # exists to close. ``map_name_holder`` carries that argument in full.
    holder = map_name_holder(map_id, raw)
    if holder is not None:
        return err(
            rid,
            ERR_INVALID_PARAMS,
            f"another map already holds this name: {holder}",
            {"reason": REFUSAL_NAME_TAKEN, "map_id": map_id, "held_by": holder},
        )

    store = MapStore()
    stored = store.read(map_id)
    if not map_expectation_matches(stored, expect_sha256, provided=expect_provided):
        return err(
            rid,
            ERR_CONFLICT,
            "the stored map is not the one this write was based on",
            {
                "reason": MAP_SHA256_MISMATCH_REASON,
                "map_id": map_id,
                "current_sha256": stored_map_sha256(stored) if stored is not None else None,
            },
        )

    try:
        outcome = store.write(map_id, raw)
    except OSError as failed:
        return err(
            rid,
            ERR_HANDLER_FAILED,
            str(failed),
            {"reason": "runtime_unavailable", "map_id": map_id},
        )

    row = map_document_row(map_id, raw, full=False)
    row["changed"] = bool(outcome["changed"])
    log_office_write(
        op="runtime.map.set",
        correlation_id=correlation_id,
        map_id=map_id,
        bytes=row["bytes"],
        sha256=row["sha256"],
        changed=row["changed"],
    )
    if correlation_id is not None:
        row["correlation_id"] = correlation_id
    return ok(rid, row)


@method("runtime.map.clear", tier=TIER_CONSOLE)
def _runtime_map_clear(rid: Any, params: dict, context: RpcContext | None = None) -> dict:
    """Remove one catalogue map, optionally compare-and-set.

    Params: ``map_id`` (required), ``expect_sha256`` (optional, the same three
    meanings ``runtime.map.set`` gives it), ``correlation_id`` (optional).

    Result: ``{map_id, cleared}`` — ``cleared: false`` when nothing was stored,
    an accepted no-op and the reason a retry converges. Absence is not an error
    HERE even though it is on ``.get``: a clear states a desired end state and
    the end state already holds, while a get asks for a thing that does not
    exist.

    Errors: as ``runtime.map.set``, minus the document ones.

    **A clear is LOCAL and is not a removal from the realm.** The pull's
    ``upstream_absent`` arm is deliberately never a delete, so a map the realm
    still publishes returns on the next pull — and here that ruling is the fix
    rather than a caveat: a catalogue entry that vanished on a peer IS the
    reported defect.
    """

    from agent_runtime.map_sync import MapStore, map_expectation_matches, stored_map_sha256

    map_id, refusal = _map_id_or_error(rid, params)
    if refusal is not None:
        return refusal
    assert map_id is not None

    try:
        expect_provided, expect_sha256 = _map_expect_param(params)
    except ParamRefused as bad:
        return bad.frame(rid, map_id=map_id)

    try:
        correlation_id = _correlation_id_param(params)
    except ParamRefused as bad:
        return bad.frame(rid, map_id=map_id)

    store = MapStore()
    stored = store.read(map_id)
    if not map_expectation_matches(stored, expect_sha256, provided=expect_provided):
        return err(
            rid,
            ERR_CONFLICT,
            "the stored map is not the one this clear was based on",
            {
                "reason": MAP_SHA256_MISMATCH_REASON,
                "map_id": map_id,
                "current_sha256": stored_map_sha256(stored) if stored is not None else None,
            },
        )

    try:
        outcome = store.clear(map_id)
    except OSError as failed:
        return err(
            rid,
            ERR_HANDLER_FAILED,
            str(failed),
            {"reason": "runtime_unavailable", "map_id": map_id},
        )

    cleared = bool(outcome["changed"])
    log_office_write(
        op="runtime.map.clear",
        correlation_id=correlation_id,
        map_id=map_id,
        cleared=cleared,
    )
    result: dict[str, Any] = {"map_id": map_id, "cleared": cleared}
    if correlation_id is not None:
        result["correlation_id"] = correlation_id
    return ok(rid, result)
