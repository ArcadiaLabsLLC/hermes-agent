"""``runtime.level.get`` / ``set`` / ``clear`` — the level document verbs.
"""

from __future__ import annotations

from typing import Any

from agent_runtime.call_authorization import TIER_CONSOLE

from agent_runtime.serve_rpc.protocol import (
    ERR_CONFLICT,
    ERR_HANDLER_FAILED,
    ERR_INVALID_PARAMS,
    RpcContext,
    err,
    ok,
)
from agent_runtime.serve_rpc.reasons import RpcRefusal
from agent_runtime.serve_rpc.registry import method
from agent_runtime.serve_rpc.params import (
    ParamRefused,
    _correlation_id_param,
    _level_expect_param,
    _level_workspace_id_or_error,
)
from agent_runtime.serve_rpc.office_read import log_office_write

__layer__ = "lanes"

__all__ = [
    "LEVEL_SHA256_MISMATCH_REASON",
    "_runtime_level_clear",
    "_runtime_level_get",
    "_runtime_level_set",
]


# ── runtime.level.* ──────────────────────────────────────────────────────────
#
# A workspace's LEVEL — the environment it stands in — read, written and
# cleared over the method lane. The owner's 2026-09-22 ruling ("one map per
# workspace, it should be in realms") made hermes the STORE of a level for every
# workspace, not merely the transport for a realm's default one: the launcher's
# office `SceneStore` becomes an adapter over these three verbs, so a level
# travels with the realm exactly like the office and the boards do instead of
# living in one machine's SharedPreferences where it can never be shared.
#
# Everything below writes through ``LevelStore``, the same door realm sync's
# pull applier uses, and hands back ``level_document_row`` — the same row the
# CLI's ``level show`` prints. Two builders that happened to agree today would
# be a permanent false conflict tomorrow, because the launcher compares the
# ``sha256`` it read on one lane against the one it is handed on the other.

#: The ``data.reason`` both writes spend when ``expect_sha256`` does not match.
LEVEL_SHA256_MISMATCH_REASON = RpcRefusal.SHA256_MISMATCH


@method("runtime.level.get", tier=TIER_CONSOLE)
def _runtime_level_get(
    rid: Any, params: dict, context: RpcContext | None = None
) -> dict:
    """ONE workspace's level document, byte for byte as stored.

    Params: ``workspace_id`` (required).

    Result: ``{workspace_id, workspace_token, present, bytes, sha256, version,
    document}`` — ``document`` is the stored bytes as a string and is ``null``
    when ``present`` is false. ``sha256`` is over the STORED BYTES and is the
    token the two writes guard on; it is deliberately NOT the semantic hash
    realm sync merges on (``level_document_hash``), which cannot answer "did my
    document survive the round trip".

    Errors: ``-32602`` ``workspace_id_required``; ``4001``
    ``workspace_not_found``.

    **Tier: ``console``, and it is the row worth arguing.** The one-line rule on
    ``_METHOD_TIERS`` would say ``read`` — nothing is mutated. It says
    ``console`` for ``runtime.media.get``'s reason, reached from the same side:
    this hands back up to 1 MB of a document's RAW BYTES, and the read tier is
    open to ``unknown``, a caller the transport authenticated and could not
    place. A viewer of a level is not automatically entitled to its source. The
    cost is named rather than hidden: a ``read``-tier device cannot load the
    environment its office draws on, which is a live question for the launcher's
    adapter and is filed as a queue row rather than decided here.
    """

    from agent_runtime.level_sync import LevelStore, level_document_row

    workspace_id, refusal = _level_workspace_id_or_error(rid, params)
    if refusal is not None:
        return refusal
    assert workspace_id is not None
    raw = LevelStore().read(workspace_id)
    return ok(rid, level_document_row(workspace_id, raw, full=True))


@method("runtime.level.set", tier=TIER_CONSOLE)
def _runtime_level_set(
    rid: Any, params: dict, context: RpcContext | None = None
) -> dict:
    """Store one workspace's level VERBATIM, optionally compare-and-set.

    Params: ``workspace_id`` (required), ``document`` (required string — the
    launcher's ``SceneSerializer`` output), ``expect_sha256`` (optional: the hex
    of the bytes the caller read, ``null`` for "there must be nothing stored",
    omitted for unconditional), ``correlation_id`` (optional gesture token).

    Result: ``{workspace_id, workspace_token, present, bytes, sha256, version,
    changed}``. ``changed: false`` means the stored bytes were already identical
    — an accepted write, not a refusal.

    Errors: ``-32602`` ``workspace_id_required`` / ``document_required`` /
    ``expect_sha256_invalid``, and ``-32602`` with
    ``data.reason = LevelDocumentError.code`` for a document this runtime will
    not store (the store door's own four words, carried through rather than
    re-derived here, so a client can say WHICH refusal it was); ``4001``
    ``workspace_not_found``; ``4090`` ``{reason: "sha256_mismatch",
    current_sha256}``.

    **``current_sha256`` IS carried, and the office verbs' ruling not to carry a
    revision is not being contradicted.** There, handing back the number invites
    a blind retry with it — the lost update the guard refused. Here the token is
    a hash OF THE DOCUMENT the caller can already fetch, and the launcher's
    adapter needs it to tell "somebody else wrote this" from "my own earlier
    write landed and I missed the ack": it compares the returned hash against
    the one it just computed. A retry still has to re-read the document to
    produce bytes worth writing, so the number buys no shortcut past the merge.

    The bytes are stored EXACTLY as handed over. hermes validates two facts (it
    is UTF-8 JSON, the object carries a ``version``) and reformats nothing — the
    day the backend's level routes land, the transport is meant to be swappable
    without a format change, and a hermes that had normalised the bytes would
    have made itself a second author of a document it does not own.

    This does NOT publish. hermes already counts unpublished levels in realm
    status and the ordinary publish carries them; an auto-publish here would put
    a half-authored environment into a git repo, where the cost is permanent.
    """

    from agent_runtime.level_sync import (
        LevelDocumentError,
        LevelStore,
        level_document_row,
        level_expectation_matches,
        stored_level_sha256,
        validate_level_document,
    )

    workspace_id, refusal = _level_workspace_id_or_error(rid, params)
    if refusal is not None:
        return refusal
    assert workspace_id is not None

    document = params.get("document")
    if not isinstance(document, str):
        return err(
            rid,
            ERR_INVALID_PARAMS,
            "invalid params: document must be a string",
            {"reason": "document_required", "workspace_id": workspace_id},
        )

    try:
        expect_provided, expect_sha256 = _level_expect_param(params)
    except ParamRefused as bad:
        return bad.frame(rid, workspace_id=workspace_id)

    try:
        correlation_id = _correlation_id_param(params)
    except ParamRefused as bad:
        return bad.frame(rid, workspace_id=workspace_id)

    raw = document.encode("utf-8")
    # Validated BEFORE the expectation is checked: a document this runtime
    # refuses is a client bug whatever the store holds, and reporting it as a
    # conflict would send the launcher to re-read a level that was never the
    # problem.
    try:
        validate_level_document(raw)
    except LevelDocumentError as refused:
        return err(
            rid,
            ERR_INVALID_PARAMS,
            str(refused),
            {"reason": refused.code, "workspace_id": workspace_id},
        )

    store = LevelStore()
    stored = store.read(workspace_id)
    if not level_expectation_matches(stored, expect_sha256, provided=expect_provided):
        return err(
            rid,
            ERR_CONFLICT,
            "the stored level is not the one this write was based on",
            {
                "reason": LEVEL_SHA256_MISMATCH_REASON,
                "workspace_id": workspace_id,
                "current_sha256": stored_level_sha256(stored) if stored is not None else None,
            },
        )

    try:
        outcome = store.write(workspace_id, raw)
    except OSError as failed:
        return err(
            rid,
            ERR_HANDLER_FAILED,
            str(failed),
            {"reason": "runtime_unavailable", "workspace_id": workspace_id},
        )

    row = level_document_row(workspace_id, raw, full=False)
    row["changed"] = bool(outcome["changed"])
    log_office_write(
        op="runtime.level.set",
        correlation_id=correlation_id,
        workspace=workspace_id,
        bytes=row["bytes"],
        sha256=row["sha256"],
        changed=row["changed"],
    )
    if correlation_id is not None:
        row["correlation_id"] = correlation_id
    return ok(rid, row)


@method("runtime.level.clear", tier=TIER_CONSOLE)
def _runtime_level_clear(
    rid: Any, params: dict, context: RpcContext | None = None
) -> dict:
    """Remove one workspace's level, optionally compare-and-set.

    Params: ``workspace_id`` (required), ``expect_sha256`` (optional, the same
    three meanings ``runtime.level.set`` gives it), ``correlation_id``
    (optional).

    Result: ``{workspace_id, cleared}`` — ``cleared: false`` when nothing was
    stored, which is an accepted no-op and the reason a retry converges.

    Errors: as ``runtime.level.set``, minus the document ones.

    **A clear is LOCAL and is not a removal from the realm.** The pull's
    ``upstream_absent`` arm is deliberately never a delete, so a level the realm
    still publishes returns on the next pull. That is the family's ruling about
    authored work, and a caller who means "this realm should stop carrying this
    level" is publishing, not clearing.
    """

    from agent_runtime.level_sync import (
        LevelStore,
        level_expectation_matches,
        stored_level_sha256,
    )

    workspace_id, refusal = _level_workspace_id_or_error(rid, params)
    if refusal is not None:
        return refusal
    assert workspace_id is not None

    try:
        expect_provided, expect_sha256 = _level_expect_param(params)
    except ParamRefused as bad:
        return bad.frame(rid, workspace_id=workspace_id)

    try:
        correlation_id = _correlation_id_param(params)
    except ParamRefused as bad:
        return bad.frame(rid, workspace_id=workspace_id)

    store = LevelStore()
    stored = store.read(workspace_id)
    if not level_expectation_matches(stored, expect_sha256, provided=expect_provided):
        return err(
            rid,
            ERR_CONFLICT,
            "the stored level is not the one this clear was based on",
            {
                "reason": LEVEL_SHA256_MISMATCH_REASON,
                "workspace_id": workspace_id,
                "current_sha256": stored_level_sha256(stored) if stored is not None else None,
            },
        )

    try:
        outcome = store.clear(workspace_id)
    except OSError as failed:
        return err(
            rid,
            ERR_HANDLER_FAILED,
            str(failed),
            {"reason": "runtime_unavailable", "workspace_id": workspace_id},
        )

    cleared = bool(outcome["changed"])
    log_office_write(
        op="runtime.level.clear",
        correlation_id=correlation_id,
        workspace=workspace_id,
        cleared=cleared,
    )
    result: dict[str, Any] = {"workspace_id": workspace_id, "cleared": cleared}
    if correlation_id is not None:
        result["correlation_id"] = correlation_id
    return ok(rid, result)
