"""``characters auto``: the one-shot autopilot that runs the pipeline steps in order.
"""

from __future__ import annotations

import contextlib
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final

from agent_runtime.cli_format import emit_json_line
from agent.charsheet.errors import CharsheetRefusal

from .payloads import _CHARACTERS_EXPECTED, _characters_draftsman, _characters_next
from .steps import (
    _characters_rows_next,
    _characters_step_approve_all,
    _characters_step_compose,
    _characters_step_rows,
    _characters_step_turnaround,
)

__layer__ = "lanes"
__all__ = [
    "CHARACTER_STEPS",
    "CharacterStep",
    "_CHARACTERS_AUTO_STEPS",
    "_characters_auto_next",
    "_characters_auto_plan",
    "_characters_auto_steps",
    "_characters_auto_write",
    "_cmd_characters_auto",
]


# ───────────────────────────── the autopilot ─────────────────────────────
#
# Stage 5 of the turn-efficiency plan, ruled in 2026-08-31 (R-3 → YES, wave
# ruling RD-10). The measured problem: a one-message "make me a character and
# drive it all the way" ask cost 27 API calls and 1.556M cumulative prompt
# tokens, and twelve of those calls were the agent asking a blocked pipeline
# "done yet?". This verb is ONE process that runs the four pipeline steps and
# prints a receipt as each lands, so the same ask costs a fire and a delivery.
#
# Three conditions the ruling adopted from the stage text, each load-bearing:
#
#   * it is for an operator's EXPLICIT "drive it all the way" ask only — it
#     auto-approves the turnaround, which is the last moment a reference can
#     change;
#   * it STOPS on a handedness refusal and never overrides one (no
#     `--accept-handedness` reaches this door, and the compose refusal it prints
#     carries no `next` hint, because the only hint available would be the
#     override itself);
#   * it writes the SAME per-attempt history the interactive verbs write — it
#     calls their bodies, so `reopen` repair, `status --json` history and every
#     QA crop work identically afterwards.

@dataclass(frozen=True)
class CharacterStep:
    """One pipeline step as the autopilot drives it (program rule 12: the step
    NAME reaches its behaviour through ``CHARACTER_STEPS``, never a ladder).

    ``stages`` — the draft stages the step can run at. ``done`` — reads the
    status payload and answers True when there is nothing left for the step to
    do (the plan then skips it with ``done_reason``); None when the step always
    has work at its stage. ``run`` — the step body both doors share, returning
    ``(receipt, human line)``. ``next_hint`` — the ``next`` hint for a refusal,
    or None when the step has no honest one.
    """

    stages: frozenset[str]
    run: Callable[[object], tuple[dict, str]]
    done: Callable[[dict], bool] | None = None
    done_reason: str = ""
    next_hint: Callable[[object], dict | None] | None = None


def _turnaround_next(draft) -> dict | None:
    # Same arm `start` takes for an anchorless draft: `turnaround` refuses
    # without the anchor, and `<image>` is the one thing the runtime cannot
    # know.
    if draft.base_image is None:
        return _characters_next("base", "--draft", draft.id, "--image", "<image>")
    return None


def _run_rows_step(draft) -> tuple[dict, str]:
    # The pending list is re-read HERE rather than reused from the plan: the
    # steps before this one can fail a row, and the batch must ask for what is
    # missing now.
    return _characters_step_rows(draft, draft.status_payload()["pending"]["rows"])


#: The four pipeline steps, in the order the autopilot runs them. `compose` has
#: no ``next_hint`` on purpose — see :func:`_characters_auto_next`.
CHARACTER_STEPS: Final[Mapping[str, CharacterStep]] = MappingProxyType(
    {
        "turnaround": CharacterStep(
            stages=frozenset({"turnaround"}),
            run=_characters_step_turnaround,
            done=lambda status: not status["missing"]["turnaround"],
            done_reason="every authored direction already has a reference",
            next_hint=_turnaround_next,
        ),
        "approve-direction": CharacterStep(
            stages=frozenset({"turnaround"}),
            run=_characters_step_approve_all,
        ),
        "rows": CharacterStep(
            stages=frozenset({"turnaround", "rows"}),
            run=_run_rows_step,
            done=lambda status: not status["pending"]["rows"],
            done_reason="every authored row already has an approved strip",
            next_hint=lambda draft: _characters_rows_next(draft, None),
        ),
        "compose": CharacterStep(
            stages=frozenset({"turnaround", "rows"}),
            run=lambda draft: _characters_step_compose(draft, []),
        ),
    }
)

#: The step vocabulary: the table's keys, which `--through`'s ``choices=`` reads.
_CHARACTERS_AUTO_STEPS: Final[tuple[str, ...]] = tuple(CHARACTER_STEPS)


def _characters_auto_write(args, data: dict, human: str) -> None:
    """One receipt line, written and FLUSHED the moment its stage lands.

    Flushed on purpose. The turn that fires this verb backgrounds it and reads
    its log while it runs — a 10-20 minute `rows` batch is the whole reason the
    verb exists — and Python block-buffers stdout when it is a pipe. Without the
    flush every receipt arrives at once, at exit, and the operator watches a
    silent process for twenty minutes: exactly the "frozen" reading the plan
    measured on the live fire-imp run.

    `--json` frames with `emit_json_line`, never `emit_json`: the indenting
    encoder every other verb uses would break the newline framing this stream
    IS. Human mode prints the verb's own line, which for `compose` is a block.

    Every line carries the draftsman stamp when the seam is armed, not just the
    summary: each one IS a `characters` result, and the consumer reading this
    stream mid-batch is exactly the reader who needs to know which door drew the
    rows it is watching land (RL-26).
    """
    sys.stdout.write(
        (emit_json_line({**data, **_characters_draftsman()}) if getattr(args, "json", False) else human) + "\n"
    )
    sys.stdout.flush()


def _characters_auto_plan(draft, status: dict, through: str) -> tuple[list[str], list[dict]]:
    """Which steps this run will attempt, and the reason it skips each of the rest.

    Read the draft's STATE, never a fixed script. Driven as a flat script the
    autopilot is destructive twice over: `run_turnaround` re-rolls every
    direction reference AND clears the approvals, and `run_rows` with no
    `--only` regenerates every authored row — including the ones an operator
    kept. On the `reopen`-repair path that discards the QA work the operator
    just did and spends ten to twenty minutes of generation doing it. So the
    turnaround step runs only when some direction has NO attempt at all (the
    strip is generated whole, so there is no partial resume), and the rows step
    runs only over the rows with no approved strip — the same two lists the 4b
    resume hint reads, `missing.turnaround` and `pending.rows`.

    Every skip is REPORTED. An autopilot that quietly does three of four steps
    and exits 0 is indistinguishable from one that did all four, which is the
    one thing a caller who ended its turn cannot afford to be wrong about.
    """
    limit = _CHARACTERS_AUTO_STEPS.index(through)
    plan: list[str] = []
    skipped: list[dict] = []
    for index, (name, step) in enumerate(CHARACTER_STEPS.items()):
        reason = _characters_auto_skip_reason(step, draft.stage, status, past_through=index > limit, through=through)
        if reason is None:
            plan.append(name)
        else:
            skipped.append({"step": name, "reason": reason})
    return plan, skipped


def _characters_auto_skip_reason(
    step: CharacterStep, stage: str, status: dict, *, past_through: bool, through: str
) -> str | None:
    """Why the plan skips ``step``, or None when it runs — three guards, in order."""
    if past_through:
        return f"past --through {through}"
    if stage not in step.stages:
        return f"draft is at stage {stage!r}"
    if step.done is not None and step.done(status):
        return step.done_reason
    return None


def _characters_auto_next(step: str, draft) -> dict | None:
    """The `next` hint for a step that refused — or nothing, honestly.

    `compose` is deliberately absent. Its refusing shape is the handedness
    gate, and the only command that answers it is
    `compose --accept-handedness <row>:<basis>` — the override R-3 forbids this
    verb from nudging anyone toward. The refusal text already names every
    flagged row and its basis; an autopilot adds nothing to that but pressure.
    """
    hint = CHARACTER_STEPS[step].next_hint
    return None if hint is None else hint(draft)


def _cmd_characters_auto(args) -> int:
    from agent.charsheet.draft import CharacterDraft

    draft_id = str(getattr(args, "draft", "") or "").strip()
    through = str(getattr(args, "through", "compose") or "compose")

    def refuse(message: str, *, step: str, draft=None, hint: dict | None = None) -> int:
        """A refusal is a LINE, and the summary still follows it.

        `_characters_error` is not used anywhere in this verb: it emits the
        indented `emit_json` block, and one multi-line block in the middle of a
        newline-framed stream is unparseable by the consumer the framing exists
        for. Every line this verb writes — receipts, refusals, summary — has
        one shape, and the LAST line is always the summary.
        """
        line = {"ok": False, "error": message, "draft": draft_id, "step": step}
        if draft is not None:
            line["stage"] = draft.stage
        if hint is not None:
            line["next"] = hint
        _characters_auto_write(args, line, message)
        return 2

    try:
        draft = CharacterDraft.load(draft_id)
    except _CHARACTERS_EXPECTED as exc:
        refuse(str(exc), step="load")
        _characters_auto_write(
            args,
            {
                "ok": False,
                "draft": draft_id,
                "step": "auto",
                "through": through,
                "ran": [],
                "skipped": [],
                "stopped_at": "load",
                "error": str(exc),
            },
            f"Autopilot ran nothing: {exc}",
        )
        return 2

    # ONE acquisition around the WHOLE plan, not one per step. The lock is
    # re-entrant for this thread, so the step bodies below take it again and
    # get a no-op; a per-step lock would leave a gap between `turnaround` and
    # `rows` that a second generation could walk into, and this verb spends
    # ten to twenty minutes standing in those gaps.
    holding = contextlib.ExitStack()
    try:
        holding.enter_context(draft.generation_lock("auto"))
    except CharsheetRefusal as exc:
        refuse(str(exc), step="lock", draft=draft, hint=_characters_next("status", "--draft", draft.id))
        _characters_auto_write(
            args,
            {
                "ok": False,
                "draft": draft.id,
                "stage": draft.stage,
                "step": "auto",
                "through": through,
                "ran": [],
                "skipped": [],
                "stopped_at": "lock",
                "code": getattr(exc, "code", ""),
                "error": str(exc),
            },
            f"Autopilot ran nothing: {exc}",
        )
        return 2

    with holding:
        return _characters_auto_steps(args, draft, through, refuse)


def _characters_auto_steps(args, draft, through: str, refuse) -> int:
    """The plan, the loop and the summary — everything under the draft's lock.

    Split out of :func:`_cmd_characters_auto` only so the acquisition can refuse
    before any of it runs; the body is the verb it always was.
    """

    plan, skipped = _characters_auto_plan(draft, draft.status_payload(), through)
    ran: list[str] = []
    stopped_at: str | None = None
    error: str | None = None

    if not plan:
        # Nothing to drive is a REFUSAL, not a quiet success. The caller of this
        # verb ended its turn expecting a character; "ok, did nothing" twenty
        # minutes later is the reply it cannot act on.
        message = (
            f"nothing for the autopilot to run: draft {draft.id} is at stage "
            f"{draft.stage!r} and --through is {through!r}"
        )
        hint = (
            _characters_next("reopen", "--draft", draft.id)
            if draft.stage == "composed"
            else None
        )
        refuse(message, step="plan", draft=draft, hint=hint)
        stopped_at, error = "plan", message

    for step in plan:
        try:
            result, human = CHARACTER_STEPS[step].run(draft)
        except _CHARACTERS_EXPECTED as exc:
            refuse(str(exc), step=step, draft=draft, hint=_characters_auto_next(step, draft))
            stopped_at, error = step, str(exc)
            break
        line = {"ok": True, "draft": draft.id, "stage": draft.stage, "step": step}
        line.update(result)
        _characters_auto_write(args, line, human)
        ran.append(step)

    summary = {
        "ok": error is None,
        "draft": draft.id,
        "stage": draft.stage,
        "step": "auto",
        "through": through,
        "ran": ran,
        "skipped": skipped,
    }
    if error is not None:
        summary["error"] = error
        summary["stopped_at"] = stopped_at
    _characters_auto_write(
        args,
        summary,
        f"Draft {draft.id}: autopilot ran {len(ran)} step(s)"
        + (f" ({', '.join(ran)})" if ran else "")
        + f"; stage is now '{draft.stage}'"
        + (f" — stopped at {stopped_at}" if error is not None else ""),
    )
    return 0 if error is None else 2
