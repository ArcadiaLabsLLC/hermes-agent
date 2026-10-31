"""``runtime.profiles.avatar`` — a profile's avatar image, bytes inline, for a remote reader.

The local launcher reads ``<root>/profiles/<profile>/assets/avatar.*`` straight off the disk
(``EterniaLauncher/lib/core/services/hermes/hermes_profile_avatar.dart``); a launcher reading a
REMOTE install has no disk to read, so its Agent Console fell through to the character assignment
and then to initials (launcher plan ``REMOTE_PROFILE_AVATAR_TRANSPORT_2026-10-31.md`` §D1, H1).

The home is resolved through ``profile_context._profile_home_for_token`` — the one place a profile
token becomes a directory — so an unsafe token is ``invalid_profile`` and never a path. The first of
``assets/avatar.{png,jpg,jpeg,webp}`` that exists is read inside the launcher's own size window
(empty or more than 8 MiB is ``unavailable``), and a file whose real path leaves the home is
``unavailable`` too. The bytes ride the reply for the reason ``runtime.pets.thumb``'s do: the media
scope is DERIVED from chat logs and admits no registration (``agent_runtime/media_handles.py``). The
handle is ``media_handles.handle_for_bytes`` of exactly those bytes and the media type is read off
the extension (``media_handles.MEDIA_TYPES``), so the launcher never guesses a decoder. Result::

    {ok: true, profile, handle: "sha256:<hex>", media_type: "image/png" | "image/jpeg" | "image/webp", data_base64}
    {ok: false, profile, reason: "invalid_profile" | "not_found" | "unavailable"}

The tier is ``read``: a view of a profile's assets, no write.
"""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

from agent_runtime.call_authorization import TIER_READ
from agent_runtime.param_readers import read_text
from agent_runtime.serve_rpc.params import ParamRefused
from agent_runtime.serve_rpc.protocol import ok
from agent_runtime.serve_rpc.reasons import RpcRefusal
from agent_runtime.serve_rpc.registry import method

__layer__ = "lanes"

__all__ = [
    "AVATAR_EXTENSIONS",
    "AVATAR_MAX_BYTES",
    "REASON_INVALID_PROFILE",
    "REASON_NOT_FOUND",
    "REASON_UNAVAILABLE",
    "_runtime_profiles_avatar",
]

#: The avatar file names tried, in order — the launcher's ``readHermesProfileAvatar`` list.
AVATAR_EXTENSIONS: tuple[str, ...] = (".png", ".jpg", ".jpeg", ".webp")

#: The launcher's size ceiling for an avatar (``hermes_profile_avatar.dart``: 0 < size <= 8 MiB).
AVATAR_MAX_BYTES = 8 * 1024 * 1024

REASON_INVALID_PROFILE = "invalid_profile"
REASON_NOT_FOUND = "not_found"
REASON_UNAVAILABLE = "unavailable"


def _param_refused(key: str, sentence: str) -> ParamRefused:
    """The :data:`agent_runtime.param_readers.Refuse` this lane hands ``read_text``."""

    return ParamRefused(f"invalid params: {sentence}", RpcRefusal.PARAM_TYPE_INVALID)


def _read_avatar(home: Path) -> tuple[bytes, str] | str:
    """``(bytes, extension)`` of the profile's avatar, or the refusal reason."""

    try:
        root = home.resolve()
    except OSError:
        return REASON_NOT_FOUND
    for extension in AVATAR_EXTENSIONS:
        candidate = home / "assets" / f"avatar{extension}"
        if not candidate.is_file():
            continue
        try:
            real = candidate.resolve()
            if not real.is_relative_to(root):
                return REASON_UNAVAILABLE
            size = real.stat().st_size
            if size <= 0 or size > AVATAR_MAX_BYTES:
                return REASON_UNAVAILABLE
            return real.read_bytes(), extension
        except OSError:
            return REASON_UNAVAILABLE
    return REASON_NOT_FOUND


@method("runtime.profiles.avatar", tier=TIER_READ)
def _runtime_profiles_avatar(rid: Any, params: dict, context=None) -> dict:
    """Params: ``profile`` (required) — the profile token, e.g. ``base`` or ``alice``."""

    from agent_runtime import media_handles
    from agent_runtime.profile_context import _profile_home_for_token

    params = params if isinstance(params, dict) else {}
    try:
        profile = read_text(params, "profile", refuse=_param_refused, required=True)
    except ParamRefused as refused:
        return refused.frame(rid)

    home = _profile_home_for_token(profile)
    if home is None:
        return ok(rid, {"ok": False, "profile": profile, "reason": REASON_INVALID_PROFILE})
    found = _read_avatar(Path(home))
    if isinstance(found, str):
        return ok(rid, {"ok": False, "profile": profile, "reason": found})
    data, extension = found
    return ok(rid, {
        "ok": True,
        "profile": profile,
        "handle": media_handles.handle_for_bytes(data),
        "media_type": media_handles.MEDIA_TYPES[extension],
        "data_base64": base64.b64encode(data).decode("ascii"),
    })
