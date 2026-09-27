"""Observation-only recovery of a native execution and its replay position."""
from typing import Literal

from pydantic import Field

from .base import Result
from .common import SessionParams
from .registry import method
from .sessions import LiveSessionSnapshot


class RecoveryParams(SessionParams):
    execution_id: str | None = None


class ExecutionEvidence(Result):
    id: str
    session_key: str
    status: str
    cancel_requested: bool
    user_row_id: int | None = None


class HistoryPosition(Result):
    session_key: str
    through_row: int
    version: int


class SegmentEnd(Result):
    assistant: int
    reasoning: int


class InflightPosition(Result):
    execution_id: str
    user: int
    assistant: int
    reasoning: int
    revision: int
    segment_ends: list[SegmentEnd]


class RecoverySnapshot(LiveSessionSnapshot):
    execution: ExecutionEvidence | None = None
    epoch: str
    latest_seq: int
    history: HistoryPosition
    inflight_position: InflightPosition | None = None


class RecoveryHistoryParams(SessionParams):
    position: HistoryPosition
    message_index: int = Field(default=0, ge=0)
    offset: int = Field(default=0, ge=0)


class RecoveryHistoryChunk(Result):
    index: int
    offset: int
    data: str
    complete: bool


class RecoveryHistoryPage(Result):
    chunks: list[RecoveryHistoryChunk]
    message_index: int
    offset: int
    more: bool
    reset: bool = False


class RecoveryInflightParams(SessionParams):
    execution_id: str
    field: Literal["user", "assistant", "reasoning"]
    revision: int = Field(default=0, ge=0)
    through: int = Field(ge=0)
    offset: int = Field(default=0, ge=0)


class RecoveryInflightPage(Result):
    text: str = ""
    offset: int = 0
    more: bool = False
    reset: bool = False


class RetirementResult(Result):
    status: Literal["retired", "protected"]


method("session.recover", params=RecoveryParams, result=RecoverySnapshot,
       doc="Observe native state and its replay checkpoint without starting a turn.")
method("session.recovery.history", params=RecoveryHistoryParams, result=RecoveryHistoryPage,
       doc="Read bounded transcript chunks through a recovery checkpoint's durable watermark.")
method("session.recovery.inflight", params=RecoveryInflightParams, result=RecoveryInflightPage,
       doc="Read an append-only prefix of the exact live execution; reset if it has settled or changed.")
method("session.retire", params=RecoveryParams, result=RetirementResult,
       doc="Release only a settled session after native eligibility checks; preserve durable history.")
