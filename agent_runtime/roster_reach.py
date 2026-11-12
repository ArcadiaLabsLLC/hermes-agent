"""The roster offers only agents a message can reach (RT-RELAY-TO-ROSTER-AGENT-WITHOUT-PROFILE).

Seen live 2026-11-12 (w1112b-cttfu, lane namespace ``stagec-smoke-lane-aaf70213f8``): five
``personainst_profile_base_agent_*`` records outlived their Hermes profiles (``profiles/`` held only
``base``), the Agent Browser listed one as "Base Agent 922892c6", and Base's ``agent_chat_send`` to it was
delivered failed "Hermes profile 'base_agent_922892c6' does not exist". RULED 2026-11-12 under the owner's
standing order (review batch w1112b §3): the roster does not offer an instance whose profile is gone, and
says so in a receipt — re-creating the profile would invent its configuration. The record is kept (its
chats stay readable); only the offer goes.
"""
from __future__ import annotations

import logging
from typing import Any, Iterable

__layer__ = "policy"
__all__ = ["offered", "profile_missing"]

logger = logging.getLogger(__name__)
_SAID: set[str] = set()


def profile_missing(instance: Any) -> str | None:
    """The profile name of a profile-backed instance whose profile directory is gone, else ``None``."""

    if getattr(instance, "role", None) != "profile":
        return None
    profile = str(getattr(instance, "profile_id", None) or "").strip()
    if not profile:
        return None
    try:
        from hermes_cli.profiles import profile_exists

        return None if profile_exists(profile) else profile
    except Exception:  # an unreadable profiles root hides nothing
        return None


def offered(instances: Iterable[Any]) -> list[Any]:
    """``instances`` less the ones no message can reach; each hidden id is receipted once per process."""

    kept = []
    for instance in instances:
        missing = profile_missing(instance)
        if missing is None:
            kept.append(instance)
            continue
        instance_id = str(getattr(instance, "id", "") or "")
        if instance_id not in _SAID:
            _SAID.add(instance_id)
            logger.info("roster_instance_hidden instance=%s profile=%s reason=profile_missing", instance_id, missing)
    return kept
