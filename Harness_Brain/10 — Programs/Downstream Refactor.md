---
type: program
program: downstream-refactor
status: active
cursor: "2026-09-24 — DESIGN refresh on branch docs/god-file-design-2026-09-24 (lane GOD-D): 62 fork files over 800 raw lines (34 by code lines), the owner's enterprise bar as rules 12–17 with gates W0-G5/G6/G7, three wave-1 layout sheets (persona_commands, harness, serve), the dead-code queue, weakness escalation in CLAUDE.md; five owner questions in the program note §9. First executable unit after owner review: Wave 0 + H1, unchanged from the 09-21 plan."
tags: [program/downstream-refactor, program, refactor]
---

# Downstream Refactor (the god-file program)

Every fork-owned production file under a flat 800-code-line ceiling, split to a responsibility layout, one MOVE + one CHANGE commit per lane, a dead-code delete list, a duplicate-collapse list, and a mechanical "keep out of upstream" fence. The hermes half of the program the launcher ran 2026-09-18 → 21.

> [!info] Cursor
> `cursor::` see frontmatter.

## Where the truth lives

- **The 2026-09-24 refresh (reads first):** [`docs/agent-runtime-harness/planned/god-file-program-2026-09-24.md`](../../docs/agent-runtime-harness/planned/god-file-program-2026-09-24.md) — the scope rule, the 62 measured, rules 12–17 and their gates, which §§ of the 09-21 plan it supersedes; layout sheets in [`god-file-layout-sheets/`](../../docs/agent-runtime-harness/planned/god-file-layout-sheets/); deletions in [[dead-code-burn-down-queue]].
- **The plan (the spine):** [`docs/agent-runtime-harness/planned/downstream-god-file-refactor.md`](../../docs/agent-runtime-harness/planned/downstream-god-file-refactor.md) — §0 ground truth, §1 rules, §2 lanes with a layout for every file, §3 order, §4 dead-code list, §5 duplicate list, §6 method (the launcher playbook applied), §7 what the operator owes, §8 ledger.
- **Field notes:** [`downstream-god-file-refactor-field-notes-2026-09-21.md`](../../docs/agent-runtime-harness/planned/downstream-god-file-refactor-field-notes-2026-09-21.md) — how every number was taken; lane sections appended by builders.
- **The instrument:** `scripts/refactor_census.py` — code-line counter (matches the operator's table), per-file survey, dead-name census, duplicate-body census.
- **The method's origin:** `EterniaLauncher/docs/mission_control/planned/mission-control-refactor-program.md` (four owner amendments) and `EterniaLauncher/docs/tooling/SUBAGENT_DEPLOYMENT_PLAYBOOK_2026-09-21.md`.
- **The EXEC_CARD** (one page an exec lane reads) is a Wave 0 deliverable: `planned/downstream-god-file-refactor-EXEC_CARD.md`.

## The facts that shape it

- Files 1 and 2 (`persona_commands.py` 6,271 + `harness.py` 5,105) are ONE namespace: the parts are `exec`'d into harness.py's globals, and 263 test patches on `harness.<name>` depend on that. Converting a part to a module makes those patches silent no-ops unless harness.py stops re-exporting — gate W0-G4. [[Touching the harness CLI]].
- File 3 (`serve.py`) is one 3,760-line function with 39 closures; `_handle_message` reads 21 enclosing locals. H4 turns it into `ServeSession`, last, gated on RB-7/RO-9 and an operator boot.
- The by-name dead-code census finds **0** unreferenced top-level names in the 41 (the 2026-08 waves burned them). The delete list = 12 test-only production functions + the argv fallback lanes R-C4 marked for delete + a coverage reach census (W0-D). The 16 `serve_rpc` names the census printed as dead are `@method`-registered false positives.
- All 41 are fork-only; the fence is a proof, not a design constraint.

## Order

`W0 → H1 → {H2, H3} → H4 (last)`; `S1 → {R1, R2, R3, R4, C1, T1, D1}` in parallel. Thirteen lanes. Design sittings one at a time on the strongest model; review-and-fix lanes run their killing mutations; exec lanes uncapped on touched tests only; one batched landing at a time with concurrent gates; every lane reports its tool-call count.

## Owed by the operator

1. One boot on the H4 build (the restart fence lives in the code H4 turns into a class).
2. The §4.2 rulings where the launcher still lowers a verb to argv.
