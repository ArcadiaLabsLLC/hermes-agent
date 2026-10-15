"""``runtime.prefab.list`` / ``get`` / ``set`` / ``clear`` -- a profile's user prefab shelf.

The map catalogue's sibling (``serve_rpc/map.py``), keyed by ``(profile,
prefab_id)``: the launcher's ``UserPrefabStore`` keeps one shelf per signed-in
profile, so every verb names the profile and never falls back to a default one.
Everything writes through ``PrefabStore`` (``agent_runtime/prefab_store.py``) and
answers ``prefab_document_row``, so the ``sha256`` a caller reads on ``.list`` /
``.get`` is the token ``.set`` / ``.clear`` compare-and-set on.
"""

from __future__ import annotations

from typing import Any

from agent_runtime.call_authorization import TIER_CONSOLE
from agent_runtime.serve_rpc.office_read import log_office_write
from agent_runtime.serve_rpc.params import (
    ParamRefused,
    _correlation_id_param,
    _map_expect_param,
    _text_param,
)
from agent_runtime.serve_rpc.protocol import (
    ERR_CONFLICT,
    ERR_HANDLER_FAILED,
    ERR_INVALID_PARAMS,
    ERR_NOT_FOUND,
    err,
    ok,
)
from agent_runtime.serve_rpc.reasons import RpcRefusal
from agent_runtime.serve_rpc.registry import method

__layer__ = "lanes"

__all__ = [
    "_runtime_prefab_clear",
    "_runtime_prefab_get",
    "_runtime_prefab_list",
    "_runtime_prefab_set",
]


def _profile_or_error(rid: Any, params: dict) -> tuple[str | None, dict | None]:
    profile = _text_param(params, "profile")
    if profile is None:
        return None, err(rid, ERR_INVALID_PARAMS, "invalid params: profile must be a non-empty string",
                         {"reason": "profile_required"})
    return profile, None


def _address_or_error(rid: Any, params: dict) -> tuple[tuple[str, str] | None, dict | None]:
    """``((profile, prefab_id), None)`` or ``(None, error_frame)`` -- one spelling for three verbs."""

    profile, refusal = _profile_or_error(rid, params)
    if refusal is not None:
        return None, refusal
    prefab_id = _text_param(params, "prefab_id")
    if prefab_id is None:
        return None, err(rid, ERR_INVALID_PARAMS, "invalid params: prefab_id must be a non-empty string",
                         {"reason": "prefab_id_required", "profile": profile})
    return (profile, prefab_id), None


def _conflict(rid: Any, profile: str, prefab_id: str, stored: bytes | None) -> dict:
    from agent_runtime.prefab_store import stored_prefab_sha256

    return err(rid, ERR_CONFLICT, "the stored prefab is not the one this write was based on", {
        "reason": RpcRefusal.SHA256_MISMATCH, "profile": profile, "prefab_id": prefab_id,
        "current_sha256": stored_prefab_sha256(stored) if stored is not None else None,
    })


@method("runtime.prefab.list", tier=TIER_CONSOLE)
def _runtime_prefab_list(rid: Any, params: dict, context=None) -> dict:
    """One profile's shelf WITHOUT the bytes: ``{profile, prefabs: [row, ...], count}``.

    Params: ``profile`` (required). Console tier for ``runtime.map.list``'s
    reason: the rows are the operator's own authored vocabulary.
    """

    from agent_runtime.prefab_store import PrefabStore, prefab_document_row

    profile, refusal = _profile_or_error(rid, params)
    if refusal is not None:
        return refusal
    store = PrefabStore(profile)
    rows = [prefab_document_row(profile, token, store.read(token)) for token in store.list_prefab_tokens()]
    return ok(rid, {"profile": profile, "prefabs": rows, "count": len(rows)})


@method("runtime.prefab.get", tier=TIER_CONSOLE)
def _runtime_prefab_get(rid: Any, params: dict, context=None) -> dict:
    """ONE prefab's row plus ``document`` (the stored bytes as a string).

    Params: ``profile``, ``prefab_id``. ``4001`` ``prefab_not_found`` when the
    shelf holds no such prefab: the document IS the shelf entry, as for a map.
    """

    from agent_runtime.prefab_store import PrefabStore, prefab_document_row

    address, refusal = _address_or_error(rid, params)
    if refusal is not None:
        return refusal
    profile, prefab_id = address
    raw = PrefabStore(profile).read(prefab_id)
    if raw is None:
        return err(rid, ERR_NOT_FOUND, f"unknown prefab: {prefab_id}",
                   {"reason": "prefab_not_found", "profile": profile, "prefab_id": prefab_id})
    return ok(rid, prefab_document_row(profile, prefab_id, raw, full=True))


@method("runtime.prefab.set", tier=TIER_CONSOLE)
def _runtime_prefab_set(rid: Any, params: dict, context=None) -> dict:
    """Store one prefab VERBATIM, optionally compare-and-set.

    Params: ``profile``, ``prefab_id``, ``document`` (the launcher's prefab wire
    as a string), ``expect_sha256`` (optional: hex, ``null`` for "nothing
    stored", omitted for unconditional), ``correlation_id`` (optional).

    Result: the ``.list`` row plus ``changed``. Errors: ``-32602``
    ``profile_required`` / ``prefab_id_required`` / ``document_required`` /
    ``expect_sha256_invalid`` / a ``PrefabDocumentError`` code /
    ``label_taken`` (``held_by``); ``4090`` ``sha256_mismatch``.
    """

    from agent_runtime.prefab_store import (
        REFUSAL_LABEL_TAKEN,
        PrefabDocumentError,
        PrefabStore,
        prefab_document_row,
        prefab_expectation_matches,
        validate_prefab_document,
    )

    address, refusal = _address_or_error(rid, params)
    if refusal is not None:
        return refusal
    profile, prefab_id = address
    document = params.get("document")
    if not isinstance(document, str):
        return err(rid, ERR_INVALID_PARAMS, "invalid params: document must be a string",
                   {"reason": "document_required", "profile": profile, "prefab_id": prefab_id})
    try:
        expect_provided, expect_sha256 = _map_expect_param(params)
        correlation_id = _correlation_id_param(params)
    except ParamRefused as bad:
        return bad.frame(rid, profile=profile, prefab_id=prefab_id)

    raw = document.encode("utf-8")
    try:
        validate_prefab_document(raw)
    except PrefabDocumentError as refused:
        return err(rid, ERR_INVALID_PARAMS, str(refused),
                   {"reason": refused.code, "profile": profile, "prefab_id": prefab_id})
    store = PrefabStore(profile)
    holder = store.label_holder(prefab_id, raw)
    if holder is not None:
        return err(rid, ERR_INVALID_PARAMS, f"another prefab on this shelf already holds this label: {holder}",
                   {"reason": REFUSAL_LABEL_TAKEN, "profile": profile, "prefab_id": prefab_id, "held_by": holder})
    stored = store.read(prefab_id)
    if not prefab_expectation_matches(stored, expect_sha256, provided=expect_provided):
        return _conflict(rid, profile, prefab_id, stored)
    try:
        outcome = store.write(prefab_id, raw)
    except OSError as failed:
        return err(rid, ERR_HANDLER_FAILED, str(failed),
                   {"reason": "runtime_unavailable", "profile": profile, "prefab_id": prefab_id})

    row = prefab_document_row(profile, prefab_id, raw)
    row["changed"] = bool(outcome["changed"])
    log_office_write(op="runtime.prefab.set", correlation_id=correlation_id, profile=profile,
                     prefab_id=prefab_id, bytes=row["bytes"], sha256=row["sha256"], changed=row["changed"])
    if correlation_id is not None:
        row["correlation_id"] = correlation_id
    return ok(rid, row)


@method("runtime.prefab.clear", tier=TIER_CONSOLE)
def _runtime_prefab_clear(rid: Any, params: dict, context=None) -> dict:
    """Remove one prefab from the shelf, optionally compare-and-set.

    Result: ``{profile, prefab_id, cleared}`` -- ``cleared: false`` when nothing
    was stored, an accepted no-op so a retry converges.
    """

    from agent_runtime.prefab_store import PrefabStore, prefab_expectation_matches

    address, refusal = _address_or_error(rid, params)
    if refusal is not None:
        return refusal
    profile, prefab_id = address
    try:
        expect_provided, expect_sha256 = _map_expect_param(params)
        correlation_id = _correlation_id_param(params)
    except ParamRefused as bad:
        return bad.frame(rid, profile=profile, prefab_id=prefab_id)
    store = PrefabStore(profile)
    stored = store.read(prefab_id)
    if not prefab_expectation_matches(stored, expect_sha256, provided=expect_provided):
        return _conflict(rid, profile, prefab_id, stored)
    try:
        outcome = store.clear(prefab_id)
    except OSError as failed:
        return err(rid, ERR_HANDLER_FAILED, str(failed),
                   {"reason": "runtime_unavailable", "profile": profile, "prefab_id": prefab_id})
    cleared = bool(outcome["changed"])
    log_office_write(op="runtime.prefab.clear", correlation_id=correlation_id, profile=profile,
                     prefab_id=prefab_id, cleared=cleared)
    result: dict[str, Any] = {"profile": profile, "prefab_id": prefab_id, "cleared": cleared}
    if correlation_id is not None:
        result["correlation_id"] = correlation_id
    return ok(rid, result)
