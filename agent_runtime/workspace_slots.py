"""Repo slots — the workspace declares, the machine fills, the agent is assigned (OWNER 2026-10-04).

Plan ``docs/agent-runtime-harness/planned/build-running-work-2026-10-04.md`` §3.

A WORKSPACE declares named **repo slots** (``launcher``, ``backend``, ``hermes``) — the
portable identity that travels with the realm: clone URL, default branch, the toolchain
and the environment KEYS it expects, its context files. Each MACHINE fills each slot: the
local PATH (a machine root, ``roots.<slot>``, through the existing single write site
``write_machine_roots``) and the environment (``workspace_slot_env``), both private and
never synced, but ACCOUNTED FOR in this document's ``machines.<id>`` block — set /
missing / unknown per key, never a value and never a path.

**One idea, not three.** A slot's machine fill IS a machine root: binding slot
``launcher`` writes ``roots.launcher``, so every ``${roots.launcher}`` token and every
``repo_scope: "${roots.launcher}"`` keeps resolving, and a root an operator bound by hand
before any workspace declared the name is ADOPTED as the fill (``adopted_existing_root``
in the first report, call 8g).

**No hard limits anywhere** (owner refinement 2026-10-04): no cap on slots, keys, tools or
machines. The document lives at ``paths.workspace_slots_path`` (``store/workspace_slots/
<token>.json``), beside the workspace record and not inside it — the record syncs by
generic overwrite, this document merges key-wise (``workspace_slots_sync``).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from utils import atomic_json_write

from . import paths
from .machine_roots import _ROOT_NAME_RE, load_machine_roots, write_machine_roots

__layer__ = "stores"

SLOTS_SCHEMA_VERSION = 1
#: ``context.files`` when a declaration names none (owner correction 2026-10-04: BOTH).
DEFAULT_CONTEXT_FILES = ("CLAUDE.md", "AGENTS.md")

REASON_INVALID_SLOT_NAME = "invalid_slot_name"
REASON_INVALID_CLONE_URL = "invalid_clone_url"
REASON_INVALID_DECLARATION = "invalid_declaration"
REASON_SLOT_NOT_DECLARED = "slot_not_declared"
REASON_INVALID_PATH = "invalid_path"
REASON_PATH_NOT_FOUND = "path_not_found"
REASON_STALE_REVISION = "stale_revision"
REASON_WORKSPACE_NOT_FOUND = "workspace_not_found"
REASON_REALM_PUBLISH_DENIED = "realm_publish_denied"
REASON_MACHINE_UNIDENTIFIED = "machine_identity_unavailable"

_CLONE_URL_RE = re.compile(r"^(https?://\S+|ssh://\S+|[\w.-]+@[\w.-]+:\S+)$")


class SlotRefused(ValueError):
    """A slot request this store will not apply; ``reason`` is the wire word."""

    def __init__(self, reason: str, detail: str = "") -> None:
        super().__init__(detail or reason)
        self.reason = reason
        self.detail = detail


@dataclass(frozen=True)
class BoundSlot:
    """A slot this machine fills: which workspace, which slot, the local checkout."""

    workspace_id: str
    slot: str
    path: Path


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def stamp_epoch(text: Any) -> float | None:
    """Epoch seconds for an ISO stamp (naive read as UTC); None when unusable."""

    raw = str(text or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw[:-1] + "+00:00" if raw.endswith("Z") else raw)
    except ValueError:
        return None
    return (parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)).timestamp()


def machine_id() -> str:
    """This machine's key in ``machines.<id>``: the gateway install id of this store root."""

    from .gateway_identity import ensure_install_identity

    identity = ensure_install_identity(paths.store_root())
    if not identity.ok or not identity.install_id:
        raise SlotRefused(REASON_MACHINE_UNIDENTIFIED, identity.state)
    return str(identity.install_id)


# ── the document ─────────────────────────────────────────────────────────────


def empty_document(workspace_id: str) -> dict[str, Any]:
    return {"schema_version": SLOTS_SCHEMA_VERSION, "workspace_id": workspace_id, "issued_at": "", "slots": {}, "machines": {}}


def load_document(workspace_id: str) -> dict[str, Any]:
    """The slot document, or an empty one. An unreadable file reads as empty — and is overwritten only by a declare."""

    try:
        payload = json.loads(paths.workspace_slots_path(workspace_id).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return empty_document(workspace_id)
    if not isinstance(payload, dict) or payload.get("schema_version") != SLOTS_SCHEMA_VERSION:
        return empty_document(workspace_id)
    payload.setdefault("slots", {})
    payload.setdefault("machines", {})
    return payload


def write_document(workspace_id: str, document: dict[str, Any]) -> None:
    target = paths.workspace_slots_path(workspace_id)
    target.parent.mkdir(parents=True, exist_ok=True)
    atomic_json_write(target, document, indent=2, sort_keys=True)


def live_slots(document: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """The declared slots that are not tombstoned."""

    return {name: slot for name, slot in (document.get("slots") or {}).items()
            if isinstance(slot, dict) and not slot.get("removed_at")}


def secret_keys(slot: dict[str, Any]) -> frozenset[str]:
    """Every key the declaration marks ``secret`` (env keys and ``.env`` keys alike)."""

    toolchain = slot.get("toolchain") or {}
    rows = list(toolchain.get("env_keys") or []) + list((toolchain.get("dotenv") or {}).get("keys") or [])
    return frozenset(str(row.get("key")) for row in rows if isinstance(row, dict) and row.get("secret"))


# ── declare ──────────────────────────────────────────────────────────────────


def _key_rows(rows: Any, *, default_required: bool) -> list[dict[str, Any]]:
    if rows is None:
        return []
    if not isinstance(rows, list):
        raise SlotRefused(REASON_INVALID_DECLARATION, "key lists must be lists")
    out = []
    for row in rows:
        row = {"key": row} if isinstance(row, str) else row
        if not isinstance(row, dict) or not isinstance(row.get("key"), str) or not row["key"].strip():
            raise SlotRefused(REASON_INVALID_DECLARATION, "every key row names a key")
        out.append({"key": row["key"].strip(), "required": bool(row.get("required", default_required)),
                    "secret": bool(row.get("secret", False))})
    return out


def _toolchain(value: Any) -> dict[str, Any]:
    value = value or {}
    if not isinstance(value, dict):
        raise SlotRefused(REASON_INVALID_DECLARATION, "toolchain must be an object")
    tools = []
    for tool in value.get("tools") or []:
        tool = {"name": tool} if isinstance(tool, str) else tool
        if not isinstance(tool, dict) or not isinstance(tool.get("name"), str) or not tool["name"].strip():
            raise SlotRefused(REASON_INVALID_DECLARATION, "every tool names itself")
        tools.append({"name": tool["name"].strip(), "min_version": str(tool.get("min_version") or "") or None})
    dotenv = value.get("dotenv")
    if dotenv is not None:
        if not isinstance(dotenv, dict):
            raise SlotRefused(REASON_INVALID_DECLARATION, "dotenv must be an object")
        dotenv = {"path": str(dotenv.get("path") or ".env"), "keys": _key_rows(dotenv.get("keys"), default_required=True)}
    return {"kind": str(value.get("kind") or ""), "tools": tools,
            "env_keys": _key_rows(value.get("env_keys"), default_required=True), "dotenv": dotenv}


def _context(value: Any) -> dict[str, Any]:
    value = value or {}
    files = value.get("files") if isinstance(value, dict) and value.get("files") is not None else list(DEFAULT_CONTEXT_FILES)
    if not isinstance(files, list) or not all(isinstance(f, str) and f and ".." not in f.replace("\\", "/").split("/")
                                              and not Path(f).is_absolute() for f in files):
        raise SlotRefused(REASON_INVALID_DECLARATION, "context.files are relative paths inside the checkout")
    return {"role": str((value or {}).get("role") or ""), "files": list(files)}


def normalize_declaration(entry: Any) -> tuple[str, dict[str, Any]]:
    """``(name, {repo, toolchain, context})`` for one declared slot, or :class:`SlotRefused`."""

    if not isinstance(entry, dict):
        raise SlotRefused(REASON_INVALID_DECLARATION, "every slot is an object")
    name = str(entry.get("name") or "")
    if not _ROOT_NAME_RE.match(name):
        raise SlotRefused(REASON_INVALID_SLOT_NAME, f"{name!r} is not a root name ([A-Za-z0-9_]+)")
    repo = entry.get("repo") or {}
    clone_url = str(repo.get("clone_url") or "") if isinstance(repo, dict) else ""
    if not _CLONE_URL_RE.match(clone_url):
        raise SlotRefused(REASON_INVALID_CLONE_URL, f"{clone_url!r} is not an http(s) or ssh clone URL")
    return name, {
        "repo": {"clone_url": clone_url, "default_branch": str(repo.get("default_branch") or "main")},
        "toolchain": _toolchain(entry.get("toolchain")),
        "context": _context(entry.get("context")),
    }


def declare(workspace_id: str, slots: Any, *, issued_at: str, machine: str) -> dict[str, Any]:
    """REPLACE the declared set: names missing from ``slots`` are tombstoned, never deleted.

    A slot that stays keeps its ``recipe`` (Phase B's, edited separately); a tombstoned name
    that is declared again comes back. An ``issued_at`` older than the document's last
    declare is refused ``stale_revision`` — a retried request cannot undo a newer edit.
    """

    if not isinstance(slots, list):
        raise SlotRefused(REASON_INVALID_DECLARATION, "slots must be a list")
    declared = dict(normalize_declaration(entry) for entry in slots)
    document = load_document(workspace_id)
    last, issued = stamp_epoch(document.get("issued_at")), stamp_epoch(issued_at)
    if issued is None:
        raise SlotRefused(REASON_INVALID_DECLARATION, "issued_at must be an ISO-8601 stamp")
    if last is not None and issued < last:
        raise SlotRefused(REASON_STALE_REVISION, "a newer declaration already landed")
    current = document.setdefault("slots", {})
    for name, body in declared.items():
        held = current.get(name) or {}
        current[name] = {**body, "recipe": held.get("recipe") or {"revision": 0, "steps": [], "edited_at": None, "edited_by": None},
                         "declared_at": issued_at, "declared_by_machine": machine, "issued_at": issued_at, "removed_at": None}
    tombstoned = [name for name, slot in current.items() if name not in declared and not slot.get("removed_at")]
    for name in tombstoned:
        current[name] = {**current[name], "removed_at": issued_at, "issued_at": issued_at}
    document["issued_at"] = issued_at
    document["workspace_id"] = workspace_id
    write_document(workspace_id, document)
    from .persona_slots import drop_removed_slots

    # A removed slot leaves every assignment in the same write (build plan §3.3).
    dropped_from = drop_removed_slots(workspace_id, frozenset(tombstoned))
    return {"document": document, "declared": sorted(declared), "tombstoned": sorted(tombstoned),
            "assignments_dropped": dropped_from}


# ── this machine's fill ──────────────────────────────────────────────────────


def bound_path(slot: str) -> Path | None:
    """The machine root of the slot's name, when bound (the root IS the fill)."""

    value = load_machine_roots(refresh=True).roots.get(slot)
    return Path(value) if value else None


def bind(workspace_id: str, slot: str, path: str, *, issued_at: str) -> dict[str, Any]:
    """Bind ``slot`` on THIS machine: write ``roots.<slot>`` through the single write site.

    A checkout whose remote does not match the declaration still binds (call 8c): the
    report carries ``checkout: remote_mismatch`` as a typed warning.
    """

    if slot not in live_slots(load_document(workspace_id)):
        raise SlotRefused(REASON_SLOT_NOT_DECLARED, f"{workspace_id} declares no slot {slot!r}")
    target = Path(str(path or "")).expanduser()
    if not target.is_absolute():
        raise SlotRefused(REASON_INVALID_PATH, "a slot binds an ABSOLUTE local path")
    if not target.is_dir():
        raise SlotRefused(REASON_PATH_NOT_FOUND, f"{target} is not a directory on this machine")
    roots = dict(load_machine_roots(refresh=True).roots)
    roots[slot] = str(target)
    write_machine_roots(roots, dry_run=False)
    from .workspace_slots_probe import report

    row = report(workspace_id, fresh_binds=frozenset({slot}))["slots"].get(slot, {})
    warnings = ["remote_mismatch"] if row.get("checkout") == "remote_mismatch" else []
    return {"slot": slot, "bound_here": True, "path": str(target), "report": row, "warnings": warnings, "issued_at": issued_at}


def show(workspace_id: str) -> dict[str, Any]:
    """The document plus THIS machine's fill per slot — never another machine's path."""

    import time

    from .builds.unknowns import UNKNOWN_SLOT_UNBOUND_HERE, UnknownsIndex

    document = load_document(workspace_id)
    here = {}
    for name in live_slots(document):
        path = bound_path(name)
        bound_here = bool(path and path.is_dir())
        row = {"bound_here": bound_here, "path": str(path) if bound_here else None, "unknowns": []}
        if not bound_here:
            index = UnknownsIndex()
            machines = binding_machines(document, name)
            index.add(UNKNOWN_SLOT_UNBOUND_HERE,
                      f"{name}: bound on " + (", ".join(machines) if machines else "no reporting machine"), time.time())
            row["unknowns"] = index.wire()
        here[name] = row
    return {"document": document, "here": here}


def binding_machines(document: dict[str, Any], slot: str) -> list[str]:
    """The machine ids whose last report says they bind ``slot`` (the evidence for ``slot_unbound_here``)."""

    return sorted(machine for machine, entry in (document.get("machines") or {}).items()
                  if (((entry or {}).get("slots") or {}).get(slot) or {}).get("bound"))


# ── what detection watches ───────────────────────────────────────────────────


def realm_workspace_ids() -> list[str]:
    """Every workspace of the ACTIVE realm (call 4c); with no active realm, every slot document."""

    from .store import RealmStore, WorkspaceStore

    realm_id = RealmStore().active_id()
    if not realm_id:
        directory = paths.workspace_slots_dir()
        documents = sorted(directory.glob("*.json")) if directory.is_dir() else []
        return [load_document_from(path).get("workspace_id") or path.stem for path in documents]
    return sorted(ws.id for ws in WorkspaceStore().list_all(include_archived=False) if ws.realm_id == realm_id)


def load_document_from(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


@dataclass(frozen=True)
class SlotCensus:
    """What detection may watch: whether any slot is declared, and the ones bound here."""

    declared: int
    bound: tuple[BoundSlot, ...]


def slot_census() -> SlotCensus:
    declared = 0
    bound: list[BoundSlot] = []
    roots = load_machine_roots(refresh=True).roots
    for workspace_id in realm_workspace_ids():
        for name in live_slots(load_document(workspace_id)):
            declared += 1
            value = roots.get(name)
            if value and Path(value).is_dir():
                bound.append(BoundSlot(workspace_id, name, Path(value)))
    return SlotCensus(declared, tuple(bound))


def authorized_roots_bound_here() -> list[BoundSlot]:
    """Every slot bound on this machine across every workspace of the active realm (§3.6)."""

    return list(slot_census().bound)


def slot_for_path(path: Any, bound: list[BoundSlot] | tuple[BoundSlot, ...]) -> BoundSlot | None:
    """The bound slot ``path`` sits under — the DEEPEST wins; None when under none."""

    import os

    try:
        target = os.path.normcase(os.path.realpath(str(path)))
    except (OSError, ValueError):
        return None
    best: BoundSlot | None = None
    best_len = -1
    for candidate in bound:
        root = os.path.normcase(os.path.realpath(str(candidate.path)))
        if (target == root or target.startswith(root.rstrip(os.sep) + os.sep)) and len(root) > best_len:
            best, best_len = candidate, len(root)
    return best


__all__ = [
    "BoundSlot",
    "DEFAULT_CONTEXT_FILES",
    "SlotCensus",
    "SlotRefused",
    "authorized_roots_bound_here",
    "bind",
    "bound_path",
    "declare",
    "live_slots",
    "load_document",
    "machine_id",
    "show",
    "slot_census",
    "slot_for_path",
    "write_document",
]


def require_publish_right(workspace_id: str, credential: Any = None) -> None:
    """``slots.declare`` (and Phase B's ``recipe.set``) — whoever may PUBLISH the realm (call 8a).

    The existing ``realm_sync.git._authorize(realm, "publish", membership)`` decision: a
    server-less realm answers the local allow stub; a server-bound realm needs the
    launcher-brokered credential and fails CLOSED without one. A workspace in no realm has
    nothing to publish, so its declaration is this machine's own.
    """

    from .realm_sync.git import _authorize
    from .realm_sync.models import RealmSyncError
    from .store import RealmStore, WorkspaceStore

    workspace = WorkspaceStore().get(workspace_id)
    if not workspace.realm_id:
        return
    try:
        _authorize(RealmStore().get(workspace.realm_id), "publish", None, credential)
    except RealmSyncError as exc:
        raise SlotRefused(REASON_REALM_PUBLISH_DENIED, exc.code) from exc
