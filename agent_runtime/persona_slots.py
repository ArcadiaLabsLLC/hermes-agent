"""A persona instance's repo-slot ASSIGNMENT, and the context its turns load from it (build plan §3.3).

The authority is the instance record (``assigned_slots``, ``primary_slot``,
``slots_issued_at``); the launcher's Agent Console edits it through
``runtime.persona.instance.slots.set`` (owner correction 2026-10-04) — the workspace side
declares and fills slots and never assigns agents.

* **A subset, never "all".** Every assigned name is a live slot of the instance's workspace's
  slot document (``slot_not_in_workspace``); empty means NONE. A slot may sit in several
  instances' lists at once (OWNER 2026-10-04 example): ``set`` touches one record, so
  assigning a slot to the frontend agent never takes it from the backend agent. A slot the
  workspace removes is dropped from every assignment in the same write
  (:func:`drop_removed_slots`), and a primary that left is cleared.
* **ONE primary** (OWNER 2026-10-04 full-stack): the default working directory. Unset
  means the first assigned, and :func:`resolve_primary` says which it used —
  ``explicit | first_assigned | none`` — so a default is never mistaken for a choice.
  Instructions load for ALL assigned slots, never only the primary.
* **The context**: for each assigned slot BOUND here, each of the declaration's
  ``context.files`` loads through the per-file loader (128 KB each, no total cap) as its OWN
  section headed by the slot name (``## launcher — CLAUDE.md``). A declaration that names none
  loads ONE file (owner ruling 2026-11-01): ``AGENTS.md`` when it has content of its own, else
  ``CLAUDE.md``, never one that only points at the other (:func:`default_context_choice`); the
  loaded file's receipt carries ``default_choice`` and the other's says why it did not load
  (``not_default``, or ``missing``). Receipts list every assigned slot and every file — an
  unbound slot (``slot_unbound_here``, naming the machines that bind it) and a missing file
  (``missing``) included.
* **The agent's own pick** (RT-SLOT-CONTEXT-FILE-PICKS): an instance may OVERRIDE, per assigned
  slot, which files load — ``CLAUDE.md`` and ``AGENTS.md`` as on/off toggles plus one custom
  ``.md`` (an absolute path, this machine's own). An override outranks the declaration's list and
  the one-file default; every loaded file's receipt carries ``override_choice: slot_override`` and a
  toggled-off one says ``override_off``. No override keeps today's ruling. ``slots.set`` accepts it
  as ``context_files``, ``slots.show`` returns it on each slot row (:func:`context_files_override`).
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
REASON_CONTEXT_FILES_INVALID = "context_files_invalid"

#: The two files an override toggles, in the order their sections load.
OVERRIDE_TOGGLE_FILES: tuple[str, ...] = ("CLAUDE.md", "AGENTS.md")
#: The reason every receipt under an override names.
OVERRIDE_CHOICE = "slot_override"

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
    """A slot an instance of a workspace may be assigned: its name, record and the document it lives in."""

    key: str
    name: str
    record: dict[str, Any]
    document: dict[str, Any]


def visible_slots(workspace_id: str) -> dict[str, VisibleSlot]:
    """Every live slot of the workspace's slot document, by name: what its instances may be assigned."""

    from .workspace_slots import live_slots, load_document

    document = load_document(workspace_id)
    return {name: VisibleSlot(name, name, record, document) for name, record in sorted(live_slots(document).items())}


def _parse_context_files(context_files: Any, slots: list[str]) -> tuple[dict[str, list[str]], dict[str, str]]:
    """``slots.set``'s ``context_files`` → ``(toggles, custom paths)``; refusals are typed.

    ``{<assigned slot>: {"files": [subset of CLAUDE.md / AGENTS.md], "custom_path": abs .md | null} | null}``.
    A slot mapped to ``null`` (or left out) has no override.
    """

    if not isinstance(context_files, dict):
        raise SlotAssignmentRefused(REASON_CONTEXT_FILES_INVALID, "context_files must be an object keyed by slot")
    toggles: dict[str, list[str]] = {}
    custom: dict[str, str] = {}
    for slot, pick in context_files.items():
        if slot not in slots:
            raise SlotAssignmentRefused(REASON_CONTEXT_FILES_INVALID, f"{slot}: not an assigned slot")
        if pick is None:
            continue
        files = pick.get("files") if isinstance(pick, dict) else None
        if not isinstance(files, list) or not all(isinstance(name, str) and name in OVERRIDE_TOGGLE_FILES
                                                  for name in files):
            raise SlotAssignmentRefused(REASON_CONTEXT_FILES_INVALID,
                                        f"{slot}: files must be a subset of {list(OVERRIDE_TOGGLE_FILES)}")
        toggles[slot] = [name for name in OVERRIDE_TOGGLE_FILES if name in files]
        path = pick.get("custom_path")
        if path is None:
            continue
        if not isinstance(path, str) or not Path(path).is_absolute() or not path.lower().endswith(".md"):
            raise SlotAssignmentRefused(REASON_CONTEXT_FILES_INVALID,
                                        f"{slot}: custom_path must be an absolute path to a .md file")
        custom[slot] = path
    return toggles, custom


def context_files_override(instance: Any, slot: str) -> dict[str, Any] | None:
    """``{"files": [...], "custom_path": str | None}`` — the slot's override on this machine, or None (no
    override: the declaration's list, else the one-file default)."""

    toggles = getattr(instance, "slot_context_files", None) or {}
    if slot not in toggles:
        return None
    return {"files": list(toggles[slot]), "custom_path": (getattr(instance, "slot_context_custom", None) or {}).get(slot)}


def set_instance_slots(instance_id: str, slots: Any, primary: Any = None, *, issued_at: str,
                       context_files: Any = None) -> dict[str, Any]:
    """REPLACE one instance's assignment and primary; refusals are typed.

    ``context_files`` (optional) REPLACES the per-slot context override map; omitted, the
    overrides of slots still assigned are kept. Either way an unassigned slot's override leaves.
    """

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
    if context_files is not None:
        toggles, custom = _parse_context_files(context_files, slots)
    else:
        toggles = {k: v for k, v in (instance.slot_context_files or {}).items() if k in slots}
        custom = {k: v for k, v in (instance.slot_context_custom or {}).items() if k in toggles}
    held = instance.slots_issued_at
    if held is not None and issued < held.timestamp():
        raise SlotAssignmentRefused(REASON_STALE_REVISION, "a newer assignment already landed")
    instance.assigned_slots = list(dict.fromkeys(slots))
    instance.primary_slot = primary or None
    instance.slot_context_files = toggles
    instance.slot_context_custom = custom
    instance.slots_issued_at = datetime.fromisoformat(issued_at)
    _store().update(instance)
    return show_instance_slots(instance_id)


def set_instance_recall(instance_id: str, enabled: Any, *, issued_at: str) -> dict[str, Any]:
    """``recall_shared_projects`` on one instance (plan project-slots-and-shared-chats §6), on the slot clock."""

    from .workspace_slots import stamp_epoch

    if not isinstance(enabled, bool):
        raise SlotAssignmentRefused(REASON_INVALID_REQUEST, "enabled must be a boolean")
    issued = stamp_epoch(issued_at)
    if issued is None:
        raise SlotAssignmentRefused(REASON_INVALID_REQUEST, "issued_at must be an ISO-8601 stamp")
    instance = _slot_instance(instance_id)
    if not instance.workspace_id:
        raise SlotAssignmentRefused(REASON_INSTANCE_HAS_NO_WORKSPACE, "the canonical persona channel has no workspace")
    held = instance.slots_issued_at
    if held is not None and issued < held.timestamp():
        raise SlotAssignmentRefused(REASON_STALE_REVISION, "a newer assignment already landed")
    instance.recall_shared_projects = enabled
    instance.slots_issued_at = datetime.fromisoformat(issued_at)
    _store().update(instance)
    return show_instance_slots(instance_id)


def show_instance_slots(instance_id: str) -> dict[str, Any]:
    """``{workspace_id, slots: [{name, slot, bound_here, path, status, context_files}], primary_slot,
    primary_source}`` — ``context_files`` is the slot's override (:func:`context_files_override`, ``null`` =
    today's ruling)."""

    instance = _slot_instance(instance_id)
    declared = visible_slots(instance.workspace_id) if instance.workspace_id else {}
    rows = []
    for name in instance.assigned_slots or []:
        held = declared.get(name)
        path = _bound(held, instance.workspace_id) if held else None
        bound = bool(path and path.is_dir())
        status = "bound" if bound else ("unbound_here" if held else "not_declared")
        rows.append({"name": name, "slot": held.name if held else name, "bound_here": bound,
                     "path": str(path) if bound else None, "status": status,
                     "context_files": context_files_override(instance, name)})
    primary, source = resolve_primary(instance)
    return {"persona_instance_id": instance.id, "workspace_id": instance.workspace_id, "slots": rows,
            "primary_slot": primary, "primary_source": source,
            "recall_shared_projects": bool(getattr(instance, "recall_shared_projects", False))}


def _bound(held: VisibleSlot, workspace_id: str) -> Path | None:
    from .workspace_slots import bound_path

    return bound_path(held.name, workspace_id=workspace_id)


def drop_removed_slots(workspace_id: str, removed: set[str] | frozenset[str]) -> list[str]:
    """Drop ``removed`` slot keys from every instance of ``workspace_id``; returns the ids touched."""

    return _drop_where(lambda instance: instance.workspace_id == workspace_id, lambda key: key in removed)


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
            slot_context_files={k: v for k, v in (instance.slot_context_files or {}).items() if not drops(k)},
            slot_context_custom={k: v for k, v in (instance.slot_context_custom or {}).items() if not drops(k)},
        )
        touched.append(instance.id)
    return touched


def rekey_project_assignments(project_id: str, home: str | None, rename: dict[str, str]) -> list[str]:
    """The workspace merge's instance step (RT-WS-ABSORB-MIGRATION): ``<project>/<slot>`` keys become bare.

    In the Project's home workspace a key takes its (renamed) slot name; in any other workspace, or for a
    slot that did not move, it is dropped — the Project is no longer seen there. ``slots_issued_at`` stamped.
    """

    prefix = f"{project_id}/"
    store = _store()
    touched = []
    stamp = datetime.now().astimezone()
    for instance in store.list_all():
        keys = list(instance.assigned_slots or [])
        owned = [key for key in (*keys, instance.primary_slot or "", *(instance.slot_context_files or {}),
                                 *(instance.slot_context_custom or {})) if key.startswith(prefix)]
        if not owned:
            continue

        def moved(key: str) -> str | None:
            if not key.startswith(prefix):
                return key
            return rename.get(key[len(prefix):]) if home is not None and instance.workspace_id == home else None

        store.patch_fields(
            instance.id,
            assigned_slots=list(dict.fromkeys(key for key in map(moved, keys) if key)),
            primary_slot=moved(instance.primary_slot) if instance.primary_slot else instance.primary_slot,
            slot_context_files={moved(k): v for k, v in (instance.slot_context_files or {}).items() if moved(k)},
            slot_context_custom={moved(k): v for k, v in (instance.slot_context_custom or {}).items() if moved(k)},
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


def sections_text(sections: Any) -> str:
    """Sections as the system message carries them: each under its heading, blank-line separated."""

    return "\n\n".join(f"{section.heading}\n\n{section.content.strip()}" for section in sections)


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
    @property
    def bindings(self) -> tuple[Any, ...]:
        """The bound assigned slots as overlay bindings (the turn's env scope, §3.3)."""

        from .workspace_slot_overlay import SlotBinding

        return tuple(SlotBinding(self.workspace_id, slot, path) for slot, path in self.bound)

    @property
    def content(self) -> str:
        return sections_text(self.sections)

    @property
    def dedup_receipt(self) -> dict[str, Any] | None:
        """``{"against": cwd, "dropped": [[slot, file], ...]}``, or None when no dedup ran."""

        if self.dedup_against is None:
            return None
        return {"against": self.dedup_against, "dropped": [list(item) for item in self.dedup_dropped]}


#: A file at most this big that names the other file is a POINTER to it, not content of its own
#: (Eternia's 2 KB ``AGENTS.md`` reads "CLAUDE.md … is the single canonical agent-context file").
POINTER_MAX_BYTES = 4096

DEFAULT_AGENTS_HAS_OWN_CONTENT = "agents_md_has_own_content"
DEFAULT_AGENTS_POINTS_AT_CLAUDE = "agents_md_points_at_claude_md"
DEFAULT_AGENTS_ABSENT = "agents_md_missing_or_empty"
DEFAULT_CLAUDE_ABSENT = "claude_md_missing_or_empty"


def points_at(content: str, other: str) -> bool:
    """Whether ``content`` is only a pointer at the file named ``other``: short, and naming it."""

    return len(content.encode("utf-8")) <= POINTER_MAX_BYTES and other.lower() in content.lower()


def default_context_choice(agents: str | None, claude: str | None) -> tuple[str | None, str]:
    """``(file to load, reason)`` for a slot whose declaration names no ``context.files``.

    ``agents`` / ``claude`` are the files' contents (None or blank when absent). Pure, so the rule
    is pinned without a checkout (RT-SLOT-ONE-CONTEXT-FILE-DEFAULT).
    """

    agents = agents if agents and agents.strip() else None
    claude = claude if claude and claude.strip() else None
    if agents is not None and not points_at(agents, "CLAUDE.md"):
        return "AGENTS.md", DEFAULT_AGENTS_HAS_OWN_CONTENT
    if claude is not None:
        return "CLAUDE.md", DEFAULT_AGENTS_POINTS_AT_CLAUDE if agents is not None else DEFAULT_AGENTS_ABSENT
    if agents is not None:
        return "AGENTS.md", DEFAULT_CLAUDE_ABSENT
    return None, DEFAULT_AGENTS_ABSENT


def _default_file_receipts(slot: str, path: Path, load: Any) -> tuple[list[dict[str, Any]], list[SlotContextSection]]:
    """The one-file default for one bound slot: the chosen file loaded, the other one's receipt saying why not."""

    loaded = {"AGENTS.md": load(str(path / "AGENTS.md"), allowed_names=None)}
    agents = getattr(loaded["AGENTS.md"], "content", None)
    if not agents or points_at(agents, "CLAUDE.md"):
        loaded["CLAUDE.md"] = load(str(path / "CLAUDE.md"), allowed_names=None)
    chosen, reason = default_context_choice(agents, getattr(loaded.get("CLAUDE.md"), "content", None))
    receipts: list[dict[str, Any]] = []
    sections: list[SlotContextSection] = []
    for file in ("CLAUDE.md", "AGENTS.md"):
        if file == chosen:
            receipts.append(_file_receipt(slot, file, loaded[file]) | {"default_choice": reason})
            sections.append(SlotContextSection(slot, file, loaded[file].content))
            continue
        here = (path / file).is_file()
        receipts.append({"slot": slot, "file": file, "label": f"{slot}/{file}", "kind": "workspace_context",
                         "included": False, "status": "not_default" if here else "missing", "evidence": reason})
    return receipts, sections


def _override_file_receipts(slot: str, path: Path, override: dict[str, Any],
                            load: Any) -> tuple[list[dict[str, Any]], list[SlotContextSection]]:
    """The agent's own pick for one bound slot: each toggled-on file and the custom ``.md`` loaded, each
    toggled-off file's receipt saying so; every receipt names the override as its reason."""

    receipts: list[dict[str, Any]] = []
    sections: list[SlotContextSection] = []
    on = override.get("files") or []
    for file in OVERRIDE_TOGGLE_FILES:
        if file not in on:
            receipts.append({"slot": slot, "file": file, "label": f"{slot}/{file}", "kind": "workspace_context",
                             "included": False, "status": "override_off", "evidence": OVERRIDE_CHOICE})
            continue
        loaded = load(str(path / file), allowed_names=None)
        receipts.append(_file_receipt(slot, file, loaded) | {"override_choice": OVERRIDE_CHOICE})
        if getattr(loaded, "content", None):
            sections.append(SlotContextSection(slot, file, loaded.content))
    custom = override.get("custom_path")
    if custom:
        file = Path(custom).name
        loaded = load(custom, allowed_names=None)
        receipts.append(_file_receipt(slot, file, loaded) | {"override_choice": OVERRIDE_CHOICE, "custom_path": custom})
        if getattr(loaded, "content", None):
            sections.append(SlotContextSection(slot, file, loaded.content))
    return receipts, sections


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


@dataclass(frozen=True)
class CategoryContext:
    """The workspace's listed documents and shared guidance for one turn (its ``documents`` and
    ``guidance`` categories, ``workspace_categories.category_context``).

    Its own turn-context field, beside the slot context: it reaches every instance of the workspace —
    assigned or not — and never supersedes the ``--agents-file`` alias.
    """

    sections: tuple[SlotContextSection, ...] = ()
    receipts: tuple[dict[str, Any], ...] = ()

    @property
    def content(self) -> str:
        return sections_text(self.sections)


def load_category_context(instance: Any) -> CategoryContext | None:
    """The instance's workspace's category context, or None when the workspace has nothing to offer."""

    from .workspace_categories import category_context

    workspace_id = getattr(instance, "workspace_id", None)
    if not workspace_id:
        return None
    sections, receipts = category_context(workspace_id)
    if not sections and not receipts:
        return None
    return CategoryContext(tuple(SlotContextSection(slot, file, content) for slot, file, content in sections),
                          tuple(receipts))


def load_slot_context(instance: Any) -> SlotContext | None:
    """The turn's slot context, or None when the instance has no assignment (EMPTY ⇒ nothing, never all)."""

    from .prompt_observability.workspace_agents import load_workspace_agents_context

    assigned = list(getattr(instance, "assigned_slots", None) or [])
    workspace_id = getattr(instance, "workspace_id", None)
    if not assigned or not workspace_id:
        return None
    declared = visible_slots(workspace_id)
    sections: list[SlotContextSection] = []
    receipts: list[dict[str, Any]] = []
    bound: list[tuple[str, str]] = []
    for slot in assigned:
        held = declared.get(slot)
        path = _bound(held, workspace_id) if held else None
        if path is None or not path.is_dir():
            receipts.append(_unbound_receipt(held.name, held.document) | {"slot": slot, "label": slot} if held else
                            {"slot": slot, "label": slot, "kind": "workspace_context", "included": False,
                             "status": "slot_not_declared"})
            continue
        bound.append((slot, str(path)))
        override = context_files_override(instance, slot)
        if override is not None:
            override_receipts, override_sections = _override_file_receipts(
                slot, Path(path), override, load_workspace_agents_context)
            receipts.extend(override_receipts)
            sections.extend(override_sections)
            continue
        files = (held.record.get("context") or {}).get("files")
        if not files:
            default_receipts, default_sections = _default_file_receipts(slot, Path(path), load_workspace_agents_context)
            receipts.extend(default_receipts)
            sections.extend(default_sections)
            continue
        for file in files:
            loaded = load_workspace_agents_context(str(Path(path) / file), allowed_names=None)
            receipts.append(_file_receipt(slot, file, loaded))
            if getattr(loaded, "content", None):
                sections.append(SlotContextSection(slot, file, loaded.content))
    primary, source = resolve_primary(instance)
    primary_path = dict(bound).get(primary) if primary else None
    return SlotContext(tuple(sections), tuple(receipts), primary, source, primary_path, tuple(bound), workspace_id)


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
