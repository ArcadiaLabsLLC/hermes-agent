"""Conversation ownership and dispatch evidence; no transport or agent engine."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

__layer__ = "models"


class Refusal(StrEnum):
    INVALID_REQUEST = "invalid_request"
    UNAVAILABLE = "conversation_unavailable"
    WRONG_OWNER = "conversation_owner_changed"
    BUSY = "conversation_busy"
    UNKNOWN = "turn_outcome_unknown"
    CONFLICT = "idempotency_conflict"
    WORKER_LOST = "conversation_worker_lost"
    RUNTIME_STOPPING = "runtime_stopping"
    NATIVE_REFUSAL = "native_refusal"
    RESPONSE_TOO_LARGE = "response_too_large"


class ConversationError(ValueError):
    def __init__(self, reason: Refusal, *, native_code: int | None = None):
        self.reason, self.native_code = reason, native_code
        super().__init__(reason.value)


class TurnState(StrEnum):
    DISPATCHING = "dispatching"
    RUNNING = "running"
    COMPLETED = "completed"
    STOPPED = "stopped"
    FAILED = "failed"
    UNKNOWN = "unknown"


UNSETTLED = (TurnState.DISPATCHING, TurnState.RUNNING, TurnState.UNKNOWN)


def identifier(value: Any) -> str:
    if not isinstance(value, str) or not value or len(value) > 512 or any(ord(c) < 32 for c in value):
        raise ConversationError(Refusal.INVALID_REQUEST)
    return value


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=True,
                                    separators=(",", ":")).encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class ConversationScope:
    actor: str
    client: str
    profile: str

    @property
    def key(self) -> str:
        return digest([self.actor, self.client, self.profile])


@dataclass(frozen=True, slots=True)
class ConversationRoute:
    id: str
    owner: str
    profile: str
    cwd: str
    home: str
    native_id: str
    worker_pid: int = 0
    worker_created: float = 0


@dataclass(frozen=True, slots=True)
class TurnReceipt:
    conversation_id: str
    turn_id: str
    digest: str
    state: TurnState
