"""The gate's two verbs: ``_claims_for`` (the inventory lane) and ``run`` (the mutating lane).

``run`` prints the report CI and landings read, then -- outside ``--list`` --
takes the worktree lock, runs the baselines and splices each mutant. Every seam
a test patches is bound in THIS module's globals (``from .selection import ...``),
so ``monkeypatch.setattr(scripts.mutation_check.run, name, ...)`` lands. The map
is ``scripts/mutation_check/__init__.py``.
"""

from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Any

from .anchor import _anchor_or_raise, _read_source
from .schema import ANCHOR_KEY, DERIVED_AT_KEY, LOCK_PATH, REPO_ROOT, SELECTION_KEY
from .selection import (
    _changed_sources,
    _commits_since_derivation,
    _current_platform,
    _declared_platforms,
    _load_json,
    _partition_claims,
    _path_matches,
    _symbol_head,
    _symbol_matches,
    _validate_exemptions,
)

__layer__ = "lanes"


def _claims_for(claims_path: Path, query: str) -> int:
    """Print every claim anchored at ``query``. A REPORT, never a refusal.

    The gap this closes, measured on the 2026-08-30 lifecycle merge: two claims
    anchored inside one function's remediation string, the handoff named only
    one, and the second was found by the selector's configuration error rather
    than by review. "Which claims anchor in the symbol I am about to rewrite?"
    was answerable only by reading 113 rows by eye.

    Anchors are resolved but a failure to resolve is REPORTED, not raised: the
    moment this command is most useful is mid-rewrite, when some anchors have
    already stopped resolving, and a pre-flight that dies on the first rotted
    row would be useless exactly then.
    """

    rows = _load_json(claims_path).get("claims", [])
    if not isinstance(rows, list):
        raise RuntimeError(f"{claims_path}: claims must be a list")
    wanted_path, separator, wanted_symbol = query.replace("\\", "/").partition("::")
    matched: list[dict[str, Any]] = []
    for claim in rows:
        if not isinstance(claim, dict):
            raise RuntimeError(f"{claims_path}: claim rows must be objects")
        path = str(claim.get("path", "")).replace("\\", "/")
        head = _symbol_head(claim)
        if separator:
            if _path_matches(path, wanted_path) and _symbol_matches(head, wanted_symbol):
                matched.append(claim)
            continue
        if _path_matches(path, wanted_path) or _symbol_matches(head, wanted_path):
            matched.append(claim)

    print(f"claims anchored at {query}: {len(matched)}")
    for claim in matched:
        try:
            anchor, _ = _anchor_or_raise(claim)
            where = f"lines {min(anchor.lines)}-{max(anchor.lines)}"
            if anchor.shift:
                where += f", re-indented {anchor.shift:+d}"
        except RuntimeError as error:
            where = f"ANCHOR DOES NOT RESOLVE TODAY: {error}"
        print(f"  {claim['id']}: {claim['path']}::{claim['symbol']} [{claim['operator']}] {where}")
    if not matched:
        print("  (nothing anchored there — a rewrite here moves no registered guarantee)")
    return 0


def _command(claim: dict[str, Any]) -> list[str]:
    raw = claim["test"]
    if not isinstance(raw, list) or not raw or not all(isinstance(item, str) for item in raw):
        raise RuntimeError(f"{claim['id']}: test must be a non-empty string list")
    return [
        item.replace("{python}", sys.executable).replace("{repo}", str(REPO_ROOT))
        for item in raw
    ]


def _run_command(command: list[str]) -> int:
    return subprocess.run(command, cwd=REPO_ROOT, check=False).returncode


def _acquire_gate_lock() -> bool:
    """Exclusive-create :data:`LOCK_PATH`; ``False`` when someone already holds it.

    Only MUTATING runs take it. ``--list`` and ``--claims-for`` are inventory
    questions that never touch a source file, so locking them would refuse a
    harmless read for a reason that does not apply to it.

    The create is the test: ``open(..., "x")`` is atomic, so two runs racing for
    the lock cannot both win. There is deliberately NO liveness probe on the
    recorded pid — ``os.kill(pid, 0)`` KILLS the process on Windows, and this
    gate's primary host is Windows. A stale lock is therefore cleared by hand,
    and the refusal prints the exact path to delete. That is the honest trade: a
    manual step after a crash, in exchange for never mistaking a live run for a
    dead one.
    """

    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    marker = LOCK_PATH.parent / ".gitignore"
    if not marker.exists():
        marker.write_text("*\n", encoding="utf-8", newline="\n")
    try:
        with open(LOCK_PATH, "x", encoding="utf-8") as stream:
            stream.write(
                f"pid: {os.getpid()}\n"
                f"started: {datetime.now(timezone.utc).isoformat()}\n"
                f"argv: {' '.join(sys.argv)}\n"
            )
    except FileExistsError:
        return False
    return True


def _refuse_because_locked() -> int:
    """Print who holds the lock, in a block that pastes cleanly, and exit 2."""

    try:
        held = LOCK_PATH.read_text(encoding="utf-8").strip()
    except Exception:  # noqa: BLE001 — the lock existing is the fact; its text is a courtesy
        held = "(the lock file exists but its contents could not be read)"
    print(
        "another mutation run appears active in this worktree; if none is "
        f"running, delete {LOCK_PATH} and retry\n"
        "\n```\n" + held + "\n```",
        file=sys.stderr,
    )
    return 2


def _over_budget(started: float, wall_budget_seconds: float) -> bool:
    """Has this run spent its wall-clock budget."""

    return (time.monotonic() - started) >= wall_budget_seconds


def _refuse_over_budget(
    started: float, wall_budget_seconds: float, done: int, total: int
) -> int:
    """Exit 2, naming the numbers and the cure — the cap refusal's whole lesson.

    An exit 2 that means "your change is big" used to read as "your claims are
    bad", the wrong signal on the wrong lane, measured on the H1-H4 landing. So
    this says what was spent, what the bound was, how far the run got, and both
    cures — and the ORDER matters: raising the budget is named first, because
    splitting the diff is not available to a landing whose whole argument is
    that its stages land together.
    """

    print(
        f"wall budget exhausted: {time.monotonic() - started:.0f}s of "
        f"--wall-budget-seconds {wall_budget_seconds:.0f}, after {done} of "
        f"{total} claim(s); raise the budget visibly (a multi-stage LANDING run "
        "passes its own, e.g. --wall-budget-seconds 1800), or split the diff",
        file=sys.stderr,
    )
    return 2


def run(
    base: str,
    claims_path: Path,
    exemptions_path: Path,
    wall_budget_seconds: float,
    list_only: bool,
) -> int:
    started = time.monotonic()
    _validate_exemptions(exemptions_path)
    claims, unselected = _partition_claims(base, claims_path)
    # REPORTED, never asserted (ruled 2026-09-04). The trailing parenthetical is
    # load-bearing in a way the number is not: CI's selector greps
    # `^mutation candidates: 0 ` — with the trailing space — to decide whether to
    # install the test environment at all, so this line keeps a token after the
    # count whatever the bound is called.
    print(
        f"mutation candidates: {len(claims)} "
        f"(reported, not capped; wall budget {wall_budget_seconds:.0f}s)"
    )
    for claim in claims:
        via = " (selected by symbol)" if claim.get(SELECTION_KEY) == "symbol" else ""
        print(
            f"  {claim['id']}: {claim['path']}::{claim['symbol']} "
            f"[{claim['operator']}]{via}"
        )
    # The census that makes a ZERO attributable. A registration-gated gate is
    # silent in two completely different situations — "this diff touched no
    # production source" and "this diff touched seven and nobody registered a
    # claim for any of them" — and until this line they printed the same
    # `mutation candidates: 0` and CI skipped identically. Measured on S5, which
    # landed with zero executable claims (`--base 748687daa3^ --list` -> 0) and
    # looked exactly like a slice that needed nothing.
    #
    # Reported, never enforced: whether a changed source MUST carry a claim is a
    # policy question with a real answer for some files and no answer for
    # others, and a gate that guesses it would be turned off inside a week. This
    # only refuses to let the two zeros look alike.
    changed_sources = _changed_sources(base)
    registered_paths = {
        str(claim["path"]).replace("\\", "/") for claim in (*claims, *unselected)
    }
    unregistered = [path for path in changed_sources if path not in registered_paths]
    print(
        f"changed production sources: {len(changed_sources)} "
        f"({len(unregistered)} carry no registered claim)"
    )
    for path in unregistered:
        print(f"  NO CLAIM ANCHORS HERE: {path}")
    # AFTER the candidate line for the same reason the UNSELECTED rows are, and
    # for BOTH halves: a claim re-anchored onto a re-indented block is a fact
    # about this run whether or not the diff selected it, and a silent
    # re-anchor is the same false all-clear as a silent skip.
    for claim in (*claims, *unselected):
        anchor = claim[ANCHOR_KEY]
        if anchor.shift:
            print(
                f"RE-ANCHORED: {claim['id']} ({claim['path']}::{claim['symbol']} "
                f"re-indented {anchor.shift:+d} columns)"
            )
    # The QUIET failure, made visible. A needle that stopped occurring is a
    # configuration error nobody can miss; a needle that still resolves after a
    # semantic edit runs a mutation nobody re-derived, and until this line the
    # run said nothing at all about that. Only for the SELECTED claims: this is
    # a prompt about work this run is actually doing.
    #
    # A WARNING and never a failure (ruled 2026-09-04), and printed on stdout
    # beside the rest of the report rather than on stderr, because it is not an
    # error channel — it is a line a reader of a GREEN run is meant to read.
    for claim in claims:
        moved = _commits_since_derivation(claim)
        if moved:
            print(
                f"WARNING: stale derivation: {claim['id']} was derived at "
                f"{str(claim[DERIVED_AT_KEY])[:12]} and {claim['path']} has moved "
                f"in {moved} commit(s) since; re-derive the needle or re-stamp "
                f"{DERIVED_AT_KEY}"
            )
    if list_only:
        # Only under ``--list``, which is the inventory lane. A real run prints
        # what it is about to mutate and nothing else; this is for the reader
        # asking "and what did this diff NOT put on the hook".
        #
        # AFTER the candidate line and never instead of it: CI branches on
        # ``^mutation candidates: 0 `` to decide whether to install the test
        # environment at all, so these rows are additive and that line keeps
        # its meaning.
        for claim in unselected:
            print(f"UNSELECTED (0 changed lines): {claim['id']}")
    # Reported for BOTH lanes and always by name, because the whole point is
    # that this claim is accounted for on a host that cannot run it. The
    # alternative is what the queue row measured: a hand-run on this host is
    # permanently one known SURVIVED away from green, which is exactly the
    # "silence looks like success" state the gate exists to prevent — except
    # here the noise looks like failure and gets learned as background.
    here = _current_platform()
    runnable: list[dict[str, Any]] = []
    for claim in claims:
        declared = _declared_platforms(claim)
        if declared is not None and here not in declared:
            print(
                f"SKIPPED (platform): {claim['id']} "
                f"(declared {'/'.join(sorted(declared))}; this host is {here})"
            )
        else:
            runnable.append(claim)
    if list_only or not runnable:
        return 0
    # The budget is checked HERE, before the lock, for the reason the cap was:
    # a refused run must hold nothing, or a run that stops for being too big
    # leaves a lock behind for the split-up runs that follow it. It is checked
    # after the ``--list`` return because the inventory lane runs no tests and
    # so has nothing to bound — under the cap, a big diff could not even ask
    # what it had selected, which is the one thing it needed to know.
    if _over_budget(started, wall_budget_seconds):
        return _refuse_over_budget(started, wall_budget_seconds, 0, len(runnable))

    # Everything past here READS OR WRITES the tree, so everything past here is
    # inside the lock — the baseline runs included. They do not mutate, but they
    # are part of the same run and a second run's mutants would corrupt them
    # exactly as they corrupt the mutation runs.
    if not _acquire_gate_lock():
        return _refuse_because_locked()
    try:
        commands: dict[tuple[str, ...], list[str]] = {}
        for claim in runnable:
            command = _command(claim)
            commands.setdefault(tuple(command), command)
        for command in commands.values():
            print(f"BASELINE: {' '.join(command)}")
            if _run_command(command) != 0:
                print("baseline failed; mutation result would be meaningless", file=sys.stderr)
                return 2

        survivors: list[str] = []
        for done, claim in enumerate(runnable):
            # Checked between claims and never inside one: a run that stopped
            # mid-mutation would be a run that left a spliced file on disk,
            # which is the one thing this gate may never do. So the bound is
            # honoured at the only safe boundary, and the overrun a single very
            # slow claim can cause is bounded by that claim, not by the budget.
            if _over_budget(started, wall_budget_seconds):
                return _refuse_over_budget(
                    started, wall_budget_seconds, done, len(runnable)
                )
            target = REPO_ROOT / str(claim["path"])
            original, text = _read_source(target)
            anchor = claim[ANCHOR_KEY]
            if text[anchor.offset : anchor.offset + len(anchor.find)] != anchor.find:
                # The baseline run moved the file under us. Refusing beats splicing
                # at an offset that now points somewhere else.
                raise RuntimeError(f"{claim['id']}: {claim['path']} changed after the anchor resolved")
            # Spliced at the anchor's offset, never ``str.replace``: uniqueness is a
            # property of the SYMBOL now, so an identical line earlier in the file
            # is legal — and would be the one a first-occurrence replace rewrote.
            mutated = text[: anchor.offset] + anchor.replace + text[anchor.offset + len(anchor.find) :]
            try:
                target.write_text(mutated, encoding="utf-8", newline="")
                print(f"MUTATE: {claim['id']}")
                if _run_command(_command(claim)) == 0:
                    survivors.append(str(claim["id"]))
                else:
                    print(f"KILLED: {claim['id']}")
            finally:
                target.write_bytes(original)
    finally:
        # Released on EVERY exit — including the RuntimeError above and a
        # KeyboardInterrupt — because a lock that outlives its run turns the
        # guard into the obstruction it exists to prevent.
        LOCK_PATH.unlink(missing_ok=True)
    if survivors:
        print(f"SURVIVED: {', '.join(survivors)}", file=sys.stderr)
        return 1
    return 0
