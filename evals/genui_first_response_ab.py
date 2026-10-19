"""GenUI first-response A/B eval (RT-VERIFY-IMPROVE-FIRST-RESPONSE) — a receipt reader.

Plan: ``docs/agent-runtime-harness/planned/p10-agent-2026-10-19.md`` §3. The question is
whether a comparison prompt's FIRST tool call is ``launcher_generated_list`` /
``launcher_generated_create`` (and the turn creates a document) instead of a Markdown
table, per agent and provider, under two Launcher guidance arms that are switched by QA
build (owner ruling 2026-10-19), and what the guidance costs per turn.

This module never starts a serve, never calls a provider and never sends a message. It
reads two receipts a QA serve already writes under its ``HERMES_HOME``:

- the turn record (``agent_runtime.mission_chat_turns.reads.mission_chat_turn_record``):
  the turn's ``tool`` / ``segment`` elements and its settle state;
- the mission-chat observability row ``ctx_<hash>.json``
  (``agent_runtime.prompt_observability``): ``final_model_input.system_prompt_sections``
  blocks and ``final_model_input.tool_schema.per_tool_chars``.

Stages: G1 reader (``read_turn``, ``read_cost``, ``score``).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Iterable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

#: A hit's first tool: the catalog read or the create itself (plan §3.2).
HIT_FIRST_TOOLS = frozenset({"launcher_generated_list", "launcher_generated_create"})
CREATE_TOOL = "launcher_generated_create"
#: The five generated tools the Launcher declares ``alwaysLoaded``
#: (``EterniaLauncher/lib/core/services/hermes/runtime/data/capabilities/harness_generated_capabilities.dart``).
GENERATED_TOOLS = (
    "launcher_generated_list",
    "launcher_generated_inspect",
    "launcher_generated_create",
    "launcher_generated_update",
    "launcher_generated_edit",
)
GENERATED_PREFIX = "launcher_generated_"
TOOL_GUIDANCE_SECTION = "eternia-harness.tool-guidance"
#: ``hermes_cli.plugins_dispatch.format_system_prompt_section`` heads every plugin section so;
#: ``model_input_observability._prompt_block_receipts`` keys the block by that line (80 chars).
TOOL_GUIDANCE_BLOCK_HEADING = f"## Plugin Context: {TOOL_GUIDANCE_SECTION}"
_SECTION_TEXT_RE = re.compile(
    re.escape(TOOL_GUIDANCE_BLOCK_HEADING) + r"\n<!-- hermes-plugin-section-chars:(\d+) -->\n\n"
)
_DOCUMENT_ID_RE = re.compile(
    r"""["']?(?:document_id|documentId|generated_document_id|id)["']?\s*[:=]\s*["']?([A-Za-z0-9][A-Za-z0-9_.:-]{2,})"""
)
_FAILED_STATUSES = frozenset({"failed", "error", "refused", "blocked", "timed_out", "denied"})
_SETTLED_STATES = frozenset({"completed", "failed", "interrupted", "projected", "abandoned"})


# ── where the receipts live ─────────────────────────────────────────────────


@contextmanager
def _home_scope(home: str | os.PathLike[str], runtime_root: str | os.PathLike[str] | None) -> Iterator[None]:
    """Resolve the runtime store for *home* (resolved at call time, never module scope)."""

    from agent_runtime.resolution import runtime_resolution_scope

    env = dict(os.environ)
    env["HERMES_HOME"] = str(home)
    env.pop("HERMES_AGENT_RUNTIME_ROOT", None)
    if runtime_root:
        env["HERMES_AGENT_RUNTIME_ROOT"] = str(runtime_root)
    with runtime_resolution_scope(env=env):
        yield


# ── the turn ────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class TurnOutcome:
    """What one turn did first, read from its record."""

    turn_id: str
    state: str
    first_tool: str | None
    tool_turns: int
    created_document_id: str | None
    prose_only: bool
    tool_names: tuple[str, ...] = ()

    @property
    def settled(self) -> bool:
        return self.state in _SETTLED_STATES

    @property
    def is_hit(self) -> bool:
        """First tool is the catalog read or create, and a document was created."""

        return self.first_tool in HIT_FIRST_TOOLS and self.created_document_id is not None

    @property
    def called_generated(self) -> bool:
        return any(name.startswith(GENERATED_PREFIX) for name in self.tool_names)


def _created_document_id(element: Mapping[str, Any]) -> str | None:
    if element.get("name") != CREATE_TOOL or str(element.get("status") or "") in _FAILED_STATUSES:
        return None
    for key in ("tool_result", "output", "summary", "detail"):
        match = _DOCUMENT_ID_RE.search(str(element.get(key) or ""))
        if match:
            return match.group(1)
    return None


def turn_outcome(record: Mapping[str, Any]) -> TurnOutcome:
    """Project one (safe) turn record onto the eval's outcome."""

    elements = sorted(
        (item for item in record.get("elements") or [] if isinstance(item, Mapping)),
        key=lambda item: (int(item.get("seq") or 0), str(item.get("id") or "")),
    )
    tools = [item for item in elements if item.get("kind") == "tool"]
    names = tuple(str(item.get("name") or "") for item in tools)
    answer = "".join(
        str(item.get("text") or "")
        for item in elements
        if item.get("kind") == "segment" and (item.get("seg_type") or "answer") == "answer"
    )
    created = next((doc for doc in map(_created_document_id, tools) if doc), None)
    return TurnOutcome(
        turn_id=str(record.get("turn_id") or ""),
        state=str(record.get("state") or "completed"),
        first_tool=names[0] if names else None,
        tool_turns=len(tools),
        created_document_id=created,
        prose_only=not tools and bool(answer.strip()),
        tool_names=names,
    )


def read_turn(
    home: str | os.PathLike[str],
    session_id: str,
    client_message_id: str,
    *,
    runtime_root: str | os.PathLike[str] | None = None,
) -> TurnOutcome | None:
    """The turn's outcome from the QA home's journal, or ``None`` when it has no record."""

    from agent_runtime.mission_chat_turns.reads import mission_chat_turn_record

    with _home_scope(home, runtime_root):
        record = mission_chat_turn_record(session_id=session_id, client_message_id=client_message_id)
    return None if record is None else turn_outcome(record)


# ── the cost ────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class CostReceipt:
    """The guidance's per-turn size, from one observability row (chars; tokens = chars/4)."""

    context_id: str
    guidance_chars: int
    per_tool_chars: dict[str, int] = field(default_factory=dict)
    guidance_sha256: str | None = None
    comparison_in_guidance: bool | None = None
    provider: str | None = None
    model: str | None = None

    @property
    def total_chars(self) -> int:
        return self.guidance_chars + sum(self.per_tool_chars.values())

    @property
    def tokens(self) -> float:
        return self.total_chars / 4


def _guidance_text(final_model_input: Mapping[str, Any]) -> str | None:
    for message in final_model_input.get("messages") or []:
        if not isinstance(message, Mapping) or message.get("role") != "system":
            continue
        content = str(message.get("content") or "")
        match = _SECTION_TEXT_RE.search(content)
        if match:
            text = content[match.end() : match.end() + int(match.group(1))]
            return text if len(text) == int(match.group(1)) else None
    return None


def cost_receipt(row: Mapping[str, Any]) -> CostReceipt:
    """Project one observability row onto the cost receipt."""

    final = row.get("final_model_input") if isinstance(row.get("final_model_input"), Mapping) else {}
    guidance_chars = sum(
        int(block.get("chars") or 0)
        for section in final.get("system_prompt_sections") or []
        if isinstance(section, Mapping)
        for block in section.get("blocks") or []
        if isinstance(block, Mapping) and block.get("heading") == TOOL_GUIDANCE_BLOCK_HEADING
    )
    schema = final.get("tool_schema") if isinstance(final.get("tool_schema"), Mapping) else {}
    raw_per_tool = schema.get("per_tool_chars") if isinstance(schema.get("per_tool_chars"), Mapping) else {}
    per_tool = {name: int(raw_per_tool[name]) for name in GENERATED_TOOLS if name in raw_per_tool}
    text = _guidance_text(final)
    selection = row.get("model_selection") if isinstance(row.get("model_selection"), Mapping) else {}
    return CostReceipt(
        context_id=str(row.get("context_id") or ""),
        guidance_chars=guidance_chars,
        per_tool_chars=per_tool,
        guidance_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest() if text is not None else None,
        comparison_in_guidance=None if text is None else bool(re.search(r"compar", text, re.IGNORECASE)),
        provider=selection.get("effective_provider") or selection.get("chat_provider") or selection.get("default_provider"),
        model=selection.get("effective_model") or selection.get("chat_model") or selection.get("default_model"),
    )


def _context_dirs() -> list[Path]:
    from agent_runtime import paths

    return [paths.prompt_observability_dir(), paths.prompt_observability_archive_dir()]


def _load_row(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def read_cost(
    home: str | os.PathLike[str],
    context_id: str,
    *,
    runtime_root: str | os.PathLike[str] | None = None,
) -> CostReceipt | None:
    """The cost receipt of row *context_id* (live dir, then archive), or ``None``."""

    with _home_scope(home, runtime_root):
        for directory in _context_dirs():
            row = _load_row(directory / f"{context_id}.json")
            if row is not None:
                return cost_receipt(row)
    return None


def find_context_id(
    home: str | os.PathLike[str],
    *,
    session_id: str,
    turn_id: str | None,
    runtime_root: str | os.PathLike[str] | None = None,
) -> str | None:
    """The ``ctx_`` row of this turn: same ``turn_id`` first, else the session's newest row."""

    session_rows: list[tuple[float, str]] = []
    with _home_scope(home, runtime_root):
        for directory in _context_dirs():
            for path in directory.glob("ctx_*.json") if directory.is_dir() else ():
                row = _load_row(path)
                if row is None or row.get("session_id") != session_id:
                    continue
                if turn_id and row.get("turn_id") == turn_id:
                    return str(row.get("context_id") or path.stem)
                session_rows.append((path.stat().st_mtime, str(row.get("context_id") or path.stem)))
    return max(session_rows)[1] if session_rows else None


# ── the score ───────────────────────────────────────────────────────────────

COMPARISON = "comparison"
CONTROL = "control"


@dataclass(frozen=True)
class PromptResult:
    """One prompt's turn, on one agent, as read back."""

    prompt_id: str
    kind: str  # COMPARISON | CONTROL
    agent: str
    outcome: TurnOutcome | None
    cost: CostReceipt | None = None
    provider: str | None = None

    @property
    def provider_key(self) -> str:
        return self.provider or (self.cost.provider if self.cost else None) or "unknown"


@dataclass(frozen=True)
class ArmScore:
    """One (agent, provider) cell of an arm."""

    agent: str
    provider: str
    hits: int
    comparisons: int
    misses: tuple[str, ...]
    controls_prose: int
    controls: int
    control_failures: tuple[str, ...]
    unread: tuple[str, ...]
    cost_chars: int | None
    guidance_sha256: str | None = None

    @property
    def cost_tokens(self) -> float | None:
        return None if self.cost_chars is None else self.cost_chars / 4


def score(results: Iterable[PromptResult]) -> list[ArmScore]:
    """Group *results* by (agent, provider) and count hits, prose controls and cost.

    A comparison scores only on a hit (``TurnOutcome.is_hit``); a control passes only
    when no generated tool was called. An unread or unsettled turn is neither: it is
    named in ``unread`` and counts as a miss / a failed control.
    """

    groups: dict[tuple[str, str], list[PromptResult]] = {}
    for result in results:
        groups.setdefault((result.agent, result.provider_key), []).append(result)
    scores: list[ArmScore] = []
    for (agent, provider), cell in sorted(groups.items()):
        comparisons = [item for item in cell if item.kind == COMPARISON]
        controls = [item for item in cell if item.kind == CONTROL]
        unread = tuple(item.prompt_id for item in cell if item.outcome is None or not item.outcome.settled)
        hit_ids = {item.prompt_id for item in comparisons if item.outcome and item.outcome.settled and item.outcome.is_hit}
        prose_ids = {
            item.prompt_id
            for item in controls
            if item.outcome and item.outcome.settled and not item.outcome.called_generated
        }
        costs = [item.cost for item in cell if item.cost is not None]
        shas = sorted({cost.guidance_sha256 for cost in costs if cost.guidance_sha256})
        scores.append(
            ArmScore(
                agent=agent,
                provider=provider,
                hits=len(hit_ids),
                comparisons=len(comparisons),
                misses=tuple(item.prompt_id for item in comparisons if item.prompt_id not in hit_ids),
                controls_prose=len(prose_ids),
                controls=len(controls),
                control_failures=tuple(item.prompt_id for item in controls if item.prompt_id not in prose_ids),
                unread=unread,
                cost_chars=max((cost.total_chars for cost in costs), default=None),
                guidance_sha256=",".join(shas) or None,
            )
        )
    return scores
