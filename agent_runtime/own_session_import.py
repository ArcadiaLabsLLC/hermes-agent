"""``hermes namespace import-sessions <id> <export.jsonl>`` — Hermes' OWN export into a namespace.

Row RT-SESSIONS-IMPORT-OWN-EXPORT; plan
``EterniaLauncher/docs/embedded_hermes/planned/ONE_HERMES_INSTALL_PROFILE_NAMESPACE_2026-10-19.md`` §3
step 3 (the owner's reseed into ``acct-<hex>``: export from the base root, import into the
namespace) and the owner's 2026-10-18 ruling for QA (export, never attach). A verb of the fork's
``hermes namespace`` rather than a ``--from hermes`` on upstream's ``hermes sessions import``: that
would add two upstream files to the footprint ratchet (``tests/scripts/test_upstream_footprint.py``),
which rises only on an owner ruling. The target is always a NAMED namespace, never ``base`` — the
root an export comes from is never the one it is written into.

The export is ``hermes sessions export <file>`` (JSONL, one ``SessionDB.export_session`` dict per
line, every stored row with its ``active``/``compacted`` flags). The import homes the process inside the
namespace for the run (``HERMES_HOME`` / ``HERMES_HEAD_HOME`` / ``HERMES_AGENT_RUNTIME_ROOT`` and
``HERMES_NAMESPACE``, so the isolation check applies) and writes those rows into the namespace's
chat store (:func:`chat_session_scope.open_chat_session_db`) through the one import door,
``SessionDB.import_sessions``. It only ever READS the export file, so the source is never
written.

**The binding.** A Mission Control chat belongs to a persona instance through its row's
``model_config.persona_instance_id`` (``persona_chat_history.history_rows._persisted_persona_instance_id``).
Persona INSTANCES are not seeded (``namespace_admin``: they carry the source's ``runtime_root``,
``chat_head_home`` and session ids), so the target re-creates its own; each persona chat is REBOUND
to one of them, first rule wins (:class:`BoundBy`):

1. ``--bind SRC=DST`` — SRC is the chat's source instance id or its persona id; DST must be an
   instance of the target (else the whole run refuses ``import_bind_target_unknown``);
2. ``same_instance`` — the target has an instance with the chat's own instance id;
3. ``persona_channel`` — the target has the persona's canonical channel
   (``persona_instance_id_for(persona_id)``);
4. ``persona_only_instance`` — the target has exactly one instance of that persona.

Otherwise the chat is skipped with a reason (:class:`Skip`) — ``ambiguous_target`` names the
candidates, so a ``--bind`` resolves it — and never dropped silently. A target with no persona
instance at all refuses the run (``import_no_target_instances``) before writing anything. A row
that is not a persona chat imports unchanged (``not_a_persona_chat``).

Idempotent: a session id already in the target is skipped ``already_present``, so a second import
of the same export imports nothing. Session ids are kept, so the chat's own lineage
(``parent_session_id``, ``mission_chat_root_id``) stays intact; a child is imported after its
parent and skipped when its parent was.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

from hermes_cli._namespace_bootstrap import DEPENDENCY_ENV, ENV, Layout, validate_id

from . import chat_session_scope
from .models import PersonaInstance
from .namespace_admin import existing_namespace
from .persona_assignments import PersonaInstanceStore, persona_instance_id_for
from .persona_chat_continuity import PERSONA_CHAT_SESSION_SOURCE
from .persona_chat_history.history_rows import _infer_persona_id, _model_config, _persisted_persona_instance_id
from .persona_chat_history.vocabulary import canonical_chat_persona_id

__layer__ = "lanes"
__all__ = [
    "BoundBy", "ImportRefused", "Refusal", "Skip", "import_into_namespace", "import_own_export", "parse_binds",
    "run_namespace_verb",
]


class Refusal(StrEnum):
    """Why the whole import refused before writing anything."""

    PATH_MISSING = "import_path_missing"
    BIND_MALFORMED = "import_bind_malformed"
    BIND_TARGET_UNKNOWN = "import_bind_target_unknown"
    NO_TARGET_INSTANCES = "import_no_target_instances"
    CHAT_STORE_UNAVAILABLE = "import_chat_store_unavailable"


class Skip(StrEnum):
    """Why one exported line or session was not imported."""

    UNPARSEABLE = "unparseable_line"
    NO_SESSION_ID = "no_session_id"
    ALREADY_PRESENT = "already_present"
    NO_PERSONA = "no_persona"
    NO_TARGET_INSTANCE = "no_target_instance"
    AMBIGUOUS_TARGET = "ambiguous_target"
    PARENT_SKIPPED = "parent_skipped"
    REJECTED = "rejected"


class BoundBy(StrEnum):
    """Which rule bound an imported session (the module docstring's ladder, in order)."""

    BIND = "bind"
    SAME_INSTANCE = "same_instance"
    PERSONA_CHANNEL = "persona_channel"
    PERSONA_ONLY_INSTANCE = "persona_only_instance"
    NOT_A_PERSONA_CHAT = "not_a_persona_chat"


class ImportRefused(RuntimeError):
    def __init__(self, reason: Refusal, detail: str) -> None:
        super().__init__(f"{reason.value}: {detail}")
        self.reason = reason
        self.detail = detail

    def payload(self) -> dict[str, Any]:
        return {"ok": False, "error": "sessions_import_refused", "reason": self.reason.value, "detail": self.detail}


def parse_binds(values: Iterable[str] | None) -> dict[str, str]:
    """``["SRC=DST", …]`` -> ``{SRC: DST}``; a malformed or repeated SRC refuses."""
    out: dict[str, str] = {}
    for raw in values or ():
        src, sep, dst = str(raw).partition("=")
        src, dst = src.strip(), dst.strip()
        if not sep or not src or not dst or out.get(src, dst) != dst:
            raise ImportRefused(Refusal.BIND_MALFORMED, f"--bind wants SRC=DST once per SRC, got {raw!r}")
        out[src] = dst
    return out


def read_export(path: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """The export's sessions in file order, and one skip row per line that is not a session."""
    sessions: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    with open(path, encoding="utf-8-sig") as handle:
        for number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except ValueError:
                row = None
            if not isinstance(row, dict):
                skipped.append({"line": number, "reason": Skip.UNPARSEABLE.value})
            elif not str(row.get("id") or "").strip():
                skipped.append({"line": number, "reason": Skip.NO_SESSION_ID.value})
            else:
                sessions.append(row)
    return sessions, skipped


#: ``(target instance id or None, how it bound or why it was skipped, detail)``.
Outcome = tuple[str | None, BoundBy | Skip, str]


@dataclass
class Targets:
    """The target's persona instances, indexed the ways the binding ladder asks."""

    instances: list[PersonaInstance]
    by_id: dict[str, PersonaInstance] = field(init=False)
    by_persona: dict[str, list[str]] = field(init=False)

    def __post_init__(self) -> None:
        self.by_id = {item.id: item for item in self.instances}
        self.by_persona = {}
        for item in self.instances:
            persona = canonical_chat_persona_id(item.persona_id)
            if persona:
                self.by_persona.setdefault(persona, []).append(item.id)

    def resolve(self, session: Mapping[str, Any], binds: Mapping[str, str]) -> Outcome:
        """Where one persona chat binds in this home, or why it cannot."""
        source_instance = _persisted_persona_instance_id(dict(session)) or ""
        persona = _infer_persona_id(dict(session), session_id=str(session["id"])) or ""
        for key in (source_instance, persona):
            if key and key in binds:
                return binds[key], BoundBy.BIND, key
        if source_instance in self.by_id:
            return source_instance, BoundBy.SAME_INSTANCE, source_instance
        if not persona:
            return None, Skip.NO_PERSONA, source_instance or "no persona_instance_id, no persona marker"
        if persona_instance_id_for(persona) in self.by_id:
            return persona_instance_id_for(persona), BoundBy.PERSONA_CHANNEL, persona
        candidates = sorted(self.by_persona.get(persona, ()))
        if len(candidates) == 1:
            return candidates[0], BoundBy.PERSONA_ONLY_INSTANCE, persona
        if candidates:
            return None, Skip.AMBIGUOUS_TARGET, f"{persona}: {', '.join(candidates)} (use --bind)"
        return None, Skip.NO_TARGET_INSTANCE, persona


def _is_persona_chat(session: Mapping[str, Any]) -> bool:
    return str(session.get("source") or "") == PERSONA_CHAT_SESSION_SOURCE or bool(
        _persisted_persona_instance_id(dict(session)))


def _rebound(session: dict[str, Any], instance_id: str) -> dict[str, Any]:
    """The session with its owning-instance binding rewritten, in the export's own encoding."""
    raw = session.get("model_config")
    config = {**_model_config(raw), "persona_instance_id": instance_id}
    return {**session, "model_config": config if isinstance(raw, dict) else json.dumps(config, sort_keys=True)}


def _parents_first(sessions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """File order, except a child whose parent is in the export follows that parent."""
    by_id = {str(s["id"]): s for s in sessions}
    ordered: list[dict[str, Any]] = []
    placed: set[str] = set()

    def place(session: dict[str, Any], chain: frozenset[str]) -> None:
        sid = str(session["id"])
        if sid in placed:
            return
        parent = str(session.get("parent_session_id") or "")
        if parent in by_id and parent not in chain:
            place(by_id[parent], chain | {sid})
        placed.add(sid)
        ordered.append(session)

    for session in sessions:
        place(session, frozenset())
    return ordered


def _decide(session: dict[str, Any], targets: Targets, binds: Mapping[str, str], db: Any,
            dropped: set[str]) -> Outcome:
    """One session's outcome before any write: lineage, idempotency, then the binding ladder."""
    parent = str(session.get("parent_session_id") or "")
    if parent in dropped:
        return None, Skip.PARENT_SKIPPED, parent
    if db is not None and db.get_session(str(session["id"])) is not None:
        return None, Skip.ALREADY_PRESENT, str(session["id"])
    if _is_persona_chat(session):
        return targets.resolve(session, binds)
    return None, BoundBy.NOT_A_PERSONA_CHAT, str(session.get("source") or "")


def _import_rows(sessions: list[dict[str, Any]], targets: Targets, binds: Mapping[str, str], db: Any,
                 dry_run: bool, skipped: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Import each session through ``SessionDB.import_sessions`` (one door), accounting every skip."""
    imported: list[dict[str, Any]] = []
    dropped: set[str] = set()  # sessions NOT in the target after this run: their children follow them out
    for session in sessions:
        sid = str(session["id"])
        target, how, detail = _decide(session, targets, binds, db, dropped)
        if not dry_run and not isinstance(how, Skip):
            result = db.import_sessions([_rebound(session, target) if target else session])
            if not result.get("ok") or not result.get("imported"):
                how = Skip.REJECTED if not result.get("ok") else Skip.ALREADY_PRESENT
                detail = json.dumps(result.get("errors") or [], sort_keys=True)[:400]
        if isinstance(how, Skip):
            if how is not Skip.ALREADY_PRESENT:
                dropped.add(sid)
            skipped.append({"session_id": sid, "reason": how.value, "detail": detail})
            continue
        imported.append({"session_id": sid, "persona_instance_id": target, "bound_by": how.value})
    return imported, skipped


def import_own_export(path: Path | str, *, binds: Mapping[str, str] | None = None, dry_run: bool = False,
                      session_db: Any = None, instances: list[PersonaInstance] | None = None) -> dict[str, Any]:
    """Import one ``sessions export`` file into this home's chat store; see the module docstring."""
    path = Path(path)
    if not path.is_file():
        raise ImportRefused(Refusal.PATH_MISSING, f"no export file at {path}")
    binds = dict(binds or {})
    targets = Targets(PersonaInstanceStore().list_all() if instances is None else list(instances))
    unknown = sorted({dst for dst in binds.values() if dst not in targets.by_id})
    if unknown:
        raise ImportRefused(Refusal.BIND_TARGET_UNKNOWN, f"--bind names no instance of this home: {unknown}")
    sessions, skipped = read_export(path)
    if not targets.instances and any(_is_persona_chat(s) for s in sessions):
        raise ImportRefused(Refusal.NO_TARGET_INSTANCES,
                            "this home has no persona instance to bind the chats to — open each agent once "
                            "(or create it) in this home, then import; nothing was written")
    db = session_db if session_db is not None else chat_session_scope.open_chat_session_db(
        access=chat_session_scope.SessionDbAccess.READ if dry_run else chat_session_scope.SessionDbAccess.WRITE)
    if db is None and not dry_run:
        raise ImportRefused(Refusal.CHAT_STORE_UNAVAILABLE,
                            f"cannot open {chat_session_scope.chat_session_db_path()} — is the namespace seeded "
                            "and its operator home present?")
    store = str(getattr(db, "db_path", None) or chat_session_scope.chat_session_db_path())
    try:
        imported, skipped = _import_rows(_parents_first(sessions), targets, binds, db, dry_run, skipped)
    finally:
        if session_db is None and db is not None:
            db.close()
    reasons: dict[str, int] = {}
    for row in skipped:
        reasons[row["reason"]] = reasons.get(row["reason"], 0) + 1
    return {
        "ok": True, "verb": "sessions-import", "from": "hermes", "path": str(path), "dry_run": dry_run,
        "target_store": store,
        "counts": {"sessions": len(sessions), "imported": len(imported), "skipped": len(skipped)},
        "skipped_by_reason": dict(sorted(reasons.items())), "imported": imported, "skipped": skipped,
    }


@contextmanager
def _homed_in(item: Layout) -> Iterator[None]:
    """This process's homes pinned inside namespace ``item`` for the body (isolation-checked), then restored."""
    pins = {ENV: item.id, "HERMES_HOME": str(item.home()), "HERMES_HEAD_HOME": str(item.head_home),
            "HERMES_AGENT_RUNTIME_ROOT": str(item.store_root), DEPENDENCY_ENV: str(item.base_root)}
    saved = {key: os.environ.get(key) for key in pins}
    os.environ.update(pins)
    try:
        yield
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def import_into_namespace(ns_id: str, path: Path | str, env: Mapping[str, str], *,
                          binds: Mapping[str, str] | None = None, dry_run: bool = False) -> dict[str, Any]:
    """Import an export into NAMED namespace ``ns_id``. Never ``base``: the source root is never a target."""
    item = existing_namespace(validate_id(ns_id), env)
    source = Path(path).resolve()
    with _homed_in(item):
        report = import_own_export(source, binds=binds, dry_run=dry_run)
    return {**report, "namespace": item.id}


def run_namespace_verb(args: Any, env: Mapping[str, str]) -> dict[str, Any]:
    """``hermes namespace import-sessions <id> <export.jsonl> [--bind SRC=DST …] [--dry-run]``.

    The report, or a typed refusal payload (``ok: false``); a namespace refusal propagates.
    """
    try:
        return import_into_namespace(args.id, args.path, env, binds=parse_binds(args.bind), dry_run=args.dry_run)
    except ImportRefused as exc:
        return exc.payload()
