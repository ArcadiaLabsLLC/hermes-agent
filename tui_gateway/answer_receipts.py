"""Bounded acknowledgements; no answers or reusable secret hashes are retained."""
import hashlib
import hmac
import json
import secrets
import time
from collections import OrderedDict


class AnswerReceipts:
    def __init__(self, *, limit=1024, ttl=900):
        self.limit, self.ttl = limit, ttl
        self._key = secrets.token_bytes(32)
        self._rows = OrderedDict()

    def fingerprint(self, frame):
        payload = json.dumps(frame.get("result"), sort_keys=True, separators=(",", ":"))
        return hmac.new(self._key, payload.encode(), hashlib.sha256).digest()

    def remember(self, request_id, sid, frame):
        self._rows[request_id] = (sid, self.fingerprint(frame), time.monotonic())
        while len(self._rows) > self.limit:
            self._rows.popitem(last=False)

    def accepted(self, frame, sid=None):
        now = time.monotonic()
        while self._rows and now - next(iter(self._rows.values()))[2] > self.ttl:
            self._rows.popitem(last=False)
        row = self._rows.get(frame.get("id"))
        if row is None or (sid and row[0] != sid):
            return False
        if not hmac.compare_digest(row[1], self.fingerprint(frame)):
            raise ValueError("This question was already answered differently.")
        return True

    def clear(self):
        self._rows.clear()
