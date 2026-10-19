"""The landing gate, run by code (row RT-BATCH-GATE-RECEIPT, owner ruling 2026-10-18).

The landing lane's persona merges the batch and reports; its ``work_report`` verdict is ADVISORY. What
decides ``AWAITING_APPROVAL`` is this module: ``GateRunner.run`` executes a slot's gate commands
(``slot_gate``, carried as the landing lane's ``Lane.gates``) in each slot's landing worktree and returns a
``GateReceipt`` — command, exit code, summary line, the HEAD it ran on. ``BatchLaneExecutor`` runs it
off-thread when the landing turn settles; ``require_green`` is ``approve``'s check: every slot's landing HEAD
named by a green receipt, else ``gate_not_green``.

The gate's output goes to ``gate-<slot>.log`` in the landing worktree's scratch directory; the receipt keeps
only the summary line (the last line naming ``Summary``, else the last non-empty line).

WHICH commands run in a slot (row RT-BATCH-GATE-PER-SLOT-COMMAND, p10-work §3, owner ruling 2026-10-19):
``slot_gate`` reads the slot's declared ``context.gate`` first, then ``GATES_BY_TOOLCHAIN_KIND`` for its
``toolchain.kind``, then the default brain's ``GATE_NONE`` (green, no subprocess); anything else is None —
the lane executor's red "no gate declared" receipt, never a skip.
"""

from __future__ import annotations

import shlex
import shutil
import subprocess
import sys
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from ..work_store.models import GateReceipt
from ..work_store.reasons import Reason, WorkRefused
from .lane_git import LaneGit, Site
from .planner import LANDING_GATE

__layer__ = "stores"
__all__ = [
    "GATES_BY_TOOLCHAIN_KIND", "GATE_NONE", "GATE_NONE_SUMMARY", "GATE_TIMEOUT_S", "GateRunner", "gate_argv",
    "is_green", "no_gate_summary", "require_green", "slot_gate", "summary_line",
]

#: The longest a landing gate may run (a hub-file batch selects ~2,600 files: over an hour).
GATE_TIMEOUT_S = 3 * 3600
_SUMMARY_MAX = 300
#: Git Bash, never ``C:\Windows\System32\bash.exe`` (WSL), which ``CreateProcess`` finds first.
_GIT_BASH = Path(r"C:\Program Files\Git\bin\bash.exe")

#: The shell no-op: a brain-only slot's gate. ``GateRunner`` answers it green WITHOUT a subprocess
#: (``:`` through ``gate_argv`` is ``FileNotFoundError`` on Windows).
GATE_NONE = ":"
GATE_NONE_SUMMARY = "no code to test: brain-only slot"
#: The fallback by the slot's declared ``toolchain.kind`` (a table, never a ladder; lower-cased key).
GATES_BY_TOOLCHAIN_KIND: dict[str, tuple[str, ...]] = {
    "python": (LANDING_GATE,),
    "hermes": (LANDING_GATE,),
    "flutter": ("dart tool/heavy_run/run.dart -- dart tool/run_tier.dart",),
    "django": ("bash scripts/test.sh",),
    "backend": ("bash scripts/test.sh",),
    "brain": (GATE_NONE,),
}


def slot_gate(slot: Mapping[str, Any] | None, *, is_default: bool) -> tuple[str, ...] | None:
    """The landing gate's commands for one slot declaration; None = no gate declared (a RED receipt).

    Order: (1) the declared ``context.gate`` (``[]`` is "declared none" and stays empty — red too),
    (2) ``GATES_BY_TOOLCHAIN_KIND[toolchain.kind]``, (3) the default brain: ``(GATE_NONE,)``, (4) None.
    """

    context = (slot or {}).get("context") or {}
    if isinstance(context, Mapping) and context.get("gate") is not None:
        return tuple(str(command) for command in context["gate"])
    toolchain = (slot or {}).get("toolchain") or {}
    kind = str(toolchain.get("kind") or "").strip().lower() if isinstance(toolchain, Mapping) else ""
    if kind in GATES_BY_TOOLCHAIN_KIND:
        return GATES_BY_TOOLCHAIN_KIND[kind]
    return (GATE_NONE,) if is_default else None


def no_gate_summary(slot: str) -> str:
    return f"no gate declared for slot {slot}; set context.gate"


def gate_argv(command: str) -> list[str]:
    """``command`` as argv; a leading ``bash`` on Windows is Git Bash by its absolute path."""

    argv = shlex.split(command)
    if argv and argv[0] == "bash" and sys.platform == "win32":
        argv[0] = str(_GIT_BASH) if _GIT_BASH.is_file() else (shutil.which("bash") or "bash")
    return argv


def summary_line(output: str) -> str:
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    named = [line for line in lines if "Summary" in line]
    return (named or lines or [""])[-1][:_SUMMARY_MAX]


class GateRunner:
    """Run the landing gate's commands in a landing worktree; one ``GateReceipt`` per slot."""

    def __init__(self, *, git: LaneGit | None = None, run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
                 timeout: float = GATE_TIMEOUT_S, clock: Callable[[], float] = time.monotonic) -> None:
        self._git = git or LaneGit()
        self._run = run
        self._timeout = timeout
        self._clock = clock

    def run(self, site: Site, commands: Sequence[str]) -> GateReceipt:
        command = " && ".join(commands)
        head = self._git.head(site.worktree)
        if not commands:
            return GateReceipt(site.slot, command, -1, "the landing brief names no gate command", head)
        if tuple(commands) == (GATE_NONE,):
            return GateReceipt(site.slot, GATE_NONE, 0, GATE_NONE_SUMMARY, head)
        if self._git.dirty(site.worktree):
            return GateReceipt(site.slot, command, -1, "the landing worktree is dirty; commit or merge first", head)
        log = site.scratch / f"gate-{site.slot}.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        started = self._clock()
        code, output = 0, ""
        for one in commands:
            code, text = self._one(site.worktree, one)
            output += f"$ {one}\n{text}\n"
            if code != 0:
                break
        log.write_text(output, encoding="utf-8", newline="\n")
        return GateReceipt(site.slot, command, code, summary_line(output), head, self._clock() - started)

    def _one(self, worktree: Path, command: str) -> tuple[int, str]:
        try:
            done = self._run(gate_argv(command), cwd=str(worktree), stdin=subprocess.DEVNULL,
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT, encoding="utf-8",
                             errors="replace", timeout=self._timeout)
        except FileNotFoundError as missing:
            return 127, f"command not found: {missing}"
        except subprocess.TimeoutExpired:
            return 124, f"gate timed out after {self._timeout:.0f}s"
        return done.returncode, str(done.stdout or "")


def require_green(receipts: Iterable[GateReceipt], slots: Iterable[str], heads: Mapping[str, str] | None = None) -> None:
    """A green receipt for every slot the batch lands; with ``heads``, one naming that slot's landing HEAD.

    The dispatcher asks it at the landing's settle (green → ``AWAITING_APPROVAL``) and before ``approve``;
    ``GitLander`` asks it again with the HEADs it is about to push. Refuses ``gate_not_green``.
    """

    receipts = tuple(receipts)
    wanted = list(dict.fromkeys(slots))
    if not receipts or not wanted:
        raise WorkRefused(Reason.GATE_NOT_GREEN, "no code-run gate receipt for this landing")
    red = [f"{g.slot}: exit {g.exit_code} — {g.summary}" for g in receipts if not g.green]
    missing = [slot for slot in wanted if slot not in {g.slot for g in receipts}]
    if red or missing:
        raise WorkRefused(Reason.GATE_NOT_GREEN, "; ".join(red + [f"{slot}: no gate ran" for slot in missing]))
    green = {(g.slot, g.sha) for g in receipts}
    stale = [f"{slot}@{sha[:10]}" for slot, sha in (heads or {}).items() if (slot, sha) not in green]
    if stale:
        raise WorkRefused(Reason.GATE_NOT_GREEN, "no green gate receipt for the landing HEAD " + ", ".join(stale))


def is_green(receipts: Iterable[GateReceipt], slots: Iterable[str]) -> bool:
    try:
        require_green(receipts, slots)
    except WorkRefused:
        return False
    return True
