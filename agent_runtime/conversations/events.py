"""Bounded native-event replay. Durable conversation history stays in SessionDB."""
from __future__ import annotations

import json
import threading
from collections import deque

from .model import ConversationError, Refusal

__layer__ = "stores"


class ConversationEvents:
    def __init__(self, *, maximum_bytes: int = 8 * 1024 * 1024):
        self._maximum = maximum_bytes
        self._bytes = 0
        self._next = 1
        self._events: deque[tuple[dict, int]] = deque()
        self._lock = threading.Lock()

    def append(self, turn_id: str | None, frame: dict) -> None:
        with self._lock:
            event = {"seq": self._next, "turn_id": turn_id, "frame": frame}
            size = len(json.dumps(event, ensure_ascii=True))
            self._next += 1
            self._events.append((event, size))
            self._bytes += size
            while self._events and self._bytes > self._maximum:
                self._bytes -= self._events.popleft()[1]

    def since(self, cursor: int, *, maximum_bytes: int = 700 * 1024) -> dict:
        if type(cursor) is not int or cursor < 0:
            raise ConversationError(Refusal.INVALID_REQUEST)
        with self._lock:
            first = self._events[0][0]["seq"] if self._events else self._next
            result, size = [], 0
            for event, length in self._events:
                if event["seq"] <= cursor:
                    continue
                if result and size + length > maximum_bytes:
                    break
                if length > maximum_bytes:
                    raise ConversationError(Refusal.INVALID_REQUEST)
                result.append(event)
                size += length
            last = result[-1]["seq"] if result else cursor
            return {"events": result, "cursor": last, "truncated": cursor < first - 1,
                    "more": last < self._next - 1}
