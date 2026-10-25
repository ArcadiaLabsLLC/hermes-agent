"""Adopt a quiescent profile route into the canonical instance transcript store.

The old route receipt fences execution; the existing mint receipt owns the new
root. SessionDB imports every stored message atomically, without sending a turn.
Neither the donor database nor the instance's selected-chat pointer is written.
"""
from __future__ import annotations

import hashlib
import json
from contextlib import closing
from pathlib import Path

from agent_runtime.conversation_owner import client_scope, require_session_owner
from agent_runtime.persona_assignments import PersonaInstanceStore, persona_chat_session_id_for
from agent_runtime.persona_chat_durability import default_persona_session_db, persona_chat_ownership
from agent_runtime.persona_chat_mints import reserve_persona_chat_mint
from agent_runtime.persona_profile_binding import binding_index
from agent_runtime.profile_context import active_profile_name
from agent_runtime.workspace_scope import effective_workspace_id

from .model import MIGRATE_PARAMS, ConversationError, Refusal, identifier, permission_subject

__layer__ = "lanes"

def migration_target(scope, params):
    """An explicit instance with the same effective profile, never a guessed peer."""
    if client_scope(scope.client) is None or set(params) - set(MIGRATE_PARAMS):
        raise ConversationError(Refusal.INVALID_REQUEST)
    store = PersonaInstanceStore()
    instance = store.get(identifier(params["persona_instance_id"]))
    if (instance.persona_id != identifier(params["persona_id"])
            or store.retired_instance_archive_path(instance.id, persona_id=instance.persona_id) is not None):
        raise ConversationError(Refusal.WRONG_OWNER)
    binding = binding_index().get(instance.persona_id)
    if binding is None or (binding.effective_profile or active_profile_name()) != scope.profile:
        raise ConversationError(Refusal.WRONG_OWNER)
    return instance


def _source_segments(service, route):
    from hermes_state import SessionDB

    path = Path(route.home) / "state.db"
    if not service.store.has_turns(route):
        return [{"id": route.native_id or route.id, "messages": [], "cwd": route.cwd}]
    if not route.native_id or not path.is_file():
        raise ConversationError(Refusal.UNAVAILABLE)
    with closing(SessionDB(db_path=path, read_only=True)) as db:
        exported = db.export_session_lineage(route.native_id, include_inactive=True)
    if not exported or not exported.get("segments"):
        raise ConversationError(Refusal.UNAVAILABLE)
    return exported["segments"]


def _adopted_segments(segments, route, instance, owner, root, receipts):
    # The root is reserved once; descendants are deterministic across retries.
    ids = {row["id"]: root if index == 0 else persona_child_id(root, row["id"])
           for index, row in enumerate(segments)}
    adopted = []
    for index, row in enumerate(segments):
        session_id = ids[row["id"]]
        config = _adopted_model_config(row, selection=segments[-1] if index == 0 else row)
        ownership = persona_chat_ownership(session_id, instance.persona_id, client_scope=owner, independent=True)
        provenance = {"route_id": route.id, "profile": route.profile, "session_id": row["id"],
                      "turns": receipts}
        config.update(ownership, mission_chat_root_id=root, legacy_conversation=provenance)
        # Imported roots remain visible even when the donor was archived. Message
        # active/compacted flags are left intact by the public SessionDB importer.
        adopted.append({**row, "id": session_id, "source": ownership["source"], "model_config": config,
                        "parent_session_id": ids.get(row.get("parent_session_id")),
                        "archived": 0, "auto_archived": 0,
                        "title": f"{row.get('title') or 'Imported conversation'} ({session_id[-12:]})"
                                 if index == 0 else None})
    return adopted


def _adopted_model_config(row, *, selection):
    """Translate the donor's persisted selection into the native chat tier.

    Gateway history stores its last selection at the top level. Native chats
    deliberately read their own override contract, so copying those bytes alone
    silently loses the choice. Endpoints and credentials are resolved by the
    existing provider owner, never transplanted as an execution override.
    """
    from hermes_state import SessionDB
    from agent_runtime.persona_chat_session import (
        _CHAT_MODEL_OVERRIDE_CONFIG_KEY, _chat_model_override_from_config, _chat_reasoning_effort,
    )

    raw = row.get("model_config") or {}
    config = json.loads(raw) if isinstance(raw, str) else dict(raw)
    if _CHAT_MODEL_OVERRIDE_CONFIG_KEY not in config:
        raw_selection = selection.get("model_config") or {}
        chosen = json.loads(raw_selection) if isinstance(raw_selection, str) else raw_selection
        route = SessionDB.session_gateway_runtime(selection)
        reasoning = chosen.get("reasoning_config") or {}
        candidate = {_CHAT_MODEL_OVERRIDE_CONFIG_KEY: {
            "model": selection.get("model") or chosen.get("model"), "provider": route.get("provider"),
            "reasoning_effort": _chat_reasoning_effort(reasoning.get("effort"))
                if isinstance(reasoning, dict) else None,
            "source": "profile_migration",
        }}
        override = _chat_model_override_from_config(candidate)
        if override is not None:
            config[_CHAT_MODEL_OVERRIDE_CONFIG_KEY] = override
    return config


def persona_child_id(root, source_id):
    # Keep the canonical instance prefix; a lineage child is owned by the same
    # instance, but must never collide with another imported or new chat.
    suffix = hashlib.sha256(json.dumps([root, source_id]).encode()).hexdigest()[:12]
    return root.rsplit("_", 1)[0] + "_" + suffix


def _verify_import(db, root, route, instance, owner):
    row = db.get_session(root)
    if row is None:
        raise ConversationError(Refusal.UNAVAILABLE)
    require_session_owner(row, owner)
    config = row.get("model_config") or {}
    config = json.loads(config) if isinstance(config, str) else config
    if (config.get("persona_instance_id") != instance.id
            or config.get("legacy_conversation", {}).get("route_id") != route.id):
        raise ConversationError(Refusal.WRONG_OWNER)


def _preserve_permission(route, instance, root):
    """Copy the existing grant before the new chat is visible; never extend it."""
    from agent_runtime.tool_permissions import ChatToolPermissionStore

    permissions = ChatToolPermissionStore()
    if permissions.get(persona_id=instance.persona_id, session_id=root) is not None:
        return
    grant = permissions.get(persona_id=permission_subject(route), session_id=route.id)
    if grant is not None:
        permissions.set(persona_id=instance.persona_id, session_id=root, mode=grant.mode,
                        reason=grant.reason, source=grant.source, expires_at=grant.expires_at,
                        turns_remaining=grant.turns_remaining)


def migrate_conversation(service, scope, route, instance):
    with reserve_persona_chat_mint(
        idempotency_key="profile-migration:" + route.id, persona_id=instance.persona_id,
        persona_instance_id=instance.id, session_id=persona_chat_session_id_for(instance.id),
        client_scope=scope.client, select_session=False,
    ) as mint, closing(default_persona_session_db()) as db:
        root = mint.receipt.session_id
        if not mint.receipt.bound and db.get_session(root) is None:
            segments = _source_segments(service, route)
            # Ownership/profile changes during the disk read cannot retarget an import.
            current = service._owned_route(scope, route.id)
            if current != route or migration_target(scope, {"persona_id": instance.persona_id,
                    "persona_instance_id": instance.id}) != instance:
                raise ConversationError(Refusal.WRONG_OWNER)
            receipts = service.store.turn_receipts(route)
            adopted = _adopted_segments(segments, route, instance, scope.client, root, receipts)
            if any(db.get_session(row["id"]) is not None for row in adopted):
                raise ConversationError(Refusal.CONFLICT)
            _preserve_permission(route, instance, root)
            # A crash after the atomic import but before mark_bound reuses these
            # exact IDs; user-deleted IDs stay fenced by SessionDB itself.
            result = db.import_sessions(adopted)
            if not result.get("ok"):
                raise ConversationError(Refusal.UNAVAILABLE)
            _verify_import(db, root, route, instance, scope.client)
        _verify_import(db, root, route, instance, scope.client)
        mint.mark_bound()
        return {"install_id": service.install_id, "client_scope": scope.client,
                "persona_id": instance.persona_id, "persona_instance_id": instance.id,
                "workspace_id": effective_workspace_id(instance, active_workspace_id=None),
                "session_id": root, "legacy_session_id": route.id,
                "idempotent_replay": mint.receipt.idempotent_replay,
                "turns": service.store.turn_receipts(route)}
