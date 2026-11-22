"""``runtime.files.status`` / ``runtime.files.diff`` — git status and one file's diff on this device's folder.

Row ``MC-PHONE-FILES-GIT-STATUS-AND-DIFF-ON-A-PHONE-PROJECT-FOLDER`` (Eternia plan
``docs/embedded_hermes/planned/PHONE_PROJECT_FOLDERS_FILE_TREE_2026-11-21.md`` §5): Eternia on a
phone has no git program, so it asks its local hermes in-process for a project folder's changed
files and one file's diff, and keeps reading the files themselves directly (path (a)). hermes
answers through ``agent_runtime.project_files.changes``: dulwich on a phone, the git program on a
desktop, whichever ``realm_sync.git.sync_git`` picks.

The folder is named by its absolute ``root`` on THIS device, so both verbs are on
``LOCAL_CONSOLE_METHODS``: only the device's own Eternia (the machine owner, who already reads the
folder directly) may name a path. A paired or remote caller never names this device's disk; serving
a device's roots to another device is ``MC-PHONE-FILES-AN-AGENTS-FILES-ARE-SERVED-BY-ITS-ENGINE-AS-ONE-TREE``.
Nothing here writes. Every refusal is ``data.reason``, a rule-spec refusal code
(``not_a_git_root``, ``invalid_path``, ``outside_root``, ``ignored``, ``not_found``,
``not_a_file``, ``bad_argument``).
"""

from agent_runtime.call_authorization import TIER_CONSOLE
from agent_runtime.serve_rpc.protocol import ERR_INVALID_PARAMS, ERR_NOT_FOUND, err, ok
from agent_runtime.serve_rpc.registry import method

__layer__ = "lanes"

_NOT_FOUND = {"not_found", "not_a_git_root"}


def _refused(rid, reason: str, detail: str) -> dict:
    code = ERR_NOT_FOUND if reason in _NOT_FOUND else ERR_INVALID_PARAMS
    return err(rid, code, "The project files request was refused.", {"reason": reason, "detail": detail})


def _offset(params: dict) -> int:
    from agent_runtime.project_files.rules import ProjectFileRefusal

    offset = params.get("offset", 0)
    if not isinstance(offset, int) or isinstance(offset, bool):
        raise ProjectFileRefusal("bad_argument", f"offset must be a whole number, not {offset!r}")
    return offset


def _string(params: dict, name: str) -> str:
    from agent_runtime.project_files.rules import ProjectFileRefusal

    value = params.get(name)
    if not isinstance(value, str):
        raise ProjectFileRefusal("invalid_path", f"{name} must be a path string")
    return value


def _answered(handler):
    def run(rid, params, context=None):
        from agent_runtime.project_files.rules import ProjectFileRefusal

        try:
            return ok(rid, handler(params or {}))
        except ProjectFileRefusal as exc:
            return _refused(rid, exc.code, exc.message)
    return run


@method("runtime.files.status", tier=TIER_CONSOLE)
@_answered
def _files_status(params):
    """``root`` (absolute) -> ``{path: "", entries: [{path, state}], total, offset, next?}``."""

    from agent_runtime.project_files.changes import status

    return status(_string(params, "root"), offset=_offset(params))


@method("runtime.files.diff", tier=TIER_CONSOLE)
@_answered
def _files_diff(params):
    """``root``, ``path`` -> ``{path, change, body}`` plus, for a text body, ``chars, offset, content, next?``."""

    from agent_runtime.project_files.changes import diff

    return diff(_string(params, "root"), _string(params, "path"), offset=_offset(params))
