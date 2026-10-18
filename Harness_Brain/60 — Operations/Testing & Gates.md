---
type: operations
tags: [operations, testing, gates]
---

# Testing & Gates

Which checks exist and what each guarantees is the canon's [gate directory](../../docs/agent-runtime-harness/11-gate-directory.md) (kept current by `tests/tooling/test_gate_directory_current.py`). There is no push gate ([[0002 — No push gates, checks are tests]]) — a check is only real when someone runs it. How and when to run them: [[Running the tests]]. This note keeps the operational side: the unattended run, CI, and positive controls.

## Unattended

`scripts/unattended_suite_run.ps1` writes a dated report to `qa-artifacts/` (validated suite + mutation `--list` + the two outside scopes). `scripts/hermes-unattended-suite-task.xml` is a Task Scheduler definition the operator registers by hand (two `REPLACE-ME` markers → the primary checkout). Nothing in the repo registers it.

## CI

The fork's `fork-gates.yml` is active again as of 2026-10-12; [main run 38312372163](https://github.com/ArcadiaLabsLLC/hermes-agent/actions/runs/38312372163) passed. It runs selected mutation claims plus the tombstone and docket gates. The upstream `ci.yaml` remains disabled at that check. These jobs do not replace the bundled landing suite or native-platform proof. Check the exact workflow and source SHA; [[Running the tests]] owns landing requirements.

## Positive controls

A new gate lands with its killing mutation recorded through `changed_line_mutation_check.py`; a CHANGE commit carries its control's pasted red. A control that has not been run is a belief.
