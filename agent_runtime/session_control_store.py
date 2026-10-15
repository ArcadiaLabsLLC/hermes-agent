"""Conversation settings, independent of wholesale native session-meta writes."""
from __future__ import annotations

import hashlib
import json
from threading import RLock

from . import paths
from .serde import write_json_atomic

__layer__ = "stores"
_LOCK = RLock()


class SessionControlStore:
    def _path(self, session_id: str):
        digest = hashlib.sha256(session_id.encode("utf-8")).hexdigest()
        return paths.store_root() / "session_controls" / f"{digest}.json"

    def read(self, session_id: str) -> dict:
        path = self._path(session_id)
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        if not isinstance(record, dict) or record.get("session_id") != session_id:
            raise ValueError("invalid session controls")
        return record

    def update(self, session_id: str, key: str, value: str | None) -> None:
        with _LOCK:
            record = self.read(session_id)
            if value is None:
                record.pop(key, None)
            else:
                record[key] = value
            record.update(schema_version=1, session_id=session_id)
            write_json_atomic(self._path(session_id), record)
