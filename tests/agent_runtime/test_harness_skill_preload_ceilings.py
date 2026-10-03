"""Every canonical harness skill's preloaded SKILL.md fits its declared ceiling.

`scripts/verify_harness_skill_install.py` reports an overage only at install
time (the post-merge install said FAILED for harness-runtime-model, 16,724 B
against 16,384 B, on 2026-10-03); this reds the tree that carries one. The fix
for an overage is moving prose to the skill's references/, never raising the
ceiling silently.
"""

from __future__ import annotations

from agent_runtime.skill_install import HARNESS_SKILLS, harness_skill_size_overages, harness_skill_size_states


def test_no_canonical_harness_skill_preloads_over_its_ceiling():
    names = list(HARNESS_SKILLS)
    assert names, "the canonical skill set enumerated empty"
    # Positive control: the states are real reads of real files, not an empty set.
    assert {state.skill for state in harness_skill_size_states(names)} >= {"harness-runtime-model"}
    overages = harness_skill_size_overages(names)
    assert overages == [], [f"{s.skill}: {s.size} B > {s.ceiling} B" for s in overages]
