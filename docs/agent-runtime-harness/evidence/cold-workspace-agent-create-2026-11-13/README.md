# Cold workspace agent creation

On 2026-11-13, the Windows app's Default workspace contained a canonical
workspace record but no office surface. Agent creation returned
`workspace_not_found` because `AgentCreate.workspace_gate` tested
`OfficeStore.surface_exists`. Opening a scene first was an accidental
prerequisite.

The gate now uses the existing `OfficeStore.workspace_resolves` predicate,
which reads canonical workspace records. Placement remains in the same writer:
`OfficeStore.upsert_actor` creates the surface under its existing lock after
validation. No UI startup, alternate creation flow or new runtime owner was added.
An orphan scene alone no longer admits creation into a missing workspace.

## Live proof

Pinned Hermes `9832130316294885035427a3f5e7d8de0b32cdf5` through the supported
`hermes_checkout` launch option, with Eternia build
`f0d1e59fb2e5e9db8a97a33c5b4f3cb7704657c3`. This was a fresh QA namespace
and process, with the nonbillable text model fixture.

Home → AI → Default workspace → Agents → Add agent → Base → Create produced
`personainst_profile_base_agent_69e4d101`, listed as Connected. Mission Control
was never opened; the graph snapshot returned `mounted: false`.
The [app screenshot](cold-workspace-created.png) shows one connected agent.
The process closed gracefully with no turns in flight.

A second client lane independently reproduced successful creation and completed
a two-participant group discussion on the same runtime change; that lane retains
its full reply evidence in the Eternia client repository.

## Regression evidence

The new RPC-level regression starts with a real workspace and no scene, then
reads back the durable persona instance and actor. Same-key replay keeps the
instance and actor revision. The negative controls inventory all store bytes
before and after missing-workspace requests, both with and without an orphan scene.

In a scratch worktree, restoring `surface_exists` as the creation gate produced
**2 failed, 1 passed**: the valid cold workspace was refused and the orphan scene
was incorrectly admitted to placement. Restoring the fix passed all three cases.

Focused creation/service/subphase/RPC coverage plus name censuses: **140 passed**,
with one unrelated pre-existing ladder census failure in
`workspace_slot_recipe.py`'s `readiness`. The identical census row reproduced
on base `03ed4abd18` (**1 failed, 7 passed**), and was filed separately.
