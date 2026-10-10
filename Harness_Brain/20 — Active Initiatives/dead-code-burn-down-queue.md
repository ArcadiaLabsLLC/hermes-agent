---
type: queue
program: downstream-refactor
status: open
tags: [queue, program/downstream-refactor, dead-code]
---

# Dead code burn-down — the hermes half

**This is a QUEUE, not evidence.** Every row is one line and a pointer. The census that wrote the first instalment is `docs/agent-runtime-harness/planned/god-file-program-2026-09-24.md` §0.1 (its third instrument) and §5; the per-file reads are the layout sheets under `docs/agent-runtime-harness/planned/god-file-layout-sheets/`. Nothing is restated here — a second copy of a fact is free to disagree with the first. The launcher's queue of the same name (`EterniaLauncher/Launcher_Brain/20 — Active Initiatives/dead-code-burn-down-queue.md`) is the format's origin; this file is the hermes half and holds only fork code (the program's scope rule).

## Why this is listed apart from the domain queues

[[TODO]] files work by the surface it serves. A dead-code deletion serves no surface — it is the execution register of one program (the god-file refactor, cursor in [[Downstream Refactor]]), and split by surface its rows would stop sharing a gate (the tombstone registry, `tests/agent_runtime/test_tombstone_registry.py`), a census, and a definition of done. Each row names the lane that owns the file, and its deletion lands in that lane's DELETE commit (never inside the MOVE, never inside the CHANGE). If this queue ever holds a row that is not a deletion, a test-seam move or a "kept, with reason" verdict, it is misfiled — send it to [[runtime-queue]] or [[fork-hygiene-queue]].

Row grammar: `- [ ] **symbol** · file · lines · class · evidence · lane`. Classes: **DELETE** (no caller anywhere; tombstone row), **TEST SEAM** (production has no caller, tests do — moves to `tests/_downstream/_seams.py` and is deleted from production; tombstone row), **KEEP** (a caller the census cannot see, named; the row closes as a verdict, not a deletion), **DECIDE** (an owner call).

## First instalment — filed 2026-09-24 by lane GOD-D (census over the 62 files; struck: 24 `@method`-registered `serve_rpc` handlers, false positives by construction)


## Second instalment — the reach census (W0-D), filed 2026-09-24 by lane W0

106 rows, one per cold function or cold arm; evidence note `docs/agent-runtime-harness/planned/downstream-god-file-refactor-reach-census.md` (population, traced suite, the 4 unrelated reds). Class DECIDE until the owning lane rules it (§4.3 of the 09-21 plan); a DELETE ruling lands under "Working a slice".


## Filed on arrival — 2026-10-06 (lane h-bundle-epoch)

- [ ] **`tools.registry.registry_epoch` has no production caller after h-bundle-epoch (chat_lane_bundle keys on content + `check_fn_epoch`); only tests read it** · fork seam in upstream file · evidence: `bc43588550` · lane: dead-code slice · released 2026-10-10 (lane-1010 returned L5.15, upstream; reason in `queue-sweep-2026-10-10/L5-outcomes.md`)

## Owed censuses (rows arrive when they run)

- [ ] **The argv census (09-21 plan §4.2)** · `fork / refactor` · which `_cmd_*` the launcher still lowers to argv; rows where "method exists, launcher no longer lowers" are deletions with their parser family entry and tests · H1 builder runs it; the launcher-side read is the launcher queue's · VERDICT 2026-09-29 h10-fhrel: the census is two-sided and the hermes half alone cannot rule a deletion: which `_cmd_*` the launcher still lowers to argv is read in `EterniaLauncher` (the launcher queue owns that read), and a "no longer lowered" verdict also needs the operator-CLI and script callers checked. Owed: the H1 builder lane runs both halves at once and files one DELETE row per handler with its parser-family entry and tests · OWNER 2026-09-29: schedule as a joint launcher+hermes lane, low priority; hermes half may start · VERDICT 2026-09-29 h10b-refac: hermes half taken — `docs/agent-runtime-harness/planned/argv-census-2026-09-29.md` (156 handlers over 157 argv paths, runtime parser walk; 18 with a method twin; 11 with a production caller outside the parser; 35 named by no test file). The launcher half (which of the 18 twin-carrying verbs `EterniaLauncher` still lowers to argv) is handed to the launcher `mission-control-queue.md`; one DELETE row per handler follows that read · SWEPT 2026-09-30 h13-sweep: hermes half landed (`docs/agent-runtime-harness/planned/argv-census-2026-09-29.md`); the launcher-half read has no row in `EterniaLauncher/Launcher_Brain/20 — Active Initiatives/mission-control-queue.md` yet (handed back to the orchestrator to file); the DELETE rows wait on it · released 2026-10-10 (lane-1010 returned L5.16, launcher side; reason in `queue-sweep-2026-10-10/L5-outcomes.md`)

## Working a slice

Campaign rule, every deletion: **delete and add the tombstone-registry row in the SAME commit, with the `git grep` proof in the commit body** (`git grep -nw <symbol> -- '*.py'` at the parent commit, pasted, showing only the definition and the tests being deleted with it); **reintroduce the symbol; watch `tests/agent_runtime/test_tombstone_registry.py` go red naming the row; revert; confirm green.** A TEST SEAM row is a deletion from production plus a move under `tests/_downstream/_seams.py`, same proof. Where nothing covers a deletion (a name with a live declaration elsewhere, so a tombstone would fire on correct code), that absence is reported as a finding under "Named absences" below — it is not a reason to delete quietly.

A "dead" verdict computed before a lane's commits is stale. Re-verify each row against the tree at dispatch time with the same grep; the census is a worklist, not a warrant. A deletion never rides a MOVE or a CHANGE commit (program rule 3): it is the lane's own DELETE commit.

## Named absences

(none yet)

## Closing a row

Delete it. When the last row of an instalment closes, the program ledger (`god-file-program-2026-09-24.md` §8) takes the count in the same commit.

## Filed on arrival — 2026-09-25, lane B3


## Filed on arrival — 2026-09-26, lane ACP-DROP

## Filed on arrival — 2026-10-07 (landing prep/hermes-waves-reviewed)


## Filed on arrival — 2026-10-10 (native representation review)

## Filed on arrival — 2026-10-10 (queue sweep lane-1010, filed by the orchestrator)

- [ ] **The post-v0.21.6 census slice: 14 names confirmed dead by `git grep -w` (`map_token_for_published_path`, `with_skill_evidence`, `drop_slot_fill`, `writer_registry_dir`, `settings_path`, `LIVE_PHASES`, `_registry_content_revision`, `PROMOTED_BRIEF_DESCRIPTION_CHARS`, `_LAUNCHER_QA_CORE_TOOLS`, five `builds/vocabulary.py` constants — check the launcher contract first) and 51 test-only names to DECIDE (seam vs delete); none traces to the v0.21.6 removals** · `fork / dead code` · `queue-sweep-2026-10-10/L5-outcomes.md` § L5.17 census · lane: one slice under "Working a slice"
