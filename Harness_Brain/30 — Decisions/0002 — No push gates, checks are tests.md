---
type: adr
id: 0002
status: accepted
date: 2026-09-03
tags: [adr, process, gates]
---

# 0002 — No push gates, checks are tests

> [!summary]
> **No pre-push hooks in either repo.** hermes `504953f6ad`, launcher `cba592ddb`. The checks the hook ran (doc-cite adjacency + CLI contract; the validated suite) remain as commands and tests that someone runs; pushes are instant (launcher 2.6 s).

## Context

A pre-push hook that costs a suite run (≥ 25 min for the validated scope) is not how the checks get value: it made landings serial, tempted bypasses, and still missed whole-program gates that only a full run reaches. The history: release-only lanes 2026-08-30, hermes lane B added 2026-09-02, both removed 2026-09-03 by operator ruling.

## Decision

The one hook that stays is `post-merge` (re-installs the canonical skill packages). Everything else is a test or a script: `scripts/run_tests.sh` on the four validated directories, `scripts/dump_cli_contract.py --check`, `scripts/dump_payload_contract.py --check`, `scripts/doc_cite_adjacency.py` in its ruled scope, `scripts/changed_line_mutation_check.py`. `scripts/unattended_suite_run.ps1` is a REPORT the operator may schedule, not a gate. **Never run the tooling gate as a landing blocker.**

## Consequences

- An unrun gate is indistinguishable from a passing one: `main` went red unreported twice (`6979bad59`, 2026-09-04). The lander runs the gates; the batched-landing lane of the refactor method runs them once per batch, concurrently.
- The fork's CI is "largely inert"; making it fire again is a queue row, not a hook.

## Alternatives

Keep the hook for release branches only (was the 2026-08-30 shape; retired with the rest).
