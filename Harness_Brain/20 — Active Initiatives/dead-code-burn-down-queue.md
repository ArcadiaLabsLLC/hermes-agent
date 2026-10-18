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

Row grammar: [[0011 — One brain per repo, one Mission Control queue in the launcher]] § Row grammar (one line, a `DEAD-…` ID, exactly one status) — here `- **`DEAD-<SLUG>` — symbol** · file · lines · class · evidence · lane · <status>`. Classes: **DELETE** (no caller anywhere; tombstone row), **TEST SEAM** (production has no caller, tests do — moves to `tests/_downstream/_seams.py` and is deleted from production; tombstone row), **KEEP** (a caller the census cannot see, named; the row closes as a verdict, not a deletion), **DECIDE** (an owner call).

## First instalment — filed 2026-09-24 by lane GOD-D (census over the 62 files; struck: 24 `@method`-registered `serve_rpc` handlers, false positives by construction)


## Second instalment — the reach census (W0-D), filed 2026-09-24 by lane W0

106 rows, one per cold function or cold arm; evidence note `docs/agent-runtime-harness/planned/downstream-god-file-refactor-reach-census.md` (population, traced suite, the 4 unrelated reds). Class DECIDE until the owning lane rules it (§4.3 of the 09-21 plan); a DELETE ruling lands under "Working a slice".


## Filed on arrival — 2026-10-06 (lane h-bundle-epoch)


## Owed censuses (rows arrive when they run)


## Filed on arrival — 2026-10-15 (argv census cut, lane w1015e-fh-h)


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


## Filed on arrival — 2026-10-16 (lane h5-deadcode)
