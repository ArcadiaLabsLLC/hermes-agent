"""The harness agents' background skill-review prompts (RT-REVIEW-WRITE-BIAS-UPSTREAM,
RT-CURATOR-COST-FROM-TURN-RECORD).

Upstream's skill review prompt tells every agent "Be ACTIVE — most sessions produce at least one
skill update … A pass that does nothing is a missed learning opportunity", and the review sees only
the transcript, where a terminal result carries no duration. So a clean, ordinary turn was pushed to
write something and could only write what a tool PRINTED: after the owner's Neko trial the review
wrote "it takes a few seconds" about a ``flutter test`` call whose measured ``duration_ms`` was
202601 (flutter's printed ``00:01`` starts after the compile).

RULED 2026-10-25: fork only, through upstream's own door — ``AIAgent`` exposes the prompts as class
attributes "so per-agent overrides work" (``agent.background_review.spawn_background_review_thread``
reads ``getattr(agent, name)`` at spawn). :func:`arm_review_prompts` sets the two skill-bearing
overrides on a persona-turn agent:

* the always-write push is cut (:data:`PUSH_CUTS`; :func:`remaining_push` names any upstream
  sentence a merge added back), and
* a verifiable-claims rule plus this turn's **measured** tool timings are appended, so any cost,
  duration, count or "fast" a review writes comes from the runtime's clock, never a tool's output.

The timings are folded by the plugin's ``post_tool_call`` hook (:func:`on_post_tool_call`, the
hook's ``duration_ms`` — the runtime's own measurement of the call) onto the agent for the turn in
flight; a new turn id starts a new ledger. ``_MEMORY_REVIEW_PROMPT`` is untouched.
"""

from __future__ import annotations

import json
from typing import Any

__layer__ = "policy"
__all__ = [
    "PUSH_CUTS", "VERIFIABLE_CLAIMS_BLOCK", "arm_review_prompts", "harness_review_prompts",
    "on_post_tool_call", "remaining_push", "timings_block",
]

#: Upstream's always-write sentences and what a harness agent reads instead.
PUSH_CUTS: tuple[tuple[str, str], ...] = (
    ("Be ACTIVE — most sessions produce at least one skill update, even if small. A pass that does "
     "nothing is a missed learning opportunity, not a neutral outcome.\n\n",
     "Write only on a real signal below. An ordinary turn that went to plan needs no update, and "
     "'Nothing to save.' is a correct outcome.\n\n"),
    ("'Nothing to save.' is a real option but should NOT be the default. If the session ran "
     "smoothly with no corrections and produced no new technique, just say 'Nothing to save.' and "
     "stop. Otherwise, act.",
     "If the session ran smoothly with no corrections and produced no new technique, say "
     "'Nothing to save.' and stop."),
    ("Be ACTIVE — most sessions produce at least one skill update. A pass that does nothing is a "
     "missed learning opportunity, not a neutral outcome.\n\n",
     "Write a skill only on a real signal below; an ordinary turn needs none.\n\n"),
    ("If genuinely nothing stands out on either, say 'Nothing to save.' and stop — but don't reach "
     "for that conclusion as a default.",
     "If nothing stands out on either, say 'Nothing to save.' and stop."),
)

#: Phrases that mean upstream's push survived (a merge reworded a cut sentence).
_PUSH_MARKERS = ("Be ACTIVE", "missed learning opportunity", "should NOT be the default", "as a default")

VERIFIABLE_CLAIMS_BLOCK = (
    "\n\nVerifiable claims (this harness): a cost, a duration, a count, or a 'fast' / 'slow' / "
    "'takes a few seconds' claim may go into a skill ONLY from the measured timings listed below — "
    "never from a time a tool printed in its output (a test runner's clock starts after its compile) "
    "and never from memory. If the step you would recommend is the one that dominated this turn's "
    "wall time, name the cheaper alternative this turn itself shows (a call that timed out, was "
    "retried, or did the same job faster), or do not recommend it."
)

_TIMINGS_TOP = 12
_LEDGER_MAX = 200
_COMMAND_LIMIT = 160
_LEDGER_ATTR = "_hermes_review_tool_timings"


def remaining_push(prompt: str) -> list[str]:
    """The upstream push phrases still in ``prompt`` (empty for a correctly derived override)."""
    return [marker for marker in _PUSH_MARKERS if marker in prompt]


def harness_review_prompts() -> tuple[str, str]:
    """``(skill, combined)`` — upstream's two skill-bearing prompts with the push cut."""
    from agent_runtime._upstream_doors import background_review_prompts

    derived = []
    for base in background_review_prompts():
        for old, new in PUSH_CUTS:
            base = base.replace(old, new)
        derived.append(base + VERIFIABLE_CLAIMS_BLOCK)
    return derived[0], derived[1]


def timings_block(rows: list[dict[str, Any]]) -> str:
    """This turn's measured tool timings, slowest first, as the review reads them."""
    if not rows:
        return ("\n\nMeasured tool timings for this turn: none recorded — write no cost, duration or "
                "speed claim.")
    total = sum(int(row.get("duration_ms") or 0) for row in rows)
    lines = [f"\n\nMeasured tool timings for this turn (the runtime's duration_ms; {len(rows)} call(s), "
             f"{total} ms in tools; slowest {min(len(rows), _TIMINGS_TOP)} first):"]
    for row in sorted(rows, key=lambda item: -int(item.get("duration_ms") or 0))[:_TIMINGS_TOP]:
        flag = " TIMED OUT" if row.get("timed_out") else ""
        code = f" exit {row['exit_code']}" if row.get("exit_code") is not None else ""
        command = f": {row['command']}" if row.get("command") else ""
        lines.append(f"  - {row.get('name')} {int(row.get('duration_ms') or 0)} ms{flag}{code}{command}")
    return "\n".join(lines)


def _ledger(agent: Any) -> list[dict[str, Any]]:
    turn_id = str(getattr(agent, "_persona_chat_turn_id", None) or "")
    ledger = getattr(agent, _LEDGER_ATTR, None)
    if not isinstance(ledger, dict) or ledger.get("turn_id") != turn_id:
        ledger = {"turn_id": turn_id, "rows": []}
        setattr(agent, _LEDGER_ATTR, ledger)
    return ledger["rows"]


def arm_review_prompts(agent: Any) -> None:
    """Set the per-agent skill and combined review overrides for the turn in flight."""
    if agent is None:
        return
    skill, combined = harness_review_prompts()
    block = timings_block(_ledger(agent))
    agent._SKILL_REVIEW_PROMPT = skill + block
    agent._COMBINED_REVIEW_PROMPT = combined + block


def _exit_code(result: Any) -> int | None:
    payload = result
    if isinstance(payload, str) and payload.strip().startswith("{"):
        try:
            payload = json.loads(payload, strict=False)
        except ValueError:
            return None
    code = payload.get("exit_code") if isinstance(payload, dict) else None
    return code if type(code) is int else None


def on_post_tool_call(tool_name: Any = None, args: Any = None, result: Any = None,
                      duration_ms: Any = None, **_context: Any) -> None:
    """``post_tool_call``: fold one measured call into the bound persona turn's ledger, re-arm."""
    from agent_runtime.persona_turn_binding import current_persona_turn_agent

    agent = current_persona_turn_agent()
    if agent is None:
        return
    rows = _ledger(agent)
    if len(rows) < _LEDGER_MAX and type(duration_ms) in (int, float) and duration_ms >= 0:
        code = _exit_code(result) if tool_name == "terminal" else None
        command = args.get("command") if isinstance(args, dict) and tool_name == "terminal" else None
        rows.append({
            "name": str(tool_name or "tool"),
            "duration_ms": int(duration_ms),
            "exit_code": code,
            "timed_out": code == 124,
            "command": " ".join(str(command).split())[:_COMMAND_LIMIT] if command else None,
        })
    arm_review_prompts(agent)
