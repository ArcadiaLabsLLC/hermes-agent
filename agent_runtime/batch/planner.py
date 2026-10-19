"""The batching policy — ready rows into thick lanes by domain (dispatcher plan §3.1). Pure.

1. Group by ``source.domain_of(row)`` = ``Domain(slot, note, heading)``: one lane per domain, never per row.
2. A lane's size is budgeted by how big its rows are (owner ruling 2026-10-18 on
   ``RT-DISPATCH-B2-BATCH``): a row's effort is the files it names (its code-span pointers that are
   paths, citations under ``docs/`` or a ``*_Brain`` excluded; at least 1). A domain over
   ``Budget.max_effort_per_lane`` — or over ``max_rows_per_lane`` (65, only a ceiling) — splits by
   the first touched file's top-level directory, areas packed whole while they fit.
3. A lane naming a file an earlier lane names is SEQUENCED after it (``Lane.after``), never run beside it.
4. A lane takes its rows' ``assignee`` (two different ones refuse ``plan_refused``); rows with none take
   the workspace roster's instance whose ``role`` is the slot's ``context.role``; when nothing matches,
   ``Lane.persona`` is None and the plan ASKS the operator (``Plan.asks``; ``start`` refuses
   ``persona_unresolved`` until answered).
5. ``heavy``: a row naming a release merge, a daily branch or a suite run. ``quiet_box``: a row judging a
   timeout or a flake (it runs only on an idle box).
6. The plan ends with ONE landing lane, after every lane. It carries ``Lane.gates``: the gate commands per
   slot the lanes touch (``gate.slot_gate``, handed in as ``slot_gates``); a slot with none is None there and
   the lane executor answers it with a RED receipt (row RT-BATCH-GATE-PER-SLOT-COMMAND, owner ruling 2026-10-19).
7. ``Lane.skills``: the UNION of its rows' ``skills:`` segments (p10-work S1), listed in the lane brief and
   queued for the lane's turn by the executor.

The plan id is ``BATCH-<6 base32>`` of the lanes' rows, so planning the same board twice gives the same
id and ``start`` can tell the board moved (``idempotency_conflict``).
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from enum import StrEnum
from pathlib import PurePosixPath
from typing import Any

from ..work_store.grammar import Row, RowRef, domain_of
from ..work_store.models import Brief, Domain
from ..work_store.reasons import Reason, WorkRefused

__layer__ = "policy"
__all__ = [
    "LANDING_GATE",
    "LANDING_ID",
    "Budget",
    "Lane",
    "LaneKind",
    "Member",
    "Plan",
    "area_of",
    "plan",
    "row_effort",
    "touched_files",
]

LANDING_ID = "LAND"
#: The hermes slot's landing gate (``gate.GATES_BY_TOOLCHAIN_KIND``; `Running the tests.md`).
LANDING_GATE = "bash scripts/run_tests_bundled.sh tests"
#: The playbook's measured ceiling; a lane is sized by effort first (owner ruling 2026-10-18).
MAX_ROWS_PER_LANE = 65
#: Files touched per lane, summed over its rows (a row naming none counts 1, so 65 trivial rows fit).
MAX_EFFORT_PER_LANE = 65
HEAVY = re.compile(r"release merge|daily branch|suite run", re.IGNORECASE)
QUIET_BOX = re.compile(r"\btimeouts?\b|\bflak(?:e|y|es)\b", re.IGNORECASE)
_EXTENSION = re.compile(r"\.[A-Za-z0-9]{1,5}$")
_BRACES = re.compile(r"\{([^{}]*)\}")
#: Top-level directories a pointer CITES rather than edits.
_CITATIONS = ("docs",)
_LANE_CONSTRAINTS = (
    "Edit only what these rows name; the dispatcher writes every row's ending — never edit the rows.",
    "Run only the tests that import what you touched (scripts/run_tests.sh -j 4); other lanes are live.",
    "One CHANGE commit (a MOVE, if any, separately); report your tool-call count.",
)


class LaneKind(StrEnum):
    WORK = "work"
    LANDING = "landing"


@dataclass(frozen=True)
class Budget:
    """How many lanes run at once (plan §3.3) and how big one lane may be (§3.1)."""

    max_lanes: int = 4
    heavy_at_once: int = 1
    light_at_once: int = 6
    max_rows_per_lane: int = MAX_ROWS_PER_LANE
    max_effort_per_lane: int = MAX_EFFORT_PER_LANE

    def wire(self) -> dict[str, int]:
        return {"max_lanes": self.max_lanes, "heavy_at_once": self.heavy_at_once,
                "light_at_once": self.light_at_once, "max_rows_per_lane": self.max_rows_per_lane,
                "max_effort_per_lane": self.max_effort_per_lane}


@dataclass(frozen=True)
class Member:
    """One persona instance of the workspace roster: what the role match reads."""

    instance_id: str
    persona_id: str
    role: str


@dataclass(frozen=True)
class Lane:
    id: str
    kind: LaneKind
    domain: Domain | None
    rows: tuple[RowRef, ...]
    persona: str | None
    brief: Brief
    heavy: bool = False
    quiet_box: bool = False
    after: tuple[str, ...] = ()
    effort: int = 0
    files: tuple[str, ...] = field(default=(), compare=False)
    #: The landing lane's gate commands per slot; None = no gate declared (a red receipt).
    gates: Mapping[str, tuple[str, ...] | None] = field(default_factory=dict, hash=False)
    #: The skills the lane's rows lend (their union, in row order).
    skills: tuple[str, ...] = ()

    def wire(self) -> dict[str, Any]:
        brief = self.brief
        return {"id": self.id, "kind": self.kind.value,
                "domain": None if self.domain is None else [self.domain.slot, self.domain.note, self.domain.heading],
                "rows": [[r.slot, r.note, r.id] for r in self.rows], "persona": self.persona,
                "heavy": self.heavy, "quiet_box": self.quiet_box, "after": list(self.after), "effort": self.effort,
                "files": list(self.files),
                "gates": {slot: None if cmds is None else list(cmds) for slot, cmds in self.gates.items()},
                "skills": list(self.skills),
                "brief": {"title": brief.title, "objective": brief.objective, "inputs": list(brief.inputs),
                          "constraints": list(brief.constraints), "acceptance": brief.acceptance,
                          "tests": list(brief.tests)}}

    @classmethod
    def from_wire(cls, raw: Mapping[str, Any]) -> Lane:
        brief = raw["brief"]
        return cls(
            id=str(raw["id"]), kind=LaneKind(raw["kind"]),
            domain=Domain(*raw["domain"]) if raw.get("domain") else None,
            rows=tuple(RowRef(*map(str, r)) for r in raw.get("rows") or ()),
            persona=raw.get("persona") or None,
            brief=Brief(title=str(brief["title"]), objective=str(brief["objective"]),
                        inputs=tuple(brief.get("inputs") or ()), constraints=tuple(brief.get("constraints") or ()),
                        acceptance=str(brief.get("acceptance") or ""), tests=tuple(brief.get("tests") or ())),
            heavy=bool(raw.get("heavy")), quiet_box=bool(raw.get("quiet_box")),
            after=tuple(raw.get("after") or ()), effort=int(raw.get("effort") or 0),
            files=tuple(raw.get("files") or ()),
            gates={str(slot): None if cmds is None else tuple(map(str, cmds))
                   for slot, cmds in (raw.get("gates") or {}).items()},
            skills=tuple(map(str, raw.get("skills") or ())),
        )


@dataclass(frozen=True)
class Plan:
    id: str
    workspace_id: str
    lanes: tuple[Lane, ...]
    landing: Lane
    budget: Budget

    @property
    def asks(self) -> tuple[str, ...]:
        """The lanes whose persona the operator must name before ``start``."""

        return tuple(lane.id for lane in (*self.lanes, self.landing) if lane.persona is None)

    def with_personas(self, personas: Mapping[str, str]) -> Plan:
        """The operator's answers (``{lane_id: instance_id}``) over the planned personas; the id is unchanged."""

        pick = lambda lane: replace(lane, persona=personas.get(lane.id) or lane.persona)
        lanes = tuple(pick(lane) for lane in self.lanes)
        landing = pick(self.landing)
        if landing.persona is None and lanes:
            landing = replace(landing, persona=lanes[0].persona)
        return replace(self, lanes=lanes, landing=landing)

    def wire(self) -> dict[str, Any]:
        return {"id": self.id, "workspace_id": self.workspace_id, "lanes": [lane.wire() for lane in self.lanes],
                "landing": self.landing.wire(), "budget": self.budget.wire(), "asks": list(self.asks)}

    @classmethod
    def from_wire(cls, raw: Mapping[str, Any]) -> Plan:
        return cls(str(raw["id"]), str(raw["workspace_id"]), tuple(Lane.from_wire(lane) for lane in raw["lanes"]),
                   Lane.from_wire(raw["landing"]), Budget(**raw.get("budget") or {}))


# ── effort ─────────────────────────────────────────────────────────────────


def _expand(pointer: str) -> list[str]:
    match = _BRACES.search(pointer)
    if match is None:
        return [pointer]
    return [p for part in match.group(1).split(",")
            for p in _expand(pointer[:match.start()] + part.strip() + pointer[match.end():])]


def touched_files(row: Row) -> tuple[str, ...]:
    """The files a row names that a lane would edit: path-shaped pointers, citations excluded."""

    found: list[str] = []
    for pointer in row.pointers:
        head = pointer.split("::")[0].split()[0] if pointer.split() else ""
        if "/" not in head and not _EXTENSION.search(head):
            continue
        top = PurePosixPath(head).parts[0] if PurePosixPath(head).parts else ""
        if top in _CITATIONS or top.endswith(("_Brain", "_brain")):
            continue
        found.extend(_expand(head))
    return tuple(dict.fromkeys(found))


def row_effort(row: Row) -> int:
    return max(1, len(touched_files(row)))


def area_of(row: Row) -> str:
    """The first touched file's top-level directory ("" when the row names none)."""

    files = touched_files(row)
    return PurePosixPath(files[0]).parts[0] if files and "/" in files[0] else ""


# ── grouping and sizing ────────────────────────────────────────────────────


def _fits(rows: Sequence[Row], extra: Sequence[Row], budget: Budget) -> bool:
    return (len(rows) + len(extra) <= budget.max_rows_per_lane
            and sum(map(row_effort, rows)) + sum(map(row_effort, extra)) <= budget.max_effort_per_lane)


def _chunks(rows: Sequence[Row], budget: Budget) -> list[list[Row]]:
    """Rows packed in order into lanes within budget; a row over budget alone is its own lane."""

    out: list[list[Row]] = []
    for row in rows:
        if out and _fits(out[-1], [row], budget):
            out[-1].append(row)
        else:
            out.append([row])
    return out


def _split(rows: Sequence[Row], budget: Budget) -> list[list[Row]]:
    """One lane for the domain when it fits; else by area, areas packed whole while they fit."""

    if _fits(rows, (), budget):
        return [list(rows)]
    areas: dict[str, list[Row]] = {}
    for row in rows:
        areas.setdefault(area_of(row), []).append(row)
    lanes: list[list[Row]] = []
    for area in sorted(areas):
        for chunk in _chunks(areas[area], budget):
            if lanes and _fits(lanes[-1], chunk, budget):
                lanes[-1].extend(chunk)
            else:
                lanes.append(list(chunk))
    return lanes


# ── persona ────────────────────────────────────────────────────────────────


def _resolve_token(token: str, roster: Sequence[Member]) -> str | None:
    """An instance id names itself; a persona id names its first roster instance (roster order is the
    preference: the workspace's own first); else None (ask)."""

    if any(m.instance_id == token for m in roster):
        return token
    return next((m.instance_id for m in roster if m.persona_id == token), None)


def _persona(domain: Domain, rows: Sequence[Row], roster: Sequence[Member], slot_roles: Mapping[str, str]) -> str | None:
    tokens = sorted({row.assignee.token for row in rows if row.assignee is not None})
    if len(tokens) > 1:
        raise WorkRefused(Reason.PLAN_REFUSED, f"mixed_assignees: {domain.slot} · {domain.heading} · {tokens}")
    if tokens:
        return _resolve_token(tokens[0], roster)
    role = slot_roles.get(domain.slot)
    return next((m.instance_id for m in roster if role and m.role == role), None)


# ── briefs ─────────────────────────────────────────────────────────────────


def _lent(rows: Sequence[Row]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(skill for row in rows for skill in row.skills))


def _lane_brief(lane_id: str, domain: Domain, rows: Sequence[Row]) -> Brief:
    where = domain.heading or PurePosixPath(domain.note).stem
    lent = _lent(rows)
    objective = "\n".join([f"Work these {len(rows)} row(s) of {domain.slot} · {where}:",
                           *(f"- {row.ref.id}: {row.title}" for row in rows),
                           *([f"Skills lent for this lane (preloaded): {', '.join(lent)}"] if lent else [])])
    pointers = dict.fromkeys(p for row in rows for p in row.pointers)
    return Brief(title=f"lane {lane_id} — {domain.slot} · {where}", objective=objective,
                 inputs=(*(row.raw for row in rows), *(f"`{p}`" for p in pointers)),
                 constraints=_LANE_CONSTRAINTS,
                 acceptance="every row done, or blocked with the one question for the owner")


def _gate_line(slot: str, commands: tuple[str, ...] | None) -> str:
    return f"- {slot}: " + ("NO GATE DECLARED" if commands is None else " && ".join(f"`{c}`" for c in commands))


def _landing_brief(lane_ids: Sequence[str], gates: Mapping[str, tuple[str, ...] | None]) -> Brief:
    return Brief(
        title="the landing lane",
        objective="\n".join([
            f"Land the batch: merge the reported lanes in order with --no-ff ({', '.join(lane_ids)}).",
            "Resolve any conflict and commit; leave the landing worktree clean. Fix a caused red as its own commit.",
            "When you settle, the executor runs each slot's gate here and records its receipt:",
            *(_gate_line(slot, commands) for slot, commands in gates.items()),
            "Your verdict is advisory. Do NOT push main: the push is the owner's approve."]),
        constraints=("Never push main; never force-push; never amend.",),
        acceptance="every lane merged and committed, the worktree clean; the code-run gate decides green",
        tests=tuple(dict.fromkeys(c for commands in gates.values() for c in commands or ())))


# ── the plan ───────────────────────────────────────────────────────────────


def _plan_id(workspace_id: str, lanes: Sequence[Lane]) -> str:
    key = [workspace_id, [[lane.id, [[r.slot, r.note, r.id] for r in lane.rows]] for lane in lanes]]
    digest = hashlib.sha256(json.dumps(key, sort_keys=True).encode("utf-8")).digest()
    return "BATCH-" + base64.b32encode(digest).decode("ascii")[:6]


def _sequenced(lanes: list[Lane]) -> list[Lane]:
    out: list[Lane] = []
    for lane in lanes:
        before = tuple(prior.id for prior in out if set(prior.files) & set(lane.files))
        out.append(replace(lane, after=before))
    return out


def plan(
    rows: Iterable[Row],
    *,
    workspace_id: str,
    roster: Sequence[Member] = (),
    slot_roles: Mapping[str, str] | None = None,
    budget: Budget | None = None,
    slot_gates: Mapping[str, tuple[str, ...] | None] | None = None,
) -> Plan:
    """The batch for ``rows`` (the source's ``ready``): thick lanes, sequenced, one landing. Writes nothing."""

    budget = budget or Budget()
    by_domain: dict[Domain, list[Row]] = {}
    for row in rows:
        by_domain.setdefault(domain_of(row), []).append(row)
    if not by_domain:
        raise WorkRefused(Reason.PLAN_REFUSED, "nothing_ready: no READY row is free to claim")
    lanes: list[Lane] = []
    for domain in sorted(by_domain, key=lambda d: (d.slot, d.note, d.heading)):
        members = by_domain[domain]
        persona = _persona(domain, members, roster, slot_roles or {})
        for part in _split(members, budget):
            lane_id = f"L{len(lanes) + 1}"
            files = tuple(dict.fromkeys(f for row in part for f in touched_files(row)))
            lanes.append(Lane(
                id=lane_id, kind=LaneKind.WORK, domain=domain, rows=tuple(row.ref for row in part), persona=persona,
                brief=_lane_brief(lane_id, domain, part), heavy=any(HEAVY.search(row.raw) for row in part),
                quiet_box=any(QUIET_BOX.search(row.raw) for row in part), effort=sum(map(row_effort, part)),
                files=files, skills=_lent(part)))
    lanes = _sequenced(lanes)
    slots = dict.fromkeys(lane.domain.slot for lane in lanes if lane.domain is not None)
    gates = {slot: (slot_gates or {}).get(slot) for slot in slots}
    landing = Lane(id=LANDING_ID, kind=LaneKind.LANDING, domain=None, rows=(), persona=lanes[0].persona,
                   brief=_landing_brief([lane.id for lane in lanes], gates), after=tuple(lane.id for lane in lanes),
                   gates=gates)
    return Plan(_plan_id(workspace_id, lanes), workspace_id, tuple(lanes), landing, budget)
