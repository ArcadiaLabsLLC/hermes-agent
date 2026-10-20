"""The seed's persona-instance carry: hired and canonical instances, REBASED (row RT-NAMESPACE-SEED-HIRED-INSTANCES).

Owner ruling 2026-10-19: "fix the seed (carry hired instances, rebased)". The office a seed copies
places hired instances (``personainst_<persona>_agent_<hex>``); without their records every placed
agent read "Not linked here", because boot re-mints only the canonical instance of each persona.

A record never seeds AS-IS. Each ``agent-runtime/persona_instances/*.json`` that decodes as a
:class:`~agent_runtime.models.PersonaInstance` (the model's own decoder, ``serde.from_jsonable``)
is carried with:

* **rebased** — every string value that names the source root (``runtime_root``,
  ``chat_head_home``, any other) re-rooted under the namespace root, keeping its relative tail.
  The match is per path segment and case-insensitive (Windows paths are);
* **cleared** — :data:`CLEARED` reset to the model's own defaults, ``state`` to ``idle``: the
  session pointers, the skill hash, the live run/assignment/task/goal bindings, the heartbeat;
* **kept** — every other field (model, provider, api_mode, reasoning, realm, workspace, slots,
  display name, persona, profile, role, mode, spawned_by, steering).

A carried value that STILL names the source root after the rebase (a path inside a sentence, say)
refuses the whole seed typed (``namespace_instance_not_rebased``) before anything is copied.
The aliases registry (``persona_instance_aliases.json``) is carried through the same rebase,
because ``PersonaInstanceStore.get`` resolves a legacy id only through it. A record the target
already holds stays the target's. The plan also reads the source office (``read_actor_dir``,
``actor_bound_instance_id`` — the readers ``office_placement_evidence`` uses) and lists each
live placement as resolved or "placed but no source instance".
"""

from __future__ import annotations

import json
import re
from dataclasses import MISSING, dataclass, fields
from pathlib import Path
from typing import Any

from hermes_cli._namespace_bootstrap import STORE_DIRNAME, Layout, NamespaceRefused, Reason
from utils import atomic_json_write

from ..models import PersonaInstance, looks_like_persona_instance_id
from ..office_store.files import read_actor_dir
from ..paths import safe_path_token
from ..persona_instance_identity import actor_bound_instance_id
from ..serde import from_jsonable, to_jsonable
from ..states import WorkerSessionState

__layer__ = "lanes"

INSTANCES_DIRNAME = "persona_instances"
ALIASES_NAME = "persona_instance_aliases.json"
#: Store entries this step plans (the store-level allowlist walk leaves them to it).
HANDLED = frozenset({INSTANCES_DIRNAME, ALIASES_NAME})
#: Fields a carried record is born without: reset to the model's default (``state``: idle).
CLEARED = ("session_id", "default_chat_session_id", "skill_manifest_hash", "active_run_id",
           "current_assignment_id", "current_task_id", "current_chat_goal", "goal_id", "last_heartbeat_at",
           "returned_to", "token_budget_used", "state")
#: Placement accounting labels.
PLACED_NO_SOURCE = "placed but no source instance"
UNPARSEABLE = "not a persona-instance record"
TARGET_HOLDS = "target holds this id (the target wins)"


def _parts(text: str) -> list[str]:
    return [part for part in re.split(r"[\\/]+", text) if part]


@dataclass(frozen=True, slots=True)
class Rebase:
    """Re-roots a string that names ``source`` under ``target``; says whether a string still names it."""

    source: Path
    target: Path

    def value(self, text: str) -> tuple[str, str | None]:
        """``(new value, the tail checked for leftovers)``; an unrooted value comes back unchanged, tail ``None``."""
        src, parts = [p.casefold() for p in _parts(str(self.source))], _parts(text)
        if len(parts) < len(src) or [p.casefold() for p in parts[:len(src)]] != src:
            return text, None
        tail = parts[len(src):]
        return str(self.target.joinpath(*tail)), "/".join(tail)

    def names_source(self, text: str) -> bool:
        root = "/".join(p.casefold() for p in _parts(str(self.source)))
        return re.search(re.escape(root) + r"(?![\w.-])", "/".join(_parts(text.casefold()))) is not None


def _rebase_tree(value: Any, rebase: Rebase, path: str, rebased: dict[str, str], leftovers: list[str]) -> Any:
    if isinstance(value, str):
        new, tail = rebase.value(value)
        if tail is not None:
            rebased[path] = new
        if rebase.names_source(value if tail is None else tail):
            leftovers.append(path)
        return new
    if isinstance(value, list):
        return [_rebase_tree(item, rebase, f"{path}[{i}]", rebased, leftovers) for i, item in enumerate(value)]
    if isinstance(value, dict):
        return {key: _rebase_tree(item, rebase, f"{path}.{key}" if path else str(key), rebased, leftovers)
                for key, item in value.items()}
    return value


def _cleared_defaults() -> dict[str, Any]:
    out: dict[str, Any] = {"state": WorkerSessionState.IDLE}
    for item in fields(PersonaInstance):
        if item.name in CLEARED and item.name != "state":
            out[item.name] = item.default if item.default is not MISSING else item.default_factory()  # type: ignore[misc]
    return out


def _decode(path: Path) -> PersonaInstance | None:
    """The record at ``path`` through the model's decoder, or ``None`` when it is not one (or is misfiled)."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        record = from_jsonable(PersonaInstance, raw) if isinstance(raw, dict) else None
    except (OSError, ValueError, TypeError, KeyError):
        return None
    if record is None or not looks_like_persona_instance_id(record.id):
        return None
    return record if f"{safe_path_token(record.id)}.json" == path.name else None


@dataclass(frozen=True, slots=True)
class CarriedInstance:
    id: str
    source: Path
    destination: Path
    body: dict[str, Any]
    rebased: dict[str, str]
    cleared: tuple[str, ...]

    def row(self) -> dict[str, Any]:
        return {"id": self.id, "path": f"{STORE_DIRNAME}/{INSTANCES_DIRNAME}/{self.source.name}",
                "rebased": self.rebased, "cleared": list(self.cleared)}


@dataclass(frozen=True, slots=True)
class InstancePlan:
    carried: tuple[CarriedInstance, ...]
    skipped: tuple[dict[str, str], ...]
    aliases: tuple[Path, Path, dict[str, Any]] | None
    resolved: tuple[str, ...]
    orphaned: tuple[str, ...]

    def payload(self) -> dict[str, Any]:
        return {"carried": [item.row() for item in self.carried], "skipped": list(self.skipped),
                "aliases": f"{STORE_DIRNAME}/{ALIASES_NAME}" if self.aliases else None,
                "placements": {"resolved": list(self.resolved),
                               "orphaned": [{"id": i, "reason": PLACED_NO_SOURCE} for i in self.orphaned]}}


def _refuse_leftovers(label: str, leftovers: list[str], rebase: Rebase) -> None:
    if leftovers:
        raise NamespaceRefused(Reason.INSTANCE_NOT_REBASED,
                               f"{label} still names the source root {rebase.source} in {sorted(leftovers)} "
                               "after the rebase; nothing copied")


def _carry(path: Path, record: PersonaInstance, rebase: Rebase, destination: Path) -> CarriedInstance:
    cleared = _cleared_defaults()
    body = {**to_jsonable(record), **to_jsonable(cleared)}
    rebased: dict[str, str] = {}
    leftovers: list[str] = []
    body = _rebase_tree(body, rebase, "", rebased, leftovers)
    _refuse_leftovers(f"{STORE_DIRNAME}/{INSTANCES_DIRNAME}/{path.name}", leftovers, rebase)
    body = to_jsonable(from_jsonable(PersonaInstance, body))  # what the store will read back
    return CarriedInstance(record.id, path, destination, body, rebased, tuple(CLEARED))


def _placed_ids(src_store: Path) -> list[str]:
    """Instance ids the source office places live, read as ``OfficeStore`` reads it (a workspace is a
    directory holding ``office.json``; archived placements are not shown, so not counted)."""
    office = src_store / "office"
    placed: set[str] = set()
    for workspace in sorted(office.iterdir()) if office.is_dir() and not office.is_symlink() else []:
        for actor in read_actor_dir(workspace / "actors").actors if (workspace / "office.json").is_file() else []:
            bound = actor_bound_instance_id(actor)
            if bound:
                placed.add(bound)
    return sorted(placed)


def plan_instances(src_root: Path, item: Layout) -> InstancePlan:
    """Read-only: what the seed carries, skips and resolves. Refuses before any copy on a leftover."""
    rebase = Rebase(src_root, item.root)
    src_store, dst_dir = src_root / STORE_DIRNAME, item.store_root / INSTANCES_DIRNAME
    folder = src_store / INSTANCES_DIRNAME
    carried: list[CarriedInstance] = []
    skipped: list[dict[str, str]] = []
    held: set[str] = set()
    listed = folder.is_dir() and not folder.is_symlink()
    for path in sorted(folder.iterdir(), key=lambda p: p.name) if listed else []:
        label = f"{STORE_DIRNAME}/{INSTANCES_DIRNAME}/{path.name}"
        record = None if path.is_symlink() or not path.is_file() else _decode(path)
        if record is None:
            skipped.append({"path": label, "reason": UNPARSEABLE})
        elif (dst_dir / path.name).exists():
            skipped.append({"path": label, "reason": TARGET_HOLDS})
            held.add(record.id)
        else:
            carried.append(_carry(path, record, rebase, dst_dir / path.name))
    aliases = None
    alias_file = src_store / ALIASES_NAME
    if (item.store_root / ALIASES_NAME).exists():
        skipped.append({"path": f"{STORE_DIRNAME}/{ALIASES_NAME}", "reason": TARGET_HOLDS})
    elif alias_file.is_file() and not alias_file.is_symlink():
        leftovers: list[str] = []
        try:
            body = _rebase_tree(json.loads(alias_file.read_text(encoding="utf-8")), rebase, "", {}, leftovers)
        except (OSError, ValueError):
            skipped.append({"path": f"{STORE_DIRNAME}/{ALIASES_NAME}", "reason": "unreadable"})
        else:
            _refuse_leftovers(f"{STORE_DIRNAME}/{ALIASES_NAME}", leftovers, rebase)
            aliases = (alias_file, item.store_root / ALIASES_NAME, body)
    known = {c.id for c in carried} | held
    alias_map = aliases[2] if aliases and isinstance(aliases[2], dict) else {}
    resolved, orphaned = [], []
    for placed in _placed_ids(src_store):
        (resolved if placed in known or alias_map.get(placed) in known else orphaned).append(placed)
    return InstancePlan(tuple(carried), tuple(skipped), aliases, tuple(resolved), tuple(orphaned))


def write_instances(plan: InstancePlan) -> None:
    """Write the carried records and the aliases registry. The plan already left every id the target holds."""
    for carried in plan.carried:
        carried.destination.parent.mkdir(parents=True, exist_ok=True)
        atomic_json_write(carried.destination, carried.body, indent=2, sort_keys=True)
    if plan.aliases:
        atomic_json_write(plan.aliases[1], plan.aliases[2], indent=2, sort_keys=True)
