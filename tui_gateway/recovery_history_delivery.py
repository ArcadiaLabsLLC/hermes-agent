"""Disposable, seekable delivery of an already projected native history."""
from __future__ import annotations

from collections import OrderedDict
from contextlib import ExitStack
import json
import struct
import tempfile
import threading
import time

_LOCATION = struct.Struct("!QQ")


class HistoryDelivery:
    """Delete-on-close files bound retained RAM independently of transcript size."""

    def __init__(self, messages):
        self._files = ExitStack()
        self.count = 0
        try:
            self._data = self._files.enter_context(tempfile.TemporaryFile())
            self._index = self._files.enter_context(tempfile.TemporaryFile())
            for message in messages:
                # ASCII keeps wire-character offsets directly seekable, including Unicode escapes.
                encoded = json.dumps(message, ensure_ascii=True, separators=(",", ":")).encode("ascii")
                self._index.write(_LOCATION.pack(self._data.tell(), len(encoded)))
                self._data.write(encoded)
                self.count += 1
        except BaseException:
            self.close()
            raise

    def chunk(self, index, offset, limit):
        if not 0 <= index < self.count:
            raise ValueError("Invalid history position")
        self._index.seek(index * _LOCATION.size)
        start, length = _LOCATION.unpack(self._index.read(_LOCATION.size))
        if not 0 <= offset < length:
            raise ValueError("Invalid history offset")
        self._data.seek(start + offset)
        text = self._data.read(min(limit, length - offset)).decode("ascii")
        return text, offset + len(text) == length

    def close(self):
        self._files.close()


class HistoryDeliveries:
    """A bounded delivery cache, never session/history authority. Misses rebuild."""

    def __init__(self, *, capacity=16, idle_seconds=60, clock=time.monotonic):
        self._capacity, self._idle_seconds, self._clock = capacity, idle_seconds, clock
        self._entries = OrderedDict()
        self._lock = threading.RLock()

    def read(self, key, load, render):
        with self._lock:
            self._prune()
            entry = self._entries.pop(key, None)
            delivery = entry[1] if entry else HistoryDelivery(load())
            try:
                result = render(delivery)
                if result["more"]:
                    self._entries[key] = (self._clock(), delivery)
                    self._prune()
                else:
                    delivery.close()
                return result
            except BaseException:
                delivery.close()
                raise

    def discard(self, owner):
        with self._lock:
            for key in list(self._entries):
                if key[0] is owner:
                    self._entries.pop(key)[1].close()

    def prune(self):
        if not self._lock.acquire(blocking=False):
            return
        try:
            self._prune()
        finally:
            self._lock.release()

    def _prune(self):
        now = self._clock()
        while self._entries:
            key, (touched, delivery) = next(iter(self._entries.items()))
            if len(self._entries) <= self._capacity and now - touched < self._idle_seconds:
                return
            self._entries.pop(key)
            delivery.close()
