---
type: operations
tags: [operations, testing, gates]
---

# Testing & Gates

Every check this repo has, who runs it, and what it protects. There is no push gate ([[0002 — No push gates, checks are tests]]) — a check is only real when someone runs it. How to run the suite itself: [[Running the suite]].

## The gates (run at a landing, concurrently)

| gate | command / test | protects | shrinks-only list? |
|---|---|---|---|
| validated suite | `scripts/run_tests.sh tests/agent_runtime tests/hermes_cli tests/hermes_state` | everything; ≥ 25 min | — |
| CLI contract | `scripts/dump_cli_contract.py --check` ↔ `tests/hermes_cli/test_cli_contract_dump.py` | the launcher's argv buttons | — |
| payload contract | `scripts/dump_payload_contract.py --check` ↔ `tests/hermes_cli/test_payload_contract_dump.py` | the launcher's character keys | — |
| doc-cite adjacency | `scripts/doc_cite_adjacency.py --exclude archive --exclude planned` (RULED scope; the bare walk is red by 829 by ruling) | canon anchors point at real code | — |
| docket stage claims | `tests/test_docket_stage_claims.py` | a plan that says EXECUTED names a SHA in this history | — (one pre-existing red, queue row) |
| frozen HERMES_HOME | `tests/test_no_frozen_hermes_home.py` | call-time home resolution | yes |
| tombstone registry | `tests/agent_runtime/test_tombstone_registry.py` | deleted symbols stay deleted (census ≥ 703; loops expand literals — never grep-count) | yes |
| duplicate helper bodies | `tests/agent_runtime/test_duplicate_helper_bodies.py` (`_GRANDFATHERED`) | one authority per helper; widened by the refactor's W0-G3 | yes |
| changed-line mutation | `scripts/changed_line_mutation_check.py` (`--list --base origin/main` is safe unattended; a real run takes `.mutation_gate.lock`) | every claimed test line still kills its mutation | — |
| coverage claims | `scripts/run_tests.sh tests/test_coverage_claims_resolve.py tests/scripts` | citations resolve; outside the validated four dirs, run by nobody unless named | — |
| toolset manifest | `scripts/dump_toolset_manifest.py` ↔ `tests/agent_runtime/test_harness_tool_inventory.py` | the fork's tool inventory | — |
| test-env drift | `scripts/check_test_env_drift.py` | the hermetic env the runner builds | — |
| upstream sync gate | `scripts/upstream_sync_gate.py` | (read it — queue row) | — |
| **refactor gates (Wave 0, planned)** | `tests/tooling/test_downstream_size_ceiling.py` (`[ds-size]`), `test_refactor_stays_downstream.py`, `test_harness_namespace_is_thin.py` | 800-line ceiling, upstream fence, no silent patch no-ops | yes |

## Unattended

`scripts/unattended_suite_run.ps1` writes a dated report to `qa-artifacts/` (validated suite + mutation `--list` + the two outside scopes). `scripts/hermes-unattended-suite-task.xml` is a Task Scheduler definition the operator registers by hand (two `REPLACE-ME` markers → the primary checkout). Nothing in the repo registers it.

## CI

`.github/workflows/tests-os.yml` (one plain `pytest` per OS, fails on zero selected tests), `tests.yml`, `ci.yaml`, `js-tests.yml`, `rust-tests.yml`, `installer-tests.yml`, `plugin-catalog-ci.yml` — all UPSTREAM workflows. On the fork they are "largely inert" (billing) and **no run has fired on `main` since 2026-09-07** (queue row). Do not read CI as evidence until that row closes.

## Positive controls

A new gate lands with its killing mutation recorded through `changed_line_mutation_check.py`; a CHANGE commit carries its control's pasted red. A control that has not been run is a belief.
