"""Run bounded, explicit mutation claims that intersect changed production lines.

**This gate REWRITES SOURCE FILES IN PLACE while it runs.** Each mutant is
spliced into the real file on disk, the claim's test command runs against it,
and the original bytes are restored in a ``finally``. For the duration of a run
this worktree does not hold the code you committed.

Never run pytest -- or anything else that reads the tree -- in the same worktree
during a run. A concurrent test run reads sabotaged source and reds tests that
pass in isolation, and at the console that is indistinguishable from a real
defect. A second MUTATING run against the same tree is refused outright
(``run._acquire_gate_lock``); a concurrent pytest is not something this script
can see, which is why it is written down here as well as enforced.

Registration is not coverage, and the report says so. This gate can only run
guarantees somebody wrote down, so a run with zero candidates has two readings --
the diff touched no production source, or it touched several and nobody
registered a claim for any of them. Every run therefore carries a
``changed production sources:`` census naming the changed ``.py`` files no claim
anchors in. It is REPORTED, never enforced: whether a given file must carry a
claim is a policy question this script has no honest default for.

Budget doctrine (ruled 2026-09-04; replaces the candidate cap). The bound is
WALL CLOCK -- ``--wall-budget-seconds`` -- and the candidate count is REPORTED,
never asserted. The cap it replaces was always a proxy for runtime, and
symbol-overlap selection RAISES candidate pressure by design while a PR-shaped
and a push-shaped base over the same work select wildly different counts; none
of that changes how long the run takes, which is the only thing the bound was
ever protecting.

The budget is checked before the mutating phase begins and again before each
claim, so a run that outgrows it STOPS with what it has done and what remains
-- it does not discover the overrun by being killed. The enforced number stays
readable beside the command that enforces it: CI passes its own in
``.github/workflows/fork-gates.yml``, and a multi-stage LANDING run passes its own
the same way. See ``tool/test_quality/README.md``.

**The map** (lane B5, 2026-09-25; the layout sheet is
``docs/agent-runtime-harness/planned/god-file-layout-sheets/changed_line_mutation_check.md``).
The ENTRY keeps its path -- CI, ``scripts/unattended_suite_run.ps1``, ``CLAUDE.md``
and the gate's own tests name it -- and this package holds everything it runs::

    scripts/changed_line_mutation_check.py   wiring   the ENTRY: argparse ``main``; re-exports the names the tests read
    scripts/mutation_check/
      __init__.py    wiring   this map; imports nothing (``run`` is a MODULE here, never shadowed)
      schema.py      models   the vocabulary/table: paths, claim-schema keys, ``ClaimAnchor``
      anchor.py      policy   pure text + AST: resolve a claim's symbol and needle to an offset
      selection.py   stores   the claims file and git: which claims this diff selects
      run.py         lanes    the two verbs: ``_claims_for`` (inventory) and ``run`` (mutating)

Following an entry point: a landing's ``--list --base`` -> the entry -> ``run`` ->
``selection`` (-> ``anchor`` for the resolution); ``--claims-for`` -> the entry ->
``run`` -> ``selection``; a mutating run -> the entry -> ``run`` -> ``anchor``.
Layers go DOWN: entry -> ``run`` -> ``selection`` -> ``anchor`` -> ``schema``; no
cycle, no lazy import. Everything here is stdlib-only: the selector runs in CI
BEFORE the repository environment is installed, so no module in this package may
import ``agent_runtime`` (or ``scripts.god_file_probe``, a subject of this gate).
"""

__layer__ = "wiring"


# ── History: the measurements the contract comments above were written from ──
# (relocated from the comments beside the code by lane B5, 2026-09-25 -- rule 7:
# measurements move, contracts stay)
#
# * Concurrency: the H landing (2026-08-31) spent ten minutes on a phantom red
#   before a concurrent pytest in the same worktree was identified as its cause.
# * The S5 zero: until 2026-09-04 "no production source changed" and "seven
#   changed, none registered" both printed `mutation candidates: 0`; S5 landed
#   with zero executable claims (`--base 748687daa3^ --list` -> 0) and looked
#   exactly like a slice that needed nothing. Hence the census line.
# * The W1-H3 counts: symbol-overlap selection moved W1-H3's own diffs 6 -> 27,
#   32 -> 64 and 98 -> 104 against a cap of 20; on a push-shaped base (HEAD~1) a
#   two-commit branch selects 2 and 2. Hence the wall-clock budget.
# * The S4 inventory: `s4-a-pre-plan-done-receipt-re-enters-the-skills-phase`
#   anchored a line its slice did not change and appeared in no output at all.
#   Hence the UNSELECTED rows under --list.
# * The H-H2 miss (`0ecb921b9d`): that landing rewrote 82 lines of
#   agent_create.py, 41 inside `_reply`, and rendered the two lines
#   `hh2-the-one-reply-builder-stops-observing-the-revision` anchors on
#   (1170-1171) as unchanged CONTEXT, so the claim registered FOR the slice was
#   not selected by its own landing. Hence selection by SYMBOL.
# * The Z1 deletion-only hunk (`4bf4387760`): `@@ -32 +31,0 @@` contributed no
#   changed line, so every retirement wave reported `candidates: 0` with zero
#   mutation coverage by construction. Hence the two surrounding lines.
# * The locks.py platform fork: agent_runtime/locks.py defines
#   `_try_acquire` / `_prepare` / `_release` once per arm of `if os.name == "nt"`.
#   The walk descends into blocks since 2026-09-02, so both copies are reachable
#   and collide; `hh6-posix-file-lock-ignores-its-deadline` anchors at `module`,
#   is selected by lines (which is what selected and killed it on ubuntu-latest
#   all along), and `platforms` keeps it from reporting SURVIVED off POSIX.
# * derived_at: S8b and the S5 landing both paid the loud failure (a needle that
#   stopped occurring); 289 claims existed at the 2026-09-04 ruling and none was
#   backfilled.
