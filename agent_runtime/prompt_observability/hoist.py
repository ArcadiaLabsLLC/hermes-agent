"""The S3 read model: skill lists hoisted to content-addressed refs, debug payloads evicted to stubs.

Separate because it is pure shaping over rows the stores already read.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from ..persona_assignments import safe_assignment_token
from ..serde import to_jsonable
from .safe_views import (
    _safe_cache_routing,
    _safe_int,
    _safe_system_prompt_sections,
    _safe_user_message_wire,
)
from .spans import PROMPT_OBSERVABILITY_TIMINGS_KEY

__layer__ = "policy"
__all__ = [
    "SKILLS_REF_HASH_LEN",
    "HOISTED_SKILL_LIST_FIELDS",
    "_skills_list_content_hash",
    "_hoist_skills_catalogs",
    "_evict_final_model_input",
    "PROMPT_LAYER_CONTENT_FETCH",
    "_evict_builder_timings",
    "_evict_prompt_layer_content",
]


# --------------------------------------------------------------------------- #
# S3 read-model — hoist duplicated globals + evict on-demand debug payloads.
#
# The skills catalog is a GLOBAL (one installed catalog per config; one
# accessible set per persona), yet the pre-S3 frame stored ``available_skills``
# / ``skills_catalog`` (installed catalog, ~19KB) AND ``accessible_skills`` /
# ``skills`` (per-persona set, ~8KB) INLINE on EVERY ``chat_contexts`` row —
# byte-identical across rows (S1 audit: 1.91 MiB wasted of a 6.05 MiB frame).
# S3 stores each distinct skill list ONCE, content-addressed, under
# ``prompt_observability.skills_catalogs`` and replaces the four inline fields
# with two hash refs (``available_skills_ref`` / ``accessible_skills_ref``); the
# two byte-identical alias pairs collapse to their canonical ref.
#
# ``final_model_input`` (~30KB/row) is a per-turn DEBUG artifact read only when
# an operator opens the Context peek — it has no steady-state reader yet rode
# every frame. S3 evicts it to a typed stub carrying the recorded byte count +
# message count + fetch verb; the full payload stays on disk in the persisted
# observability row (archive-never-delete) and is fetched on demand.
#
# S7-B RULING-0 COMPAT STRIP (2026-07-16): the ``read_model.inline_prompt_payloads``
# kill-switch and its inline legacy branch were removed — the hoisted/evicted
# shape is the ONLY shape. Rollback = ``git revert``, not a flag flip.
# --------------------------------------------------------------------------- #

#: Length of the content-hash refs (sha256 prefix). Short enough to be cheap on
#: every row, wide enough that a collision across a frame's skill lists is
#: astronomically unlikely.
SKILLS_REF_HASH_LEN = 16


#: The inline per-row skill-list fields hoisted out of each ``chat_contexts``
#: row in the default (hoisted) shape. ``skills_catalog`` aliases
#: ``available_skills`` and ``skills`` aliases ``accessible_skills`` — all four
#: leave the row; the two canonical lists are recoverable by resolving the two
#: refs against ``skills_catalogs``.
HOISTED_SKILL_LIST_FIELDS = (
    "available_skills",
    "skills_catalog",
    "accessible_skills",
    "skills",
)


def _skills_list_content_hash(rows: Any) -> str:
    """Stable content hash of a skill list (compact, sorted, non-ASCII-safe).

    Byte-identical lists hash to the same ref, so the global installed catalog
    (identical on every row) and any two personas sharing an accessible set map
    to one stored blob."""

    payload = json.dumps(
        to_jsonable(rows),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:SKILLS_REF_HASH_LEN]


def _hoist_skills_catalogs(
    chat_contexts: list[dict[str, Any]], catalogs: dict[str, Any]
) -> None:
    """Replace each row's inline skill lists with content-hash refs into
    ``catalogs`` (stored once). Mutates ``chat_contexts`` and ``catalogs`` in
    place. A row missing a list simply carries no ref for it — never a fake
    empty catalog (an absent ref resolves to nothing, honestly)."""

    for row in chat_contexts:
        if not isinstance(row, dict):
            continue
        available = row.get("available_skills")
        if isinstance(available, list):
            ref = _skills_list_content_hash(available)
            catalogs.setdefault(ref, available)
            row["available_skills_ref"] = ref
        accessible = row.get("accessible_skills")
        if isinstance(accessible, list):
            ref = _skills_list_content_hash(accessible)
            catalogs.setdefault(ref, accessible)
            row["accessible_skills_ref"] = ref
        for field in HOISTED_SKILL_LIST_FIELDS:
            row.pop(field, None)


def _final_model_input_stub(final_model_input: dict[str, Any], context_id: Any) -> dict[str, Any]:
    """The evicted ``final_model_input`` frame value: a typed accounting stub.

    Carries the recorded byte size (so the operator knows the payload exists and
    how large it is), the message count (so the peek can still say "N messages"),
    and the addressable fetch verb. Never a silent absence, never a fake-empty
    payload.

    Also carries a slim ``tool_schema`` accounting block (``tool_count`` +
    ``json_bytes``) and the already-small, one-way ``cache_routing`` evidence
    when present. The tool schemas are the single largest fixed slice of the
    prompt after the system message, and cache-routing fingerprints must remain
    comparable between warm and cold turns on the eviction lane. Both are
    copied through typed safety boundaries and omitted when absent."""

    payload = json.dumps(
        to_jsonable(final_model_input),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    message_count = final_model_input.get("message_count")
    if not isinstance(message_count, int):
        messages = final_model_input.get("messages")
        message_count = len(messages) if isinstance(messages, list) else 0
    token = safe_assignment_token(context_id)
    stub: dict[str, Any] = {
        "evicted": True,
        "bytes": len(payload.encode("utf-8")),
        "message_count": message_count,
        "context_id": token or None,
        "fetch": "harness prompt-context final-model-input --context-id <id> --json",
    }
    tool_schema = final_model_input.get("tool_schema")
    if isinstance(tool_schema, dict):
        stub["tool_schema"] = {
            "tool_count": _safe_int(tool_schema.get("tool_count")),
            "json_bytes": _safe_int(tool_schema.get("json_bytes")),
        }
    cache_routing = _safe_cache_routing(final_model_input.get("cache_routing"))
    if cache_routing is not None:
        # Unlike messages/tool bodies, this block is already tiny and contains
        # only one-way fingerprints. Keep it in the frame stub so operators can
        # compare a cold turn with adjacent warm turns without a disk fetch.
        stub["cache_routing"] = cache_routing
    wire = _safe_user_message_wire(final_model_input.get("user_message_wire"))
    if wire is not None:
        # T4: a handful of ints. Whether the captured user row is the WIRE copy
        # is exactly the fact an evicted payload must not take with it — the
        # operator opening a peek needs to know the record is trustworthy before
        # deciding whether the fetch is worth it.
        stub["user_message_wire"] = wire
    sections = _safe_system_prompt_sections(
        final_model_input.get("system_prompt_sections")
    )
    if sections:
        # Tiny address metadata only. The actual prompt remains evicted and is
        # fetched on demand when the operator opens a section.
        stub["system_prompt_sections"] = sections
    return stub


def _evict_final_model_input(chat_contexts: list[dict[str, Any]]) -> None:
    """Replace each row's heavy ``final_model_input`` with the accounting stub.

    Mutates ``chat_contexts`` in place. The persisted row on disk is untouched —
    only the FRAME copy is stubbed."""

    for row in chat_contexts:
        if not isinstance(row, dict):
            continue
        final_model_input = row.get("final_model_input")
        if isinstance(final_model_input, dict) and not final_model_input.get("evicted"):
            row["final_model_input"] = _final_model_input_stub(
                final_model_input, row.get("context_id")
            )


#: The verb that resolves an evicted ``prompt_layers[].content``. It is the
#: SAME persisted row ``chat_contexts_ref`` already advertises — the layer
#: bodies ride that row, so eviction adds no new fetch lane, only a new
#: pointer into the one that exists.
PROMPT_LAYER_CONTENT_FETCH = "harness prompt-context show --context-id <id> --json"


def _prompt_layer_content_stub(content: str) -> dict[str, Any]:
    """The evicted ``prompt_layers[].content`` frame value: an accounting stub.

    Carries the exact char count (so the launcher's token attribution keeps its
    number), the content hash (so two turns' identical layer bodies are
    comparable without either body) and the fetch verb. Never a silent absence,
    and deliberately never a PREVIEW — a rendered prefix of a body is the
    truncate option the 2026-09-05 ruling declined, "a lie of a different
    kind"."""

    return {
        "evicted": True,
        "chars": len(content),
        "sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
        "fetch": PROMPT_LAYER_CONTENT_FETCH,
    }


def _evict_builder_timings(chat_contexts: list[dict[str, Any]]) -> None:
    """Drop the builder's own sub-spans from every FRAME row.

    chat-turn-prep Stage 6: :func:`mission_chat_prompt_observability` returns
    :data:`OBSERVABILITY_TIMING_KEYS` under
    :data:`PROMPT_OBSERVABILITY_TIMINGS_KEY` so the mission-chat handler can
    fold them onto the turn record's ``profile_timing``. That is the mapping's
    ONLY consumer, and every other exit drops it: the handler pops it before the
    row travels on, :func:`persist_prompt_observability_context` drops it before
    a row reaches disk, and this drops it before a row reaches the read-model
    frame.

    The snapshot lane builds rows through the same function with no handler in
    between, so without this the section would put a wall-clock-dependent
    mapping onto a byte-pinned wire projection — measured, not hypothetical: it
    moved two rows of the launcher's `delta_agent_create_narrow_profile`
    fixture the first time this stage was run.

    Mutates ``chat_contexts`` in place, like its two neighbours above.
    """

    for row in chat_contexts:
        if isinstance(row, dict):
            row.pop(PROMPT_OBSERVABILITY_TIMINGS_KEY, None)


def _evict_prompt_layer_content(chat_contexts: list[dict[str, Any]]) -> None:
    """Replace each prompt layer's heavy ``content`` with the accounting stub.

    w13/h4, ruled 2026-09-05. ``prompt_layers[].content`` was the single largest
    slice of the agent-create stream golden (35.7% of 56,627 bytes across the
    two chat contexts) and of every live delta that carries the same projection.

    The stub lands under a SIBLING key, ``content_ref`` — not under ``content``
    re-typed as a map. The launcher decodes ``content`` through a nullable
    STRING parser, so a map there would silently become null and take the
    accounting with it; an ABSENT ``content`` degrades to the null that model
    already declares, and the stub rides beside it under this module's existing
    ``*_ref`` convention.

    Mutates ``chat_contexts`` in place. The persisted row on disk is untouched —
    only the FRAME copy is stubbed, so ``PROMPT_LAYER_CONTENT_FETCH`` resolves
    the exact body (archive-never-delete)."""

    for row in chat_contexts:
        if not isinstance(row, dict):
            continue
        layers = row.get("prompt_layers")
        if not isinstance(layers, list):
            continue
        for layer in layers:
            if not isinstance(layer, dict):
                continue
            content = layer.get("content")
            # A non-string body is left exactly where it is: this function
            # accounts text, and inventing a hash for something else would be a
            # fabricated receipt. An already-stubbed layer has no ``content``
            # left to find, which is what makes a second pass a no-op.
            if not isinstance(content, str):
                continue
            layer.pop("content", None)
            layer["content_ref"] = _prompt_layer_content_stub(content)
