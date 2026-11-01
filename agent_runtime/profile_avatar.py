"""Profile artwork assets: bounded reads and one compare-and-replace writer.

The existing assets/avatar.png is the authority. No character/persona record or
profile configuration is written. The content handle is the optimistic revision.
"""

from __future__ import annotations

import base64
import io
import re
from enum import StrEnum
from pathlib import Path

from agent_runtime.locks import HarnessLockUnavailable, _file_lock
from agent_runtime.media_handles import handle_for_bytes
from agent_runtime.profile_context import _profile_home_for_token

__layer__ = "stores"

AVATAR_EXTENSIONS = (".png", ".jpg", ".jpeg", ".webp")
AVATAR_MAX_BYTES = 8 * 1024 * 1024
# Base64 plus the RPC envelope stays below the transport's 1 MiB request cap.
AVATAR_UPLOAD_MAX_BYTES = 512 * 1024
AVATAR_MAX_EDGE = 1024


class AvatarRefusal(StrEnum):
    INVALID = "invalid_avatar"
    PROFILE = "invalid_profile"
    STALE = "stale_avatar"
    UNAVAILABLE = "unavailable"


class ProfileAvatarRefused(ValueError):
    def __init__(self, reason: AvatarRefusal):
        self.reason = reason
        super().__init__(reason.value)


def read_profile_avatar(home: Path, *, max_bytes: int = AVATAR_MAX_BYTES) -> tuple[bytes, str] | str:
    """Read the existing precedence order; unsafe/unreadable art never escapes."""
    try:
        root = home.resolve()
        for extension in AVATAR_EXTENSIONS:
            candidate = home / "assets" / f"avatar{extension}"
            if not candidate.is_file():
                continue
            real = candidate.resolve()
            if not real.is_relative_to(root):
                return "unavailable"
            size = real.stat().st_size
            if size <= 0 or size > max_bytes:
                return "unavailable"
            data = real.read_bytes()
            return (data, extension) if 0 < len(data) <= max_bytes else "unavailable"
        return "not_found"
    except OSError:
        return "unavailable"


def _portrait_png(encoded: object) -> bytes:
    from PIL import Image

    if not isinstance(encoded, str) or len(encoded) > (AVATAR_UPLOAD_MAX_BYTES + 2) // 3 * 4:
        raise ProfileAvatarRefused(AvatarRefusal.INVALID)
    try:
        data = base64.b64decode(encoded, validate=True)
        if not 0 < len(data) <= AVATAR_UPLOAD_MAX_BYTES:
            raise ProfileAvatarRefused(AvatarRefusal.INVALID)
        with Image.open(io.BytesIO(data)) as image:
            if (image.format != "PNG" or getattr(image, "n_frames", 1) != 1
                    or min(image.size) < 1 or max(image.size) > AVATAR_MAX_EDGE):
                raise ProfileAvatarRefused(AvatarRefusal.INVALID)
            image.verify()
        # verify checks structure/CRC; load proves that pixel decoding succeeds.
        with Image.open(io.BytesIO(data)) as image:
            image.load()
        return data
    except (ValueError, OSError, Image.DecompressionBombError) as exc:
        raise ProfileAvatarRefused(AvatarRefusal.INVALID) from exc


def replace_profile_avatar(params: dict) -> dict:
    """Commit a reviewed PNG to the named existing profile, or leave it intact."""
    profile, expected = params.get("profile"), params.get("expected_handle")
    if not isinstance(profile, str) or not profile:
        raise ProfileAvatarRefused(AvatarRefusal.PROFILE)
    if ("expected_handle" not in params or
            (expected is not None and (not isinstance(expected, str) or
             re.fullmatch(r"sha256:[0-9a-f]{64}", expected) is None))):
        raise ProfileAvatarRefused(AvatarRefusal.INVALID)
    home = _profile_home_for_token(profile)
    if home is None or not Path(home).is_dir():
        raise ProfileAvatarRefused(AvatarRefusal.PROFILE)
    data = _portrait_png(params.get("data_base64"))
    handle = handle_for_bytes(data)
    root = Path(home).resolve()
    assets = root / "assets"
    try:
        if not assets.resolve().is_relative_to(root):
            raise ProfileAvatarRefused(AvatarRefusal.UNAVAILABLE)
        assets.mkdir(exist_ok=True)
        lock = assets / ".avatar.lock"
        target = assets / "avatar.png"
        if any(path.is_symlink() for path in (assets, lock, target)):
            raise ProfileAvatarRefused(AvatarRefusal.UNAVAILABLE)
        with _file_lock(lock):
            current = read_profile_avatar(root)
            if isinstance(current, str) and current != "not_found":
                raise ProfileAvatarRefused(AvatarRefusal.UNAVAILABLE)
            current_handle = handle_for_bytes(current[0]) if isinstance(current, tuple) else None
            if current_handle != handle:
                if current_handle != expected:
                    raise ProfileAvatarRefused(AvatarRefusal.STALE)
                from utils import atomic_write_bytes

                atomic_write_bytes(target, data, fsync_dir=True)
    except (OSError, HarnessLockUnavailable) as exc:
        raise ProfileAvatarRefused(AvatarRefusal.UNAVAILABLE) from exc
    return {"ok": True, "profile": profile, "handle": handle,
            "media_type": "image/png", "data_base64": base64.b64encode(data).decode("ascii")}
