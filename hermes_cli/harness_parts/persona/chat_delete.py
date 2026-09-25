"""Delete a persona chat: ``persona chat delete`` (binding clear, tombstones, events).

Separate because it is the one verb that retires a chat's history and bindings.
"""

from __future__ import annotations

import uuid
from agent_runtime.cli_format import emit_json
from agent_runtime.config import load_agent_runtime_config
from agent_runtime.events import EventLog
from agent_runtime.models import Event
from agent_runtime.persona_assignments import (
    CHAT_BINDING_CLEARED_REASON_DELETED,
    PersonaAssignmentStore,
    PersonaInstanceStore,
    normalize_persona_or_template_id as _normalize_cli_persona_or_template_id,
    personas_equal,
    safe_assignment_text,
    safe_assignment_token,
)
from agent_runtime.persona_chat_continuity import (
    PersonaChatBusyError,
    persona_chat_root_lease,
    persona_chat_runtime_registry,
)
from agent_runtime.persona_chat_durability import (
    PersonaChatPersistenceError,
    default_persona_session_db as _default_persona_session_db,
)
from hermes_constants import get_hermes_home
from hermes_time import now
from .chat_open import _emit_persona_open_chat_payload
from .chat_session import _persona_chat_bound_owner, _persona_chat_session_owner

__layer__ = "lanes"
__all__ = [
    "_cmd_persona_chat_delete",
]


def _cmd_persona_chat_delete(args) -> int:
    # Function-local: the convention from before lane H1, when this file was
    # exec'd into harness.py's globals. The turn-outcome vocabulary is owned by
    # agent_runtime.mission_chat_outcome; nothing re-spells its values.
    from agent_runtime.mission_chat_outcome import ChatErrorKind
    cfg = load_agent_runtime_config()
    session_id = safe_assignment_text(getattr(args, "session_id", None), limit=200)
    if not session_id:
        data = {"ok": False, "error": "session_id is required"}
        _emit_persona_open_chat_payload(args, data)
        return 2

    requested_persona = None
    raw_persona = safe_assignment_text(getattr(args, "persona_id", None), limit=160)
    if raw_persona:
        try:
            requested_persona = _normalize_cli_persona_or_template_id(raw_persona)
        except Exception:
            requested_persona = safe_assignment_token(raw_persona)
    requested_instance = safe_assignment_token(getattr(args, "persona_instance_id", None))

    deleted_session = False
    try:
        session_db = _default_persona_session_db()
    except PersonaChatPersistenceError as exc:
        data = {
            "ok": False,
            "session_id": session_id,
            "error_kind": ChatErrorKind.CHAT_SESSION_DB_UNAVAILABLE,
            "persistence_operation": exc.operation,
            "error": str(exc),
        }
        print(emit_json(data) if args.json else data["error"])
        return 2
    owner_instance_id = _persona_chat_session_owner(session_db, session_id)
    if not owner_instance_id:
        owner_instance_id = _persona_chat_bound_owner(session_id)
    try:
        owner_instance = (
            PersonaInstanceStore().get(owner_instance_id)
            if owner_instance_id
            else None
        )
    except Exception:
        owner_instance = None
    session_exists = False
    try:
        session_exists = session_db.get_session(session_id) is not None
    except Exception:
        session_exists = False
    if owner_instance is None and not session_exists:
        data = {
            "ok": False,
            "status": "not_found",
            "session_id": session_id,
            "deleted_session": False,
            "cleared_bindings": [],
            "error": f"persona chat session not found: {session_id}",
        }
        print(emit_json(data) if args.json else data["error"])
        return 2
    # Third site of the same shape: the STORED ``owner_instance.persona_id``
    # compared raw against ``requested_persona``, which is
    # ``_normalize_cli_persona_or_template_id`` output — or, on that call's
    # except branch, ``safe_assignment_token`` output. Two normalizers reachable
    # from one argument, in one predicate. Folded through ``personas_equal`` so a
    # spelling can no longer refuse the delete of a root the caller owns.
    owner_persona = getattr(owner_instance, "persona_id", None)
    pin_proves_ownership = bool(requested_instance) and (
        owner_instance is not None and owner_instance.id == requested_instance
    )
    # Pin bounded exactly as in the mission-chat fence: proven ownership speaks
    # only where the persona leg is silent (an owner row with no readable
    # persona). A pin must not license deleting a root the caller has just
    # named a DIFFERENT persona for — that is caller confusion, and refusing it
    # costs nothing.
    persona_ok = (not requested_persona) or personas_equal(
        owner_persona, requested_persona
    ) or (pin_proves_ownership and not safe_assignment_token(owner_persona))
    if (
        owner_instance is None
        or (requested_instance and owner_instance.id != requested_instance)
        or not persona_ok
    ):
        data = {
            "ok": False,
            "capability_id": "persona.chat.delete",
            "error_kind": ChatErrorKind.FOREIGN_CHAT_SESSION,
            "error": "chat root is not owned by the requested persona instance",
            "session_id": session_id,
            "persona_instance_id": requested_instance or None,
        }
        print(emit_json(data) if args.json else data["error"])
        return 2
    if not bool(getattr(args, "_persona_chat_delete_lease_acquired", False)):
        try:
            with persona_chat_root_lease(
                session_id,
                owner_id=safe_assignment_token(
                    getattr(args, "requested_by", None)
                ),
                observer_kind="delete",
            ):
                args._persona_chat_delete_lease_acquired = True
                try:
                    return _cmd_persona_chat_delete(args)
                finally:
                    args._persona_chat_delete_lease_acquired = False
        except PersonaChatBusyError as exc:
            data = {
                "ok": False,
                "capability_id": "persona.chat.delete",
                "error_kind": ChatErrorKind.CHAT_BUSY,
                "session_id": session_id,
                "lease_owner": exc.owner,
                "error": str(exc),
            }
            print(emit_json(data) if args.json else data["error"])
            return 2
    try:
        from agent_runtime.session_extensions import delete_compression_lineage

        if callable(getattr(session_db, "_execute_write", None)):  # a real SessionDB
            deleted_session = bool(
                delete_compression_lineage(session_db, session_id, sessions_dir=get_hermes_home() / "sessions")
            )
        else:
            deleted_session = bool(session_db.delete_session(session_id, sessions_dir=get_hermes_home() / "sessions"))
    except TypeError:
        deleted_session = bool(session_db.delete_session(session_id))
    except Exception as exc:
        data = {
            "ok": False,
            "session_id": session_id,
            "error": f"failed to delete persona chat session: {exc}",
        }
        print(emit_json(data) if args.json else data["error"])
        return 2

    instance_store = PersonaInstanceStore()
    assignment_store = PersonaAssignmentStore()
    cleared_bindings: list[str] = []
    registry = persona_chat_runtime_registry()
    if registry is not None:
        registry.evict(session_id)
    try:
        from tools.terminal_tool_lifecycle import cleanup_vm

        cleanup_vm(session_id, force_remove=True)
    except Exception:
        pass
    closed_assignment_ids: list[str] = []
    # Unbind EVERY instance still pointing at the session that was just deleted —
    # on either pointer, and regardless of which identity was named on the
    # request. Ownership was already enforced above (a foreign request is refused
    # with ``foreign_chat_session``), so anything still holding this session id is
    # by definition a dangling pointer: id-scheme drift, a sibling steal, or the
    # legacy ``session_id`` mirror. Leaving one behind is exactly how a permanent
    # ``session_not_in_db`` parity drop is minted — the projection can only hide
    # the row, it can never repair the binding.
    for instance in instance_store.list_all():
        bound_here = session_id in {
            safe_assignment_text(getattr(instance, "default_chat_session_id", None), limit=200),
            safe_assignment_text(getattr(instance, "session_id", None), limit=200),
        }
        if not bound_here:
            continue

        assignment_id = safe_assignment_token(getattr(instance, "current_assignment_id", None))
        if assignment_id:
            try:
                assignment = assignment_store.get(assignment_id)
                if (
                    assignment.evidence_kind == "free_floating"
                    and assignment.state not in {"completed", "blocked", "cancelled"}
                ):
                    closed = assignment_store.complete(
                        assignment.id,
                        state="cancelled",
                        error=f"deleted persona chat session {session_id}",
                    )
                    closed_assignment_ids.append(closed.id)
            except Exception:
                pass

        # One write path for every unbind (delete verb + reconcile sweep): it
        # nulls only the pointers that name THIS session, demotes the mode, and
        # emits ``persona_instance.chat_binding_cleared``.
        record = instance_store.clear_chat_session_binding(
            instance,
            session_id=session_id,
            reason=CHAT_BINDING_CLEARED_REASON_DELETED,
        )
        if record is not None:
            cleared_bindings.append(instance.id)

    if not deleted_session and not cleared_bindings:
        data = {
            "ok": False,
            "status": "not_found",
            "session_id": session_id,
            "deleted_session": False,
            "cleared_bindings": [],
            "error": f"persona chat session not found: {session_id}",
            "next_expected": "refresh Harness snapshot; if the row is still visible, inspect SessionDB source and persona_instance.default_chat_session_id",
        }
        print(emit_json(data) if args.json else data["error"])
        return 2

    try:
        EventLog().append(
            Event(
                id=f"evt_{uuid.uuid4().hex[:12]}",
                type="persona_chat.deleted",
                persona_id=requested_persona or "persona",
                task_id=None,
                run_id=None,
                ts=now(),
                payload={
                    "session_id": session_id,
                    "deleted_session": deleted_session,
                    "cleared_bindings": cleared_bindings,
                    "closed_assignment_ids": closed_assignment_ids,
                    "requested_by": safe_assignment_text(getattr(args, "requested_by", None), limit=120) or "cli",
                },
            )
        )
    except Exception:
        pass

    data = {
        "ok": True,
        "session_id": session_id,
        "deleted_session": deleted_session,
        "cleared_bindings": cleared_bindings,
        "cleared_binding_count": len(cleared_bindings),
        "closed_assignment_ids": closed_assignment_ids,
        "next_expected": "refresh Harness snapshot; deleted persona chat should be absent and active bindings should be cleared",
    }
    print(emit_json(data) if args.json else f"deleted persona chat {session_id}")
    return 0
