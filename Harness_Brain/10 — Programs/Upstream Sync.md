---
type: program
program: upstream-sync
status: active
cursor: "2026-09-24 — Weekly merge of upstream f24a1d7f92 (1,663 commits) as 075fb4eba4 on seam/upstream-merge-2026-09-24, NOT on main: 73 conflicts, supersession 22 retired / 6 kept, origin/main (S2) merged in as 5b5a68bb69, ratchet 408/2612/11 -> 373/2404/10 at base f24a1d7f92, all 11 open PRs still open. Evidence: [[upstream-release-2026-09-24]]. Next: the operator lands the branch; weekly cadence."
tags: [program/upstream-sync, program, upstream]
---

# Upstream Sync

Goal (owner, 2026-09-21): **easy upstream syncs without much conflict.** The fork tracks `NousResearch/hermes-agent`, which moves ~850 commits a day. Conflicts come from exactly one place — fork edits inside upstream-owned files where upstream also moves — so the program has two halves: merge often (cadence) and shrink the delta (seams).

> [!info] Cursor
> `cursor::` see frontmatter.

## The state of the boundary (2026-09-21, [[Fork Boundary Map]])

- 1,439 fork-only files: never conflict.
- 449 upstream files carry fork edits (+18,300 / −2,300): 246 are tests (13,700 lines); ~140 production files; 118 files ≤ 5 lines; **22 files > 200 lines** — the heavy tail is the whole problem.
- A trial merge today: 40 conflicted files, 51 hunks, all in the heavy tail. `hermes_constants.py` (+286), `hermes_cli/main.py` (−187 upstream lines replaced), `scripts/run_tests_parallel.py`, the four `conftest.py` files.

## The rulings

- [[0006 — Upstream sync is a real merge, per-file reconciliation retired]] — the scheduled Codex job copied single upstream files ("reconcile X with upstream <sha>", tests NOT RUN) and never advanced the merge base; 6 files in 3 days against 3,000 commits. Retired; branches deleted.
- Cadence: a history-preserving `git merge upstream/main` **weekly**, in a worktree, conflicts resolved by rule, the validated suite run, landed fast-forward by the operator. A three-day gap already costs 40 conflicts.
- Conflict resolution rules (the merge lane's brief): keep both when additive; prefer upstream's version of upstream logic and re-apply the fork's addition on top; the fork's seams must survive (`_downstream_cli`, `_profile_bootstrap`, `_boot_clock`, harness registration, `process_registry` durable completions, profile scoping); never drop a fork test; keep the fork's `pyproject`/`uv.lock` pair plus new upstream rows.
- Fork gates apply to fork-authored lines only (`tests/_fork_scope.is_fork_authored`); no registers of upstream tests — owner 2026-09-24.

## Each merge — the supersession pass

After the conflicts are resolved and before the suite: for every upstream commit in the merge that touches a file on the footprint ledger or an area the fork carries (a `hook`/`carry` row, a recorded parallel, a second-door row), ask whether upstream now ships what the fork's edit does. If it does, adopt upstream's and delete the fork's in the merge lane (the ledger row leaves or is re-dispositioned, the ratchet follows down); if it only partly does, file an adopt row on arrival. Report the pass as rows retired / kept. Rule: rules 9 and 10 of `docs/agent-runtime-harness/planned/harness-plugin-and-upstream-seams.md` §1; evidence of the pattern: the 2026-09-24 merge's pass (22 retired / 6 kept).

## The plan: the harness as a plugin, the fork as the thin vehicle for core changes

[`docs/agent-runtime-harness/planned/harness-plugin-and-upstream-seams.md`](../../docs/agent-runtime-harness/planned/harness-plugin-and-upstream-seams.md) (2026-09-21). The hybrid end state the owner asked for: stay a fork if need be, detach if the measurement allows, keep core changes welcome.

- **Three dispositions** for every fork edit in an upstream file — `upstream` (PR), `hook` (behind the plugin surface, widening it by PR when it lacks something), `carry` (ours, additive where possible, on the ratchet with a reason).
- **Permanent carry is ruled per file (owner, 2026-09-24):** only a file with no override point (README licence line, AGENTS.md pointer, root `.gitignore`/`.gitattributes` litter, `uv.lock`) may be `carry-permanent`; nothing under `agent/`, `tools/`, `gateway/`, `hermes_cli/` is — rule 7 of `docs/agent-runtime-harness/planned/harness-plugin-and-upstream-seams.md` §1.
- **The ratchet** `[up-fp] files= deleted_lines= heavy=` only goes down; a wanted core change raises the fixture in the same commit with a `reason:` row. **Detach is a measurement:** `files=0` means the plugin runs on stock upstream and the fork is optional.
- **Stages:** S0 merge + ratchet → **S1 the harness registers its CLI as a plugin (first step; measured against the 500–650 ms plugin-discovery cost; fallback = a manifest-declared deferred CLI entry PR)** → S2 tools + prompt sections → S3 five upstream PRs (P1 = the profile-bootstrap extraction, the one replacement-shaped hunk in `main.py`) → S4 profile-home diff → S5 fork tests out of upstream test files (−242 files) → S6 desktop → S7 detach on the read (private repo on the owner's word).
- Upstream's own direction, read from its tree: core stays a narrow waist; products go to standalone repos; "plugins never touch core"; the plugin surface is an additive-only contract; the catalog is discovery only for plugins that want listing. `scripts/upstream_sync_gate.py` is read before Stage 0b writes the ratchet.

## Open upstream PRs (the pending-PR fallback: the same commit is carried on `main` and deleted when the weekly merge brings it back)

| PR | what | carried on `main` as | opened |
|---|---|---|---|
| NousResearch/hermes-agent#119069 | `fix(gateway)`: guard the POSIX-only `pwd` import in `legacy_launchd_labels_for_install` — `hermes update` crashed on Windows | `743277a3d5` (cherry-pick -x) | 2026-09-22 |
| NousResearch/hermes-agent#119071 | `test(kanban)`: the dispatcher fakes answer `poll()` so the Windows zombie-reaper branch runs under the tests | `801c24abcd` (cherry-pick -x) | 2026-09-22 |
| NousResearch/hermes-agent#121023 | the plugin compat scan skips bundled plugins (Stage 1 start-up cost) (`up/plugin-compat-bundled-skip`) | `e858df653a` via `seam/s1-proof` (in `709a3d6eba`) | 2026-09-24 |
| NousResearch/hermes-agent#121218 | `test(early-recovery)`: let the stdlib-only import guard pass relative imports (`up/import-guard-relative-imports`) | the in-place test edits whose ledger rows name `up/import-guard-relative-imports` | 2026-09-24 |
| NousResearch/hermes-agent#121219 | `test(win-pty)`: undo ConPTY hard line-wrap before matching child output (`up/win-conpty-line-wrap`) | the in-place test edits whose ledger rows name `up/win-conpty-line-wrap` | 2026-09-24 |
| NousResearch/hermes-agent#121220 | `test(env)`: match environment variable names case-insensitively on Windows (`up/win-env-var-case`) | the in-place test edits whose ledger rows name `up/win-env-var-case` | 2026-09-24 |
| NousResearch/hermes-agent#121221 | `test(line-endings)`: pin LF in byte-exact test fixtures on Windows (`up/win-line-endings`) | the in-place test edits whose ledger rows name `up/win-line-endings` | 2026-09-24 |
| NousResearch/hermes-agent#121222 | `test(home)`: patch USERPROFILE with HOME in ~-expansion tests on Windows (`up/win-tilde-home`) | the in-place test edits whose ledger rows name `up/win-tilde-home` | 2026-09-24 |
| NousResearch/hermes-agent#121224 | `test(paths)`: compare paths as paths, not POSIX spellings, on Windows (`up/win-path-spelling`) | the in-place test edits whose ledger rows name `up/win-path-spelling` | 2026-09-24 |
| NousResearch/hermes-agent#121225 | `test(posix)`: stop assuming POSIX-only os APIs and mode bits on Windows (`up/win-posix-only-apis`) | the in-place test edits whose ledger rows name `up/win-posix-only-apis` | 2026-09-24 |
| NousResearch/hermes-agent#121226 | `test(shell)`: resolve bash/python and pass bash POSIX paths on Windows (`up/win-shell-invocation`) | the in-place test edits whose ledger rows name `up/win-shell-invocation` | 2026-09-24 |

**Checked 2026-09-24 (lane MERGE):** all eleven rows above are OPEN upstream and none is in `upstream/main`; every carry stays.

**Dropped 2026-09-24 (lane UPREV, never opened):** `up/win-text-encoding` (upstream's `run_tests.sh` sets `PYTHONUTF8=1`, no red), `up/monkeypatch-undo-scoped` (no red), `up/profile-home-generic` (P7; perf memo, no red), `up/profiles-delete-guard` (P6; psutil is a pinned core dep, refusal unreachable). Their ledger rows are `carry` with reason "PR dropped 2026-09-24: …".

Rules used: branch cut from `upstream/main` (never from the fork), `fix/…` / `test/…` branch names, Conventional Commit subject, upstream's PR template filled in full, `scripts/check-windows-footguns.py` on the staged diff, platform named (this box: Windows 10 Home 22H2, build 19045 — read it from `winver`/`[System.Environment]::OSVersion`, never assume), the affected test files run before and after with the counts in the body. Rebase a PR only on request. The next seam PR is Stage 1's fallback: manifest-declared deferred CLI entries (`cli_commands:` in `plugin.yaml`), after Stage 1 measures the discovery cost on the merged tree.

## Related

- The fork's own CI runs on every push to `main` (68 `ci.yaml` runs since 2026-09-15) but has not been green once — a merge candidate nobody gets a green signal on is the old branch again. Row in [[fork-hygiene-queue]] (lane LEDGER-DOCS, 2026-09-24).
- The upstream tool dividend (26 upstream-only tool names, three renames) is recorded in the launcher's Mission Control program note as "planned, deliberately not rowed"; the SessionDB dividend (+146 upstream commits on `hermes_state*`, fork touch +98/−5) merges nearly free.
- The 2026-09-15 history reconstruction pinned upstream `110baa095b` — [[0005 — Fork history reconstruction 2026-09-15]].
