"""Building one ``state.patched`` payload: the 4 KB shrink ladder
(:func:`build_state_patch`), the correlation-id fence, and the office id scheme
with its inverse (:func:`office_patch_scope`). Pure — no store, no log.
"""

from __future__ import annotations

import json
from typing import Any

from ..events import EVENT_PAYLOAD_LIMIT_BYTES
from ..serde import to_jsonable
from .models import (
    _CORRELATION_ID_RE,
    CORRELATION_ID_KEY,
    CORRELATION_ID_MAX_LEN,
    OFFICE_ACTOR_ENTITY,
    OFFICE_CONFLICT_ENTITY,
    OFFICE_SURFACE_ENTITY,
    PATCH_OP_REFRESH,
    PATCH_OP_UPSERT,
    PATCH_VALUE_BUDGET_BYTES,
)

__layer__ = "policy"


def normalize_correlation_id(value: Any) -> str | None:
    """``value`` as a legal correlation token, or ``None``.

    THE payload-side fence. Every producer path funnels through here, so an
    illegal token can never reach an event payload no matter which caller
    threaded it: the RPC boundary REFUSES a bad id out loud (a client bug is
    worth a refusal), and this drops it silently for the in-process callers that
    have no channel to be told on (``agent_create``'s own 200-char validator is
    looser than this cap, so its tokens are re-checked here rather than trusted).

    ``None`` in, ``None`` out — which is what keeps every payload without a
    gesture behind it byte-identical to before this key existed.
    """

    if value is None:
        return None
    if not isinstance(value, str):
        return None
    token = value.strip()
    if not token or len(token) > CORRELATION_ID_MAX_LEN:
        return None
    if not _CORRELATION_ID_RE.match(token):
        return None
    return token


def _value_bytes(value: Any) -> int:
    """Serialized byte size of ``value`` under the exact encoding
    :meth:`EventLog.append` measures the payload with."""

    return len(json.dumps(to_jsonable(value), ensure_ascii=False).encode("utf-8"))


def _oversize_marker(byte_count: int) -> dict[str, Any]:
    return {"oversize": True, "bytes": int(byte_count)}


def _is_oversize_marker(value: Any) -> bool:
    return (
        isinstance(value, dict)
        and value.get("oversize") is True
        and set(value.keys()) == {"oversize", "bytes"}
    )


def _assemble(
    entity: str,
    entity_id: str,
    op: str,
    changed: dict[str, Any] | None,
    created: bool | None = None,
    correlation_id: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {"entity": str(entity), "id": str(entity_id), "op": str(op)}
    if changed is not None:
        payload["changed"] = changed
    if created is not None:
        payload["created"] = bool(created)
    if correlation_id is not None:
        payload[CORRELATION_ID_KEY] = str(correlation_id)
    return payload


def build_state_patch(
    entity: str,
    entity_id: str,
    op: str = PATCH_OP_UPSERT,
    changed: dict[str, Any] | None = None,
    created: bool | None = None,
    correlation_id: str | None = None,
) -> dict[str, Any]:
    """Build an op-based ``state.patched`` payload, sized to fit the 4 KB cap.

    * ``remove`` / ``refresh`` carry no ``changed`` → always tiny.
    * ``upsert`` carries the projected ``changed`` fields. A field value larger
      than :data:`PATCH_VALUE_BUDGET_BYTES` is replaced by an accounted
      ``{oversize: true, bytes: N}`` marker; if the assembled payload still
      exceeds :data:`EVENT_PAYLOAD_LIMIT_BYTES` (many mid-sized fields), the
      largest still-inline values are marked deterministically (largest-first,
      ties broken by field name). If it STILL overflows (or every value is an
      oversize marker), the whole patch degrades to ``op: "refresh"`` — an
      accounted "re-fetch this actor", never a partial merge.

    ``created`` is an ADDITIVE optional key (office fold-promotion plan §V4,
    2026-08-16) meaning "this row did not exist before the write, so a fold must
    INSERT it rather than merge onto an absent target". It is carried inside the
    existing 4 KB accounting — the shrink loop re-measures the assembled payload
    including it, so a create can never overflow the cap by the width of a
    boolean. It rides only where a producer states it; ``None`` keeps the payload
    byte-identical to before this key existed, which is what makes every fielded
    reader's fixed key-set read unaffected.

    It is deliberately NOT part of the fold itself: the launcher's office fold
    inserts-on-absent unconditionally. The key exists so
    :func:`~agent_runtime.patch_coverage.event_is_patch_coverable` can GATE the
    widened op behind the ``office_actor_lifecycle`` capability token, i.e. so an
    un-updated client is never PROMOTED a row its fold would answer with a
    re-hydrate.

    ``correlation_id`` is the SECOND additive optional key, on exactly the
    ``created`` pattern and for the same reason it can be (EG-2.3 / Plan D §V2):
    a payload key past required-field validation is free, and absent-when-unset
    keeps every existing payload byte-identical. It is carried INSIDE the shrink
    loop's accounting below, so a gesture token can never overflow the cap by the
    width of a 64-character string — the loop re-measures the assembled payload
    with it present and marks one more value if it has to.

    Note the ``refresh`` degrades keep the id. A refresh says *this row is not
    expressible, re-fetch it*, and "which gesture caused the re-fetch" is the
    single most valuable thing to know about a demote, so the id is the one key a
    degrade must not drop.
    """

    if op != PATCH_OP_UPSERT or not changed:
        return _assemble(
            entity,
            entity_id,
            PATCH_OP_REFRESH if op == PATCH_OP_UPSERT else op,
            None,
            # A ``refresh`` degrade is no longer a create-shaped row: the client
            # refetches, so telling it the row was new would be a claim about a
            # patch that no longer carries one. ``remove`` keeps the marker,
            # because the lifecycle gate reads the op there instead.
            created if op != PATCH_OP_UPSERT else None,
            correlation_id,
        )

    safe_changed: dict[str, Any] = {}
    for field_name, value in changed.items():
        size = _value_bytes(value)
        safe_changed[str(field_name)] = _oversize_marker(size) if size > PATCH_VALUE_BUDGET_BYTES else value

    payload = _assemble(entity, entity_id, PATCH_OP_UPSERT, safe_changed, created, correlation_id)
    while _value_bytes(payload) > EVENT_PAYLOAD_LIMIT_BYTES:
        inline = [(name, val) for name, val in safe_changed.items() if not _is_oversize_marker(val)]
        if not inline:
            # Nothing left to shrink and the payload still overflows — degrade the
            # whole patch to an accounted ``refresh`` (the launcher re-fetches this
            # actor via checkpoint) rather than ship a marker-only merge it cannot
            # fold with fidelity.
            return _assemble(entity, entity_id, PATCH_OP_REFRESH, None, None, correlation_id)
        name = max(inline, key=lambda item: (_value_bytes(item[1]), item[0]))[0]
        safe_changed[name] = _oversize_marker(_value_bytes(safe_changed[name]))
        payload = _assemble(entity, entity_id, PATCH_OP_UPSERT, safe_changed, created, correlation_id)
    return payload


def office_actor_patch_id(workspace_id: Any, actor_key: Any) -> str:
    """The patch identity for one office actor: ``"<workspace_id>/<actor_key>"``.

    An ``actor_key`` alone is NOT an identity. Actor files live at
    ``office/<workspace_id>/actors/<token>.json``, so uniqueness is per-workspace
    by construction and two workspaces may legitimately hold the same key — a
    bare key on the wire would address whichever one the fold happened to find.

    ``/`` is the separator because it is the one character that CANNOT appear in
    either half: ``serde.safe_id`` and ``paths.safe_path_token`` both
    keep only ``alnum`` plus ``_.:-`` and rewrite everything else to ``_``. Note
    ``:`` survives that filter and so could not have been used. Split on the
    FIRST ``/`` — single authority, mirrored by the launcher's fold.
    """

    return f"{workspace_id}/{actor_key}"


def office_patch_scope(patch: Any) -> str | None:
    """The office workspace one ``state.patched`` row belongs to, or ``None``.

    THE SCOPE AUTHORITY for the office push lane, and it lives here — beside the
    id BUILDERS — because a scope parser is the id scheme read backwards, and the
    two had drifted (operator task #57).

    What the drift cost. ``serve_office_subscriptions.office_patch_sink`` carried
    a private restatement of this rule that knew only ``office_actor`` and its
    slash-prefixed id. When WV-H3 (2026-08-16) widened what may PROMOTE to
    include ``office_surface`` — whose id is the BARE workspace id, no slash — a
    folder-only batch became coverable, was fanned to the sink, and failed both
    conjuncts of that private predicate: no patch, no resync, the change dropped
    on a lane whose own docstring says "a resync is recoverable; a dropped change
    is not". It survived only because a mixed batch (any actor row) admits the
    whole frame under forward-whole, and because the argv ``harness stream`` child
    still folded the same batch for the launcher.

    So both readers on that lane now call THIS, and a batch the coverage authority
    promotes is by construction either forwarded or resynced.

    The two id shapes, and why one function can hold all three entities:

    * ``office_actor`` — ``"<workspace_id>/<actor_key>"``. Split on the FIRST
      ``/`` exactly as :func:`office_actor_patch_id` joins on it (that separator
      is the one character neither half can contain, so the split is total). An id
      with no separator names no workspace and answers ``None`` rather than
      guessing; this is also what keeps ``ws_pilot_2`` out of ``ws_pilot``'s
      scope, where a naive ``startswith`` on the bare id would have leaked it.
    * ``office_conflict`` — the SAME shape, because
      :func:`emit_office_conflict_resolved_patch` reuses the same id builder, so
      it shares the actor arm rather than repeating it. Routing it here is not
      cosmetic: an office patch this function cannot place is one the subscribe
      lane silently DROPS (the WV-H3 failure this docstring records), so an
      unrouted conflict row would be a resolve that promoted its batch and folded
      nothing — strictly worse than the full core it replaced.
    * ``office_surface`` — the bare workspace id
      (:func:`emit_office_surface_patch`), so the id IS the scope.

    ``None`` for every other entity, for a malformed row, and for an office row
    whose id cannot be placed. ``None`` is NOT "every workspace": a
    ``persona_instance`` row is real state at its watermark but it moves nothing a
    one-workspace office projection holds, which is why the office lane forwards
    such a row inside an in-scope frame and never lets it put a frame in scope.
    """

    if not isinstance(patch, dict):
        return None
    entity = patch.get("entity")
    entity_id = patch.get("id")
    if not isinstance(entity_id, str) or not entity_id:
        return None
    if entity in (OFFICE_ACTOR_ENTITY, OFFICE_CONFLICT_ENTITY):
        workspace_id, separator, _actor_key = entity_id.partition("/")
        if not separator or not workspace_id:
            return None
        return workspace_id
    if entity == OFFICE_SURFACE_ENTITY:
        return entity_id
    return None
