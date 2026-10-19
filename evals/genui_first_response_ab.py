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
MCP step list the orchestrating session runs; ``collect`` reads each sent turn back); G3 report
(``report`` applies the pass bar). The owner-sitting run is ``main``'s three subcommands.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
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
    comparison_in_guidance: bool | None = None
    create_wire_chars: int | None = None

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
                comparison_in_guidance=all(flags) if (flags := [
                    c.comparison_in_guidance for c in costs if c.comparison_in_guidance is not None
                ]) else None,
                create_wire_chars=max(
                    (c.per_tool_chars[CREATE_TOOL] for c in costs if CREATE_TOOL in c.per_tool_chars), default=None
                ),
            )
        )
    return scores


# ── G2 the driver: the MCP step list, then the read-back ────────────────────

#: The launcher_qa MCP's agent-chat verbs the orchestrating session issues (plan §3.3).
OP_NEW = "launcher.agent_chat.new"
OP_SEND = "launcher.agent_chat.send"
OP_WAIT = "wait_turn_settled"


def load_prompts(path: str | os.PathLike[str]) -> list[tuple[str, str, str]]:
    """``(prompt_id, kind, text)`` for the comparisons, then the controls."""

    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return [(item["id"], COMPARISON, item["text"]) for item in data["comparisons"]] + [
        (item["id"], CONTROL, item["text"]) for item in data["controls"]
    ]


def session_ref(agent: str, provider: str | None, prompt_id: str) -> str:
    """One chat per (agent, provider, prompt): no prompt rides another's cached prefix."""

    return f"{agent}/{provider or 'default'}/{prompt_id}"


def drive(
    arm: str,
    prompts: list[tuple[str, str, str]],
    agents: Iterable[str],
    providers: Iterable[str | None] = (None,),
) -> dict[str, Any]:
    """The step list the orchestrator runs over the launcher_qa MCP, visible before approval.

    Per (agent, provider, prompt): ``agent_chat.new`` (opens ``session_ref``), ``agent_chat.send``
    of the prompt into that chat, then a wait on the turn's settle. This function sends nothing;
    the orchestrator records each new chat's ``session_id`` and each send's
    ``client_message_id`` under its ``session_ref`` in the sends file ``collect`` reads.
    """

    steps: list[dict[str, Any]] = []
    for agent in agents:
        for provider in providers:
            for prompt_id, kind, text in prompts:
                ref = session_ref(agent, provider, prompt_id)
                new_args: dict[str, Any] = {"agent": agent}
                if provider:
                    new_args["provider"] = provider
                common = {"session_ref": ref, "agent": agent, "provider": provider, "prompt_id": prompt_id}
                steps.append({"op": OP_NEW, "args": new_args, **common})
                steps.append({"op": OP_SEND, "args": {"text": text, "confirm": True}, "kind": kind, **common})
                steps.append({"op": OP_WAIT, **common})
    for index, step in enumerate(steps, 1):
        step["step"] = f"s{index:03d}"
    return {
        "schema_version": 1,
        "arm": arm,
        "sends_file_shape": {"<session_ref>": {"session_id": "<from agent_chat.new>",
                                               "client_message_id": "<from agent_chat.send>"}},
        "steps": steps,
    }


def _settled_turn(
    home: str | os.PathLike[str],
    session_id: str,
    client_message_id: str,
    *,
    runtime_root: str | os.PathLike[str] | None,
    wait_seconds: float,
    poll_seconds: float = 2.0,
) -> TurnOutcome | None:
    deadline = time.monotonic() + wait_seconds
    while True:
        outcome = read_turn(home, session_id, client_message_id, runtime_root=runtime_root)
        if (outcome is not None and outcome.settled) or time.monotonic() >= deadline:
            return outcome
        time.sleep(poll_seconds)


def collect(
    home: str | os.PathLike[str],
    plan: Mapping[str, Any],
    sends: Mapping[str, Mapping[str, str]],
    *,
    runtime_root: str | os.PathLike[str] | None = None,
    wait_seconds: float = 0.0,
) -> list[PromptResult]:
    """Read every sent turn of *plan* back from the QA home (a missing send reads as unread)."""

    results: list[PromptResult] = []
    for step in plan["steps"]:
        if step["op"] != OP_SEND:
            continue
        sent = sends.get(step["session_ref"]) or {}
        session_id, message_id = sent.get("session_id"), sent.get("client_message_id")
        outcome = cost = None
        if session_id and message_id:
            outcome = _settled_turn(home, session_id, message_id, runtime_root=runtime_root,
                                    wait_seconds=wait_seconds)
            context_id = find_context_id(home, session_id=session_id,
                                         turn_id=outcome.turn_id if outcome else None, runtime_root=runtime_root)
            cost = read_cost(home, context_id, runtime_root=runtime_root) if context_id else None
        results.append(PromptResult(prompt_id=step["prompt_id"], kind=step["kind"], agent=step["agent"],
                                    outcome=outcome, cost=cost, provider=step.get("provider")))
    return results


# ── G3 the report: the pass bar applied ─────────────────────────────────────

#: Pass bar per (agent, provider) cell (plan §3.2): ≥ 10/12 first-tool hits, every control
#: prose, and the guidance's per-turn cost ≤ +80 tokens (chars/4) over the baseline arm.
HIT_BAR = (10, 12)
COST_CEILING_TOKENS = 80


def cell_verdict(cell: ArmScore, baseline: ArmScore | None = None) -> tuple[str, float | None]:
    """``("PASS" | "FAIL" | "OVER COST", cost delta in tokens)``; a selection pass over the
    cost ceiling is reported, not adopted."""

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
        verdict, delta = cell_verdict(cell, base.get((cell.agent, cell.provider)) if baseline is not None else None)
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
        lines += ["", "Unread or unsettled turns (scored as misses): " + "; ".join(unread)]
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
    plan_cmd.add_argument("--agent", action="append", required=True)
    plan_cmd.add_argument("--provider", action="append")
    plan_cmd.add_argument("--prompts", default=str(Path(__file__).with_name("genui_first_response_prompts.json")))
    plan_cmd.add_argument("--out", required=True)
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
        plan = drive(args.arm, load_prompts(args.prompts), args.agent, args.provider or [None])
        Path(args.out).write_text(json.dumps(plan, indent=2), encoding="utf-8")
        return 0
    if args.command == "collect":
        plan = json.loads(Path(args.plan).read_text(encoding="utf-8"))
        sends = json.loads(Path(args.sends).read_text(encoding="utf-8"))
        results = collect(args.home, plan, sends, runtime_root=args.runtime_root, wait_seconds=args.wait_seconds)
        payload = {"arm": plan["arm"], "build": args.build, "results": [asdict(item) for item in results],
                   "scores": [asdict(cell) for cell in score(results)]}
        Path(args.out).write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return 0
    arm, scores, build = _scores_from(args.results)
    baseline_arm, baseline, _ = _scores_from(args.baseline) if args.baseline else (None, None, None)
    text = report(scores, arm=arm, baseline=baseline, baseline_arm=baseline_arm, build=build)
    Path(args.out).write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
