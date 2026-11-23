"""``runtime.agent.files.tree`` / ``.read`` / ``.grep`` — an agent's files, served by its engine as one tree.

Eternia row ``MC-PHONE-FILES-AN-AGENTS-FILES-ARE-SERVED-BY-ITS-ENGINE-AS-ONE-TREE``. Owner, 2026-11-21:
Eternia reads its own device's folders directly; another device's files are always read through
that device's Hermes. These are the verbs that Hermes answers: a phone driving a computer's engine
(the gateway's device lane) and a computer driving a phone's engine (the reverse lane) both call
them. The reader is ``agent_runtime/project_files/agent_tree.py``: the agent's roots are enumerated
here and a caller names a file only by a path relative to one of them.

Params (every verb takes ``persona_instance_id``):

* ``tree`` — ``path`` (absent: the agent's roots as top-level folders), ``depth`` (1-6, default 2),
  ``glob`` (a file-name glob: every matching file beneath ``path``, files only), ``offset``;
* ``read`` — ``path`` (``<root>/<relative>``), ``offset`` (code points);
* ``grep`` — ``pattern`` (1-256 characters: literal, or with ``wildcard: true`` a ``*`` spans any run
  within a line), ``path`` (absent: every root), ``glob`` (only files whose name matches), ``offset``.

* ``virtual`` — ``verb`` (``tree`` | ``read`` | ``grep``) and ``args``: this device's virtual tree
  (Eternia's generated documents), asked of this device's own Eternia with no turn bound (row
  ``RT-PHONE-FILES-THE-ENGINE-ASKS-THIS-DEVICES-ETERNIA-FOR-A-VIRTUAL-TREE-WITH-NO-TURN``); refused
  ``virtual_tree_unavailable`` when Eternia is not open here;
* ``virtual.write`` — the same with ``verb`` ``patch`` | ``write`` | ``move``: Eternia's validated edit of
  a generated document. A separate method so that a write is its own verb (row
  ``RT-FU-A-COMPUTER-DRIVING-A-PHONE-READS-THE-PHONES-GENERATED-DOCUMENTS``, review w1122b.4).

``glob`` and a wildcard ``pattern`` are the rule spec's ``patterns`` dialects, never a regular
expression: a remote caller's pattern is matched without backtracking (``project_files/patterns.py``),
holds at most 16 ``*``, and a ``tree`` with a glob or a ``grep`` that has not finished within
2,000 ms is refused ``search_timeout`` (row
``MC-FU-PROJECT-FOLDER-SEARCH-NARROWS-BY-FILE-NAME-AND-TAKES-A-PATTERN``).

Replies are the rule spec's shapes (``packages/eternia_file_tree_spec/`` in Eternia), each ``path``
prefixed by its root's name. A refusal carries the spec's code as ``data.reason``
(``invalid_path``, ``outside_root``, ``not_found``, ``ignored``, ``not_a_file``, ``too_large``,
``binary``, ``not_text``, ``bad_argument``, ``search_timeout``) or ``instance_not_found``.

**Security.** All three are ``console`` tier (row ``RT-FU-A-VIEW-ONLY-DEVICE-CANNOT-READ-AN-AGENTS-PROJECT-FILES``,
review w1118a.84, correcting w1118a.78's ``read``): a device paired view-only is refused the agent's
chats, so it is refused the project those chats are about, as ``runtime.media.get`` refuses it file
egress. Nothing here writes, each read is capped at 5 MiB (``MAX_FETCH_BYTES``, the media lane's
number; the spec's ``MAX_READ_BYTES``), a reply page is 20,000 code points, and the tree lists only
the agent's roots, never the machine's disk. A computer driving a phone reaches them only at the
account level, answered as a console-tier paired device; a peer install gets nothing new (``PEER_METHOD_ALLOWLIST`` is not widened,
plan ``PHONE_PROJECT_FOLDERS_FILE_TREE_2026-11-21`` §11).
"""

from __future__ import annotations

from typing import Any

from agent_runtime.call_authorization import TIER_CONSOLE
from agent_runtime.serve_rpc.protocol import (
    ERR_HANDLER_FAILED, ERR_INVALID_PARAMS, ERR_NOT_FOUND, RpcContext, err, ok,
)
from agent_runtime.serve_rpc.registry import method

__layer__ = "lanes"

__all__ = [
    "AGENT_FILES_METHOD_PARAMS",
    "_runtime_agent_files_grep",
    "_runtime_agent_files_read",
    "_runtime_agent_files_tree",
    "_runtime_agent_files_virtual",
    "_runtime_agent_files_virtual_write",
]

TREE_METHOD = "runtime.agent.files.tree"
READ_METHOD = "runtime.agent.files.read"
GREP_METHOD = "runtime.agent.files.grep"
VIRTUAL_METHOD = "runtime.agent.files.virtual"
VIRTUAL_WRITE_METHOD = "runtime.agent.files.virtual.write"
#: The virtual tree's verbs a caller may name, each Eternia's ``launcher.generated.<verb>``
#: (plan ``PHONE_PROJECT_FOLDERS_FILE_TREE_2026-11-21`` §4 V1, §7: Eternia is the only writer, so
#: a write is its validated edit, asked through the same lane). Reads and writes are two methods,
#: because a computer grant is a method-name allowlist that ignores a verb's tier.
VIRTUAL_READ_VERBS = ("tree", "read", "grep")
VIRTUAL_WRITE_VERBS = ("patch", "write", "move")

#: The honoured keys of each verb (the manifest's ``params``).
AGENT_FILES_METHOD_PARAMS: dict[str, tuple[str, ...]] = {
    TREE_METHOD: ("persona_instance_id", "path", "depth", "glob", "offset"),
    READ_METHOD: ("persona_instance_id", "path", "offset"),
    GREP_METHOD: ("persona_instance_id", "pattern", "path", "glob", "wildcard", "offset"),
    VIRTUAL_METHOD: ("verb", "args"),
    VIRTUAL_WRITE_METHOD: ("verb", "args"),
}

_CODES = {"not_found": ERR_NOT_FOUND, "invalid_path": ERR_INVALID_PARAMS, "bad_argument": ERR_INVALID_PARAMS}
_ID_LIMIT = 256


class _Refused(Exception):
    def __init__(self, code: int, reason: str, detail: str) -> None:
        super().__init__(detail)
        self.code, self.reason, self.detail = code, reason, detail


def _instance_id_param(params: dict) -> str:
    value = params.get("persona_instance_id")
    if not isinstance(value, str) or not value.strip() or len(value) > _ID_LIMIT:
        raise _Refused(ERR_INVALID_PARAMS, "bad_argument", "persona_instance_id is required")
    return value.strip()


def _path(params: dict, *, required: bool = False) -> str | None:
    value = params.get("path")
    if value is None and not required:
        return None
    if not isinstance(value, str):
        raise _Refused(ERR_INVALID_PARAMS, "invalid_path", "path must be a tree path (<root>/<relative>)")
    return value


def _whole_number_param(params: dict, key: str, default: int) -> int:
    value = params.get(key, default)
    if value is None:
        return default
    if not isinstance(value, int) or isinstance(value, bool):
        raise _Refused(ERR_INVALID_PARAMS, "bad_argument", f"{key} must be a whole number")
    return value


def _glob(params: dict) -> str | None:
    value = params.get("glob")
    if value is not None and not isinstance(value, str):
        raise _Refused(ERR_INVALID_PARAMS, "bad_argument", "glob must be text")
    return value


def _file_rpc_answer(rid: Any, params: Any, verb) -> dict:
    from agent_runtime.project_files.agent_tree import AgentNotFound
    from agent_runtime.project_files.rules import ProjectFileRefusal

    params = params if isinstance(params, dict) else {}
    try:
        return ok(rid, verb(params))
    except _Refused as refused:
        return err(rid, refused.code, f"The file request was refused: {refused.detail}",
                   {"reason": refused.reason, "detail": refused.detail})
    except AgentNotFound as missing:
        return err(rid, ERR_NOT_FOUND, "No agent by that id on this engine.",
                   {"reason": "instance_not_found", "detail": str(missing)})
    except ProjectFileRefusal as refusal:
        return err(rid, _CODES.get(refusal.code, ERR_HANDLER_FAILED),
                   f"The file request was refused: {refusal.message}",
                   {"reason": refusal.code, "detail": refusal.message})


# The agent's files as one tree (MC-PHONE-FILES-AN-AGENTS-FILES-ARE-SERVED-BY-ITS-ENGINE-AS-ONE-TREE):
# reads only, the agent's enumerated roots only, 5 MiB a read; so are the read and grep below.
@method(TREE_METHOD, tier=TIER_CONSOLE)
def _runtime_agent_files_tree(rid: Any, params: dict, context: RpcContext | None = None) -> dict:
    from agent_runtime.project_files import agent_tree
    from agent_runtime.project_files.rules import DEFAULT_DEPTH

    return _file_rpc_answer(rid, params, lambda p: agent_tree.tree(
        _instance_id_param(p), _path(p), depth=_whole_number_param(p, "depth", DEFAULT_DEPTH), glob=_glob(p),
        offset=_whole_number_param(p, "offset", 0)))


@method(READ_METHOD, tier=TIER_CONSOLE)
def _runtime_agent_files_read(rid: Any, params: dict, context: RpcContext | None = None) -> dict:
    from agent_runtime.project_files import agent_tree

    return _file_rpc_answer(rid, params, lambda p: agent_tree.read(
        _instance_id_param(p), _path(p, required=True), offset=_whole_number_param(p, "offset", 0)))


@method(GREP_METHOD, tier=TIER_CONSOLE)
def _runtime_agent_files_grep(rid: Any, params: dict, context: RpcContext | None = None) -> dict:
    from agent_runtime.project_files import agent_tree

    def run(p: dict) -> dict:
        pattern = p.get("pattern")
        if not isinstance(pattern, str):
            raise _Refused(ERR_INVALID_PARAMS, "bad_argument", "pattern must be text")
        wildcard = p.get("wildcard", False)
        if wildcard is None:
            wildcard = False
        if not isinstance(wildcard, bool):
            raise _Refused(ERR_INVALID_PARAMS, "bad_argument", "wildcard must be true or false")
        return agent_tree.grep(_instance_id_param(p), pattern, _path(p), glob=_glob(p), wildcard=wildcard,
                               offset=_whole_number_param(p, "offset", 0))

    return _file_rpc_answer(rid, params, run)


def _ask_virtual(rid: Any, params: Any, context: RpcContext | None, name: str, verbs: tuple[str, ...]) -> dict:
    """Ask this device's Eternia ``launcher.generated.<verb>`` for one of *verbs*, on the worker lane.

    Row ``RT-PHONE-FILES-THE-ENGINE-ASKS-THIS-DEVICES-ETERNIA-FOR-A-VIRTUAL-TREE-WITH-NO-TURN``. ``args``
    is that verb's own arguments, which Eternia validates (``document_id``, ``path``, ``read_version``…).
    No turn is bound here, so the request goes to the device-local Eternia link
    (``launcher_app_functions.device_local_launcher_link``: the machine owner's own declaring connection,
    never a peer's or a paired device's Eternia), origin ``local`` for the owner and ``paired_device`` for
    anyone else. With no such connection it refuses ``virtual_tree_unavailable`` ("Eternia is not open on
    this device"). Who may call *name* at all was settled before this runs (the dispatcher's tier and,
    for a computer driving this phone, its grant's allowlist); nothing here checks it a second time.
    """

    from agent_runtime.call_authorization import is_machine_owner
    from agent_runtime.launcher_app_functions import (
        ORIGIN_LOCAL, ORIGIN_PAIRED_DEVICE, device_local_launcher_link,
    )
    from agent_runtime.launcher_client_requests import ClientRequestFailed
    from agent_runtime.serve_rpc.protocol import defer_or_inline

    params = params if isinstance(params, dict) else {}
    verb, args = params.get("verb"), params.get("args", {})
    if verb not in verbs:
        return err(rid, ERR_INVALID_PARAMS, f"verb must be one of {', '.join(verbs)}",
                   {"reason": "bad_argument", "detail": "verb"})
    if not isinstance(args, dict):
        return err(rid, ERR_INVALID_PARAMS, "args must be an object", {"reason": "bad_argument", "detail": "args"})
    caller = context.caller if context is not None else None
    link = device_local_launcher_link(ORIGIN_LOCAL if is_machine_owner(caller) else ORIGIN_PAIRED_DEVICE)
    if link is None:
        return err(rid, ERR_HANDLER_FAILED, "Eternia is not open on this device.",
                   {"reason": "virtual_tree_unavailable"})

    def run() -> dict:
        try:
            return ok(rid, link.request(f"launcher.generated.{verb}", args))
        except ClientRequestFailed as failed:
            data = failed.data if isinstance(failed.data, dict) else {}
            reason = data.get("refusal") or ("no_reply" if failed.timed_out else "refused")
            return err(rid, ERR_HANDLER_FAILED, failed.message, {"reason": str(reason)})

    # It waits on Eternia's answer: the worker lane, never the reader's thread.
    return defer_or_inline(rid, name, context, run)


# This phone's generated documents, read through its own Eternia (tree / read / grep only;
# RT-FU-A-COMPUTER-DRIVING-A-PHONE-READS-THE-PHONES-GENERATED-DOCUMENTS). Their writes are the
# separate virtual.write below (review w1122b.4).
@method(VIRTUAL_METHOD, tier=TIER_CONSOLE)
def _runtime_agent_files_virtual(rid: Any, params: dict, context: RpcContext | None = None) -> dict:
    """Read this device's virtual tree (Eternia's generated documents): ``verb`` tree, read or grep.

    **Security.** ``console`` tier, as the agent's real folders are (``runtime.agent.files.*``; plan §11:
    a device paired view-only is refused an agent's files as it is refused its chats), so a view-only
    device's read is refused at the dispatcher before anything is asked of Eternia. Reads only; not in
    the peer allowlist.
    """

    return _ask_virtual(rid, params, context, VIRTUAL_METHOD, VIRTUAL_READ_VERBS)


@method(VIRTUAL_WRITE_METHOD, tier=TIER_CONSOLE)
def _runtime_agent_files_virtual_write(rid: Any, params: dict, context: RpcContext | None = None) -> dict:
    """Change this device's virtual tree: ``verb`` patch, write or move, as Eternia's validated edit.

    **Security.** ``console`` tier, and not in the peer allowlist (review w1122b.4); a computer on the
    phone's own account reaches it through ``paired_device_answers``.
    Hermes writes nothing itself: a write is Eternia's fenced, validated edit.
    """

    return _ask_virtual(rid, params, context, VIRTUAL_WRITE_METHOD, VIRTUAL_WRITE_VERBS)
