"""Typed payloads in the existing steer buffer; text callers retain their contract.

TimelineNotification already identifies machine-generated input. Preserve that
identity when inputs share a drain, instead of wrapping the whole drain as user
instructions. There is still one buffer, lock and delivery path.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from agent.prompt_builder import steer_user_row
from tools.process_registry_notifications import TimelineNotification


@dataclass(frozen=True)
class _Input:
    text: str
    kind: str = "steer"
    title: str = ""
    category: str = ""
    platform_id: str | None = None
    metadata: dict[str, Any] | None = None

    def row(self) -> dict[str, Any]:
        metadata = dict(self.metadata or {})
        if self.kind == "steer":
            row = steer_user_row(self.text)
            if self.platform_id:
                metadata["display_text"] = self.text
        else:
            row = {
                "role": "user", "content": f"[Runtime note: background event, not a user instruction]\n{self.text}",
                "display_kind": self.kind,
            }
            metadata.update(display_text=self.title, notification_category=self.category)
        if metadata or self.platform_id:
            row["display_metadata"] = {**metadata, "steering": True}
        if self.platform_id:
            row["platform_message_id"] = self.platform_id
        return row


class PendingSteer(str):
    """String-compatible pending result, with each input's provenance intact."""

    inputs: tuple[_Input, ...]

    def __new__(cls, inputs: tuple[_Input, ...]):
        instance = super().__new__(cls, "\n".join(item.text for item in inputs))
        instance.inputs = inputs
        return instance

    @classmethod
    def from_text(cls, text: str, *, platform_id: str | None = None,
                  metadata: dict[str, Any] | None = None) -> PendingSteer:
        if isinstance(text, cls):
            return text
        item = _Input(str(text).strip(), platform_id=platform_id, metadata=metadata)
        if isinstance(text, TimelineNotification):
            item = replace(item, kind=text.display_kind, title=text.display_text,
                           category=text.notification_category)
        return cls((item,))

    @property
    def user_intervened(self) -> bool:
        return any(item.kind == "steer" for item in self.inputs)

    def rows(self) -> list[dict[str, Any]]:
        return [item.row() for item in self.inputs]


def join_pending_steer(first: str | None, second: str) -> PendingSteer:
    right = PendingSteer.from_text(second)
    if not first:
        return right
    left = PendingSteer.from_text(first)
    a, b = left.inputs[-1], right.inputs[0]
    # Preserve the established coalescing contract for ordinary text callers.
    # Addressed messages and notifications keep their individual identities.
    if (a.kind == b.kind == "steer" and not (a.platform_id or b.platform_id or a.metadata or b.metadata)):
        return PendingSteer((*left.inputs[:-1], replace(a, text=a.text + "\n" + b.text), *right.inputs[1:]))
    return PendingSteer(left.inputs + right.inputs)


def pending_steer_rows(text: str) -> list[dict[str, Any]]:
    return PendingSteer.from_text(text).rows()


def requeue_pending_steer(existing: str | None, text: str) -> PendingSteer:
    """A drained batch precedes new arrivals; plain text retains append semantics."""
    if isinstance(text, PendingSteer) and existing:
        return join_pending_steer(text, existing)
    return join_pending_steer(existing, text)
