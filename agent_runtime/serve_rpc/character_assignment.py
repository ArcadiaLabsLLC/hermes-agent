"""Revision-checked agent character commands; independent of office/rendering.

The four method names are the capability boundary. Older runtimes continue to
use their existing writer. Once activated, an old client receives an explicit
refusal if it attempts to edit the legacy placement character.
"""

from agent_runtime.call_authorization import TIER_CONSOLE, TIER_READ
from agent_runtime.character_assignment import CharacterAssignmentReason, CharacterAssignmentRefused
from agent_runtime.character_assignment_service import preview_character_migration, read_character_assignment, write_character_assignment
from agent_runtime.errors import NotFound
from agent_runtime.serve_rpc.protocol import ERR_CONFLICT, ERR_INVALID_PARAMS, ERR_NOT_FOUND, err, ok
from agent_runtime.serve_rpc.registry import method

__layer__ = "lanes"


def _character_response(rid, params, handler, *, migrate=False):
    if not isinstance(params, dict):
        return err(rid, ERR_INVALID_PARAMS, "An agent subject is required.")
    try:
        result = handler(params, migrate=True) if migrate else handler(params)
        return ok(rid, result)
    except CharacterAssignmentRefused as exc:
        code = ERR_INVALID_PARAMS if exc.reason == CharacterAssignmentReason.INVALID else ERR_CONFLICT
        return err(rid, code, exc.detail, {"reason": exc.reason.value})
    except (FileNotFoundError, NotFound):
        return err(rid, ERR_NOT_FOUND, "The agent record is unavailable.", {"reason": "agent_not_found"})


@method("runtime.character.assignment.get", tier=TIER_READ)
def _runtime_character_assignment_get(rid, params, context=None):
    return _character_response(rid, params, read_character_assignment)


@method("runtime.character.assignment.preview_migration", tier=TIER_READ)
def _runtime_character_assignment_preview(rid, params, context=None):
    return _character_response(rid, params, preview_character_migration)


@method("runtime.character.assignment.set", tier=TIER_CONSOLE)
def _runtime_character_assignment_set(rid, params, context=None):
    return _character_response(rid, params, write_character_assignment)


@method("runtime.character.assignment.migrate", tier=TIER_CONSOLE)
def _runtime_character_assignment_migrate(rid, params, context=None):
    return _character_response(rid, params, write_character_assignment, migrate=True)
