---
type: operations
tags: [operations, pitfalls]
aliases: [Gotchas, Traps]
---

# Known Pitfalls

Each entry is a measured incident, its mechanism, and the rule that retires it. An entry stays until a gate makes it impossible.

## Repository

| pitfall | mechanism | rule |
|---|---|---|
| **Bare `pytest` in the primary checkout detaches commits** (2026-08-01, 11 commits) | updater tests run `git branch -f main origin/main` | `scripts/run_tests.sh` for anything wider than one file |
| **`fetch` + `worktree add` inside the primary checkout moved `main`** (2026-08-31, W1-H1 landing) | a read-shaped setup step rewrote the ref; reflog and `push` both said "up-to-date" | cut worktrees from a NEUTRAL cwd; merge and push in one breath; no setup steps in that window |
| **Two sessions, one index** | concurrent sessions share the clone's index; a staged file lands in someone else's commit (measured `cf69a0d842`) | stage and commit in one breath, by pathspec |
| **A pre-09-15 SHA is not in `main`'s history** | the 2026-09-15 reconstruction ([[0005 — Fork history reconstruction 2026-09-15]]) | cite the reconstruction checkpoint or the archived branch; `test_docket_stage_claims` reds a plan that claims a foreign SHA |
| **The fork's CI looks green because it never ran** | workflows inert on the fork; no `main` run since 2026-09-07 | assume nothing ran that you did not run ([[Testing & Gates]]) |
| **An upstream file edited by replacement conflicts forever** | `hermes_cli/main.py`'s 200-line block replaced by imports | additive seams only ([[Fork Boundary Map]]) |

## Runtime and tests

| pitfall | mechanism | rule |
|---|---|---|
| **A module-level `get_hermes_home()` writes fixtures into the live `state.db`** | under pytest the override is gated off, the module imports at collection, the fixture moves `HERMES_HOME` afterwards | resolve at call time; `test_no_frozen_hermes_home.py` ledger only shrinks |
| **A test with a > 30 s wait "hangs" instead of failing** | `addopts --timeout=30`; pytest-timeout kills it and prints a thread dump where its message would be | `@pytest.mark.timeout(N)` above the bound |
| **The whole-tree suite reads ~142 reds on a green `main`** | provider-network hangs, WSL bash shadowing Git Bash on `PATH`, `acp`/`ripgrep` holes | the validated scope is four directories; whole-tree is a different scope |
| **`tests/acp` will not collect from a worktree** | the editable install resolves to the primary checkout | run it from the primary or name lanes |
| **Measuring under `alice` measures a different runtime** | the launcher's serve uses `profiles/base` | check the register row's `hermes_home` first |
| **Joining the chat log on `started_at` makes events impossible** | `started_at` is the write-ahead persist stamp, 0.9–3.2 s after the anchor | join on `phases.anchored_at` |
| **Stage 5's demote deferral cannot see the pre-admit span** | it reads `_ACTIVE_RUNS`, incremented after `write_ahead` | do not "fix" pre-admit latency there |
| **`Get-MpPreference` shows no exclusion** | it is blind unelevated | the `X:/Eternia` exclusion exists (2026-09-06); do not read the blank as proof |
| **The tombstone census by `grep -c` is wrong** | loops expand literals | run the registry test's own count |

## Tooling

| pitfall | mechanism | rule |
|---|---|---|
| **A quoted heredoc in this harness's Bash tool collapses backslashes** | tool transport | write scripts with the Write tool when a literal `\` matters |
| **`| tail` on a gate hides the red** | `pipefail` + a grep for "passed/failed" | redirect to a log, capture the exit code unpiped |
| **Polling a background run** | 772 polling calls cost 35 hours on the launcher | wait for the completion notification |
| **A patch on `harness.<name>` after a part becomes a module is a silent no-op** | name resolves in the part's globals | W0-G4; [[Touching the harness CLI]] |
| **Formatting before a grandfather row is deleted grows the file** | the size gate's GREW arm has no legal repair | format after the row is gone |
