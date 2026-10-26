"""The keys each argv-twin method honours, for the manifest ``params`` block (owner ruling L4.22).

A ``models`` table so ``registry.manifest`` can read it without importing the
``lanes`` modules that register the methods. A row lists every key the handler reads.
"""

from __future__ import annotations

__layer__ = "models"

__all__ = [
    "CHARACTERS_METHOD_PARAMS",
    "CHAT_VERB_METHOD_PARAMS",
    "COURSE_METHOD_PARAMS",
    "HEALTH_METHOD_PARAMS",
    "PERSONA_TOOLSET_METHOD_PARAMS",
    "REALM_METHOD_PARAMS",
    "TWIN_METHOD_PARAMS",
]

#: ``runtime.characters.*`` (``serve_rpc/characters.py``).
CHARACTERS_METHOD_PARAMS: dict[str, tuple[str, ...]] = {
    "runtime.characters.list": (),
    "runtime.characters.recolour": ("draft", "from", "to"),
    "runtime.characters.status": ("draft",),
    "runtime.characters.thumb": ("attempt", "direction", "draft", "frame", "row", "scale", "square"),
    "runtime.characters.sprite": ("include_sheet", "slug"),
}

#: ``runtime.health`` (``serve_rpc/health.py``) takes none and refuses any.
HEALTH_METHOD_PARAMS: dict[str, tuple[str, ...]] = {"runtime.health": ()}

#: The six chat-family twins (``serve_rpc/chat_verbs.py``); ``requested_by`` is
#: read by ``chat_verbs.door.caller_requester`` before the transport's device.
CHAT_VERB_METHOD_PARAMS: dict[str, tuple[str, ...]] = {
    "runtime.chat.queue_skill": ("persona_id", "persona_instance_id", "session_id", "skill", "skills"),
    "runtime.chat.turn_audit": ("limit", "persona_instance_id", "session_id", "turn_id"),
    "runtime.chat.turn.resolve": (
        "action", "client_message_id", "persona_instance_id", "reason", "session_id", "turn_id"),
    "runtime.persona.chat.delete": ("persona_id", "persona_instance_id", "requested_by", "session_id"),
    "runtime.persona.chat.history": ("before", "limit", "session_id"),
    "runtime.persona.instance.create": (
        "add_instance", "client_message_id", "display_name", "kill_active", "persona_id", "placement_id",
        "realm_id", "requested_by", "session_id", "title", "workspace_id"),
}

#: The ten ``runtime.realm.*`` twins (``serve_rpc/realm.py`` ``REALM_METHODS``).
REALM_METHOD_PARAMS: dict[str, tuple[str, ...]] = {
    "runtime.realm.adopt": ("credential", "dry_run", "server_id", "sort"),
    "runtime.realm.agents.set": ("agents", "dry_run", "none", "realm_id", "workspace"),
    "runtime.realm.agents.show": ("realm_id",),
    "runtime.realm.skills.set": ("all", "dry_run", "none", "realm_id", "skills"),
    "runtime.realm.skills.show": ("realm_id",),
    "runtime.realm.sync.publish": ("credential", "dry_run", "realm_id", "yes"),
    "runtime.realm.sync.pull": ("credential", "dry_run", "realm_id"),
    "runtime.realm.sync.resolve": ("dry_run", "key", "realm_id", "take", "yes"),
    "runtime.realm.sync.revert": ("all", "dry_run", "items", "realm_id", "to", "yes"),
    "runtime.realm.sync.status": ("credential", "realm_id"),
}

#: ``runtime.course.*`` (``serve_rpc/course.py``) — method-lane-only, no argv twin; listed
#: here because this is the ``models`` table the manifest reads without importing a lane.
COURSE_METHOD_PARAMS: dict[str, tuple[str, ...]] = {
    "runtime.course.checkout": ("credential",),
    "runtime.course.commit": ("branch", "credential", "deletes", "files", "message", "persona_id", "persona_name"),
    "runtime.course.pull_request": ("body", "branch", "credential", "persona_id", "title"),
}

#: ``runtime.persona.toolset.*`` (``serve_rpc/console_operations.py``) — method-lane-only, no argv twin.
PERSONA_TOOLSET_METHOD_PARAMS: dict[str, tuple[str, ...]] = {
    "runtime.persona.toolset.approve": ("mode", "persona_id", "reason", "toolset"),
    "runtime.persona.toolset.list": ("persona_id",),
}

#: Every twin family's rows, merged; the manifest publishes this.
TWIN_METHOD_PARAMS: dict[str, tuple[str, ...]] = {
    **CHARACTERS_METHOD_PARAMS,
    **HEALTH_METHOD_PARAMS,
    **CHAT_VERB_METHOD_PARAMS,
    **REALM_METHOD_PARAMS,
}
