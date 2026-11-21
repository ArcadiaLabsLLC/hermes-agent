"""``runtime.pets.thumb`` — a pet's idle-frame portrait, bytes inline, for a remote reader.

The argv verb ``harness pets thumb`` (``hermes_cli/harness_parts/pets_commands.py``)
answers a ``data:`` URI to the LOCAL launcher; a launcher reading a REMOTE install has
no argv lane to it, so its Agent Console showed initials for every remote companion
(launcher plan ``REMOTE_COMPANION_PORTRAIT_TRANSPORT_2026-10-31.md`` §D1, H1).

The bytes ride the reply rather than a ``runtime.media.get`` handle because the media
scope is DERIVED from chat logs and admits no registration
(``agent_runtime/media_handles.py``); a thumbnail is a few KB. The handle is
``media_handles.handle_for_bytes`` of exactly those bytes, so the launcher files them in
its content-addressed media cache under the same contract as the media lane.

``thumbnail_png`` stays the one producer and keeps the URL rule: the installed sheet
first, else ``url`` only when it is petdex-hosted. Result::

    {ok: true, slug, handle: "sha256:<hex>", media_type: "image/png", data_base64}
    {ok: false, slug, reason: "not_installed" | "unavailable"}

``not_installed``: no pet of that slug is installed here (and a ``url`` fallback, if one
was sent, gave nothing). ``unavailable``: the pet is installed and its sheet would not crop.
The tier is ``read``: a view of the install's pet library, no write beyond the crop cache.
"""

from __future__ import annotations

import base64
from typing import Any

from agent_runtime.call_authorization import TIER_CONSOLE, TIER_READ
from agent_runtime.param_readers import read_flag, read_text
from agent_runtime.serve_rpc.params import ParamRefused
from agent_runtime.serve_rpc.protocol import RpcContext, defer_or_inline, ok
from agent_runtime.serve_rpc.reasons import RpcRefusal
from agent_runtime.serve_rpc.registry import method

__layer__ = "lanes"

__all__ = [
    "PET_THUMB_MEDIA_TYPE",
    "REASON_NOT_INSTALLED",
    "REASON_UNAVAILABLE",
    "_runtime_pets_gallery",
    "_runtime_pets_install",
    "_runtime_pets_sprite",
    "_runtime_pets_thumb",
]

PET_THUMB_MEDIA_TYPE = "image/png"
REASON_NOT_INSTALLED = "not_installed"
REASON_UNAVAILABLE = "unavailable"


def _param_refused(key: str, sentence: str) -> ParamRefused:
    """The :data:`agent_runtime.param_readers.Refuse` this lane hands ``read_text``."""

    return ParamRefused(f"invalid params: {sentence}", RpcRefusal.PARAM_TYPE_INVALID)


@method("runtime.pets.thumb", tier=TIER_READ)
def _runtime_pets_thumb(rid: Any, params: dict, context=None) -> dict:
    """Params: ``slug`` (required); ``url`` (optional, a petdex-hosted spritesheet URL)."""

    from agent.pet import store
    from agent_runtime import media_handles

    params = params if isinstance(params, dict) else {}
    try:
        slug = read_text(params, "slug", refuse=_param_refused, required=True)
        url = read_text(params, "url", refuse=_param_refused) or ""
    except ParamRefused as refused:
        return refused.frame(rid)

    data = store.thumbnail_png(slug, source_url=url)
    if not data:
        installed = store.load_pet(slug) is not None
        return ok(rid, {"ok": False, "slug": slug,
                        "reason": REASON_UNAVAILABLE if installed else REASON_NOT_INSTALLED})
    return ok(rid, {
        "ok": True,
        "slug": slug,
        "handle": media_handles.handle_for_bytes(data),
        "media_type": PET_THUMB_MEDIA_TYPE,
        "data_base64": base64.b64encode(data).decode("ascii"),
    })


@method("runtime.pets.gallery", tier=TIER_READ)
def _runtime_pets_gallery(rid: Any, params: dict, context: RpcContext | None = None) -> dict:
    """``harness pets gallery``'s payload (``pets_commands.pets_gallery_result``, the verb's own body).

    RT-PETS-PAIRING-GATEWAY-ID-AND-UNPAIR-HAVE-THEIR-OWN-CALLS-ON-THE-RUNNING-HERMES. Params: ``query``
    (optional substring), ``limit`` (optional, remote rows, 0 = all), ``local_only`` (optional bool: skip the
    remote manifest). Result: ``{ok: true, localOnly, pets: [<row>], manifestError?}``, the verb's ``--json``
    object. A manifest the network will not give is ``manifestError`` beside the installed pets, as the verb
    answers. Read tier, on the worker lane: the manifest is a network fetch.
    """

    params = params if isinstance(params, dict) else {}
    try:
        query = read_text(params, "query", refuse=_param_refused, limit=200) or ""
        local_only = read_flag(params, "local_only", refuse=_param_refused)
        limit = params.get("limit")
        if limit is not None and (type(limit) is not int or limit < 0):
            raise _param_refused("limit", "limit must be a whole number, 0 or more")
    except ParamRefused as refused:
        return refused.frame(rid)

    return _pets_verb(rid, "runtime.pets.gallery", context, "gallery",
                      query=query, limit=limit or 0, local_only=local_only)


def _pets_verb(rid: Any, name: str, context: RpcContext | None, verb: str, **flags) -> dict:
    """Run ``harness pets <verb>`` in process on the worker lane and answer its payload.

    The verb's own ``{ok: false, error}`` refusal (not installed, a manifest miss) is its RESULT, as the argv
    lane answered it, so a caller reads one shape whichever door it came through.
    """

    def build() -> dict:
        from hermes_cli.harness_parts.pets_commands import pets_operation_result

        return ok(rid, pets_operation_result(verb, **flags))

    return defer_or_inline(rid, name, context, build)


@method("runtime.pets.sprite", tier=TIER_READ)
def _runtime_pets_sprite(rid: Any, params: dict, context: RpcContext | None = None) -> dict:
    """``harness pets sprite``'s payload: an installed pet's sheet and its frame geometry.

    Params: ``slug`` (required), ``include_sheet`` (optional bool, default true; false is ``--no-sheet``, the
    sheet's path in place of its bytes). Result: ``{ok: true, pet: {...}}`` or ``{ok: false, slug, error}``.
    """

    params = params if isinstance(params, dict) else {}
    try:
        slug = read_text(params, "slug", refuse=_param_refused, required=True, limit=200)
        include_sheet = read_flag(params, "include_sheet", refuse=_param_refused, default=True)
    except ParamRefused as refused:
        return refused.frame(rid)
    return _pets_verb(rid, "runtime.pets.sprite", context, "sprite", slug=slug, no_sheet=not include_sheet)


@method("runtime.pets.install", tier=TIER_CONSOLE)
def _runtime_pets_install(rid: Any, params: dict, context: RpcContext | None = None) -> dict:
    """``harness pets install``: fetch a Petdex pet by slug into this install's pet library.

    Params: ``slug`` (required), ``force`` (optional bool: reinstall over an installed copy). Result:
    ``{ok: true, pet: <gallery row>}`` or ``{ok: false, slug, error}``. Console tier and local console only:
    it writes this machine's pet library from the network, the desktop operator's move.
    """

    params = params if isinstance(params, dict) else {}
    try:
        slug = read_text(params, "slug", refuse=_param_refused, required=True, limit=200)
        force = read_flag(params, "force", refuse=_param_refused)
    except ParamRefused as refused:
        return refused.frame(rid)
    return _pets_verb(rid, "runtime.pets.install", context, "install", slug=slug, force=force)
