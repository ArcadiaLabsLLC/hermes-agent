"""Weak object generations, never a second registry of child execution state."""
import hashlib
import hmac
import json
import secrets
import threading
import weakref

from .model import Refusal, SubagentError

__layer__ = "stores"


class References:
    def __init__(self):
        self._key = secrets.token_bytes(32)
        self._agents = weakref.WeakKeyDictionary()
        self._lock = threading.Lock()

    def generation(self, owner: tuple) -> str:
        return self._sign(owner)

    def child(self, owner: tuple, record: dict) -> str:
        agent = record["agent"]
        with self._lock:
            if agent not in self._agents:
                self._agents[agent] = secrets.token_hex(24)
            token = self._agents[agent]
        return self._sign((owner, token, record["subagent_id"], record.get("started_at")))

    def require_generation(self, owner: tuple, expected: str | None) -> str:
        actual = self.generation(owner)
        if expected is not None and not hmac.compare_digest(expected, actual):
            raise SubagentError(Refusal.STALE)
        return actual

    def _sign(self, values) -> str:
        payload = json.dumps(values, ensure_ascii=True, separators=(",", ":")).encode()
        return hmac.new(self._key, payload, hashlib.sha256).hexdigest()


references = References()
