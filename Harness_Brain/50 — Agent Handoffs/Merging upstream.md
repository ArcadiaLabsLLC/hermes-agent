---
type: handoff
program: upstream-sync
tags: [handoff, program/upstream-sync]
---

# Merging upstream

The weekly merge of the latest `NousResearch/hermes-agent` RELEASE tag into the fork — never `upstream/main` (owner, 2026-10-06). Rule: [[0006 — Upstream sync is a real merge, per-file reconciliation retired]]. State: [[Upstream Sync]].

> [!important] Never in the primary checkout, never a rebase, never `main` from a lane
> Cut a worktree from a NEUTRAL cwd; merge there; push the candidate branch; the operator lands fast-forward after the validated suite.

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
3. `git merge <tag> --no-ff --no-commit`, then resolve by rule:
   - additive on both sides → keep both;
   - upstream logic changed → upstream's version, the fork's addition re-applied on top;
   - the seams survive: `_downstream_cli.build_downstream_parsers`, upstream's `_apply_profile_override` block with the fork's three in-place deltas (entrypoint gate from `_profile_bootstrap`, `harness agent set-profile` exemption, resolution receipt), `_boot_clock`, `"harness"` in the console list, `process_registry.restore_durable_completions`, profile scoping in `hermes_constants` / `profiles.py`;
   - never drop a fork test (move it if upstream deleted its anchor);
   - `pyproject.toml`: the fork's pair (`coverage==7.16.0`, `pytest-timeout==2.4.0`, the `exclude-newer-package` exemptions, `--timeout=30` in `addopts`) plus any NEW upstream rows;
   - generated files (`uv.lock`, the two `apps/shared/src/gateway-contract.*` files) arrive as upstream's copy via the `regen` driver; after `pyproject.toml` is resolved run `uv lock`, then `python scripts/gen_gateway_contracts.py`, then `python scripts/gen_gateway_contracts.py --check`, and stage the three files.
4. Commit: `merge: upstream <tag> into main (<date>)`, body = each conflicted file + the rule applied.
5. Touched tests directly (files that import a conflicted module), background, log, unpiped exit code. Fix merge-caused reds as `fix(merge): …`; name pre-existing reds by running the one test on `main`.
6. `git push -u origin merge/upstream-<date>`. Report ≤ 30 lines.
7. **Landing (operator or landing lane):** `scripts/run_tests.sh tests/agent_runtime tests/hermes_cli tests/hermes_state` (≥ 25 min) + the two contract dumps `--check` + `scripts/doc_cite_adjacency.py` in its ruled scope; then `git push origin merge/upstream-<date>:main` if fast-forward. Update the cursor, delete the queue row, remove the worktree.

## The scheduled job (GPT/Codex, daily; acts only on a new release)

The job's whole description, pasted as its prompt — it runs the Steps above and nothing else ([[0006 — Upstream sync is a real merge, per-file reconciliation retired]]):

```
Upstream release merge for ArcadiaLabsLLC/hermes-agent. Runs daily; does nothing unless upstream has published a release the fork has not merged.
Read Harness_Brain/50 — Agent Handoffs/Merging upstream.md (the one page) and follow its Steps 0-6 exactly.
0. Fetch origin and upstream (https://github.com/NousResearch/hermes-agent) with --tags. Tag = the latest release: `gh release view --repo NousResearch/hermes-agent --json tagName -q .tagName`, or without gh, the highest `v<year>.<month>.<day>` tag by version sort (`git tag -l 'v20*' --sort=-v:refname | head -1`; never an `abandoned-rc*` tag). If `git merge-base --is-ancestor <tag> origin/main` exits 0, stop and report "nothing to merge: <tag> already in main".
1. Branch merge/upstream-<tag> from origin/main. Configure the page's Step 1 regen merge driver.
2. Size it: git merge-tree --write-tree origin/main <tag>; list the conflicted files.
3. git merge <tag> --no-ff --no-commit (history-preserving; never cherry-pick, copy single files or rebase). Resolve every conflict by the page's rules; after pyproject.toml, run uv lock and python scripts/gen_gateway_contracts.py (then --check) and stage the three generated files. Commit "merge: upstream <tag> into main (<date>)", body = each conflicted file + the rule applied.
4. Run the supersession pass (Upstream Sync, "Each merge"), then the tests that import a conflicted module (page Step 5).
5. Push merge/upstream-<tag>. Never push main, never force-push, never open a PR. If merge/upstream-<tag> already exists on origin, stop and report it instead of redoing the merge.
6. Report (<= 30 lines): upstream tag merged, conflicts per file + rule, supersession rows retired/kept, the [up-fp] line before/after, test counts with reds marked merge-caused / pre-existing (re-run on origin/main).
```

Retired with the old method: the per-file "reconcile X with upstream" prompt, its cumulative `automation/upstream-sync` branch, and `docs/agent-runtime-harness/planned/upstream-sync-automation.md` (deleted with this section).

## Known shapes

- **Upstream patches a stdlib class process-wide; the fork's own protocol must not build from the patched binding.** Since 2026-09-25 (`067fa1a257`) upstream calls `agent.ssl_verify.install_truststore()` at process start — `truststore.inject_into_ssl()` rebinds `ssl.SSLContext` to a client-only class — and the fork's gateway (self-signed certificate, fingerprint pinned one layer up, server-side wrap) went from 9 passed to 9 failed with `ServeHelloProtocolError`. `agent_runtime/gateway_tls.py::stdlib_ssl_context` builds both ends from the interpreter's class through truststore's public extract/inject under a lock; the control that proved it was the injection made a no-op (X:/wt/_holds/merge-0925/peer-control-noinject.log). Grep every `ssl.SSLContext(` in fork trees at each merge; a new one is this shape again.
- AGENTS.md carries no fork edit (removed 2026-10-06); never re-add one.
- Conflicts cluster in the 22 heavy fork-edited upstream files ([[Fork Boundary Map]]); nothing in `agent_runtime/` or `harness_parts/` conflicts.
- Upstream renames tools (`cronjob`/`process`/`todo` → `*_manage`, `todo_list`); the fork's toolset manifest gate (`scripts/dump_toolset_manifest.py`) will red on a rename — regenerate after reading the diff.
- The fork's CI runs on `main` but is red on every run (queue row); a red it reports is not yet a signal, so assume nothing passed that you did not run.
