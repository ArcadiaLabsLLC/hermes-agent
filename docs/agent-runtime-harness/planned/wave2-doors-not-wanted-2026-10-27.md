# Planned — the R008 preparation door and the R010 registrar acknowledgement are not wanted

**Status:** decided 2026-10-27 (planning lane w1027k-h-plan), closing row
`RT-WAVE2-PREP-AND-REGISTRAR-DOORS` as REFUTED. Replans the R008 and R010 sections of
[`runtime-wave2-ownership-2026-10-07.md`](runtime-wave2-ownership-2026-10-07.md) (left in
place; its R034 section shipped as the tool-form owner).

## Problem

The 2026-10-07 checkpoint designed two doors on a frozen grind base:

- **R008** — an upstream `AgentPreparationContext` so agent construction and system-prompt
  build could yield mid-step, because one prewarm step held the process-wide
  `_WORKDIR_LOCK` and a turn arriving mid-step waited for it.
- **R010** — a request-owned MCP registration handle with a cancellation
  acknowledgement, because an abandoned admission's worker held the admission mutex
  and the next admission refused `mcp_admission_lane_busy`.

The row asks whether either is still wanted after `d1324ca9dd` and `e61e5f0088`.

## Decisions

1. **R008 is not wanted.** `d1324ca9dd` (run-serialization S5) made a run pass through
   `_WORKDIR_LOCK` once at entry and hold only `root_run_lock(root)` for its body
   (`agent_runtime/profile_runner/execute.py`, `agent_runtime/profile_runner/workdir.py`), so a
   long prompt build on one chat root no longer blocks a turn on another; the profile
   binding is ContextVar-only (`agent_runtime/profile_context.py::persona_profile_context`).
   What still serialises is POSIX `HOME` under `_PROCESS_HOME_LOCK`, which is a narrower
   door already filed upstream as `RT-POSIX-TURNS-SERIALIZE-BEHIND` (a context-aware home
   resolver). A turn on the SAME root waiting for that root's prewarm is the per-root
   lock doing its job. A whole-preparation context API would be a large upstream PR
   buying nothing those two do not.
2. **R010 is not wanted.** The owner ruled on 2026-10-15 (queue-sweep L1.11, reversing
   refuse-not-wait): the next admission WAITS on the mutex within its own budget and
   refuses only when the budget is spent, and the registrar itself stays uncancellable.
   `e61e5f0088` built that (`agent_runtime/mcp_admission/registration.py::Admission`).
   The starvation R010 existed for is gone; a cancel handle would add an upstream API to
   shorten a wait the ruling accepted.
3. **Neither is a fork seam nor an upstream PR.** No candidate is carried to the
   upstream ledger. If a live measurement later shows a same-root prewarm step costing
   turns, that is a new row with its measurement, not this design.

## Slices

None. The row is deleted as REFUTED in the commit that lands this note, naming
`d1324ca9dd` and `e61e5f0088`.

## Test plan

Nothing to build. The behaviours the decisions rest on are pinned by
`tests/agent_runtime/test_run_serialization_per_root.py` (two roots run concurrently)
and `tests/agent_runtime/test_mcp_admission.py` (the bounded wait).

## Open questions

None for the owner.
