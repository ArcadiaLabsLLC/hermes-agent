"""GenUI first-response A/B eval (RT-VERIFY-IMPROVE-FIRST-RESPONSE) — a receipt reader.

Plan: ``docs/agent-runtime-harness/planned/p10-agent-2026-10-19.md`` §3. The question is
whether a comparison prompt's FIRST tool call is the generated-content list or create
tool (and the turn creates a document) instead of a Markdown
table, per agent and provider, under two Launcher guidance arms that are switched by QA
build (owner ruling 2026-10-19), and what the guidance costs per turn.

This module never starts a serve, never calls a provider and never sends a message. It
reads two receipts a QA serve already writes under its ``HERMES_HOME``:

- the turn record (``agent_runtime.mission_chat_turns.reads.mission_chat_turn_record``):
  the turn's ``tool`` / ``segment`` elements and its settle state;
- the mission-chat observability row ``ctx_<hash>.json``
  (``agent_runtime.prompt_observability``): ``final_model_input.system_prompt_sections``
  blocks and ``final_model_input.tool_schema.per_tool_chars``.

Stages: G1 reader (``read_turn``, ``read_cost``, ``score``); G2 driver (``drive`` writes the
MCP steps and ``verify-route`` checks their Console readbacks before a send; ``collect`` joins
the acknowledged session to its actual turn and model); G3 report applies the pass bar.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from collections import Counter
from collections.abc import Iterable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

#: Tool names are never spelled here (R10 gates): each is read off the vendored Launcher catalog
#: (``tests/fixtures/launcher_app_functions_catalog.json``, ``scripts/vendor_launcher_catalog.py``) by entry id.
CATALOG_PATH = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "launcher_app_functions_catalog.json"


def _tool_names(*entry_ids: str) -> tuple[str, ...]:
    by_id = {e["id"]: e["name"] for e in json.loads(CATALOG_PATH.read_text(encoding="utf-8"))["entries"]}
    return tuple(by_id[entry_id] for entry_id in entry_ids)


#: A hit's first tool: the catalog read or the create itself (plan §3.2).
HIT_FIRST_TOOLS = frozenset(_tool_names("launcher.generated.list", "launcher.generated.create"))
(CREATE_TOOL,) = _tool_names("launcher.generated.create")
#: The five generated tools the Launcher declares ``alwaysLoaded``
#: (``EterniaLauncher/lib/core/services/hermes/runtime/data/capabilities/harness_generated_capabilities.dart``).
GENERATED_TOOLS = _tool_names(
    "launcher.generated.list",
    "launcher.generated.inspect",
    "launcher.generated.create",
    "launcher.generated.update",
    "launcher.generated.edit",
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
    persona_instance_id: str | None = None

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
        persona_instance_id=record.get("persona_instance_id"),
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
        provider=selection.get("effective_provider"),
        model=selection.get("effective_model"),
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
    turn_id: str,
    runtime_root: str | os.PathLike[str] | None = None,
) -> str | None:
    """The context receipt for this exact turn and session."""

    with _home_scope(home, runtime_root):
        for directory in _context_dirs():
            for path in directory.glob("ctx_*.json") if directory.is_dir() else ():
                row = _load_row(path)
                if row and row.get("session_id") == session_id and row.get("turn_id") == turn_id:
                    return str(row.get("context_id") or path.stem)
    return None


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
    model: str | None = None
    route_error: str | None = None

    @property
    def verification_error(self) -> str | None:
        if self.route_error:
            return self.route_error
        if self.outcome is None or not self.outcome.settled:
            return "the fresh chat has no settled turn"
        if not self.cost or not self.cost.provider or not self.cost.model:
            return "this turn has no effective provider/model receipt"
        if (self.cost.provider, self.cost.model) != (self.provider, self.model):
            return "the observed provider/model differs from the planned route"
        return None


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
    comparison_in_guidance: bool | None = None
    create_wire_chars: int | None = None
    model: str | None = None

    @property
    def cost_tokens(self) -> float | None:
        return None if self.cost_chars is None else self.cost_chars / 4


def score(results: Iterable[PromptResult]) -> list[ArmScore]:
    """Put every planned prompt in its cell and count only verified turns."""

    groups: dict[tuple[str, str], list[PromptResult]] = {}
    for result in results:
        groups.setdefault((result.agent, result.provider or "unknown"), []).append(result)
    scores: list[ArmScore] = []
    for (agent, provider), cell in sorted(groups.items()):
        comparisons = [item for item in cell if item.kind == COMPARISON]
        controls = [item for item in cell if item.kind == CONTROL]
        verified = [item for item in cell if item.verification_error is None]
        unread = tuple(item.prompt_id for item in cell if item.verification_error is not None)
        hit_ids = {item.prompt_id for item in verified
                   if item.kind == COMPARISON and item.outcome and item.outcome.is_hit}
        prose_ids = {
            item.prompt_id
            for item in verified
            if item.kind == CONTROL and item.outcome and item.outcome.prose_only
        }
        costs = [item.cost for item in verified if item.cost is not None]
        shas = sorted({cost.guidance_sha256 for cost in costs if cost.guidance_sha256})
        models = {cost.model for cost in costs}
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
                comparison_in_guidance=all(flags) if (flags := [
                    c.comparison_in_guidance for c in costs if c.comparison_in_guidance is not None
                ]) else None,
                create_wire_chars=max(
                    (c.per_tool_chars[CREATE_TOOL] for c in costs if CREATE_TOOL in c.per_tool_chars), default=None
                ),
                model=next(iter(models)) if len(models) == 1 else None,
            )
        )
    return scores


# ── G2 the driver: the MCP step list, then the read-back ────────────────────

#: The launcher_qa MCP's agent-chat verbs the orchestrating session issues (plan §3.3).
OP_NEW = "launcher.agent_chat.new"
OP_SEND = "launcher.agent_chat.send"
OP_SELECT = "launcher.mission_control.agent.select"
OP_CHAT_LIST = "launcher.agent_chat.list"
OP_MODEL_SET = "launcher.agent.model.set"
OP_MODEL_LIST = "launcher.agent.model.list"
OP_VERIFY = "verify_route"
OP_WAIT = "wait_turn_settled"


def load_prompts(path: str | os.PathLike[str]) -> list[tuple[str, str, str]]:
    """``(prompt_id, kind, text)`` for the comparisons, then the controls."""

    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return [(item["id"], COMPARISON, item["text"]) for item in data["comparisons"]] + [
        (item["id"], CONTROL, item["text"]) for item in data["controls"]
    ]


def session_ref(agent: str, provider: str, prompt_id: str) -> str:
    """One chat per (agent, provider, prompt): no prompt rides another's cached prefix."""

    return f"{agent}/{provider}/{prompt_id}"


def drive(
    arm: str,
    prompts: list[tuple[str, str, str]],
    agents: Mapping[str, str],
    providers: Mapping[str, str],
) -> dict[str, Any]:
    """The step list the orchestrator runs over the launcher_qa MCP, visible before approval.

    Select the exact Console agent, make one fresh chat, then set and verify its model route.
    The operator stores the app-function results under ``session_ref``. The historical send
    acknowledges its session only; collection reads the one admitted turn from that journal.
    """

    steps: list[dict[str, Any]] = []
    for agent, agent_id in agents.items():
        for provider, model in providers.items():
            for prompt_id, kind, text in prompts:
                ref = session_ref(agent, provider, prompt_id)
                common = {"session_ref": ref, "agent": agent, "agent_id": agent_id,
                          "provider": provider, "model": model, "prompt_id": prompt_id}
                steps.extend([
                    {"op": OP_SELECT, "args": {"agent_id": agent_id}, **common},
                    {"op": OP_NEW, "args": {}, "receipt": "new", **common},
                    {"op": OP_MODEL_SET, "args": {"provider_id": provider, "model_id": model},
                     "approval_required": True, **common},
                    {"op": OP_MODEL_LIST, "args": {}, "receipt": "model", **common},
                    {"op": OP_CHAT_LIST, "args": {}, "receipt": "chat", **common},
                    {"op": OP_VERIFY, **common},
                    {"op": OP_SEND, "args": {"text": text}, "kind": kind,
                     "receipt": "send", "approval_required": True, **common},
                    {"op": OP_WAIT, **common},
                ])
    for index, step in enumerate(steps, 1):
        step["step"] = f"s{index:03d}"
    return {
        "schema_version": 2,
        "arm": arm,
        "sends_file_shape": {"<session_ref>": {key: f"<app-function result of {op}>" for key, op in (
            ("new", OP_NEW), ("model", OP_MODEL_LIST), ("chat", OP_CHAT_LIST), ("send", OP_SEND),
        )}},
        "steps": steps,
    }


def _record(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _records(value: Any) -> Iterator[Mapping[str, Any]]:
    return (item for item in value if isinstance(item, Mapping)) if isinstance(value, list) else iter(())


def _route_error(step: Mapping[str, Any], receipts: Mapping[str, Any]) -> str | None:
    """Accept only the intended fresh Console session and its selected model."""

    opened = _record(receipts.get("new"))
    chat = _record(receipts.get("chat"))
    agent = _record(chat.get("agent"))
    session_id = opened.get("session_id")
    if not isinstance(session_id, str) or not session_id or chat.get("open_session_id") != session_id:
        return "the Console did not confirm the fresh session"
    if (agent.get("instance_id"), agent.get("name"), opened.get("agent")) != (
        step["agent_id"], step["agent"], step["agent"],
    ):
        return "the Console selected a different agent"
    if not any(chat_row.get("session_id") == session_id and chat_row.get("message_count") == 0
               for chat_row in _records(chat.get("chats"))):
        return "the Console did not read back an empty new chat"
    model = _record(receipts.get("model"))
    selected = [
        (section.get("provider_id"), option.get("model_id"))
        for section in _records(model.get("providers"))
        for option in _records(section.get("models")) if option.get("selected") is True
    ]
    if model.get("agent") != step["agent"] or model.get("available") is not True or selected != [
        (step["provider"], step["model"]),
    ]:
        return "the Console did not confirm the selected provider/model"
    return None


def _settled_turn(
    home: str | os.PathLike[str],
    session_id: str,
    *,
    runtime_root: str | os.PathLike[str] | None,
    wait_seconds: float,
    poll_seconds: float = 2.0,
) -> tuple[TurnOutcome | None, str | None]:
    from agent_runtime.mission_chat_turns.reads import mission_chat_turn_records

    deadline = time.monotonic() + wait_seconds
    while True:
        with _home_scope(home, runtime_root):
            turns = mission_chat_turn_records(session_id=session_id)
        if len(turns) > 1:
            return None, "the fresh session has more than one journal turn"
        if turns and (outcome := turn_outcome(turns[0])).settled:
            return outcome, None
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return None, "the fresh session has no settled journal turn"
        time.sleep(min(poll_seconds, remaining))


def collect(
    home: str | os.PathLike[str],
    plan: Mapping[str, Any],
    sends: Mapping[str, Mapping[str, Any]],
    *,
    runtime_root: str | os.PathLike[str] | None = None,
    wait_seconds: float = 0.0,
) -> list[PromptResult]:
    """Correlate app-function acknowledgments with the exact turn and its effective model."""

    if plan.get("schema_version") != 2:
        raise ValueError("generate a new plan with selected-agent and model readbacks")
    session_counts = Counter(
        session_id for receipt in sends.values()
        if isinstance(session_id := _record(_record(receipt).get("new")).get("session_id"), str)
    )
    results: list[PromptResult] = []
    for step in _send_steps(plan):
        receipts = _record(sends.get(step["session_ref"]))
        session_id = _record(receipts.get("new")).get("session_id")
        sent = _record(receipts.get("send"))
        error = _route_error(step, receipts)
        outcome = cost = None
        if error is None and (sent.get("sent") is not True or sent.get("session_id") != session_id
                              or sent.get("agent") != step["agent"]):
            error = "the Console did not acknowledge a send to the verified session"
        if error is None and session_counts[session_id] != 1:
            error = "multiple planned prompts share the same new session"
        if error is None:
            outcome, error = _settled_turn(home, session_id, runtime_root=runtime_root, wait_seconds=wait_seconds)
        if outcome is not None:
            if outcome.persona_instance_id != step["agent_id"]:
                error = "the journal turn belongs to a different agent"
            context_id = find_context_id(home, session_id=session_id, turn_id=outcome.turn_id,
                                         runtime_root=runtime_root)
            cost = read_cost(home, context_id, runtime_root=runtime_root) if context_id else None
        results.append(PromptResult(prompt_id=step["prompt_id"], kind=step["kind"], agent=step["agent"],
                                    outcome=outcome, cost=cost, provider=step["provider"], model=step["model"],
                                    route_error=error))
    return results


def _send_steps(plan: Mapping[str, Any]) -> Iterator[Mapping[str, Any]]:
    return (step for step in plan["steps"] if step["op"] == OP_SEND)


# ── G3 the report: the pass bar applied ─────────────────────────────────────

#: Pass bar per (agent, provider) cell (plan §3.2): ≥ 10/12 first-tool hits, every control
#: prose, and the guidance's per-turn cost ≤ +80 tokens (chars/4) over the baseline arm.
HIT_BAR = (10, 12)
COST_CEILING_TOKENS = 80


def cell_verdict(cell: ArmScore, baseline: ArmScore | None = None) -> tuple[str, float | None]:
    """The acceptance label and the comparable per-turn cost delta."""

    if cell.unread or not cell.model or (baseline is not None and (baseline.unread or baseline.model != cell.model)):
        return "UNVERIFIED", None
    selection = (
        cell.comparisons > 0
        and cell.hits * HIT_BAR[1] >= HIT_BAR[0] * cell.comparisons
        and cell.controls > 0
        and cell.controls_prose == cell.controls
    )
    delta = None
    if baseline is not None and cell.cost_tokens is not None and baseline.cost_tokens is not None:
        delta = cell.cost_tokens - baseline.cost_tokens
    if not selection:
        return "FAIL", delta
    if baseline is not None and (delta is None or delta > COST_CEILING_TOKENS):
        return "OVER COST", delta
    return "PASS", delta


def report(
    scores: list[ArmScore],
    *,
    arm: str,
    baseline: list[ArmScore] | None = None,
    baseline_arm: str | None = None,
    build: str | None = None,
) -> str:
    """The arm's table (agent × provider: hits, misses, controls, cost, verdict) as Markdown."""

    base = {(cell.agent, cell.provider): cell for cell in baseline or []}
    lines = [f"## Arm {arm}" + (f" vs baseline {baseline_arm}" if baseline_arm else ""), ""]
    if build:
        lines += [f"Launcher QA build: `{build}`", ""]
    without = sorted({f"{c.agent}/{c.provider}" for c in scores if c.comparison_in_guidance is False})
    if without:
        wire = max((c.create_wire_chars for c in scores if c.create_wire_chars is not None), default=None)
        lines += [
            f"**First:** the tool-guidance section carries no comparison trigger ({', '.join(without)}); the "
            f"create entry reaches the model only as its one-line wire brief ({wire} chars). The Launcher "
            "wording moves the trigger into `guidance` before any further variant.",
            "",
        ]
    lines += [
        "| agent | provider | hits | misses | controls prose | cost chars | tokens | Δ tokens | guidance sha | verdict |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for cell in scores:
        comparison = base.get((cell.agent, cell.provider))
        verdict, delta = (("UNVERIFIED", None) if baseline is not None and comparison is None
                          else cell_verdict(cell, comparison))
        tokens = "—" if cell.cost_tokens is None else f"{cell.cost_tokens:.0f}"
        failed = f" (failed {', '.join(cell.control_failures)})" if cell.control_failures else ""
        lines.append(
            f"| {cell.agent} | {cell.provider} | {cell.hits}/{cell.comparisons} | {', '.join(cell.misses) or '—'} "
            f"| {cell.controls_prose}/{cell.controls}{failed} "
            f"| {cell.cost_chars if cell.cost_chars is not None else '—'} | {tokens} "
            f"| {'—' if delta is None else f'{delta:+.0f}'} | {(cell.guidance_sha256 or '—')[:12]} | {verdict} |"
        )
    unread = [f"{c.agent}/{c.provider}: {', '.join(c.unread)}" for c in scores if c.unread]
    if unread:
        lines += ["", "Unverified turns (cell ineligible): " + "; ".join(unread)]
    lines += ["", f"Bar: ≥ {HIT_BAR[0]}/{HIT_BAR[1]} first-tool hits, every control prose, "
              f"≤ +{COST_CEILING_TOKENS} tokens/turn over the baseline arm."]
    return "\n".join(lines) + "\n"


# ── the owner-sitting command line ──────────────────────────────────────────


def _scores_from(path: str | os.PathLike[str]) -> tuple[str, list[ArmScore], str | None]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    cells = [
        ArmScore(**{**cell, **{key: tuple(cell[key]) for key in ("misses", "control_failures", "unread")}})
        for cell in data["scores"]
    ]
    return data["arm"], cells, data.get("build")


def main(argv: list[str] | None = None) -> int:
    import argparse
    from dataclasses import asdict

    parser = argparse.ArgumentParser(description="GenUI first-response A/B eval (receipt reader)")
    sub = parser.add_subparsers(dest="command", required=True)
    plan_cmd = sub.add_parser("plan", help="write the MCP step list (sends nothing)")
    plan_cmd.add_argument("--arm", required=True)
    plan_cmd.add_argument("--agent", action="append", required=True, metavar="NAME=INSTANCE_ID")
    plan_cmd.add_argument("--provider", action="append", required=True, metavar="PROVIDER_ID=MODEL_ID")
    plan_cmd.add_argument("--prompts", default=str(Path(__file__).with_name("genui_first_response_prompts.json")))
    plan_cmd.add_argument("--out", required=True)
    verify_cmd = sub.add_parser("verify-route", help="validate one planned chat's readbacks before sending")
    verify_cmd.add_argument("--plan", required=True)
    verify_cmd.add_argument("--session-ref", required=True)
    verify_cmd.add_argument("--receipts", required=True, help="sends-file object with new, model and chat results")
    collect_cmd = sub.add_parser("collect", help="read the sent turns back from the QA home")
    collect_cmd.add_argument("--home", required=True)
    collect_cmd.add_argument("--runtime-root")
    collect_cmd.add_argument("--plan", required=True)
    collect_cmd.add_argument("--sends", required=True)
    collect_cmd.add_argument("--build", help="the Launcher QA build stamp of this arm")
    collect_cmd.add_argument("--wait-seconds", type=float, default=600.0)
    collect_cmd.add_argument("--out", required=True)
    report_cmd = sub.add_parser("report", help="apply the pass bar and write the Markdown table")
    report_cmd.add_argument("--results", required=True)
    report_cmd.add_argument("--baseline")
    report_cmd.add_argument("--out", required=True)
    args = parser.parse_args(argv)

    if args.command == "plan":
        plan = drive(args.arm, load_prompts(args.prompts), _assignments(plan_cmd, args.agent),
                     _assignments(plan_cmd, args.provider))
        Path(args.out).write_text(json.dumps(plan, indent=2), encoding="utf-8")
        return 0
    if args.command == "verify-route":
        plan = json.loads(Path(args.plan).read_text(encoding="utf-8"))
        if plan.get("schema_version") != 2:
            verify_cmd.error("generate a new plan with selected-agent and model readbacks")
        step = next((step for step in _send_steps(plan) if step["session_ref"] == args.session_ref), None)
        if step is None:
            verify_cmd.error(f"no planned chat for {args.session_ref}")
        saved = _record(json.loads(Path(args.receipts).read_text(encoding="utf-8")))
        refusal = _route_error(step, _record(saved.get(args.session_ref)))
        if refusal:
            print(f"Unverified {args.session_ref}: {refusal}")
            return 1
        print(f"Verified {args.session_ref}")
        return 0
    if args.command == "collect":
        plan = json.loads(Path(args.plan).read_text(encoding="utf-8"))
        sends = json.loads(Path(args.sends).read_text(encoding="utf-8"))
        results = collect(args.home, plan, sends, runtime_root=args.runtime_root, wait_seconds=args.wait_seconds)
        payload = {
            "arm": plan["arm"],
            "build": args.build,
            "results": [{**asdict(item), "verification_error": item.verification_error} for item in results],
            "scores": [asdict(cell) for cell in score(results)],
        }
        Path(args.out).write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return 0
    arm, scores, build = _scores_from(args.results)
    baseline_arm, baseline, _ = _scores_from(args.baseline) if args.baseline else (None, None, None)
    text = report(scores, arm=arm, baseline=baseline, baseline_arm=baseline_arm, build=build)
    Path(args.out).write_text(text, encoding="utf-8")
    return 0


def _assignments(parser, pairs: list[str]) -> dict[str, str]:
    values: dict[str, str] = {}
    for pair in pairs:
        name, _, value = pair.partition("=")
        if not name or not value or name in values:
            parser.error(f"expected a unique NAME=ID binding, got {pair!r}")
        values[name] = value
    return values


if __name__ == "__main__":
    raise SystemExit(main())
