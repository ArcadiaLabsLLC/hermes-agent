"""A persona claim that asks its run to keep going until the task is done (``RT-WORK-CLAIM-RUNS-UNTIL-DONE``).

Owner ruling 2026-11-12 on ``EterniaLauncher`` row ``COMP-WORK-V1-DECIDE-GOAL-MODE``: "it should keep going
till it judges that the users intent is complete" — at most :data:`chat_goal.MAX_PASSES` passes, 30 minutes
per pass (``goal_turns.pass_max_seconds``), a visible Stop, done judged against the task's text and its tests.

Three things live here, each read by one caller:

* **The claim's goal mode.** ``runtime.work.claim`` with ``goal_mode: "until_done"`` cannot write it on the
  row (the row grammar is shared with the Launcher and the backend), so it is kept BESIDE the claim: one
  file per row under the workspace's Work directory, naming the claimant. The engine reads it when it hands
  the row to its executor (:func:`kept`) and honours it only while that claimant still holds the row; a new
  claim rewrites or clears it (:func:`keep`), a release and the run's close forget it (:func:`forget`).
* **What done means.** :func:`objective` is the task's title and body, the goal the judge reads;
  :func:`gate_commands` are the test commands the body names — every code span on a line that starts
  ``Test:`` / ``Tests:`` — which become goal gates (``Brief.tests``).
* **The wire word.** :func:`goal_mode_of` reads a request's ``goal_mode``; an unknown word refuses
  ``goal_mode_unsupported``.

Pinned by ``tests/agent_runtime/work_store/test_until_done_claim.py``.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .. import paths
from ..serde import write_json_atomic
from .grammar import RowRef
from .reasons import Reason, WorkRefused

__layer__ = "stores"
__all__ = ["GOAL_MODES", "NONE", "UNTIL_DONE", "forget", "gate_commands", "goal_mode_of", "keep", "kept", "objective"]

#: The wire words of ``executor.GoalMode``, spelled here because this module sits below the executor
#: contract (the claim door, a store, writes it); the pinning test holds the two sets equal.
NONE, UNTIL_DONE = "none", "until_done"
GOAL_MODES: tuple[str, ...] = (NONE, UNTIL_DONE)

_TEST_LINE = re.compile(r"^[\s>*\-]*\**tests?\**\s*:", re.IGNORECASE)
_CODE_SPAN = re.compile(r"`([^`\n]+)`")
_MAX_GATES = 8


def goal_mode_of(value: Any) -> str:
    """A request's ``goal_mode`` word: absent is ``none``; a word that is no goal mode refuses."""

    if value is None:
        return NONE
    if value not in GOAL_MODES:
        raise WorkRefused(Reason.GOAL_MODE_UNSUPPORTED, "goal_mode is none | until_done")
    return str(value)


def _path(workspace_id: str, ref: RowRef) -> Path:
    name = f"{paths.safe_path_token(ref.slot)}--{paths.safe_path_token(ref.id)}.json"
    return paths.work_workspace_dir(workspace_id) / "claim_goals" / name


def keep(workspace_id: str, ref: RowRef, who: str, goal_mode: str) -> None:
    """Record the goal mode ``who``'s claim of ``ref`` asked for; ``none`` clears what an earlier claim kept."""

    if goal_mode_of(goal_mode) == NONE:
        forget(workspace_id, ref)
        return
    path = _path(workspace_id, ref)
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json_atomic(path, {"who": who, "goal_mode": goal_mode})


def kept(workspace_id: str, ref: RowRef, who: str) -> str:
    """The goal mode kept with ``who``'s claim of ``ref``; ``none`` when there is none, or it is another's."""

    try:
        raw = json.loads(_path(workspace_id, ref).read_text(encoding="utf-8"))
        return goal_mode_of(raw["goal_mode"]) if raw.get("who") == who else NONE
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return NONE


def forget(workspace_id: str, ref: RowRef) -> None:
    _path(workspace_id, ref).unlink(missing_ok=True)


def objective(title: str, body: str) -> str:
    """What the goal judge measures done against: the task's title, then its body."""

    return f"{title}\n\n{body.strip()}" if body.strip() and body.strip() != title.strip() else title


def gate_commands(body: str) -> tuple[str, ...]:
    """The test commands the task's body names: every code span on a ``Test:`` / ``Tests:`` line, in order."""

    found = [span.strip() for line in str(body or "").splitlines() if _TEST_LINE.match(line)
             for span in _CODE_SPAN.findall(line)]
    return tuple(dict.fromkeys(command for command in found if command))[:_MAX_GATES]
