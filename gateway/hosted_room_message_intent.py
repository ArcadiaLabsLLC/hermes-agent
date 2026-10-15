"""Explicit, per-message response policy. The room log remains authoritative."""
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Protocol, TypeVar

from gateway.hosted_rooms_common import identifier


class ResponseMode(str, Enum):
    DISCUSS = "discuss"
    COMPARE = "compare"
    REPLY = "reply"


class MemberIdentity(Protocol):
    member_id: str


Member = TypeVar("Member", bound=MemberIdentity)


@dataclass(frozen=True)
class MessageResponse:
    mode: ResponseMode
    members: tuple[str, ...] = ()

    @classmethod
    def parse(cls, value, *, error=ValueError) -> "MessageResponse":
        if not isinstance(value, Mapping) or set(value) != {"mode", "members"}:
            raise error("invalid response fields")
        try:
            mode = ResponseMode(value["mode"])
        except (ValueError, TypeError) as exc:
            raise error("invalid response mode") from exc
        raw = value["members"]
        if not isinstance(raw, list) or len(raw) > 128:
            raise error("invalid response members")
        members = tuple(identifier(item, label="response member", error=error) for item in raw)
        if len(set(members)) != len(members) or (mode == ResponseMode.REPLY and not members):
            raise error("invalid response members")
        return cls(mode, members)

    def validate_audience(self, members: Iterable[str], *, error=ValueError) -> None:
        if not set(self.members) <= set(members):
            raise error("response member is not in this conversation")

    def select(self, active: Sequence[Member]) -> tuple[Member, ...]:
        if not self.members:
            return tuple(active)
        available = {member.member_id: member for member in active}
        return tuple(available[key] for key in self.members if key in available)

    def to_dict(self) -> dict:
        return {"mode": self.mode.value, "members": list(self.members)}

    @property
    def single_round(self) -> bool:
        return self.mode != ResponseMode.DISCUSS


def response_from_payload(payload: Mapping, *, error=ValueError) -> MessageResponse | None:
    return MessageResponse.parse(payload["response"], error=error) if "response" in payload else None


def response_guidance(response: MessageResponse | None) -> str:
    if response is None or response.mode == ResponseMode.DISCUSS:
        return ""
    return {
        ResponseMode.COMPARE: "- Give your independent answer to the user's message. Peer answers to this message are withheld; do not request another turn.",
        ResponseMode.REPLY: "- The user addressed you for this message. Reply to them in the shared conversation; do not summon other members.",
    }[response.mode]


def published_watermark(seen: int, published: int, source_payload: Mapping | None) -> int:
    """Independent peers were not observed, even when they published first."""
    if source_payload is None:
        return seen
    response = response_from_payload(source_payload)
    return seen if response is not None and response.mode == ResponseMode.COMPARE else max(seen, published)
