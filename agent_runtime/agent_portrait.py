"""Exact-agent portrait assets over the existing profile artwork owner.

The character assignment row owns the choice and revision. Immutable bytes are
profile assets; preparing bytes is not a choice, and a failed CAS cannot change
any reader. Shared avatar files are never replaced by this path.
"""
from __future__ import annotations

import base64

from .character_assignment import CharacterAssignmentReason, CharacterAssignmentRefused
from .character_assignment_service import _character_subject, write_character_assignment
from .media_handles import handle_for_bytes
from .profile_avatar import AVATAR_UPLOAD_MAX_BYTES, AvatarRefusal, ProfileAvatarRefused, _portrait_png, agent_portrait_asset_path

__layer__ = "stores"


def write_agent_appearance(params: dict) -> dict:
    record = _character_subject(params)
    if params.get("kind") != "instance":
        raise CharacterAssignmentRefused(CharacterAssignmentReason.INVALID, "Select an exact agent for a chat portrait.")
    draft = params.get("portrait")
    if not isinstance(draft, dict) or draft.get("mode") not in {"character", "custom"}:
        raise ProfileAvatarRefused(AvatarRefusal.INVALID)
    portrait = {"mode": draft["mode"]}
    if portrait["mode"] == "custom":
        data = _portrait_png(draft.get("data_base64"))
        profile = record.profile_id
        if not profile:
            from .config.roster import ensure_persisted_personas
            from .profile_context import active_profile_name, resolve_persona_profile
            persona = next((p for p in ensure_persisted_personas() if p.id == record.persona_id), None)
            binding = resolve_persona_profile(persona) if persona is not None else None
            profile = (binding.hermes_profile or active_profile_name()) if binding is not None else None
        if not profile:
            raise ProfileAvatarRefused(AvatarRefusal.PROFILE)
        handle = handle_for_bytes(data)
        target = agent_portrait_asset_path(profile, handle)
        from utils import atomic_write_bytes
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            # Content addressed and immutable. A stale save may leave an
            # unreferenced asset; it never replaces another agent's artwork.
            if not target.exists():
                atomic_write_bytes(target, data, fsync_dir=True)
            elif target.stat().st_size != len(data) or target.read_bytes() != data:
                raise ProfileAvatarRefused(AvatarRefusal.UNAVAILABLE)
        except OSError as exc:
            raise ProfileAvatarRefused(AvatarRefusal.UNAVAILABLE) from exc
        portrait.update(profile=profile, handle=handle)
    return write_character_assignment(params, portrait=portrait)


def read_agent_portrait(params: dict) -> dict:
    record = _character_subject(params)
    if params.get("kind") != "instance":
        raise CharacterAssignmentRefused(CharacterAssignmentReason.INVALID, "An exact agent is required.")
    choice = (record.character_assignment or {}).get("portrait")
    result = {"id": record.id, "persona_id": record.persona_id, "portrait": choice}
    if not choice or choice.get("mode") != "custom":
        return result
    try:
        target = agent_portrait_asset_path(choice["profile"], choice["handle"])
        if not 0 < target.stat().st_size <= AVATAR_UPLOAD_MAX_BYTES:
            raise ProfileAvatarRefused(AvatarRefusal.UNAVAILABLE)
        data = target.read_bytes()
        if handle_for_bytes(data) != choice["handle"]:
            raise ProfileAvatarRefused(AvatarRefusal.UNAVAILABLE)
        return {**result, "data_base64": base64.b64encode(data).decode("ascii"), "media_type": "image/png"}
    except (KeyError, OSError, ProfileAvatarRefused):
        return {**result, "reason": "unavailable"}
