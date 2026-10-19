"""Who may talk to the runtime from a platform (p10-messaging §2.3) — fail closed.

``store/messaging/operators/<platform>/<user_id>.json``. A platform user with no row is not an operator
and the bridge drops their update (M3). The first operator is allowed from the desktop
(``runtime.messaging.operator.allow``), never from the platform: nothing on a platform can write here.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .. import paths
from ..serde import write_json_atomic
from .bindings import field_text
from .models import MessagingRefused, Platform, Reason, platform_of

__layer__ = "stores"
__all__ = ["Operator", "OperatorStore"]

logger = logging.getLogger(__name__)


def _user_id(value: Any) -> str:
    text = field_text(value, "user_id")
    if paths.safe_path_token(text) != text:
        raise MessagingRefused(Reason.INVALID, "user_id")
    return text


@dataclass(frozen=True, slots=True)
class Operator:
    platform: Platform
    user_id: str
    display: str
    allowed_by: str
    allowed_at: str

    def wire(self) -> dict[str, Any]:
        record = asdict(self)
        record["platform"] = self.platform.value
        return record

    @classmethod
    def from_wire(cls, raw: Mapping[str, Any]) -> Operator:
        return cls(platform=platform_of(raw["platform"]), user_id=_user_id(raw["user_id"]),
                   display=str(raw.get("display") or ""), allowed_by=str(raw.get("allowed_by") or ""),
                   allowed_at=str(raw.get("allowed_at") or ""))


class OperatorStore:
    def _dir(self, platform: Platform) -> Path:
        return paths.messaging_operators_dir() / platform.value

    def _path(self, platform: Platform, user_id: Any) -> Path:
        return self._dir(platform) / f"{_user_id(user_id)}.json"

    def allow(self, operator: Operator) -> Operator:
        path = self._path(operator.platform, operator.user_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        write_json_atomic(path, operator.wire())
        return operator

    def revoke(self, platform: Platform, user_id: Any) -> bool:
        try:
            self._path(platform, user_id).unlink()
        except FileNotFoundError:
            return False
        return True

    def get(self, platform: Platform, user_id: Any) -> Operator | None:
        try:
            path = self._path(platform, user_id)
        except MessagingRefused:
            return None  # a user id that cannot be a file name was never allowed
        return self._read(path)

    def is_allowed(self, platform: Platform, user_id: Any) -> bool:
        return self.get(platform, user_id) is not None

    def list(self, platform: Platform | None = None) -> list[Operator]:
        platforms = [platform] if platform is not None else list(Platform)
        found: list[Operator] = []
        for each in platforms:
            base = self._dir(each)
            if base.is_dir():
                found += [o for o in map(self._read, sorted(base.glob("*.json"))) if o is not None]
        return sorted(found, key=lambda o: (o.platform.value, o.user_id))

    @staticmethod
    def _read(path: Path) -> Operator | None:
        try:
            return Operator.from_wire(json.loads(path.read_text(encoding="utf-8")))
        except FileNotFoundError:
            return None
        except (OSError, KeyError, TypeError, ValueError, MessagingRefused):
            logger.warning("messaging operator %s is unreadable; that user is refused until re-allowed", path.name)
            return None
