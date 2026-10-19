"""The platform bot tokens (p10-messaging §2.4) — one file in the serve HEAD profile, behind the host-store seam.

``<get_hermes_head_home()>/messaging/credentials.json`` = ``{"telegram": {"bot_token": …, "set_at": …}}``.
A bot token is a RUNTIME identity (one poller per token), so it lives in the head home, never in a
persona's profile. Unbound (full Hermes) the file is plaintext under the profile, owner-only where the OS
has modes; bound (``auth.os_secure_store``, a phone) every read and write goes through
``host_store.secret_files`` into the slot ``hermes/v1/<profile>/messaging/credentials.json`` and a plaintext
file left at the path is unlinked by the write itself.

ONE reader, :func:`bot_token`. The token never leaves through anything else: :func:`credential_state`
answers ``present`` / ``absent`` for every reply and receipt, and nothing here logs a value. The env
override ``HERMES_MESSAGING_<PLATFORM>_TOKEN`` (a headless box provisioned by a secret manager) is read
through the head profile's secret scope, never ``os.environ``, so a multiplexed home cannot borrow another
profile's token; when present it wins over the file.
"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..host_store import secret_files
from ..profile_home import get_hermes_head_home
from ..serde import write_json_atomic
from .models import MessagingRefused, Platform, Reason

__layer__ = "stores"
__all__ = ["bot_token", "clear_token", "credential_state", "credentials_path", "env_key", "set_token",
           "valid_token"]

logger = logging.getLogger(__name__)

PRESENT, ABSENT = "present", "absent"

#: The shape a platform's token must have before it is stored. Telegram: ``<bot id>:<secret>``.
_TOKEN_SHAPES: dict[Platform, re.Pattern[str]] = {
    Platform.TELEGRAM: re.compile(r"\d{3,20}:[A-Za-z0-9_-]{20,100}"),
}


def credentials_path(home: Path | None = None) -> Path:
    return Path(home or get_hermes_head_home()) / "messaging" / "credentials.json"


def env_key(platform: Platform) -> str:
    return f"HERMES_MESSAGING_{platform.value.upper()}_TOKEN"


def valid_token(platform: Platform, token: Any) -> str:
    """The token, stripped, when it has the platform's shape; else a refusal that does not echo it."""
    text = str(token or "").strip() if isinstance(token, str) else ""
    if not _TOKEN_SHAPES[platform].fullmatch(text):
        raise MessagingRefused(Reason.TOKEN_INVALID, "token")
    return text


def _read(path: Path) -> dict[str, Any]:
    view = secret_files.view(path)
    try:
        if not view.exists():
            return {}
        data = json.loads(view.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        logger.warning("messaging credentials file is unreadable; every platform reads as absent")
        return {}
    return data if isinstance(data, dict) else {}


def _write(path: Path, data: dict[str, Any]) -> None:
    if secret_files.bound():
        secret_files.write_json(path, data)
        return
    write_json_atomic(path, data)
    try:
        os.chmod(path, 0o600)
    except OSError:  # a filesystem without modes: the profile directory's own ACL is the guard
        pass


def _env_token(platform: Platform, home: Path) -> str | None:
    try:
        from agent.secret_scope import build_profile_secret_scope
        from hermes_cli.env_loader import hydrate_profile_secret_sources

        hydrate_profile_secret_sources(home)
        value = build_profile_secret_scope(home).get(env_key(platform))
    except Exception:
        logger.warning("the head profile's secret scope could not be read; the env override is ignored")
        return None
    return str(value).strip() or None if value else None


def bot_token(platform: Platform, *, home: Path | None = None) -> str | None:
    """The ONE reader of a platform's token: the env override, else the stored file, else None."""
    head = Path(home or get_hermes_head_home())
    override = _env_token(platform, head)
    if override:
        return override
    entry = _read(credentials_path(head)).get(platform.value)
    token = entry.get("bot_token") if isinstance(entry, dict) else None
    return str(token).strip() or None if token else None


def credential_state(platform: Platform, *, home: Path | None = None) -> str:
    return PRESENT if bot_token(platform, home=home) else ABSENT


def set_token(platform: Platform, token: Any, *, home: Path | None = None) -> None:
    value = valid_token(platform, token)
    path = credentials_path(home)
    data = _read(path)
    data[platform.value] = {"bot_token": value, "set_at": datetime.now(UTC).isoformat(timespec="seconds")}
    _write(path, data)


def clear_token(platform: Platform, *, home: Path | None = None) -> bool:
    """Forget the stored token; True when one was stored. The env override is the secret manager's, not ours."""
    path = credentials_path(home)
    data = _read(path)
    if data.pop(platform.value, None) is None:
        return False
    if data:
        _write(path, data)
    elif secret_files.bound():
        secret_files.delete(path)
    else:
        path.unlink(missing_ok=True)
    return True
