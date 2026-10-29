"""A persona instance's repo-slot ASSIGNMENT, and the context its turns load from it (build plan §3.3).

The authority is the instance record (``assigned_slots``, ``primary_slot``,
``slots_issued_at``); the launcher's Agent Console edits it through
``runtime.persona.instance.slots.set`` (owner correction 2026-10-04) — the workspace side
declares and fills slots and never assigns agents.

* **A subset, never "all".** Every assigned name is a live slot the instance's workspace
  sees (``slot_not_in_workspace``); empty means NONE. A slot a Project declares is assigned as
  ``<project>/<slot>`` (plan project-slots-and-shared-chats §3) and is visible only while the
  workspace holds that Project in ``project_ids``; a bare name is a slot of the workspace's own,
  not-yet-migrated document. Disconnecting a Project drops ``<project>/*`` from every instance of
  that workspace in the same write (:func:`drop_project_slots`). A slot may sit in several
  instances' lists at once (OWNER 2026-10-04 example): ``set`` touches one record, so
  assigning a slot to the frontend agent never takes it from the backend agent. A slot the
  workspace removes is dropped from every assignment in the same write
  (:func:`drop_removed_slots`), and a primary that left is cleared.
* **ONE primary** (OWNER 2026-10-04 full-stack): the default working directory. Unset
  means the first assigned, and :func:`resolve_primary` says which it used —
  ``explicit | first_assigned | none`` — so a default is never mistaken for a choice.
  Instructions load for ALL assigned slots, never only the primary.
* **The context**: for each assigned slot BOUND here, each of the declaration's
  ``context.files`` (default ``CLAUDE.md`` AND ``AGENTS.md``) loads through the per-file
  loader (128 KB each, no total cap) as its OWN section headed by the slot name
  (``## launcher — CLAUDE.md``). Receipts list every assigned slot and every file —
  an unbound slot (``slot_unbound_here``, naming the machines that bind it) and a missing
  file (``missing``) included.
* **Not twice** (D1.12): when the persona opts into core context files and the turn is
  grounded, upstream's prompt builder injects the cwd chain's ``AGENTS.md`` / ``CLAUDE.md``
  for the workdir itself. A slot section whose content that chain carries WHOLE is dropped
  (:func:`slot_context_for_prompt`); every other section is kept, and the receipt names
  what was dropped and against which cwd.
"""

from __future__ import annotations

import functools
import logging
from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path
from typing import Any

__layer__ = "stores"

logger = logging.getLogger(__name__)

REASON_SLOT_NOT_IN_WORKSPACE = "slot_not_in_workspace"
REASON_PRIMARY_NOT_ASSIGNED = "primary_not_assigned"
REASON_INSTANCE_HAS_NO_WORKSPACE = "instance_has_no_workspace"
REASON_INSTANCE_NOT_FOUND = "instance_not_found"
REASON_STALE_REVISION = "stale_revision"
REASON_INVALID_REQUEST = "invalid_request"

PRIMARY_SOURCE_EXPLICIT = "explicit"
PRIMARY_SOURCE_FIRST_ASSIGNED = "first_assigned"
PRIMARY_SOURCE_NONE = "none"

#: The receipt the one-release ``--agents-file`` alias gets under an assignment (call 4e).
SUPERSEDED_BY_ASSIGNMENT = "superseded_by_assignment"


class SlotAssignmentRefused(ValueError):
    def __init__(self, reason: str, detail: str = "") -> None:
        super().__init__(detail or reason)
        self.reason = reason
        self.detail = detail


def resolve_primary(instance: Any) -> tuple[str | None, str]:
    """``(primary slot, primary_source)`` for an instance record."""

    assigned = list(getattr(instance, "assigned_slots", None) or [])
    primary = getattr(instance, "primary_slot", None)
    if primary and primary in assigned:
        return primary, PRIMARY_SOURCE_EXPLICIT
    if assigned:
        return assigned[0], PRIMARY_SOURCE_FIRST_ASSIGNED
    return None, PRIMARY_SOURCE_NONE


def _store():
    from .persona_assignments import PersonaInstanceStore

    return PersonaInstanceStore()


def _slot_instance(instance_id: str):
    try:
        return _store().get(instance_id)
    except (FileNotFoundError, KeyError) as exc:
        raise SlotAssignmentRefused(REASON_INSTANCE_NOT_FOUND, instance_id) from exc


@dataclass(frozen=True)
class VisibleSlot:
    """A slot an instance of a workspace may be assigned: its key, owner, record and the document it lives in."""

    key: str
    name: str
    project_id: str | None
    record: dict[str, Any]
    document: dict[str, Any]


def visible_slots(workspace_id: str) -> dict[str, VisibleSlot]:
    """Every live slot a workspace's instances may be assigned, by key (``<project>/<slot>`` or a bare name)."""

    from .project_store import load_project
    from .workspace_slots import live_slots, load_document, slot_key, slots_of_workspace

    documents: dict[str | None, dict[str, Any]] = {}
    out: dict[str, VisibleSlot] = {}
    for project_id, name in slots_of_workspace(workspace_id):
        if project_id not in documents:
            documents[project_id] = load_project(project_id) if project_id else load_document(workspace_id)
        document = documents[project_id]
        key = slot_key(project_id, name)
        out[key] = VisibleSlot(key, name, project_id, live_slots(document)[name], document)
    return out


def set_instance_slots(instance_id: str, slots: Any, primary: Any = None, *, issued_at: str) -> dict[str, Any]:
    """REPLACE one instance's assignment and primary; refusals are typed."""

    from .workspace_slots import stamp_epoch

    if not isinstance(slots, list) or not all(isinstance(name, str) and name for name in slots):
        raise SlotAssignmentRefused(REASON_INVALID_REQUEST, "slots must be a list of slot names")
    issued = stamp_epoch(issued_at)
    if issued is None:
        raise SlotAssignmentRefused(REASON_INVALID_REQUEST, "issued_at must be an ISO-8601 stamp")
    instance = _slot_instance(instance_id)
    if not instance.workspace_id:
        raise SlotAssignmentRefused(REASON_INSTANCE_HAS_NO_WORKSPACE, "the canonical persona channel has no assignment")
    declared = visible_slots(instance.workspace_id)
    unknown = [name for name in slots if name not in declared]
    if unknown:
        raise SlotAssignmentRefused(REASON_SLOT_NOT_IN_WORKSPACE, ", ".join(unknown))
    if primary is not None and primary not in slots:
        raise SlotAssignmentRefused(REASON_PRIMARY_NOT_ASSIGNED, str(primary))
    held = instance.slots_issued_at
    if held is not None and issued < held.timestamp():
        raise SlotAssignmentRefused(REASON_STALE_REVISION, "a newer assignment already landed")
    instance.assigned_slots = list(dict.fromkeys(slots))
    instance.primary_slot = primary or None
    instance.slots_issued_at = datetime.fromisoformat(issued_at)
    _store().update(instance)
    return show_instance_slots(instance_id)


def show_instance_slots(instance_id: str) -> dict[str, Any]:
    """``{workspace_id, slots: [{name, project_id, slot, bound_here, path, status}], projects, primary_slot,
    primary_source}`` — ``projects`` groups the assigned keys by the Project that declares them
    (``null`` for the workspace's own document)."""

    instance = _slot_instance(instance_id)
    declared = visible_slots(instance.workspace_id) if instance.workspace_id else {}
    rows = []
    projects: dict[str, list[str]] = {}
    for name in instance.assigned_slots or []:
        held = declared.get(name)
        path = _bound(held, instance.workspace_id) if held else None
        bound = bool(path and path.is_dir())
        status = "bound" if bound else ("unbound_here" if held else "not_declared")
        rows.append({"name": name, "project_id": held.project_id if held else None,
                     "slot": held.name if held else name, "bound_here": bound,
                     "path": str(path) if bound else None, "status": status})
        projects.setdefault(held.project_id if held and held.project_id else "", []).append(name)
    primary, source = resolve_primary(instance)
    return {"persona_instance_id": instance.id, "workspace_id": instance.workspace_id, "slots": rows,
            "projects": [{"project_id": pid or None, "slots": keys} for pid, keys in projects.items()],
            "primary_slot": primary, "primary_source": source}


def _bound(held: VisibleSlot, workspace_id: str) -> Path | None:
    from .workspace_slots import bound_path

    if held.project_id:
        return bound_path(held.name, project_id=held.project_id)
    return bound_path(held.name, workspace_id=workspace_id)


def drop_removed_slots(workspace_id: str, removed: set[str] | frozenset[str]) -> list[str]:
    """Drop ``removed`` slot keys from every instance of ``workspace_id``; returns the ids touched."""

    return _drop_where(lambda instance: instance.workspace_id == workspace_id, lambda key: key in removed)


def drop_project_slots(project_id: str, *, workspace_id: str | None = None,
                       removed: set[str] | frozenset[str] | None = None) -> list[str]:
    """Drop ``<project>/*`` (or only ``<project>/<removed>``) from every instance of ``workspace_id``
    (every workspace when ``None``); the ids touched. A Project's disconnect and a Project slot's
    tombstone both leave every assignment in the same write."""

    prefix = f"{project_id}/"
    return _drop_where(
        lambda instance: workspace_id is None or instance.workspace_id == workspace_id,
        lambda key: key.startswith(prefix) and (removed is None or key[len(prefix):] in removed))


def _drop_where(owns, drops) -> list[str]:
    store = _store()
    touched = []
    for instance in store.list_all():
        keys = list(instance.assigned_slots or [])
        if not owns(instance) or not any(drops(key) for key in keys):
            continue
        store.patch_fields(
            instance.id,
            assigned_slots=[key for key in keys if not drops(key)],
            primary_slot=None if instance.primary_slot and drops(instance.primary_slot) else instance.primary_slot,
        )
        touched.append(instance.id)
    return touched


def rekey_workspace_assignments(workspace_id: str, project_id: str, names: set[str] | frozenset[str]) -> list[str]:
    """The slot migration's step 3 (plan §4): bare names of a migrated document become ``<project>/<slot>``.

    Set-to-value per instance (a key already re-keyed is left as it is), ``slots_issued_at`` stamped.
    """

    store = _store()
    touched = []
    stamp = datetime.now().astimezone()
    for instance in store.list_all():
        keys = list(instance.assigned_slots or [])
        if instance.workspace_id != workspace_id or not any(key in names for key in keys):
            continue
        store.patch_fields(
            instance.id,
            assigned_slots=list(dict.fromkeys(f"{project_id}/{key}" if key in names else key for key in keys)),
            primary_slot=(f"{project_id}/{instance.primary_slot}" if instance.primary_slot in names
                          else instance.primary_slot),
            slots_issued_at=stamp,
        )
        touched.append(instance.id)
    return touched


# ── the context a turn loads ─────────────────────────────────────────────────


@dataclass(frozen=True)
class SlotContextSection:
    slot: str
    file: str
    content: str

    @property
    def heading(self) -> str:
        return f"## {self.slot} — {self.file}"


@dataclass(frozen=True)
class SlotContext:
    """The assigned slots' context for one turn: sections, receipts, and the primary."""

    sections: tuple[SlotContextSection, ...] = ()
    receipts: tuple[dict[str, Any], ...] = ()
    primary_slot: str | None = None
    primary_source: str = PRIMARY_SOURCE_NONE
    primary_path: str | None = None
    bound: tuple[tuple[str, str], ...] = field(default_factory=tuple)
    workspace_id: str = ""
    #: The cwd the sections were deduplicated against (D1.12), or None when no dedup ran.
    dedup_against: str | None = None
    #: ``(slot, file)`` of every section dropped because the cwd chain carries it whole.
    dedup_dropped: tuple[tuple[str, str], ...] = ()
    #: ``(assigned key, (slot name, project id | None))`` for each bound slot (a Project's slot keys as
    #: ``<project>/<slot>``; its env overlay reads the Project's fill and declaration).
    owners: tuple[tuple[str, tuple[str, str | None]], ...] = ()

    @property
    def bindings(self) -> tuple[Any, ...]:
        """The bound assigned slots as overlay bindings (the turn's env scope, §3.3)."""

        from .workspace_slot_overlay import SlotBinding

        owned = dict(self.owners)
        bindings = []
        for slot, path in self.bound:
            name, project_id = owned.get(slot, (slot, None))
            bindings.append(SlotBinding(self.workspace_id, name, path, project_id))
        return tuple(bindings)

    @property
    def content(self) -> str:
        return "\n\n".join(f"{section.heading}\n\n{section.content.strip()}" for section in self.sections)

    @property
    def dedup_receipt(self) -> dict[str, Any] | None:
        """``{"against": cwd, "dropped": [[slot, file], ...]}``, or None when no dedup ran."""

        if self.dedup_against is None:
            return None
        return {"against": self.dedup_against, "dropped": [list(item) for item in self.dedup_dropped]}


def _file_receipt(slot: str, file: str, loaded: Any) -> dict[str, Any]:
    receipt = dict(getattr(loaded, "receipt", None) or {})
    receipt.pop("preview", None)
    receipt.update(slot=slot, file=file, label=f"{slot}/{file}", kind="workspace_context")
    return receipt


def _unbound_receipt(slot: str, document: dict[str, Any]) -> dict[str, Any]:
    from .workspace_slots import binding_machines

    machines = binding_machines(document, slot)
    return {"slot": slot, "label": slot, "kind": "workspace_context", "included": False, "status": "slot_unbound_here",
            "evidence": "bound on " + (", ".join(machines) if machines else "no reporting machine")}


def load_slot_context(instance: Any) -> SlotContext | None:
    """The turn's slot context, or None when the instance has no assignment (EMPTY ⇒ nothing, never all)."""

    from .prompt_observability.workspace_agents import load_workspace_agents_context
    from .workspace_slots import DEFAULT_CONTEXT_FILES

    assigned = list(getattr(instance, "assigned_slots", None) or [])
    workspace_id = getattr(instance, "workspace_id", None)
    if not assigned or not workspace_id:
        return None
    declared = visible_slots(workspace_id)
    sections: list[SlotContextSection] = []
    receipts: list[dict[str, Any]] = []
    bound: list[tuple[str, str]] = []
    owners: dict[str, tuple[str, str | None]] = {}
    for slot in assigned:
        held = declared.get(slot)
        path = _bound(held, workspace_id) if held else None
        if path is None or not path.is_dir():
            receipts.append(_unbound_receipt(held.name, held.document) | {"slot": slot, "label": slot} if held else
                            {"slot": slot, "label": slot, "kind": "workspace_context", "included": False,
                             "status": "slot_not_declared"})
            continue
        bound.append((slot, str(path)))
        owners[slot] = (held.name, held.project_id)
        files = (held.record.get("context") or {}).get("files") or list(DEFAULT_CONTEXT_FILES)
        for file in files:
            loaded = load_workspace_agents_context(str(Path(path) / file), allowed_names=None)
            receipts.append(_file_receipt(slot, file, loaded))
            if getattr(loaded, "content", None):
                sections.append(SlotContextSection(slot, file, loaded.content))
    # The workspace's Projects' documents (listed files only) and shared guidance (plan §7, H-P4).
    from .project_categories import project_context

    project_sections, project_receipts = project_context(workspace_id)
    sections.extend(SlotContextSection(slot, file, content) for slot, file, content in project_sections)
    receipts.extend(project_receipts)
    primary, source = resolve_primary(instance)
    primary_path = dict(bound).get(primary) if primary else None
    return SlotContext(tuple(sections), tuple(receipts), primary, source, primary_path, tuple(bound), workspace_id,
                       owners=tuple(sorted(owners.items())))


# ── not twice: the slot sections against the prompt builder's cwd chain (D1.12) ──

#: The context-file kinds upstream renders VERBATIM; ``.hermes.md`` is rendered with its YAML
#: frontmatter stripped, so equal raw content is not equal prompt text and never matches.
_VERBATIM_KINDS = frozenset({"agents_md", "claude_md", "cursorrules"})


def _comparable(text: str) -> str:
    """The text as upstream's ``_read_context_file`` yields it: no BOM, universal newlines, stripped.

    The slot loader decodes raw bytes, so a CRLF checkout's section would otherwise never equal
    the chain's copy of the same file."""

    return text.lstrip("\ufeff").replace("\r\n", "\n").replace("\r", "\n").strip()


@functools.lru_cache(maxsize=16)
def _scan_blocks(content: str) -> bool:
    """Whether upstream's context-scope injection scan BLOCKS ``content``.

    A pure function of the text (module-constant patterns), memoised because the scan costs
    ~14 ms per turn over two ~12 KB files and a slot's files rarely change between turns."""

    from tools.threat_patterns import scan_for_threats

    return bool(scan_for_threats(content, scope="context"))


def _chain_carries_whole(cwd: Path) -> frozenset[str]:
    """The contents the prompt builder's context-files block carries WHOLE for ``cwd``.

    From upstream's public finder (one discovery walk, the builder's own): non-empty, rendered
    verbatim, clean of the injection scan (a hit is replaced by a BLOCKED marker), and inside
    the context-file cap's floor — per file, and for the merged ``AGENTS.md`` directory chain,
    which the builder caps again. Over the floor a larger model's cap may still carry it, but
    the guard keeps the section rather than bet on the window.
    """

    from agent.prompt_builder import CONTEXT_FILE_MAX_CHARS, discover_context_files

    found = [(kind, label, _comparable(content)) for kind, label, _path, content in discover_context_files(cwd)
             if content and kind in _VERBATIM_KINDS]
    rendered = {content: len(f"## {label}\n\n{content}") for _kind, label, content in reversed(found)}
    agents = list(dict.fromkeys(content for kind, _label, content in found if kind == "agents_md"))
    agents_chain = sum(rendered[content] for content in agents) + 2 * max(len(agents) - 1, 0)
    return frozenset(
        content for kind, _label, content in found
        if rendered[content] <= CONTEXT_FILE_MAX_CHARS
        and not (kind == "agents_md" and agents_chain > CONTEXT_FILE_MAX_CHARS)
        and not _scan_blocks(content)
    )


def dedup_against_chain(
    sections: tuple[SlotContextSection, ...], *, cwd: str
) -> tuple[tuple[SlotContextSection, ...], tuple[SlotContextSection, ...]]:
    """``(kept, dropped)``: a section is dropped when the cwd chain carries its content whole.

    Pure and never raises: a finder fault keeps every section (the prompt may carry a file
    twice, never lose one)."""

    try:
        carried = _chain_carries_whole(Path(cwd))
    except Exception:  # a context-file fault never fails a turn, nor drops a section
        logger.debug("slot context dedup: the cwd chain could not be read for %s", cwd, exc_info=True)
        return tuple(sections), ()
    dropped = tuple(section for section in sections if _comparable(section.content) in carried)
    return tuple(section for section in sections if section not in dropped), dropped


def slot_context_for_prompt(slot_context: SlotContext | None, *, persona: Any, workdir: Any) -> SlotContext | None:
    """The slot context as the turn's PROMPT carries it (D1.12).

    Dedup runs ONLY when the persona opts into core context files (else the builder injects no
    chain) AND the workdir is grounded (an ungrounded run's cwd is the process cwd, where the
    builder's install-tree guard decides — the fork does not second-guess it)."""

    if slot_context is None or not bool(getattr(persona, "include_core_context_files", False)):
        return slot_context
    if workdir is None or not getattr(workdir, "grounded", False) or not getattr(workdir, "path", None):
        return slot_context
    kept, dropped = dedup_against_chain(slot_context.sections, cwd=str(workdir.path))
    return replace(slot_context, sections=kept, dedup_against=str(workdir.path),
                   dedup_dropped=tuple((section.slot, section.file) for section in dropped))
