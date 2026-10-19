"""Lens PROVENANCE: who sent a forged Episode turn, as the chat lane's ``requested_by``.

Plan ``p10-agent-2026-10-19.md`` §5.2 decision 3. A forged turn is a role="user"
row that no operator typed; the mission-chat handler decodes this value (in
``chat_history_writes._resolve_relay_sender_marker``) into the ``lens_episode:``
``finish_reason`` marker that ``relay_policy`` builds and parses, so the row reads
as Lens, never as the operator. Same road as a dispatch delivery
(``dispatch_delivery.vocabulary.delivery_requested_by``).

* ``requested_by`` = ``lens-episode:<episode_id>:<monitor_id>``;
* ``client_message_id`` = ``lens-episode-<episode_id>`` — the idempotency key, so a
  retried forge converges on the chat lane's existing dedup (as
  ``dispatch-delivery-<id>`` does).
"""

from __future__ import annotations

from dataclasses import dataclass

__layer__ = "models"

LENS_REQUESTED_BY = "lens-episode"


@dataclass(frozen=True)
class LensEpisodeOrigin:
    """A decoded ``requested_by``. ``monitor_id`` is None when the segment was absent."""

    episode_id: str
    monitor_id: str | None = None


def lens_requested_by(episode_id: str, monitor_id: str) -> str:
    return f"{LENS_REQUESTED_BY}:{str(episode_id).strip()}:{str(monitor_id).strip()}"


def lens_client_message_id(episode_id: str) -> str:
    return f"{LENS_REQUESTED_BY}-{str(episode_id).strip()}"


def parse_lens_requested_by(value) -> LensEpisodeOrigin | None:
    """The origin, or None for every other value (an Episode id is required)."""

    if not isinstance(value, str):
        return None
    prefix = f"{LENS_REQUESTED_BY}:"
    token = value.strip()
    if not token.startswith(prefix):
        return None
    episode_id, _, monitor_id = token[len(prefix):].partition(":")
    if not episode_id.strip():
        return None
    return LensEpisodeOrigin(episode_id=episode_id.strip(), monitor_id=monitor_id.strip() or None)
