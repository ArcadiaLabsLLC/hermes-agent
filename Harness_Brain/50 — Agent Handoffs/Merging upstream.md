---
type: handoff
program: upstream-sync
tags: [handoff, program/upstream-sync]
---

# Merging upstream

The weekly merge of `NousResearch/hermes-agent:main` into the fork. Rule: [[0006 — Upstream sync is a real merge, per-file reconciliation retired]]. State: [[Upstream Sync]].

> [!important] Never in the primary checkout, never a rebase, never `main` from a lane
> Cut a worktree from a NEUTRAL cwd; merge there; push the candidate branch; the operator lands fast-forward after the validated suite.

## Steps

1. From `X:/Eternia` (not inside the checkout): `git -C X:/Eternia/hermes-agent fetch origin && git -C X:/Eternia/hermes-agent fetch upstream`; `git -C X:/Eternia/hermes-agent worktree add X:/Eternia/worktrees/merge-upstream-<date> -b merge/upstream-<date> main`.
2. Size it first: `git merge-tree --write-tree main upstream/main` lists the conflicts without touching the tree; count hunks per file (`git show <tree>:<file> | grep -c '^<<<<<<<'`).
3. `git merge upstream/main --no-ff --no-commit`, then resolve by rule:
   - additive on both sides → keep both;
   - upstream logic changed → upstream's version, the fork's addition re-applied on top;
   - the seams survive: `_downstream_cli.build_downstream_parsers`, upstream's `_apply_profile_override` block with the fork's three in-place deltas (entrypoint gate from `_profile_bootstrap`, `harness agent set-profile` exemption, resolution receipt), `_boot_clock`, `"harness"` in the console list, `process_registry.restore_durable_completions`, profile scoping in `hermes_constants` / `profiles.py`;
   - never drop a fork test (move it if upstream deleted its anchor);
   - `pyproject.toml` / `uv.lock`: the fork's pair (`coverage==7.16.0`, `pytest-timeout==2.4.0`, the `exclude-newer-package` exemptions, `--timeout=30` in `addopts`) plus any NEW upstream rows.
4. Commit: `merge: upstream/main <sha> into main (<date>)`, body = each conflicted file + the rule applied.
5. Touched tests directly (files that import a conflicted module), background, log, unpiped exit code. Fix merge-caused reds as `fix(merge): …`; name pre-existing reds by running the one test on `main`.
   5b. **Re-check the skip list** (`tests/fixtures/upstream_skip_list.txt`, plan `docs/agent-runtime-harness/planned/suite-speed-2026-10-05.md` §3 Stage 1). Name every `env` / `upstream` row's file on one `scripts/run_tests_bundled.sh --scope full <file> <file> …` run (a named file always runs), background, log, unpiped exit code. A file green on the merge candidate leaves the list in the merge commit; a file still red keeps its row with the SHA advanced to the incoming upstream tip. `P0` rows are NOT run here: they run only under the watchdog/VM the fork-hygiene P0 row names, and keep their SHA.
6. `git push -u origin merge/upstream-<date>`. Report ≤ 30 lines.
7. **Landing (operator or landing lane):** `scripts/run_tests_bundled.sh --scope full tests` (the skip list applies; never on a workstation while the fork-hygiene P0 row is open) + the two contract dumps `--check` + `scripts/doc_cite_adjacency.py` in its ruled scope; then `git push origin merge/upstream-<date>:main` if fast-forward. Update the cursor, delete the queue row, remove the worktree.

## The scheduled job (Codex cloud, weekly)

The job's whole description, pasted as its prompt — it runs the Steps above and nothing else ([[0006 — Upstream sync is a real merge, per-file reconciliation retired]]):

```
Weekly upstream merge candidate for ArcadiaLabsLLC/hermes-agent.
Read Harness_Brain/50 — Agent Handoffs/Merging upstream.md (the one page) and follow its Steps 1-6 exactly.
1. Fetch origin and upstream (NousResearch/hermes-agent). Branch merge/upstream-<YYYY-MM-DD> from origin/main.
2. git merge upstream/main --no-ff (history-preserving; never cherry-pick or copy single files; never rebase).
3. Resolve every conflict by the page's rules; commit "merge: upstream/main <sha> into main (<date>)", body = each conflicted file + the rule applied.
4. Run the supersession pass (Upstream Sync, "Each merge"), then scripts/run_tests.sh on the validated scope named on the page.
5. Push merge/upstream-<date>. Never push main, never force-push, never open a PR.
6. Report (<= 30 lines): upstream sha merged, conflicts per file + rule, supersession rows retired/kept, the [up-fp] line before/after, suite counts with reds marked merge-caused / pre-existing (re-run on origin/main).
```

Retired with the old method: the per-file "reconcile X with upstream" prompt, its cumulative `automation/upstream-sync` branch, and `docs/agent-runtime-harness/planned/upstream-sync-automation.md` (deleted with this section).

## Known shapes

- **Upstream patches a stdlib class process-wide; the fork's own protocol must not build from the patched binding.** Since 2026-09-25 (`067fa1a257`) upstream calls `agent.ssl_verify.install_truststore()` at process start — `truststore.inject_into_ssl()` rebinds `ssl.SSLContext` to a client-only class — and the fork's gateway (self-signed certificate, fingerprint pinned one layer up, server-side wrap) went from 9 passed to 9 failed with `ServeHelloProtocolError`. `agent_runtime/gateway_tls.py::stdlib_ssl_context` builds both ends from the interpreter's class through truststore's public extract/inject under a lock; the control that proved it was the injection made a no-op (X:/wt/_holds/merge-0925/peer-control-noinject.log). Grep every `ssl.SSLContext(` in fork trees at each merge; a new one is this shape again.
- Conflicts cluster in the 22 heavy fork-edited upstream files ([[Fork Boundary Map]]); nothing in `agent_runtime/` or `harness_parts/` conflicts.
- Upstream renames tools (`cronjob`/`process`/`todo` → `*_manage`, `todo_list`); the fork's toolset manifest gate (`scripts/dump_toolset_manifest.py`) will red on a rename — regenerate after reading the diff.
- The fork's CI runs on `main` but is red on every run (queue row); a red it reports is not yet a signal, so assume nothing passed that you did not run.
