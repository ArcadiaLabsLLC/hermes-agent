---
type: map
tags: [map, invariants, rules]
aliases: [Invariants, Rules, Hard Rules]
---

# Architecture Invariants

Hard rules that hold across all fork work. Distilled from [`docs/downstream-development.md`](../../docs/downstream-development.md), the canon's [00-index rules](../../docs/agent-runtime-harness/00-index.md), [`CLAUDE.md`](../../CLAUDE.md) and the ADRs in `30 — Decisions/`. **Read those for full text** — this is the briefing card.

## Runtime

1. **Resolve `get_hermes_home()` at CALL time, never at module scope.** Under pytest the profile override is gated off, modules import at collection, and the hermetic-home fixture moves `HERMES_HOME` afterwards — a frozen constant stays on the operator's live store while every caller believes it moved (it deposited fixture sessions into the live `state.db`). Gate: `tests/test_no_frozen_hermes_home.py`, a ledger that only shrinks. A frozen name is legal only as a LABEL (`display_hermes_home()`).
2. **Chat is the only lane.** The goal/task mission lane (daemon, stage graph, proof gates, role gating) was removed 2026-07-30. Nothing new re-grows it. [[0008 — Chat is the only lane]].
3. **Profile declaration is the SOLE MCP admission authority.** Role fields are reporting-only. [[0009 — Profile declaration is the sole MCP admission authority]].
4. **The wire is additive-only.** Observability lands as log receipts, never as new keys on the parity envelope; byte-pinned goldens on BOTH repos enforce it (canon 03 + 07). A removed key in a contract dump is a launcher button that now exits 2 — read the diff before regenerating.
5. **Every write lane rides the hermes method lane by manifest membership.** argv is a fallback marked for delete. [[0003 — RPC route first]].
6. **We own the better PUSH, upstream owns the better CALL — build the union.** `agent_runtime` is not in upstream; the push lane is live-on-by-default. [[0001 — Fork boundary, PUSH vs RPC union]].
7. **A domain doc states implemented, verified truth only**, with a code anchor. Unbuilt work lives in `planned/`, one file per plan, with its field-notes stub. No new root files in the canon. When code moves, the doc moves in the same change set.

## Repository

8. **Upstream files are edited additively or not at all.** One import, one call, at a stable anchor. Replacing or deleting upstream lines is a permanent merge conflict. Refactor lanes never touch an upstream file (gate W0-G2). [[Fork Boundary Map]].
9. **Upstream sync is a real, history-preserving merge, weekly, tested.** Per-file reconciliation is retired. [[0006 — Upstream sync is a real merge, per-file reconciliation retired]].
10. **No push gates; checks are tests; never baseline to pass.** Pushes are instant. The gates exist and someone runs them; a ratchet list only shrinks. [[0002 — No push gates, checks are tests]] · [[0010 — Stale sweep and ratchets first, never baseline]].
11. **`scripts/run_tests.sh`, never bare `pytest`, for anything wider than one file.** Updater tests inside the validated scope do `git branch -f main origin/main`; bare pytest in the primary checkout detached 11 unpushed commits (2026-08-01). The validated scope is exactly `tests/agent_runtime tests/hermes_cli tests/hermes_state`, 8 workers, ≥25 min.
12. **A wait bound above 30 s declares its own `pytest.mark.timeout`.** `addopts` carry `--timeout=30`; a test whose bound exceeds it is killed before it can say what went wrong.
13. **Concurrent sessions share ONE git index.** Stage and commit in one breath. Cut worktrees from a NEUTRAL cwd — a `fetch` + `worktree add` run inside the primary checkout yanked `main` back to its pre-merge tip once (2026-08-31), and both usual tells lied.
14. **Every heavy command:** background, explicit timeout, log file, exit code captured unpiped, never polled, never piped through `tail`.
15. **The 800-code-line ceiling is flat; MOVE and CHANGE never share a commit; one MOVE + one CHANGE per lane.** [[0007 — Flat 800-line ceiling and bulk mode]].
16. **Fable plans, Opus builds; every lane writes its own field notes in the repo it stands in; the skill is written last.** [[0004 — Fable plans first, Opus builds, field notes per lane]].
17. **A brief is a work order: ≤ 40 lines, one page to read, steps, capped report.** `CLAUDE.md` § Briefing a subagent.

> [!important] Run the thing before fixing it
> A filed row is often right that something is wrong and wrong about why. Re-measure before you re-design (three of the placement-verb lane's rows were wrong about their own mechanism; the "pulled agent invisible" row had no pull at all).
