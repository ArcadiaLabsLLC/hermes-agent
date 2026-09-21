# The harness as a plugin, and the fork's seams — running record (hermes half)

Field notes for [`harness-plugin-and-upstream-seams.md`](harness-plugin-and-upstream-seams.md). Every lane appends its own section here, in this repo. The launcher's installer change (Stage 7) writes its notes beside `EterniaLauncher/docs/mission_control/`.

## 0. The read that wrote the plan (Fable, 2026-09-21, read-only, `main` @ `9e0f7a5472`, `upstream/main` @ `ea0c2b820b`)

- **Upstream's direction** was read from its tree, not from talk: `AGENTS.md` § Contribution Rubric (the Footprint Ladder), `plugins/AGENTS.md` (the "plugins never touch core" ruling, the closed in-tree kinds, the catalog as the only discovery, the Sep-2026 compat window ending 2026-09-14), `website/docs/developer-guide/plugins/index.md` (the compatibility contract, manifest v2, capabilities), `hermes_cli/plugins.py` (`PluginContext` methods, the 28 hook names, deferred platform entries), `hermes_cli/main.py` (`_plugin_cli_discovery_needed`, `_register_plugin_cli_commands`, the 500–650 ms comment, `_resolve_deferred_platform_cli_command` / issue #54678), `plugin-catalog/README.md`, the commit stream since 2026-09-01 (598 plugin-related subjects of 12,724), the issue tracker (`gh issue list --search`: dozens of open "god-file decomposition" rows), `gh repo view NousResearch/hermes-example-plugins` (pushed 2026-05-10). Discussions are disabled on the repo (`gh api` → 410).
- **The fork's footprint** was measured as `git diff --numstat <merge-base> main` restricted to `git ls-tree -r --name-only upstream/main` (the script is `scripts/refactor_census.py`'s sibling logic, inline in the session; Stage 0b lands it as `scripts/upstream_footprint.py`). The merge base was `c62bd9f207`. The trial merge was `git merge-tree --write-tree main upstream/main` with `grep -c '^<<<<<<<'` per conflicted file.
- **`main.py`'s eight hunks** were read from `git diff <merge-base> main -- hermes_cli/main.py` (+32 / −187): the profile-bootstrap replacement is the only replacement-shaped edit; `dispatch_command` and `is_hermes_cli_entrypoint` were read from `hermes_cli/_downstream_cli.py` and `hermes_cli/_profile_bootstrap.py`; the tail import `_warn_legacy_console_gateway_task` has no caller in `main.py` by grep (Stage 1 confirms).
- **The boot-cost figure** the plan's Stage 1 threshold is set against: `_plugin_cli_discovery_needed`'s docstring ("~500-650ms") and the fork's own `harness_parser_ms` note in `agent_runtime/tool_visibility.py` ("2110 -> 593"). Neither was re-measured in this session; Stage 1's first act is to take both on the merged tree.
- **Not run:** no plugin was written, no `discover_plugins()` was timed, no PR was opened, nothing was written outside `docs/` and `Harness_Brain/`.

## 1. Open at plan time

- The merged tree's numbers (Stage 0a lands first; every §0.2 figure is pre-merge).
- Whether upstream's native profile support already covers parts of `hermes_constants.py` / `profiles.py` (Stage 4's diff).
- Whether the desktop plugin SDK reaches the skills pages' needs (Stage 6).
- What `scripts/upstream_sync_gate.py` gates today (fork-hygiene queue row) — read before Stage 0b writes the ratchet.

## 2. Lane sections (appended by builders)

<!-- S0 / S1 / S2 / S3-P1..P5 / S4 / S5 / S6 / S7 — one section each: worktree + branch + base SHA, the measurement taken (numbers, instrument, command), the disposition rows changed, the `[up-fp]` line before/after, the commits, the PR link and its outcome where one was opened. -->

S0 disposition: hermes_cli/doctor.py `HERMES_HOME` (with `_DHH`) = carry the NAME, not the constant — served live by a PEP 562 `__getattr__` so upstream's tests can patch it while `tests/test_no_frozen_hermes_home.py` sees no module-level freeze; the fork keeps call-time dotenv loading.
