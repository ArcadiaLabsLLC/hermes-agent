# Planned — the fork's plugins reach Hermes core only through published doors (2026-11-21)

Row: `RT-FU-THE-FORK-PLUGINS-REACH-HERMES-CORE-ONLY-THROUGH-ITS-PUBLIC-DOORS` (runtime queue, review
w1118a.69), carrying the merged `RT-FU-THE-USAGE-READ-FAILED-REASON-READS-A-PRIVATE-UPSTREAM-TABLE`.
Lane w1118a-sw69-doors. Census read at origin/main 9b02232295 with `scripts/boundary_lint.py`'s own
`collect()` / `regressions()` and `tests/tooling/test_fork_import_layers.py`.

## What the census says

`test_boundary_lint`: 61 keys over upstream's baseline, 65 import sites. `test_fork_import_layers`
`private_upstream_imports`: 1 NEW site. Read by target, not by file:

- 59 sites are a fork plugin importing the fork's OWN package (`agent_runtime.*`, or a fork-only module
  that sits in an upstream package: `hermes_cli._downstream_cli`, `hermes_cli.harness_cli_setup`,
  `hermes_cli.harness_parts.*`, `hermes_cli.subcommands.postinstall`, `tools.downstream_schema`). No
  upstream release can move these; upstream's lint counts them because pyproject ships `agent_runtime`
  as a Hermes package, so anything not on `hermes_cli/data/plugin_api.json` is "core internal" to it.
  The fork's own fence (`tests/tooling/test_plugin_imports_public_surface.py`, plan
  `harness-plugin-and-upstream-seams.md` rule 3) already allows them.
- 4 sites reach a real upstream module from a fork plugin: `hermes_cli.profiles` (dashboard),
  `tools.skills_tool.check_skills_requirements`, `tools.terminal_scope.terminal_env` (2).
- 1 site is fork code inside an upstream plugin (`plugins/model-providers/openai-codex`, a carried hunk).
- 1 site is fork core naming an upstream platform module (`agent_runtime/messaging/serve_lane.py` →
  `plugins.platforms.telegram.adapter`).
- 1 site (import layers) is fork core reading upstream's private `agent.account_usage._USAGE_FETCHERS`.

## Routes, in the row's order

1. **Not needed** — the fork already owns a seam that answers it.
2. **A published door** — the plugin imports one fork door module per plugin under
   `agent_runtime/plugin_doors/`, and that module is the only fork name on the published surface.
3. **An upstream PR** — none needed (see below).

### The publication seam (what was tried)

A door module is still an import of `agent_runtime`, so the lint must learn it is published. Tried:

- A dynamic `importlib.import_module(name)` with a computed name: hides the import from the lint
  without changing the coupling. Rejected.
- Moving the plugins to `hermes_agent.plugins` entry points (plan Stage 7's shape): no `plugins/`
  directory, no lint subject. Rejected now: entry points exist only after a reinstall, the bundles list
  plugin directories, and the plan gates Stage 7 on the detach read.
- Appending a fork group to `hermes_cli/data/plugin_api.json`: data-only, but the same file renders
  upstream's user docs page (`scripts/gen_plugin_api_docs.py`), so the page would have to carry fork
  internals.
- **Taken:** a fork-owned `hermes_cli/data/plugin_api_fork.json` naming ONLY the door modules, read
  beside upstream's list by an additive two-line hunk in `hermes_cli/plugin_validate_private_imports.py`
  (`_public_api`). `hermes plugins validate` and the boundary lint then agree that the doors are public.
  A test holds the fork list to modules under `agent_runtime/plugin_doors/` that exist, so it can never
  grow into a list of internals.
- Upstream footprint: the openai-codex hunk leaves its upstream file in the same slice (route 1 below),
  so `[up-fp]` stays `files=228` and `deleted_lines` falls 879 → 878. No ceiling is raised.

## Every crossing and its target

| Slice | Site(s) | Target | Route |
|---|---|---|---|
| 1 | `plugins/model-providers/openai-codex/__init__.py:8` → `agent_runtime.reasoning_control_catalog.cached_control_efforts` | the fork's own layer: both callers already reach the profile through the fork-owned `agent_runtime/reasoning_capabilities.py` (`read_declared_efforts`, `codex_declared_or_static_efforts`); an un-overridden openai-codex profile's vocabulary is read from the control cache there, and the upstream plugin returns to upstream bytes | 1 |
| 1 | `plugins/eternia-lens/__init__.py:19` → 7 names of `agent_runtime.lens.tool` | `agent_runtime.plugin_doors.lens` | 2 |
| 2 | `plugins/eternia-harness/__init__.py` → 46 sites over `agent_runtime.*` (attribute_commits, background_completion, cache_routing, chat_lane_tool_form, codex_observability ×2, console_suggestions, conversation_observability, flutter_build_guard, gateway_queue_status, generated_tree_teach ×2, launcher_app_functions ×3, lens.act ×2, persona_turn_binding ×3, prompt_guidance ×4, provider_access, provider_challenge, review_prompts ×2, review_skill_changes, review_skill_gate, skill_search, skill_view_result, terminal_block_class ×2, text_summary, tool_blocks ×5, turn_outcome, usage_ledger, work_store.schedule_tool ×3) | `agent_runtime.plugin_doors.harness` (lazy: a name is imported on first use, so the plugin keeps costing nothing at discovery) | 2 |
| 2 | same file → fork-only modules in upstream packages: `hermes_cli._downstream_cli.cmd_postinstall`, `hermes_cli.harness_cli_setup.setup_harness_parser`, `hermes_cli.harness_parts.start_time_setup.run_start_time_setup`, `hermes_cli.subcommands.postinstall.add_postinstall_arguments`, `tools.downstream_schema.brief_request_tools` | `agent_runtime.plugin_doors.harness` | 2 |
| 2 | same file → upstream `tools.skills_tool.check_skills_requirements`, `tools.terminal_scope.terminal_env` (2) | `agent_runtime.plugin_doors.harness`: the coupling moves out of the plugin into fork core, where the import-layers gate and the footprint ledger watch it | 2 |
| 2 | `plugins/eternia-harness/dashboard/plugin_api.py` → `agent_runtime.blueprints.resolve.promote_profile_to_persona`, `agent_runtime.bundle_profiles.model_downloads.gate_model_download_routes`, upstream `hermes_cli.profiles` | `agent_runtime.plugin_doors.harness` | 2 |
| 3 | `agent_runtime/messaging/serve_lane.py:147` → `plugins.platforms.telegram.adapter` | upstream's own discovery door: `hermes_cli.plugins.discover_plugins()` + the published `gateway.platform_registry.platform_registry.create_adapter("telegram", …)` (its factory also applies the operator's notifications mode, which the direct construction skipped) | 1 |
| 4 | `agent_runtime/_upstream_doors.py::has_account_usage_fetcher` → private `agent.account_usage._USAGE_FETCHERS` | the fork's own layer: `agent_runtime/provider_account.py` keeps the providers that report usage; a test compares that set with upstream's table, so an upstream merge that adds a fetcher reds the test, not the product | 1 |

## Not this lane's

- `tools/agent_chat_dispatch` and the turn path belong to lane w1118a-onepath-hm; no crossing is
  there. The harness plugin's hook bodies are turn-path code: slice 2 changes only where their imports
  come from (`from agent_runtime.plugin_doors.harness import …`), not what they do.

## Done when

`tests/scripts/test_boundary_lint.py` and `tests/tooling/test_fork_import_layers.py` are green on main,
`scripts/boundary_lint_baseline.json` and `tests/fixtures/import_layers_grandfathered.json` unchanged,
`[up-fp]` not above `files=228 deleted_lines=879 heavy=1`.
