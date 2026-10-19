"""Platform chat → persona instance bindings (p10-messaging §2.3) — a POINTER, never a session.

``store/messaging/bindings/<platform>/<digest(chat_id, thread_id)>.json``, one file per chat (or forum
thread). A binding names the persona INSTANCE; the session a turn runs on is that instance's current chat
root, resolved at send time (``PersonaTurnExecutor``'s root-or-mint), so a ``/new`` in the launcher, a
retire or a different thread moves the platform chat with it. The wire is exactly :data:`FIELDS`: a
session or root id on disk would be the second session store the runtime.chat lane forbids, and
:meth:`Binding.from_wire` drops any key outside the set. Written only by ``runtime.messaging.binding.*``
(``messaging/rpc.py``). An unreadable file is skipped and logged, never trusted.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Mapping
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any

from .. import paths
from ..serde import write_json_atomic
from .models import MessagingRefused, Platform, Reason, platform_of

__layer__ = "stores"
__all__ = ["FIELDS", "Binding", "BindingStore", "chat_key", "field_text"]

logger = logging.getLogger(__name__)


def field_text(value: Any, name: str, *, required: bool = True) -> str | None:
    text = str(value).strip() if value is not None else ""
    if not text:
        if required:
            raise MessagingRefused(Reason.INVALID, name)
        return None
    if len(text) > 200 or any(ch in text for ch in "\r\n\0"):
        raise MessagingRefused(Reason.INVALID, name)
    return text


@dataclass(frozen=True, slots=True)
class Binding:
    platform: Platform
    chat_id: str
    thread_id: str | None
    persona_instance_id: str
    bound_by: str
    bound_at: str

    def wire(self) -> dict[str, Any]:
        record = asdict(self)
        record["platform"] = self.platform.value
        return record

    @classmethod
    def from_wire(cls, raw: Mapping[str, Any]) -> Binding:
        return cls(platform=platform_of(raw["platform"]), chat_id=field_text(raw["chat_id"], "chat_id"),
                   thread_id=field_text(raw.get("thread_id"), "thread_id", required=False),
                   persona_instance_id=field_text(raw["persona_instance_id"], "persona_instance_id"),
                   bound_by=str(raw.get("bound_by") or ""), bound_at=str(raw.get("bound_at") or ""))


FIELDS = frozenset(field.name for field in fields(Binding))


def chat_key(chat_id: Any, thread_id: Any = None) -> tuple[str, str | None]:
    """The normalized ``(chat_id, thread_id)`` a binding is addressed by."""
    return field_text(chat_id, "chat_id"), field_text(thread_id, "thread_id", required=False)


def _digest(chat_id: str, thread_id: str | None) -> str:
    return hashlib.sha256(f"{chat_id}\0{thread_id or ''}".encode()).hexdigest()[:32]


class BindingStore:
    """The bindings on disk. The files ARE the state; nothing is cached between calls."""

    def _dir(self, platform: Platform) -> Path:
        return paths.messaging_bindings_dir() / platform.value

    def _path(self, platform: Platform, chat_id: str, thread_id: str | None) -> Path:
        return self._dir(platform) / f"{_digest(chat_id, thread_id)}.json"

    def set(self, binding: Binding) -> Binding:
        path = self._path(binding.platform, binding.chat_id, binding.thread_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        write_json_atomic(path, binding.wire())
        return binding

    def clear(self, platform: Platform, chat_id: Any, thread_id: Any = None) -> bool:
        try:
            self._path(platform, *chat_key(chat_id, thread_id)).unlink()
        except FileNotFoundError:
            return False
        return True

    def get(self, platform: Platform, chat_id: Any, thread_id: Any = None) -> Binding | None:
        key = chat_key(chat_id, thread_id)
        binding = self._read(self._path(platform, *key))
        if binding is not None and (binding.chat_id, binding.thread_id) != key:
            return None  # a digest collision is a miss, never another chat's binding
        return binding

    def list(self, platform: Platform | None = None) -> list[Binding]:
        platforms = [platform] if platform is not None else list(Platform)
        found: list[Binding] = []
        for each in platforms:
            base = self._dir(each)
            if base.is_dir():
                found += [b for b in map(self._read, sorted(base.glob("*.json"))) if b is not None]
        return sorted(found, key=lambda b: (b.platform.value, b.chat_id, b.thread_id or ""))

    @staticmethod
    def _read(path: Path) -> Binding | None:
        try:
            return Binding.from_wire(json.loads(path.read_text(encoding="utf-8")))
        except FileNotFoundError:
            return None
        except (OSError, KeyError, TypeError, ValueError, MessagingRefused):
            logger.warning("messaging binding %s is unreadable; it routes nothing until re-set", path.name)
            return None
