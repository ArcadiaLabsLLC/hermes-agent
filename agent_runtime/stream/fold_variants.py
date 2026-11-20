"""The fold-variants envelope and its per-subscriber resolution.

A MIXED room (some subscribers fold the batch's patch, some cannot) gets one
envelope carrying both halves (:func:`fold_variants_frame`, built by
``build._batch_frames_with_liveness``), and each subscriber is handed the half
its own declaration can fold (:func:`resolve_fold_variant`, at the serve hub's
fan-out). Split out of ``frames`` when the patch frame's ``events[]`` took it
over the size ceiling: the pair is the envelope's whole vocabulary, read by
``build`` and ``serve_stream_hub`` and by nothing in ``frames``.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from ..patch_coverage import normalize_fold_entities
from .vocabulary import FOLD_VARIANTS_FRAME_TYPE

__layer__ = "stores"


def fold_variants_frame(
    *,
    patch: dict[str, Any],
    core: dict[str, Any],
    required_tokens: Iterable[str],
) -> dict[str, Any]:
    """Pair one batch's promoted patch with its demoted core for a MIXED room.

    ``required_tokens`` is what a subscriber's declaration must contain to be
    handed the ``patch`` half (:func:`~agent_runtime.patch_coverage
    .batch_required_fold_tokens`). Everyone else gets ``core``, which is the
    identical frame the intersection rule would have sent them anyway — the
    demotion moves from the ROOM to the SUBSCRIBER and nothing else about it
    changes.

    **The build is not paid twice.** The core in here was going to be built
    regardless: under the old intersection rule a batch that any subscriber
    could not fold demoted the whole room, so the snapshot build happened then
    too. What changes is who receives the megabyte, not how many megabytes are
    made. A batch nobody can fold never reaches this function (the caller emits
    the bare core), and a batch everybody can fold never reaches it either (the
    caller emits the bare patch and builds no core at all) — so the envelope
    exists exactly on the batches where the room genuinely disagrees.
    """

    return {
        "type": FOLD_VARIANTS_FRAME_TYPE,
        "required_fold_tokens": sorted(required_tokens),
        "patch": patch,
        "core": core,
    }


def resolve_fold_variant(
    frame: dict[str, Any], declared: Iterable[str] | None
) -> dict[str, Any]:
    """The frame ONE subscriber should be handed, given what it declared.

    Any frame that is not a :data:`FOLD_VARIANTS_FRAME_TYPE` envelope is returned
    unchanged — which is every frame on a homogeneous lane, so the resolver costs
    one dict lookup on the overwhelmingly common path.

    ``declared`` is that subscriber's own declaration, normalized by the same
    :func:`~agent_runtime.patch_coverage.normalize_fold_entities` the coverage
    gate uses (so ``None`` means the historical set here exactly as it does
    there, and never the empty set).

    **The default direction is the core**, and it is the reason this resolver
    takes a declaration rather than a boolean: a caller that passes nothing
    coherent, or a subscriber lane added later that never learned to declare,
    receives the demoted core — correct, merely un-promoted. The failure mode of
    the opposite default is a client handed a patch it answers with a
    re-hydrate, which is the exact regression this negotiation exists to
    prevent, and it would be silent.
    """

    if frame.get("type") != FOLD_VARIANTS_FRAME_TYPE:
        return frame
    required = frozenset(
        str(token) for token in (frame.get("required_fold_tokens") or ())
    )
    if required <= normalize_fold_entities(declared):
        patch = frame.get("patch")
        if isinstance(patch, dict):
            return patch
    core = frame.get("core")
    return core if isinstance(core, dict) else frame
