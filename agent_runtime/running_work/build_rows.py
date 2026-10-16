"""The ``build`` row: one shape for all three sources (plan ``build-running-work-2026-10-04.md`` §1).

A lane gathers what it KNOWS about one build into :class:`BuildFacts`; :func:`build_row`
turns it into the shared ``work_row`` plus every build key of §1 — each present on every
row, an unknown value ``null`` (or the ``unknown`` arm) and never a guess. The status on
the wire is DERIVED from ``liveness`` + ``outcome`` here, once (§1's table), so no lane can
answer "is this build running" its own way.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import PurePath
from typing import Any

from ..builds.unknowns import UNKNOWN_SLOT_UNRESOLVED, UNKNOWN_STARTER_UNKNOWN, UnknownsIndex
from ..builds.vocabulary import (
    ARTIFACT_KIND_OTHER,
    ARTIFACT_KINDS,
    BUILD_LIVENESS,
    BUILD_MODES,
    BUILD_SOURCES,
    BUILD_TOOLCHAINS,
    COMMAND_LIMIT,
    CONTROL_ALLOWED,
    CONTROL_REASONS,
    CONTROL_REFUSED,
    CONTROL_STATES,
    CONTROL_UNAVAILABLE,
    ENV_SOURCE_ARMS,
    ENV_SOURCE_SLOT_PREFIX,
    ENV_SOURCE_UNKNOWN,
    LABEL_LIMIT,
    LIVENESS_DEAD,
    LIVENESS_STALLED,
    LIVENESS_UNKNOWN,
    OUTCOME_SUCCEEDED,
    PROGRESS_SIGNAL_NONE,
    PROGRESS_SIGNALS,
    STAGE_UNKNOWN,
    STAGE_DETAIL_LIMIT,
    STARTED_BY_KINDS,
    STARTED_BY_TOOL,
    TOOLCHAIN_UNKNOWN,
)
from ..projection_accountant import ProjectionAccountant
from .rows import bounded_operator_text, work_row
from .vocabulary import (
    KIND_BUILD,
    LANE_DURABLE,
    STATUS_COMPLETED,
    STATUS_ERROR,
    STATUS_RUNNING,
    STATUS_STALLED,
    STATUS_STALLING,
    STATUS_UNKNOWN,
)

__layer__ = "policy"


@dataclass
class BuildFacts:
    """Everything one lane knows about one build; ``build_row`` owns the wire shape."""

    source: str
    stable_id: str
    command: str = ""
    label: str = ""
    pid: Any = None
    pid_verified: bool = False
    persona_id: str = ""
    persona_instance_id: str = ""
    session_id: str = ""
    started_at: str = ""
    elapsed_seconds: int = 0
    tail_preview: str = ""
    source_lane: str = LANE_DURABLE
    project_root: str = ""
    workspace_id: str | None = None
    slot_id: str | None = None
    env_source: str = "unknown"
    toolchain: str = "unknown"
    target: str = ""
    mode: str = ""
    stage: str = STAGE_UNKNOWN
    stage_detail: str = ""
    liveness: str = LIVENESS_UNKNOWN
    stalling: bool = False
    progress_signal: str = PROGRESS_SIGNAL_NONE
    seconds_since_progress: float | None = None
    expected_ms: int | None = None
    history_samples: int = 0
    outcome: str | None = None
    exit_code: int | None = None
    artifact: dict[str, Any] | None = None
    finished_at: str = ""
    started_by: dict[str, str] = field(default_factory=lambda: {"kind": "external", "label": ""})
    stop: tuple[str, str] = (CONTROL_REFUSED, "")
    restart_control: tuple[str, str] = (CONTROL_REFUSED, "")
    restart: dict[str, Any] | None = None
    origin_work_id: str | None = None
    announcement: dict[str, Any] | None = None
    mcp_job: dict[str, str] | None = None
    restart_of: str | None = None
    unknowns: UnknownsIndex = field(default_factory=UnknownsIndex)


#: §1's table: ``(outcome is None, liveness)`` → the shared status word, outcome first.
_STATUS_BY_LIVENESS = {
    LIVENESS_STALLED: STATUS_STALLED,
    LIVENESS_DEAD: STATUS_ERROR,
    LIVENESS_UNKNOWN: STATUS_UNKNOWN,
}


def wire_status(liveness: str, outcome: str | None, *, stalling: bool) -> str:
    if outcome is not None:
        return STATUS_COMPLETED if outcome == OUTCOME_SUCCEEDED else STATUS_ERROR
    if liveness in _STATUS_BY_LIVENESS:
        return _STATUS_BY_LIVENESS[liveness]
    return STATUS_STALLING if stalling else STATUS_RUNNING


def apply_slot(facts: BuildFacts, path: str, slot: Any, bound_count: int, *, now: float) -> None:
    """``workspace_id`` / ``slot_id`` from the slot the lane resolved, or ``slot_unresolved`` with the path."""

    if slot is None:
        facts.unknowns.add(UNKNOWN_SLOT_UNRESOLVED, f"{path or '(no path)'}: under none of {bound_count} bound slot(s)", now)
        return
    facts.workspace_id, facts.slot_id = slot.workspace_id, slot.slot


def note_starter(facts: BuildFacts, evidence: str, *, now: float) -> None:
    """``started_by_instance`` is the owner's instance; none ⇒ ``starter_unknown`` with what was seen."""

    if not facts.persona_instance_id:
        facts.unknowns.add(UNKNOWN_STARTER_UNKNOWN, evidence, now)


def slot_env_source(slot_id: str | None, fallback: str) -> str:
    return f"{ENV_SOURCE_SLOT_PREFIX}{slot_id}" if slot_id else fallback


def _eta(facts: BuildFacts) -> tuple[int | None, float | None]:
    if facts.expected_ms is None or facts.outcome is not None:
        return None, None
    elapsed_ms = facts.elapsed_seconds * 1000
    fraction = min(1.0, max(0.0, elapsed_ms / facts.expected_ms)) if facts.expected_ms > 0 else None
    return max(0, facts.expected_ms - elapsed_ms), None if fraction is None else round(fraction, 3)


def spelled(value: Any, words: tuple[str, ...], field_name: str) -> str:
    """``value``, which hermes itself chose, checked against its vocabulary tuple.

    These words are only ever written from the vocabulary's constants, so a word outside
    the tuple is a producer bug: it raises, and the frame reports the lane as
    ``collector_failed`` (``surface.build_running_work``) instead of shipping a word the
    launcher cannot decode.
    """

    if value not in words:
        raise ValueError(f"build row {field_name}={value!r} is not a word of {words}")
    return value


def closed_word(value: Any, words: tuple[str, ...], fallback: str) -> str:
    """``value`` when it is a word of ``words``, else the vocabulary's unknown arm.

    For the words an announced WRITER (or a restart mark) supplies: the build row says
    ``unknown`` rather than guess, as ``stage`` and ``outcome`` already do.
    """

    return value if value in words else fallback


def _env_source(value: Any) -> str:
    """``slot:<name>`` is the arm named by its prefix; anything else must be a whole arm."""

    text = str(value or "")
    arm = ENV_SOURCE_SLOT_PREFIX if text.startswith(ENV_SOURCE_SLOT_PREFIX) else text
    return text if arm in ENV_SOURCE_ARMS and text != ENV_SOURCE_SLOT_PREFIX else ENV_SOURCE_UNKNOWN


def _artifact(value: dict[str, Any] | None) -> dict[str, Any] | None:
    if value is None:
        return None
    return {**value, "kind": closed_word(value.get("kind"), ARTIFACT_KINDS, ARTIFACT_KIND_OTHER)}


def build_extra(facts: BuildFacts, accountant: ProjectionAccountant | None) -> dict[str, Any]:
    """Every §1 build key, in one place — every closed word spelled from its vocabulary tuple."""

    eta_ms, fraction = _eta(facts)
    root = facts.project_root or ""
    started_by = dict(facts.started_by)
    started_by["kind"] = closed_word(started_by.get("kind"), STARTED_BY_KINDS, STARTED_BY_TOOL)
    return {
        "source": spelled(facts.source, BUILD_SOURCES, "source"),
        "project": {"root": root, "name": PurePath(root).name if root else ""},
        "workspace_id": facts.workspace_id,
        "slot_id": facts.slot_id,
        "env_source": _env_source(facts.env_source),
        "started_by_instance": facts.persona_instance_id or None,
        "unknowns": facts.unknowns.wire(accountant, entity_id=f"{KIND_BUILD}:{facts.stable_id}"),
        "toolchain": closed_word(facts.toolchain, BUILD_TOOLCHAINS, TOOLCHAIN_UNKNOWN),
        "target": facts.target,
        "mode": closed_word(facts.mode, BUILD_MODES, ""),
        "stage": facts.stage,
        "stage_detail": bounded_operator_text(facts.stage_detail, limit=STAGE_DETAIL_LIMIT),
        "liveness": spelled(facts.liveness, BUILD_LIVENESS, "liveness"),
        "progress_signal": spelled(facts.progress_signal, PROGRESS_SIGNALS, "progress_signal"),
        "seconds_since_progress": None if facts.seconds_since_progress is None else round(facts.seconds_since_progress, 1),
        "progress_fraction": fraction,
        "expected_ms": facts.expected_ms,
        "eta_ms": eta_ms,
        "history_samples": facts.history_samples,
        "outcome": facts.outcome,
        "exit_code": facts.exit_code,
        "artifact": _artifact(facts.artifact),
        "finished_at": facts.finished_at,
        "started_by": started_by,
        "controls": _controls(facts),
        "restart": facts.restart,
        "origin_work_id": facts.origin_work_id,
        "announcement": facts.announcement,
        "mcp_job": facts.mcp_job,
        "restart_of": facts.restart_of,
    }


_REASONS = ("", *CONTROL_REASONS)


def _controls(facts: BuildFacts) -> dict[str, str]:
    return {
        "stop": spelled(facts.stop[0], CONTROL_STATES, "controls.stop"),
        "stop_reason": spelled(facts.stop[1], _REASONS, "controls.stop_reason"),
        "restart": spelled(facts.restart_control[0], CONTROL_STATES, "controls.restart"),
        "restart_reason": spelled(facts.restart_control[1], _REASONS, "controls.restart_reason"),
    }


def build_row(facts: BuildFacts, accountant: ProjectionAccountant | None) -> dict[str, Any]:
    """The ``build:<source>:<stable>`` row."""

    if facts.liveness == LIVENESS_UNKNOWN and facts.stop[0] == CONTROL_ALLOWED:
        # Identity unproven (rule 2): hermes will not signal a process it cannot name.
        facts.stop = (CONTROL_UNAVAILABLE, "")
    return work_row(
        kind=KIND_BUILD,
        stable_id=f"{facts.source}:{facts.stable_id}",
        label=bounded_operator_text(facts.label, limit=LABEL_LIMIT) or facts.stable_id,
        status=wire_status(facts.liveness, facts.outcome, stalling=facts.stalling),
        source_lane=facts.source_lane,
        command=bounded_operator_text(facts.command, limit=COMMAND_LIMIT),
        pid=facts.pid,
        pid_verified=facts.pid_verified,
        persona_id=facts.persona_id,
        persona_instance_id=facts.persona_instance_id,
        session_id=facts.session_id,
        started_at=facts.started_at,
        elapsed_seconds=facts.elapsed_seconds,
        tail_preview=facts.tail_preview,
        cancellable=facts.stop[0] == CONTROL_ALLOWED,
        extra=build_extra(facts, accountant),
    )


def label_for(toolchain: str, kind: str, target: str, root: str) -> str:
    """``flutter build windows · eternia_launcher`` — the row's human name."""

    words = " ".join(word for word in (toolchain, kind, target) if word and word != "unknown")
    name = PurePath(root).name if root else ""
    return f"{words} · {name}" if name else words
