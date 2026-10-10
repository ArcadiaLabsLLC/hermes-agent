---
type: handoff
program: upstream-sync
tags: [handoff, program/upstream-sync]
---

# Merging upstream

The weekly merge of the latest `NousResearch/hermes-agent` RELEASE tag into the fork — never `upstream/main` (owner, 2026-10-06). Rule: [[0006 — Upstream sync is a real merge, per-file reconciliation retired]]. State: [[Upstream Sync]].

> [!important] Never in the primary checkout, never a rebase, never `main` from a lane
> Cut a worktree from a NEUTRAL cwd; merge there; push the candidate branch; the operator lands fast-forward after the Step 7 gate.

## Steps

0. Pick the tag: `gh release view --repo NousResearch/hermes-agent --json tagName -q .tagName` → `<tag>`. If `git merge-base --is-ancestor <tag> origin/main` exits 0, stop: nothing to merge.
1. From `X:/Eternia` (not inside the checkout): `git -C X:/Eternia/hermes-agent fetch origin && git -C X:/Eternia/hermes-agent fetch upstream --tags`; `git -C X:/Eternia/hermes-agent worktree add X:/Eternia/worktrees/merge-upstream-<date> -b merge/upstream-<date> main`. Then, inside the merge worktree, before merging — generated files take upstream's side and are regenerated in Step 3 (owner, 2026-10-06):
   ```
   git config merge.regen.name "take upstream, regenerate after merge"
   git config merge.regen.driver "cp %B %A"
   attrs="$(git rev-parse --git-common-dir)/info/attributes"; mkdir -p "$(dirname "$attrs")"
   for f in uv.lock apps/shared/src/gateway-contract.generated.ts apps/shared/src/gateway-contract.openrpc.json; do
     grep -qxF "$f merge=regen" "$attrs" 2>/dev/null || echo "$f merge=regen" >> "$attrs"
   done
   ```
   The config and attributes live in the shared clone and stay (set once; the lines are idempotent).
2. Size it first: `git merge-tree --write-tree main <tag>` lists the conflicts without touching the tree (it ignores merge drivers, so it still lists the three regen files); count hunks per file (`git show <tree>:<file> | grep -c '^<<<<<<<'`).
2b. **Replay the daily branch's resolutions** (see "Daily integration branch" below): `git config rerere.autoUpdate false`, then `sh scripts/rerere_train.sh origin/main..origin/integration/upstream-daily`. It re-runs each daily merge, records its committed resolution, and leaves the worktree where it started. In Step 3, rerere pre-fills every conflict the daily branch already solved; read each one (`git rerere diff`) before staging it — the cache is shared by every worktree of the clone.
3. `git merge <tag> --no-ff --no-commit`, then resolve by rule:
   - **every fork addition in a conflicted hunk gets one of three verdicts (owner, 2026-10-07), asked in this order:**
     1. **drop** — upstream's new code now does what the fork's addition does: take upstream's and delete the fork's. Proof: the fork test covering that behaviour passes on upstream's code (no such test → write it first). Partly covered → keep only the missing part.
     2. **extract** — still needed and more than a couple of lines: move the logic into a fork-owned module (`agent_runtime/` or a fork-only file the ledger already lists) and leave one call line in the upstream file. A MOVE commit separate from the merge, behaviour identical, the same tests green.
     3. **upstream it** — generic enough that upstream would take it (a bug fix, a missing hook, a public name): keep it for now and add a `PR candidate` row to `docs/agent-runtime-harness/planned/upstream-footprint-ledger.md`. Do not open the PR from the merge job.
     Never re-apply a fork addition only because the conflict showed it. Record each as `drop` / `extract` / `upstream` / `kept (reason)` in the merge commit body;
   - additive on both sides → keep both;
   - upstream logic changed → upstream's version, the fork's addition re-applied on top;
   - the seams survive: `_downstream_cli.build_downstream_parsers`, upstream's `_apply_profile_override` block with the fork's three in-place deltas (entrypoint gate from `_profile_bootstrap`, `harness agent set-profile` exemption, resolution receipt), `_boot_clock`, `"harness"` in the console list, `process_registry.restore_durable_completions`, profile scoping in `hermes_constants` / `profiles.py`;
   - never drop a fork test (move it if upstream deleted its anchor);
   - `pyproject.toml`: the fork's pair (`coverage==7.16.0`, `pytest-timeout==2.4.0`, the `exclude-newer-package` exemptions, `--timeout=30` in `addopts`) plus any NEW upstream rows;
   - generated files (`uv.lock`, the two `apps/shared/src/gateway-contract.*` files) arrive as upstream's copy via the `regen` driver; after `pyproject.toml` is resolved run `uv lock` (with the repository-pinned uv, `uv` 0.12.3 as of 2026-10-06; a newer host uv cannot resolve upstream's Android/playwright split), then `python scripts/sort_uv_lock_options.py` (uv 0.12.3 on Windows writes `[options.exclude-newer-package]` unsorted; v0.21.6 churned +82 lines), then `python scripts/gen_gateway_contracts.py`, then `python scripts/gen_gateway_contracts.py --check`, and stage the three files.
4. Commit: `merge: upstream <tag> into main (<date>)`, body = each conflicted file + the rule applied.
4b. Bring over the daily branch's own fork-side fixes that apply at this tag: `git log --reverse --format='%h %s' --grep='^fix(merge)' --grep='^refactor(merge)' origin/main..origin/integration/upstream-daily`, then `git cherry-pick -x <sha>` for each that touches code present at `<tag>`. One that conflicts on upstream code newer than the tag is skipped and named in the report. (These are the fork's own commits; upstream content still arrives only through the merge.)
5. Touched tests directly (files that import a conflicted module), background, log, unpiped exit code. Fix merge-caused reds as `fix(merge): …`; name pre-existing reds by running the one test on `main`.
   5b. **Re-check the skip list** (`tests/fixtures/upstream_skip_list.txt`, plan `docs/agent-runtime-harness/planned/suite-speed-2026-10-05.md` §3 Stage 1). Name every `env` / `upstream` row's file on one `scripts/run_tests_bundled.sh --scope full <file> <file> …` run (a named file always runs), background, log, unpiped exit code. A file green on the merge candidate leaves the list in the merge commit; a file still red keeps its row with the SHA advanced to the incoming upstream tip. `P0` rows are NOT run here: they run only under the watchdog/VM the fork-hygiene P0 row names, and keep their SHA.
   5c. **Retire the upstream-red marks the release fixed** (class row, 2026-10-10: v0.21.6 turned ten strict `_up_red` marks into XPASS(strict) reds after the merge). Collect the test files named by the rows of every `tests/_downstream/id_markers/upstream_reds*.py` table and run them on the merge candidate in one `scripts/run_tests.sh <file> <file> …` run, background, log, unpiped exit code. Every node reported `XPASS(strict)` is a mark upstream's fix outlived: delete its row in the merge commit and list the deleted ids in the body. A row still `xfailed` stays.
6. `git push -u origin merge/upstream-<date>`. Report ≤ 30 lines, including the supersession count (`superseded` / `partly` / `kept`) and the [up-fp] line before/after.
7. **Landing (operator or landing lane):** `scripts/run_tests_bundled.sh --scope full tests` (the skip list applies; never on a workstation while the fork-hygiene P0 row is open) + the two contract dumps `--check` + `scripts/doc_cite_adjacency.py` in its ruled scope; then `git push origin merge/upstream-<date>:main` if fast-forward. Update the cursor, delete the queue row, remove the worktree.

## Daily integration branch (owner, 2026-10-06)

`integration/upstream-daily` absorbs upstream a day at a time so a release merge replays known answers instead of solving ~3,000 commits cold. It is never landed: it carries upstream commits past the release.

Each day, in a worktree on `integration/upstream-daily` (create it from `origin/main` the first time):
1. `git merge origin/main --no-ff` (the fork's newest work), then `git merge upstream/main --no-ff` with the Step 1 regen driver configured. History-preserving merges only; never rebase, never reset the branch.
2. Resolve by the Step 3 rules (drop / extract / upstream verdict per fork addition, drop first); an `extract` is its own `refactor(merge): …` MOVE commit; regenerate the three generated files; commit `integrate: upstream/main <sha> (<date>)`, body = each conflicted file + the rule applied.
3. A fork-side repair the merge needs is its own commit, subject `fix(merge): …` — Step 4b looks for exactly that prefix.
4. Run the tests that import a conflicted module; push the branch. Report conflicts per file, the fixes, and the test counts.

When a release tag appears, the release merge (Steps 0–7) starts fresh from `origin/main`, merges only `<tag>`, and uses Step 2b (replay the resolutions) and Step 4b (carry the `fix(merge)` commits). That branch is the one the operator lands. Proven 2026-10-06 on GPT's rehearsal `merge/upstream-main-206102314a81`: see the commit that added this section.

## The scheduled job (GPT/Codex, daily; acts only on a new release)

The job's whole description, pasted as its prompt — it runs the Steps above and nothing else ([[0006 — Upstream sync is a real merge, per-file reconciliation retired]]):

```
Upstream release merge for ArcadiaLabsLLC/hermes-agent. Runs daily; does nothing unless upstream has published a release the fork has not merged.
Read Harness_Brain/50 — Agent Handoffs/Merging upstream.md (the one page) and follow its Steps 0-6 exactly.
0. Fetch origin and upstream (https://github.com/NousResearch/hermes-agent) with --tags. Tag = the latest release: `gh release view --repo NousResearch/hermes-agent --json tagName -q .tagName`, or without gh, the highest `v<year>.<month>.<day>` tag by version sort (`git tag -l 'v20*' --sort=-v:refname | head -1`; never an `abandoned-rc*` tag). If `git merge-base --is-ancestor <tag> origin/main` exits 0, stop and report "nothing to merge: <tag> already in main".
1. Branch merge/upstream-<tag> from origin/main. Configure the page's Step 1 regen merge driver.
2. Size it: git merge-tree --write-tree origin/main <tag>; list the conflicted files.
3. git merge <tag> --no-ff --no-commit (history-preserving; never cherry-pick, copy single files or rebase). Resolve every conflict by the page's rules — every fork addition gets a drop / extract / upstream verdict, drop first; after pyproject.toml, run uv lock, python scripts/sort_uv_lock_options.py and python scripts/gen_gateway_contracts.py (then --check) and stage the three generated files. Commit "merge: upstream <tag> into main (<date>)", body = each conflicted file + the rule applied.
4. Run the supersession pass (Upstream Sync, "Each merge"), then the tests that import a conflicted module (page Step 5).
5. Push merge/upstream-<tag>. Never push main, never force-push, never open a PR. If merge/upstream-<tag> already exists on origin, stop and report it instead of redoing the merge.
6. Report (<= 30 lines): upstream tag merged, conflicts per file + rule, the verdict counts (drop / extract / upstream / kept), supersession rows retired/kept, the [up-fp] line before/after, test counts with reds marked merge-caused / pre-existing (re-run on origin/main).
```

Retired with the old method: the per-file "reconcile X with upstream" prompt, its cumulative `automation/upstream-sync` branch, and `docs/agent-runtime-harness/planned/upstream-sync-automation.md` (deleted with this section).

## Known shapes

- **Upstream patches a stdlib class process-wide; the fork's own protocol must not build from the patched binding.** Since 2026-09-25 (`067fa1a257`) upstream calls `agent.ssl_verify.install_truststore()` at process start — `truststore.inject_into_ssl()` rebinds `ssl.SSLContext` to a client-only class — and the fork's gateway (self-signed certificate, fingerprint pinned one layer up, server-side wrap) went from 9 passed to 9 failed with `ServeHelloProtocolError`. `agent_runtime/gateway_tls.py::stdlib_ssl_context` builds both ends from the interpreter's class through truststore's public extract/inject under a lock; the control that proved it was the injection made a no-op (X:/wt/_holds/merge-0925/peer-control-noinject.log). Grep every `ssl.SSLContext(` in fork trees at each merge; a new one is this shape again.
- AGENTS.md carries no fork edit (removed 2026-10-06); never re-add one.
- Conflicts cluster in the 22 heavy fork-edited upstream files ([[Fork Boundary Map]]); nothing in `agent_runtime/` or `harness_parts/` conflicts.
- Upstream renames tools (`cronjob`/`process`/`todo` → `*_manage`, `todo_list`); the fork's toolset manifest gate (`scripts/dump_toolset_manifest.py`) will red on a rename — regenerate after reading the diff.
- The fork's CI runs on `main` but is red on every run (queue row); a red it reports is not yet a signal, so assume nothing passed that you did not run.
