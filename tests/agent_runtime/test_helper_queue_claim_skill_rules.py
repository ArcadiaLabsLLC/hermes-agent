"""A helper a lead sends to an EterniaLauncher queue row claims it under a lane of its own,
pushed, from a timeout long enough to finish, and recognises its own claim (EterniaLauncher row
QA-FU-A-HELPER-CLAIMS-IN-THE-SHARED-CHECKOUT-AND-STOPS-ON-ITS-OWN-CLAIM, seen 2026-11-20).

Neko Mission Lead dispatched Launcher Dev Agent to a row without naming a lane; the helper
claimed ``--as dev`` (its persona id, shared by every instance) without ``--push`` under a 30 s
terminal timeout, the claim committed on the shared primary's ``main`` after the timeout, and
its retry read "TAKEN by dev" as another lane's and stopped. The lead's skill
(harness-runtime-model) is where a brief gets its lane; the helper's always-on skill
(harness-dev-delivery) is where the claim line, the timeout and the retry are taught.

KILLING MUTATIONS: drop the lead's "lane name of its own" bullet, or the helper's
"Claiming a queue row" section — each reddens its test below.
"""

from __future__ import annotations

from pathlib import Path

_SKILLS = Path(__file__).resolve().parents[2] / "docs" / "agent-runtime-harness" / "harness-skills"


def _section(text: str, heading: str) -> str:
    start = text.index(heading)
    rest = text[start + len(heading):]
    end = rest.find("\n## ")
    return rest if end < 0 else rest[:end]


def test_a_lead_names_each_helper_a_lane_of_its_own():
    text = (_SKILLS / "harness-runtime-model" / "SKILL.md").read_text(encoding="utf-8")
    delegation = _section(text, "## Delegation")
    assert "lane name of its own" in delegation
    # The instance handle, never the shared persona id nor the Work engine's `persona:` form.
    assert "instance handle" in delegation
    assert "bare persona id" in delegation
    assert "never\n  `persona:<id>`" in delegation or "never `persona:<id>`" in delegation
    assert "--as <lane> --tree <its own worktree> --push" in delegation
    assert "300 s" in delegation


def test_a_helper_claims_pushed_with_room_to_finish_and_knows_its_own_claim():
    text = (_SKILLS / "harness-dev-delivery" / "SKILL.md").read_text(encoding="utf-8")
    claiming = _section(text, "## Claiming a queue row")
    assert "--as <lane> --tree <your worktree> --push" in claiming
    assert "300 s" in claiming
    assert "never invent one from your persona id" in claiming
    assert "already yours" in claiming
    assert "never in the primary checkout" in claiming


def test_a_brief_closes_a_finished_row_and_never_deletes_it():
    """QA-FU-A-LEAD-AGENT-BRIEFS-HELPERS-AGAINST-THE-REPOS-OWN-RULES (seen 2026-11-20): Neko's brief
    said "delete the row on Launcher main". The lead briefs from the repo's rules file in its context
    and a helper closes with ``close_row.dart``. KILLING MUTATION: drop the lead's "repo's own rules
    file" bullet, or the helper's step 5 — each reddens an assert here."""

    lead = _section((_SKILLS / "harness-runtime-model" / "SKILL.md").read_text(encoding="utf-8"), "## Delegation")
    assert "repo's own rules file" in lead
    assert "## <slot> — CLAUDE.md" in lead
    assert "close_row.dart <ID> --done <sha> --commit" in lead
    assert "never tell a\n  helper to delete a row" in lead
    helper = _section((_SKILLS / "harness-dev-delivery" / "SKILL.md").read_text(encoding="utf-8"),
                      "## Claiming a queue row")
    assert "close_row.dart <ID> --done <sha> --commit" in helper
    assert "Never delete a row" in helper


def test_a_helper_cuts_its_worktree_outside_the_checkout_and_names_its_own_lane():
    """QA-FU-A-HELPERS-WORKTREE-LANDS-INSIDE-THE-SHARED-CHECKOUT (EterniaLauncher, seen 2026-11-20): a
    helper ran ``git worktree add … EterniaLauncher/worktrees/w1120a-qaclaimwin`` (the primary then
    showed ``?? worktrees/``), and stopped 49 s in to ``clarify`` a lane name its brief left as
    ``<lane>``. The lead's brief names the folder and the lane (or says pick one); the helper picks a
    ``wNNNNx-<slug>`` lane itself and cuts outside every primary checkout. KILLING MUTATIONS: drop the
    lead's "OUTSIDE every primary checkout" clause, or restore the helper's "ask your lead" step 1 —
    each reddens an assert here."""

    lead = " ".join(_section((_SKILLS / "harness-runtime-model" / "SKILL.md").read_text(encoding="utf-8"),
                             "## Delegation").split())
    assert "OUTSIDE every primary checkout" in lead
    assert "`EterniaLauncher-worktrees/`" in lead and "`.worktrees/` beside the clone" in lead
    assert "pick a `wNNNNx-<slug>` lane yourself, without asking" in lead
    helper = " ".join(_section((_SKILLS / "harness-dev-delivery" / "SKILL.md").read_text(encoding="utf-8"),
                               "## Claiming a queue row").split())
    assert "OUTSIDE every primary checkout" in helper
    assert "`EterniaLauncher-worktrees/<lane>`" in helper and "`.worktrees/<lane>` beside" in helper
    assert "pick a `wNNNNx-<slug>`" in helper and "never ask" in helper
    assert "ask your lead" not in helper


def test_one_unanswered_approval_neither_stops_a_helper_nor_releases_its_claim():
    """RT-FU-A-HELPER-GIVES-UP-ITS-ROW-AFTER-ONE-UNANSWERED-STEP (seen 2026-11-21 05:25Z): a helper
    whose one log read went unanswered released its row, on a brief that said "If you hit a real
    block, name it and stop". KILLING MUTATIONS: drop the helper's paragraph under "Report Blocker",
    or the lead's "never a stop condition" sentence — each reddens an assert here."""

    helper = " ".join(_section((_SKILLS / "harness-dev-delivery" / "SKILL.md").read_text(encoding="utf-8"),
                               "## Report Blocker").split())
    assert "(`block_class: unanswered`) is not a blocker" in helper
    assert "keep the task and your claim" in helper
    assert "Release a claim only when the task itself cannot go on" in helper
    lead = " ".join(_section((_SKILLS / "harness-runtime-model" / "SKILL.md").read_text(encoding="utf-8"),
                             "## Delegation").split())
    assert "One unanswered approval is never a stop condition" in lead
