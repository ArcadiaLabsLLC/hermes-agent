"""The gate's vocabulary: paths, the claim schema's keys, and the resolved-anchor record.

A TABLE module (floor-exempt): every constant the other modules read, and the
one record type they pass between them. No I/O. The map is
``scripts/mutation_check/__init__.py``.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path
import re

__layer__ = "models"


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CLAIMS = REPO_ROOT / "tests" / "mutation_claims.json"
DEFAULT_EXEMPTIONS = REPO_ROOT / "tool" / "test_quality" / "mutation_exemptions.yaml"
#: Held for the duration of a MUTATING run — see :func:`_acquire_gate_lock`.
#: Worktree-local by construction (``REPO_ROOT`` is this checkout's root), which
#: is the right scope: the hazard is a shared TREE, and two worktrees of one
#: clone have two trees. The lock's directory ignores itself (a ``.gitignore``
#: holding ``*``, written by :func:`_acquire_gate_lock`), so the checkout's root
#: ``.gitignore`` stays upstream's.
LOCK_PATH = REPO_ROOT / ".mutation-gate" / "lock"
HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")

#: The default WALL-CLOCK bound on a run, in seconds. 900 = fifteen minutes,
#: which is the ceiling the CI job already enforces with its own
#: ``timeout-minutes: 15`` — so the default is the number the slowest lane was
#: living under anyway, said out loud where a local run can read it.
#:
#: Ruled 2026-09-04, the same ruling the launcher's discovered-extras count
#: took (``kRepoLaneWallBudgetSeconds``): a bound on a COUNT is a bound on a
#: proxy, and this one kept drifting from the thing it stood for. Symbol-overlap
#: selection raises the count by design and a push-shaped base collapses it, and
#: neither moves the runtime. The count is still printed on every run — it is
#: the most useful number in the report — it is simply never asserted.
DEFAULT_WALL_BUDGET_SECONDS = 900.0

#: ``symbol`` spellings that mean "the whole module" rather than a definition
#: inside it. Module-scope claims are legitimate (an import, a constant, a
#: decorator argument) and there is no AST node to scope them to.
#:
#: A FOURTH legitimate case: a definition inside a module-level platform fork,
#: where the two arms collide under one name and an ambiguous symbol is refused
#: by design — the claim anchors at ``module`` and names its arm in the label
#: (``module/_try_acquire (POSIX arm)``); ``platforms`` scopes it. The measured
#: instance is in the package map's history (``__init__.py``).
WHOLE_MODULE_SYMBOLS = frozenset({"module", "module scope", "module-scope"})

#: Statements whose bodies the definition walk descends WITHOUT adding a name:
#: a block introduces nesting, not a naming scope. ``ExceptHandler`` and
#: ``match_case`` are in the list because they are the body-carrying children
#: of ``Try`` and ``Match`` rather than statements in their own right.
BLOCK_STATEMENTS: tuple[type[ast.AST], ...] = tuple(
    node
    for node in (
        ast.If,
        ast.Try,
        getattr(ast, "TryStar", None),
        ast.With,
        ast.AsyncWith,
        ast.For,
        ast.AsyncFor,
        ast.While,
        getattr(ast, "Match", None),
        getattr(ast, "match_case", None),
        ast.ExceptHandler,
    )
    if node is not None
)

#: The hosts a claim can declare itself bound to. Two, because two is what the
#: tree distinguishes: ``agent_runtime/locks.py`` is the only module with a
#: platform fork and it forks on ``os.name == "nt"``.
PLATFORMS = frozenset({"posix", "windows"})

#: How far a claim's block is allowed to have been re-indented and still be the
#: same claim. Four levels each way covers every dedent this repo has produced
#: (an extraction out of a nested ``try`` is two); beyond it the block has more
#: likely been rewritten than moved, and a configuration error is the honest
#: answer.
MAX_REINDENT_COLUMNS = 16

#: The optional claim field holding the commit a claim's needle was DERIVED at.
#:
#: What it is for. ``find`` is a source SPELLING inside the anchored symbol. The
#: loud failure — a spelling that stopped occurring — is a configuration error
#: and impossible to miss. The quiet one is the reason this field exists: a
#: needle that STILL resolves after a semantic edit runs a mutation nobody
#: re-derived, and the run goes green on a guarantee that may no longer be the
#: guarantee.
#:
#: Ruled 2026-09-04: ONE optional field carrying the commit, NO backfill, and a
#: stale marker is a WARNING in the report and never a failure. All three halves
#: are load-bearing. No backfill, so ABSENCE means "written before this schema"
#: and says nothing about the claim's health. And a warning rather than a refusal,
#: because staleness is a suspicion, not a defect: a claim whose file moved
#: underneath it is usually still correct, and a gate that refuses on suspicion
#: is a gate that gets its budget raised until it says nothing.
DERIVED_AT_KEY = "derived_at"

#: Where ``_partition_claims`` parks the resolved :class:`ClaimAnchor` on the
#: claim row. Not a claim FIELD — the schema check above rejects unknown-shaped
#: rows on the way in, and this is added after that check, by us, on our copy.
ANCHOR_KEY = "_anchor"

#: Where ``_partition_claims`` parks WHY a claim was selected — ``"lines"``
#: (the diff touched the anchored needle) or ``"symbol"`` (it touched the
#: definition around it). Same non-field status as :data:`ANCHOR_KEY`. It is
#: reported rather than kept private: symbol selection is a deliberate
#: widening, and a widening nobody can see in the output is indistinguishable
#: from the gate having gone vague.
SELECTION_KEY = "_selected_by"
#: The two words :data:`SELECTION_KEY` holds. Written in ``selection``, read in
#: ``run`` — named once so the report's `` (selected by symbol)`` suffix and the
#: writer cannot drift apart. A word, not an Enum: it rides a line CI and humans read.
SELECTED_BY_LINES = "lines"
SELECTED_BY_SYMBOL = "symbol"

#: The gate's two non-zero exits: a claim's mutant SURVIVED (the guarantee is
#: not held), or the run REFUSED to judge (configuration error, a failed
#: baseline, a held lock, an exhausted budget). The tests pin the literals on
#: purpose; these are the spelling the code reads.
EXIT_SURVIVED = 1
EXIT_REFUSED = 2



#: Path prefixes whose ``.py`` files are not a surface a claim can anchor in.
#: Short on purpose: every OTHER root carrying Python is code a guarantee can
#: be registered against, and nine of the registered claims already anchor in
#: ``scripts/``. Widening this list makes the census below quieter by declaring
#: code un-mutatable, which is the move it exists to detect.
NON_PRODUCTION_PREFIXES = ("tests/", "tests-js/")


@dataclass(frozen=True, slots=True)
class ClaimAnchor:
    """Where a claim's ``find`` actually sits in the file today.

    ``find``/``replace`` are the claim's strings AS THE FILE SPELLS THEM — the
    registered text re-indented onto the block's current column. The mutation is
    spliced at ``offset`` rather than handed to ``str.replace``, because
    uniqueness is now a property of the SYMBOL and a needle that also occurs
    earlier in the file must not be the one that gets rewritten.

    ``symbol_lines`` is the whole span of the definition the claim names —
    what SELECTION reads. Empty for a ``module``-scope claim, where the span is
    the file and "this diff touched the file" is not a claim about anything.
    """

    offset: int
    lines: set[int]
    find: str
    replace: str
    shift: int
    symbol_lines: frozenset[int] = frozenset()
