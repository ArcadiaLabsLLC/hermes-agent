"""The last platform users the bridge refused as strangers (RT-MESSAGING-REFUSED-RECENT).

The bridge drops an update from a user with no operator row (``bridge._refuse``, reason
``unknown_operator``) with a receipt and no reply, so the operator who wants to allow a new device had to
find the sender's Telegram user id somewhere else. This store keeps the newest :data:`RECENT_MAX` such
senders per platform — ``user_id``, ``display``, ``chat_id``, ``at`` — one row per user, newest first, in
``store/messaging/refused/<platform>.json``; ``runtime.messaging.refused.recent`` reads it and leaves out a
user allowed since. Only ``unknown_operator`` is recorded: every other refusal is of a user who is already
an operator, for whom "Allow" means nothing. Never message text.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .. import paths
from ..serde import write_json_atomic
from .models import Platform

__layer__ = "stores"
__all__ = ["RECENT_MAX", "RefusedSenders"]

logger = logging.getLogger(__name__)

#: Senders kept per platform.
RECENT_MAX = 10


class RefusedSenders:
    def _path(self, platform: Platform) -> Path:
        return paths.messaging_refused_dir() / f"{platform.value}.json"

    def record(self, platform: Platform, *, user_id: Any, display: Any, chat_id: Any) -> None:
        """Put this sender first; never raises (the drop already happened, this is the console's hint)."""
        try:
            user = str(user_id or "").strip()
            if not user:
                return
            row = {"user_id": user, "display": str(display or ""), "chat_id": str(chat_id or ""),
                   "at": datetime.now(UTC).isoformat(timespec="seconds")}
            rows = [row] + [old for old in self._read(platform) if old.get("user_id") != user]
            path = self._path(platform)
            path.parent.mkdir(parents=True, exist_ok=True)
            write_json_atomic(path, {"senders": rows[:RECENT_MAX]})
        except Exception:
            logger.warning("messaging: could not record a refused %s sender", platform.value, exc_info=True)

    def recent(self, platform: Platform) -> list[dict[str, str]]:
        """Newest first, at most :data:`RECENT_MAX`."""
        return self._read(platform)[:RECENT_MAX]

    def _read(self, platform: Platform) -> list[dict[str, str]]:
        try:
            raw = json.loads(self._path(platform).read_text(encoding="utf-8"))
        except FileNotFoundError:
            return []
        except (OSError, ValueError):
            logger.warning("messaging: the refused-sender list for %s is unreadable; starting it over", platform.value)
            return []
        senders = raw.get("senders") if isinstance(raw, dict) else None
        return [{key: str(row.get(key) or "") for key in ("user_id", "display", "chat_id", "at")}
                for row in senders or [] if isinstance(row, dict) and row.get("user_id")]
