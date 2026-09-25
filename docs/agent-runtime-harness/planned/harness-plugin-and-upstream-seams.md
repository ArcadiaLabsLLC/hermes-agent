# Planned — the harness as a plugin, and the fork's seams into upstream: toward easy syncs and an optional detach

**Status:** PLANNED 2026-09-21 (Fable, read-only against `main` @ `9e0f7a5472` and `upstream/main` @ `ea0c2b820b`). Not dispatched. Stage 0 waits on the running upstream merge (`merge/upstream-2026-09-21`). Field notes: [`harness-plugin-and-upstream-seams-field-notes-2026-09-21.md`](harness-plugin-and-upstream-seams-field-notes-2026-09-21.md). **Owner docs:** [`../01-system-architecture.md`](../01-system-architecture.md) (command surface), [`../04-boot-and-lifecycle.md`](../04-boot-and-lifecycle.md) (the boot cost this plan measures). **Brain:** `Harness_Brain/10 — Programs/Upstream Sync.md`, `Harness_Brain/00 — Maps/Fork Boundary Map.md`, ADR 0006. **Sibling plan:** [`downstream-god-file-refactor.md`](downstream-god-file-refactor.md) — shares the upstream fence (its W0-G2) and lands its lanes independently; nothing here waits on it.

**The operator's brief (2026-09-21).** *Easy upstream syncs without much conflict. A hybrid end state: stay a fork if need be, fully detach if possible, because I like making core changes sometimes. Keep it minimal. Some things are proprietary to the launcher and stay ours; open review of the code is fine. Start with registering the harness as a plugin, then walk through what's next.*

**The answer in one paragraph.** Conflicts come from exactly one place: fork edits inside upstream-owned files where upstream also moves (449 files today, 22 of them heavy; 40 conflicts and 51 hunks on a three-day gap). Upstream's own model for capability is "plugins never touch core": a plugin registers commands, tools, prompt sections, hooks and skills through a `PluginContext` whose surface is a stated additive-only compatibility contract, and ships as its own repo, private or public. So the harness becomes a plugin package inside the fork, the fork becomes the thin vehicle for core changes, and **every remaining edit to an upstream file carries one of three dispositions — upstream it, hook it, carry it — and a ratchet counts the carried ones down.** Detaching is then a measurement (the ratchet at zero), never a decision made in advance. Core changes stay welcome; a carried change is additive where possible and the ratchet makes its price visible.

This note cites SYMBOLS and FILES, never line numbers.

---

## 0. Ground truth (2026-09-21)

### 0.1 Upstream's direction, read from its tree (not from talk)

- **Core is a narrow waist; capability lives at the edges** (`AGENTS.md` § Contribution Rubric, upstream). The Footprint Ladder: extend existing code → CLI command + skill → service-gated tool → plugin → MCP server in the catalog → new core tool (last resort). "Huge mechanical extraction PRs are wanted work."
- **Plugins never touch core** (`plugins/AGENTS.md`, Teknium, May 2026). A plugin that needs a missing capability gets the generic surface widened by PR; special-casing in core is refused. In-tree memory providers closed May 2026; third-party product plugins closed June 2026 — they ship as standalone repos (`~/.hermes/plugins/` or a pip entry point `hermes_agent.plugins`). **Extraction to partner repos is for products, not for the core** — the agent loop, gateway, CLI and core tools stay in-tree.
- **The plugin surface** (`hermes_cli/plugins.py::PluginContext`): `register_cli_command(name, help, setup_fn, handler_fn)` (an argparse subparser tree wired into `hermes` at startup, no `main.py` change), `register_tool(name, toolset, schema, handler, check_fn, …)`, `register_system_prompt_section(id, content|callable, position, max_chars)`, `register_skill(name, path)` (explicit loads only — NOT installed into `<available_skills>`), `register_hook` over 28 named hooks (`pre_command`, `on_session_start/end`, `pre/post_tool_call`, `pre/post_llm_call`, `on_stream_*`, `pre_gateway_dispatch`, …), `register_middleware`, `register_platform`, `register_memory_provider`, `register_context_engine`, `emit`/`subscribe`, `register_command` (slash), `spawn_task`, `state`, `get_config`. Manifest v2 (`manifest_version`, `api_version`, `requires_plugins`, `python_dependencies`, `config_schema`, `capabilities`).
- **The compatibility contract** (`website/docs/developer-guide/plugins/index.md`): hook payloads grow by keyword fields; `PluginContext` methods are never removed or renamed; deprecations warn once and last ≥ 2 minor releases. The Sep-2026 decomposition compat window (old import paths through `PLUGIN-COMPAT` `__getattr__` blocks) **ended 2026-09-14**; `scripts/check_compat_pointers.py` reds in-tree uses.
- **Discovery:** `plugin-catalog/` (SHA-pinned YAML, human-merged PR, 117 entries and churning daily) is the ONLY discovery for out-of-tree plugins — and only for plugins that want listing. A private repo installs by path or pip and never touches the catalog.
- **The CLI attach path and its cost** (`hermes_cli/main.py::_register_plugin_cli_commands`, identical on the fork and upstream except for the fork's parser seam beside it): plugin CLI commands are attached only when `_plugin_cli_discovery_needed()` — the first positional argv token is NOT in `_BUILTIN_SUBCOMMANDS`. Then `discover_plugins()` imports every bundled plugin module: **500–650 ms by upstream's own comment**. Bundled platforms avoid it by being *deferred* entries materialized by name (`_resolve_deferred_platform_cli_command`, issue #54678); no equivalent exists for a general plugin's CLI command. `harness` is not a built-in upstream, so a plugin-registered harness pays discovery on every `hermes harness …` process.
- **Signals to weigh:** `hermes-example-plugins` (the companion repo) last pushed 2026-05-10; external-process model-provider plugins landed 2026-09-20 (`13fe9c7171`); gateway god-file extractions land daily (`4a641d7e92`, `ae85aaa366`, `70fceb80ab`); the issue tracker carries dozens of open "god-file decomposition" rows. Discussions are disabled on the repo; the roadmap is the rubric.

### 0.2 The fork's footprint in upstream files (against merge base `c62bd9f207`)

| measure | value |
|---|---|
| upstream files with fork edits | **449** (+18,323 / −2,258 lines) |
| of which test files | 246 (13,705 lines; `tests/hermes_cli/conftest.py` +1,266, `tests/conftest.py` +569, `tests/tools/conftest.py` +406, `tests/agent/conftest.py` +165) |
| production files | ~140 (hermes_cli 59, tools 40, agent 29, gateway 15, scripts 10, .github 8) |
| files with ≤ 5 changed lines | 118 |
| files with > 200 changed lines | **22** |
| upstream lines the fork DELETES | 2,258 — the replacement-shaped edits; the conflict generators |
| trial merge today | 40 conflicted files, 51 hunks, all in the heavy tail; none in `agent_runtime/` or `harness_parts/` |

### 0.3 `hermes_cli/main.py`, hunk by hunk (the worked example every other heavy file follows)

| hunk | what | disposition |
|---|---|---|
| boot-clock marks: `mark_main_import_started` (module top), `mark_main_entered` (`_default_to_chat`), `mark_main_import_completed` (module tail) | 3 one-liners | **hook** (`pre_command`) for "entered"; the two import-time marks have no hook that early → **upstream** a generic startup-timing hook, or **carry** as one-liners |
| the profile bootstrap: upstream's ~200-line block (`_scan_profile_flag`, `_apply_profile_override`, `_under_gateway_supervisor`, `_desktop_ssh_backend`, `_resolve_sudo_user_profile_env`, `_inside_mcp_add_args`) replaced by imports from `hermes_cli/_profile_bootstrap.py`, plus ONE behaviour change: `is_hermes_cli_entrypoint(__name__)` gates the override off unless the process is a genuine hermes entrypoint | −187 / +12 | **upstream** — a mechanical extraction of their own code (the shape their rubric asks for) carrying a real bug fix (an import under pytest re-parsing argv and pointing the session at the operator's live profile; `tests/test_no_frozen_hermes_home.py` is the evidence). Until merged, this hunk conflicts on every upstream edit to that block |
| `"harness", "postinstall"` in `cmd_console`'s command list | 1 line | **hook** — gone with Stage 1 |
| `process_registry.restore_durable_completions()` in `_prepare_agent_startup` | 6 guarded lines | **upstream** (generic); fallback `on_session_start` hook |
| `build_downstream_parsers(subparsers)` in `_build_cli_parser` | 2 lines | **hook** — Stage 1 |
| `dispatch_command` wrapper in `main()`: `_capture_core_cache_fingerprint_home` before the command; harness error formatting on exception | 2 lines | **hook** (`pre_command`) + error formatting inside the harness handlers — Stage 1 |
| `from hermes_cli.update_cmd_windows import _warn_legacy_console_gateway_task` at module tail | 1 line | **carry or delete** — no caller in `main.py` found by grep; the Stage 1 lane confirms and deletes |

After Stage 1 and the profile-bootstrap PR: ≤ 3 additive one-liners remain in `main.py`.

### 0.4 The other heavy seams (dispositions to confirm at their stage)

| upstream file | fork delta | what it is | likely disposition |
|---|---|---|---|
| `hermes_constants.py` | +286 / −15 | profile-aware home resolution (`get_hermes_home` at call time, `display_hermes_home`, sudo/supervisor arms) | **upstream** what upstream lacks (upstream now runs one process for several profiles, scope bound per call — much may already exist); **carry** the rest |
| `hermes_cli/profiles.py` | +301 / −29 | profile store extensions | same as above; Stage 4 diffs them |
| `tools/registry.py` | +194 / −36 | a TTL cache for `check_fn` probes + probe accounting | **upstream** (generic perf; the fork measured it) |
| `agent/prompt_builder.py` | +58 / −11 | skill environment matching, `agent_runtime.prompt_guidance` constants, a `SKILLS_GUIDANCE` sentence | **hook** (`register_system_prompt_section`) for the guidance; `skill_matches_environment` is already re-exported by upstream's `tools/skills_tool.py` — likely already upstream |
| `agent/skill_utils.py` | +41 / −4 | shared skills dir, `.realm_inbox`/`.provenance` ignore, lookup normalization | **carry** (realm-specific) as additive lines; or a skill-dirs hook PR |
| `tools/skills_tool.py` | +137 / −70 | skill resolution and search delegating to `agent_runtime.skill_resolution` / `skill_search` | **hook** — the plugin's own tool via `register_tool(override=…)`, or **carry** |
| `scripts/run_tests_parallel.py`, `scripts/run_tests.sh` | +183 / −42, +193 / −5 | the fork's hermetic runner | **upstream** the runner improvements (they ship `run_tests_parallel.py` themselves); **carry** the hermetic-env rows |
| the four `conftest.py` | +2,400 | hermetic-home fixtures, env-gap fence | **fork-only** pytest plugin, loaded by one line (Stage 5) |
| `apps/desktop/*` (4 files / 92 lines left, down from 32 files) | the uninstall git-history warning + its test, the slash-registry dump, one fork-only store test | **DONE as a stage (owner, 2026-09-24):** every remaining line is in a held bucket (the uninstall PR candidate, the `register_command` widening); no census, no plugin work — the fork does not edit upstream's electron app (Stage 6) |

---

## 1. The rules

1. **Three dispositions, one per edit to an upstream file.** `upstream` (a PR to NousResearch; generic fix or extraction), `hook` (moved behind the plugin surface; if the surface lacks it, a PR that widens the generic surface with this plugin as the concrete consumer), `carry` (ours; additive where possible; on the ratchet with a named reason). A carried edit that REPLACES upstream lines is allowed and is the one kind that conflicts; the reason says why replacement was unavoidable.
2. **The ratchet only goes down.** `scripts/upstream_footprint.py` prints `[up-fp] files=<n> deleted_lines=<n> heavy=<n>` over the fork's diff against the merge base restricted to the upstream manifest; `tests/scripts/test_upstream_footprint.py` reds if any of the three rises above `tests/fixtures/upstream_footprint.json`, and reds if the fixture is not lowered when the tree is lower (the list only shrinks). A core change the operator wants raises the fixture in the SAME commit with a `reason:` row — the price is paid visibly, never silently.
3. **The plugin never imports the fork's edits to upstream files.** It reaches upstream only through `PluginContext` and public upstream APIs; `scripts/check_compat_pointers.py` and a plugin-side import fence (`tests/tooling/test_plugin_imports_public_surface.py`) keep it so. This is what makes the package installable on stock upstream.
4. **Proprietary stays proprietary; open review is fine.** The plugin's home is the fork (public) until Stage 7 moves it to its own repo — private if the operator says so. Nothing proprietary is offered upstream. The three dispositions apply to the fork's edits in upstream files only; the plugin's own code has no disposition because it lives in no upstream file.
5. **Each stage lands with a measurement, not a belief.** Stage 1's is the boot cost; Stage 3's is the PR merged (or declined, with the fallback applied); Stages 4–6 are the ratchet line before/after.
6. **Detach is a measurement.** `[up-fp] files=0` (or only `carry` rows the operator has ruled permanent) means the harness plugin runs on stock upstream and the fork is optional. Stage 7 executes only when that line is read.
7. **Permanent carry is the exception, ruled per file (owner, 2026-09-24).** Only a file with no override point — the README licence line, the AGENTS.md pointer, root `.gitignore`/`.gitattributes` litter lines, `uv.lock` — may be `carry-permanent`. Nothing under `agent/`, `tools/`, `gateway/`, `hermes_cli/` is permanent: it moves to a fork-only file, hooks through a widening, or is adopted from upstream.
8. The god-file refactor's rules (flat ceiling, MOVE/CHANGE separation, bulk mode, terse briefs, the upstream fence) apply to every lane here. Sibling plan §1 and §6.
9. **No duplicate authority versus upstream (owner, 2026-09-23).** Pulling the fork out of upstream files follows upstream's functional progress; it never builds a parallel implementation beside it. Every stage inventory buckets each fork name as **already-upstream** (adopt upstream's, delete ours), **generic** (an upstream PR) or **ours** (plugin or carry); before a lane adds a fork-side helper it checks `upstream/main` for the equivalent and uses it. A parallel that cannot be avoided is a RECORDED ledger row: the upstream symbol it shadows, why it cannot be adopted, and the condition that retires it — an unrecorded parallel is a defect. Each weekly merge runs a supersession pass (`Harness_Brain/10 — Programs/Upstream Sync.md` § Each merge) that files adopt rows for upstream additions in areas the fork carries.
10. **A second door is a duplicate authority (owner, 2026-09-24).** A fork mechanism built beside a door upstream already has — its own request, store or routing where upstream's first door plus a plugin-set default does the job — is the rule-9 defect in its commonest shape (the 2026-09-24 `tools/process_registry.py` ruling: a late `process notify` request beside spawn-time `notify_on_complete`). Before adding a fork mechanism, check upstream's doors in this order: the plugin hook surface (`VALID_HOOKS`, the four middleware kinds), config keys and env reads, the parameters of the existing call, manifest fields; use the first that carries the behaviour, and name the one small widening PR only when none does. The per-row audit of the 46 `hook` rows against those doors is [`second-doors-2026-09-24.md`](second-doors-2026-09-24.md).

---

## 2. Stages

### Stage 0 — land the merge; baseline the ratchet

- **0a.** The running merge lane's branch `merge/upstream-2026-09-21` lands (its own initiative: `Harness_Brain/20 — Active Initiatives/upstream-merge-2026-09-21.md`). Every measurement below is re-taken on the merged tree; §0.2's numbers are pre-merge.
- **0b. ONE commit:** `scripts/upstream_footprint.py` + `tests/tooling/test_upstream_footprint.py` + `tests/fixtures/upstream_footprint.json` baselined at the merged tree's numbers; `tests/fixtures/upstream_manifest.txt` shared with the refactor's W0 (whichever lands first creates it; the other reuses it). Killing mutations: (a) add one line to an untouched upstream file → `files` rises → red; (b) lower the fixture below the tree → red; (c) delete an upstream line in a carried file → `deleted_lines` rises → red.
- **0c.** The disposition table (§0.3 + §0.4) becomes `docs/agent-runtime-harness/planned/upstream-footprint-ledger.md`: one row per upstream file the fork edits, `disposition`, `reason`, `stage`. Generated by the script's `--ledger` arm from the diff; hand-edited dispositions survive regeneration (the script merges on path).

Gate: `[up-fp]` line quoted in the commit; validated suite unchanged.

### Stage 1 — the harness registers itself as a plugin (CLI) — **the first step**

**Files.** New `plugins/eternia-harness/plugin.yaml` (manifest v2: `name: eternia-harness`, `api_version: 1`, `tags: [harness, mission-control]`, `config_schema` empty) and `plugins/eternia-harness/__init__.py` with `register(ctx)`. `plugins/` is upstream's directory but `eternia-harness` is a name upstream never creates; the package is fork-only by construction and moves whole in Stage 7.

**What `register(ctx)` does — and only this:**
```python
def register(ctx):
    ctx.register_cli_command(
        "harness", help="Agent Runtime Harness (Mission Control runtime)",
        setup_fn=_setup_harness_parser,     # imports hermes_cli.harness.build_parser LAZILY, inside the call
        handler_fn=None,                    # every harness subparser sets its own func= today
    )
    ctx.register_cli_command("postinstall", help="…", setup_fn=_setup_postinstall_parser, handler_fn=cmd_postinstall)
    ctx.register_hook("pre_command", _capture_core_cache_fingerprint_home_hook)   # replaces dispatch_command's capture
```
Harness error formatting (`emit_harness_error` on an exception escaping a handler) moves INTO `build_parser`'s handler wiring: every `set_defaults(func=…)` target is wrapped once by a `_harness_entry(fn)` decorator in `harness.py` that formats and exits. `dispatch_command`, `build_downstream_parsers` and `hermes_cli/_downstream_cli.py` are then deleted; `main.py` loses the parser seam, the console-list entry and the dispatch wrapper (three of its eight hunks). The `_warn_legacy_console_gateway_task` tail import is confirmed dead and deleted, or its caller named.

**The measurement (before any deletion is committed):**

| number | how | today | threshold |
|---|---|---|---|
| `harness_parser_ms` (the fork's own boot-clock field, read from the serve boot timeline line and `agent_runtime/tool_visibility.py`'s note "2110 → 593") | same instrument, plugin path | ~593 ms | ≤ today + 50 ms |
| cold `hermes harness doctor` wall time, 5 runs, median | `Measure-Command` / `time` on the launcher's own interpreter chain | (take it) | ≤ today + 150 ms |
| serve boot: `harness serve boot timeline:` line | byte-identical keys; `plugin_discovery_ms` may APPEAR as a new key (a receipt, allowed) | (take it) | numbers within noise; the launcher's `ready.json` recapture per its code_tree hash rule |
| what `discover_plugins()` imports on this tree | `HERMES_DEBUG` log at CLI startup; count of bundled plugin modules imported | (take it) | informs the fallback |

**If discovery costs more than the threshold** — expected, given upstream's 500–650 ms figure — the lane does NOT land the deletion and instead lands the **fallback**: a manifest-declared deferred CLI entry. The generic widening: `plugin.yaml` gains `cli_commands: [{name, help, description}]`; `PluginManager.discover_and_load` records such entries WITHOUT importing the plugin (the deferred-platform pattern generalized); `_register_plugin_cli_commands` attaches a stub whose `setup_fn` materializes the plugin by name on first parse. This is an upstream PR with this plugin as its concrete consumer (rule: "a hook with a real, stated use case is not speculative"). Until it merges, the fork carries the same change as an additive edit in `plugins.py` and `main.py` (two files on the ratchet, `hook-pending` reason), and Stage 1 lands on top of it. Either way the parser seam in `main.py` is gone.

**Gates.** `scripts/dump_cli_contract.py --check` byte-identical (the harness surface is unchanged); `hermes harness serve` boots under the launcher with the timeline line's keys unchanged; `tests/hermes_cli/test_harness_*` green; the god-file refactor's W0-G4 (thin harness namespace) unaffected — `register()` imports `hermes_cli.harness` lazily and only its public `build_parser`; `[up-fp] files` −3 (or −3 +2 with the carried fallback).

**Owed by the operator:** none — the Stage 1 boot measurement was waived 2026-09-24 (cost waived 2026-09-23; the fork-scope gate exercises the parser path).

**CORRECTED 2026-09-23 (Fable, read against `main` @ `bcf8012e6a`, merge base `d337b736aa`) — three of the mechanics above were assumed on 2026-09-21 and are wrong against the code. Stage 1 is BUILT on seam/s1-proof af093265e1, cost waived by owner 2026-09-23, see note §4 ([`seam-s1-proof-2026-09-23.md`](seam-s1-proof-2026-09-23.md)).**

1. **`pre_command` cannot carry the fingerprint capture.** `hermes_cli.plugins.fire_pre_command_hook` is invoked from exactly two places, `cli.py::HermesCLI.process_command` and `gateway/run_inbound.py` — the REPL and gateway SLASH-command paths. Nothing fires it on the argparse path that `main()` dispatches; a `register_hook("pre_command", …)` would never run for `hermes harness …`. Correction: `_capture_core_cache_fingerprint_home` moves INTO the `_harness_entry(fn)` wrapper in `hermes_cli/harness.py` (fork-only) beside the error formatting the plan already puts there; `dispatch_command` then has nothing left and is deleted. No hook, no `main.py` edit.
2. **The built-in list is the gate, and the fork's own edit to it defeats the plugin.** The fork ADDED `"harness", "postinstall"` to `hermes_cli/main.py::_BUILTIN_SUBCOMMANDS` (one replaced upstream line). Upstream's comment on that set says it: "an extra entry would let a plugin command silently fail to parse" — with the names present, `_plugin_cli_discovery_needed()` is False for every `hermes harness …`, `_register_plugin_cli_commands` returns before discovery, and a plugin-registered `harness` never attaches. Stage 1 therefore MUST drop both names from the set (which also retires that hunk), and from that moment every `hermes harness …` process is on the discovery path.
3. **The discovery path costs more than the threshold by an order of magnitude, and the fallback as written does not avoid it.** Measured 2026-09-23, one cold run, `HERMES_HOME` a temp dir, the shared test interpreter: `import hermes_cli.plugins` 436 ms, then `discover_plugins()` **875 ms** (59 plugins found, 77 `plugins.*` modules imported, `_cli_commands` empty); the second call 0 ms. `_register_plugin_cli_commands` calls `discover_plugins()` unconditionally once discovery is needed, and `PluginManager._gate_manifest` defers only manifests whose verdict is `defer` — bundled PLATFORMS — so a manifest-declared `cli_commands:` entry read AFTER `discover_plugins()` has already paid the 875 ms. The launcher spawns `hermes harness serve` and dozens of `hermes harness <verb>` processes; the threshold (+50 ms parser, +150 ms doctor) stands.
4. **The corrected Stage 1 shape (one branch, not two).** The generic widening is a PRE-discovery scan: `hermes_cli/plugins.py::discover_declared_cli_commands()` reads every `plugin.yaml` (no imports) and returns the `cli_commands:` rows; `main.py::_register_plugin_cli_commands` attaches those as stubs BEFORE the `_plugin_cli_discovery_needed()` check, each stub's `setup_fn` materialising only its own plugin by name on first parse (the memory-provider `discover_plugin_cli_commands` in `plugins/memory/__init__.py` is the in-tree precedent: it imports one `cli.py`, never the provider). Cost: reading ~60 YAML files. `_BUILTIN_SUBCOMMANDS` is left as upstream ships it. This is the upstream PR (this plugin is its concrete consumer); until it merges the fork carries the same additive change in `plugins.py` and `main.py` (two files on the ratchet, reason `hook-pending`). The measurement is re-taken on THAT path before any deletion, against the same thresholds.
5. **What Stage 1 does to the ratchet, honestly.** `hermes_cli/_downstream_cli.py` is fork-only, so deleting it moves no number. `main.py` stays in `[up-fp] files` while any hunk remains (the boot-clock marks, the profile-bootstrap replacement, `restore_durable_completions`, the tail import), so Stage 1 lowers `main.py`'s hunks (8 → about 5 after the builtin-list line, the parser seam and the dispatch wrapper go; the tail import's fate per §0.3) and `deleted_lines` by one; `files` is flat until P1 and P4 land. §5's "−3" is withdrawn; the ledger row records hunks.
6. **Proved 2026-09-23 (lane S1P, branch `seam/s1-proof`): FAIL, marginal** — doctor −80 ms (PASS), parser +51.1 ms against +50 (FAIL by 1.1 median); ON HOLD stands. Numbers, ratchet and next shape: [`seam-s1-proof-2026-09-23.md`](seam-s1-proof-2026-09-23.md).
7. **Next shape re-measured 2026-09-23 (same branch): FAIL** — parser +70.3 ms median / +52.2 min (the three trims bought ~0 on the real path); doctor −50.9 ms. The 32–37 ms manifest sweep is the budget; next: text pre-filter before YAML parse. Note §4.


### Stage 2 — tools and prompt sections through the plugin

- **Tools:** `tools/agent_chat_tool.py` (`agent_chat_send`, `agent_chat_threads`, dispatch), `tools/board_tool.py` register via `ctx.register_tool(name, toolset="harness", schema, handler, check_fn)`; the fork's edits to `tools/registry.py` that exist only to register them go; the `check_fn` TTL cache stays as an upstream PR candidate (Stage 3). The fork's `toolset_manifest`/`downstream_schema` gate reads the plugin's registrations through the same registry.
- **Prompt sections:** the `agent_runtime.prompt_guidance` constants the fork splices into `agent/prompt_builder.py` become `ctx.register_system_prompt_section("harness.guidance", content, position="after_memory")` and siblings; the `SKILLS_GUIDANCE` sentence becomes a section or an upstream one-line PR. The runtime HUD stays where it is (it is built per turn inside the harness's own chat lane, not the core prompt builder).
- **Skills:** NOT `register_skill` — it is explicit-load only and the harness needs its four skills in `<available_skills>` of every profile. `install_harness_skills_at_boot` and the `post-merge` hook stay. Recorded so nobody re-tries it.
- Gates: the prompt goldens (canon 07's byte pins) unchanged or re-pinned with the diff read; `tests/fixtures/*toolset*` regenerated with the diff read; `[up-fp]` −2 (registry, prompt_builder) or the reason rows for what stays.
- **Measured 2026-09-24 (lane S2, branch `seam/s2-plugin-surface-2026-09-24`): `[up-fp]` 408/2612/11 → 404/2602/10.** Moved: the T6b guidance + skill-confirm sentence → section `eternia-harness.tool-guidance` (renders only with `tool_describe` present; needed one additive widening line, `tool_names` in `agent/system_prompt.py::_plugin_session_info`); `skill_search` → `register_tool` into toolset `skills`; `skills link-external` → `hermes harness skills link-external`; two `skill_matches_environment` duplicates → upstream's. Stayed, `S3` with the PR each waits on (ledger rows say which): `/queue-status` (plugin commands get no gateway context and no busy dispatch), the terminal envelope (`pre_tool_call` misses direct `terminal_tool()` callers and flattens the typed block), the usage ledger (the hook has no key for one agent's turn), `skills_tool` resolution and `skills_tool_plugin` (an override would copy upstream's handlers), `auth set-key`/`login` (the launcher's argv uses them), `toolsets.py` leaves (static bundles). `agent_chat`/`board` not moved: fork-only, no ratchet effect, and a move turns manifest hits into plugin-discovery misses — decide at Stage 7. No prompt golden re-pinned; the toolset manifest lost the two `skill_search` lines. New gate `tests/tooling/test_plugin_imports_public_surface.py` (rule 3); 8 killing mutations recorded in the lane's commit messages.

### Stage 3 — upstream what upstream would take

One PR each, in this order (smallest and most obviously wanted first), each with its fallback if declined:

| PR | contents | fallback |
|---|---|---|
| **P1 profile bootstrap extraction** | `hermes_cli/_profile_bootstrap.py` as an extraction of `main.py`'s block + the `is_hermes_cli_entrypoint` gate + `tests/test_no_frozen_hermes_home.py`'s evidence | carry (it conflicts; the ledger row says so) |
| P2 durable-completion restore at startup | the 6 guarded lines | `on_session_start` hook |
| P3 `check_fn` TTL cache | `tools/registry.py` +194 with the fork's measurement | carry as additive |
| P4 startup-timing hook | a generic `on_cli_import` / `pre_command` payload carrying import-start/complete stamps; the boot-clock marks become its consumer | carry the two one-liners |
| P5 runner improvements | the parts of `run_tests_parallel.py` / `run_tests.sh` that are not hermetic-env specific | carry |

Each merged PR: the ledger row flips to `upstream`, the next merge brings the code back as upstream's own, `[up-fp]` drops. Each declined PR: the fallback lands within the same stage; the row's reason quotes the decline.

### Stage 4 — the profile-home delta

`hermes_constants.py` (+286) and `hermes_cli/profiles.py` (+301) diffed function by function against upstream's current tree (upstream runs several profiles per process now; `hermes_home_key()`, `_run_release_in_profile_scope`). Three buckets: already upstream (delete ours), generic (PR, as P6/P7), ours (carry as additive one-liners or a hook PR). Gate: `tests/test_no_frozen_hermes_home.py` ledger unchanged or shorter; `[up-fp] deleted_lines` down.

### Stage 5 — fork tests leave upstream test files

- `tests/hermes_cli/conftest.py` (+1,266), `tests/conftest.py`, `tests/tools/conftest.py`, `tests/agent/conftest.py`: the fork's fixtures become `tests/_downstream/conftest_plugin.py` (a pytest plugin) loaded by ONE `pytest_plugins = [...]` line per upstream conftest — one additive line each.
- The one-line-per-conftest shape is rejected by pytest 9.0.3 for the three non-root conftests (`pytest_plugins` outside the top-level conftest is refused), so they take a star import instead; see `docs/agent-runtime-harness/planned/seam-s4-s5-s6-inventory-2026-09-23.md` §1.5.
- Superseded 2026-09-24 (lane CARRY3): the three directory conftests are upstream's bytes again and `tests/conftest.py` has lost its `pytest_plugins` line (its three in-place hunks are PR candidates). The fork-only root `conftest.py` imports the root plugin and registers each directory module under a `<dir>/_downstream_conftest.py` name when pytest registers the matching upstream conftest (directory scope kept); `tests/*/test_downstream_conftest_loader_downstream.py` pin it.
- The 242 other upstream test files with fork test cases: each fork test moves to a fork-only sibling (`tests/<dir>/test_<name>_downstream.py`), source-pin census first (refactor rule 1.6). Mechanical; one lane per top-level test dir; MOVE-only commits.
- Gate: the validated suite selects the same test ids (a `--collect-only` diff before/after is empty modulo file names); `[up-fp] files` −242.

### Stage 6 — desktop — **DONE (owner ruling 2026-09-24; landed `b9812befc9`)**

> [!note] Closed as a stage, 2026-09-24. Only 4 files / 92 lines remain under `apps/desktop` (`settings/uninstall-section.tsx` +6 and its test +43/−1, `lib/desktop-slash-registry.json` +2, `store/session-dot-state-downstream.test.ts` +41), all in held buckets: the uninstall warning is an upstream PR candidate (PRs paused) and the slash-registry lines wait on the `register_command` widening PR. No census, no desktop-plugin work: the fork does not edit upstream's electron app. The paragraph below is the original plan, kept for the record.

`apps/desktop/src/app/skills/*` and the other 32 desktop edits: what the desktop plugin SDK reaches (`HermesPlugin` default export, the inventory/enable contract, `$HERMES_HOME/desktop-plugins/`) moves into `plugins/eternia-harness/desktop/`; the rest is carried with a reason (the SDK forbids reaching into app stores — a needed capability is an SDK hook PR). Gate: the desktop `vitest` + `eslint` run; `[up-fp]` down.

### Stage 7 — the detach read (executes only on the measurement)

When `[up-fp]` reads `files=0`, or only rows the operator has ruled `carry-permanent`: `plugins/eternia-harness/` moves whole to its own repo (private on the operator's word; a pip entry point `hermes_agent.plugins = eternia_harness:register`, or a `~/.hermes/plugins/eternia-harness` checkout); the launcher's installer (`scripts/install-mission-control-hermes.ps1` and the launcher's own) installs stock upstream + the plugin; the fork keeps only its carried rows and becomes optional per machine. Until that read, the plugin lives in the fork and both paths work.

---

## 3. Order and parallelism

```
S0 (merge lands; ratchet) ──► S1 (plugin CLI; MEASURE) ──► S2 (tools, sections) ──► S7 (detach read)
                          └──► S3 (PRs P1–P5, serial, one at a time) ──► S4 (profile-home) ─┘
                          └──► S5 (tests out) · S6 (desktop) — any time after S0, in parallel
```

Hard orderings: S0 before all; S1 before S2; P1 before S4 (S4 diffs against the tree P1 leaves). S5 and S6 are independent of everything but S0. The god-file refactor's lanes interleave freely (shared fence; disjoint files except `harness.py`, which S1 touches only at `build_parser`'s handler wiring — S1 lands before the refactor's H2, or rebases onto it).

---

## 4. What the operator owes

1. ~~One launcher boot on the Stage 1 build (the boot-cost measurement's field half).~~ None — waived 2026-09-24 (cost waived 2026-09-23; the fork-scope gate exercises the parser path).
2. The private/public ruling for the plugin's Stage 7 home (not before Stage 7).
3. Per PR in Stage 3: nothing — the fallback is pre-decided; the lane reports merged/declined.

---

## 5. Ledger

| stage | status | commits | `[up-fp]` after | notes |
|---|---|---|---|---|
| S0 | 0a landed (`b592010a65`, v0.21.4, base `d337b736aa`); 0b landed `d4d12ae12b` (ratchet) + ledger commit on `seam/s0b-upstream-footprint`; not yet on `main` | 3 | `[up-fp] files=459 deleted_lines=2834 heavy=24` | ratchet + ledger; tests in `tests/scripts/`, not `tests/tooling/` |
| S0 · dispositions | Disposition wave 2026-09-24 (lanes DISP-T/-C/-M, landed by LAND3): 0 unreviewed rows; counts per disposition: tests 207 rows (upstream 109, carry 93, hook 5), core 121 (already-upstream 14, generic 52, hook 14, carry-movable 15, carry-fixed 18, REVERT 8), misc 75 (revert 5, generic 32, hook 11, carry-movable 14, carry-fixed 13); whole ledger after the 4 dropped PRs were re-dispositioned: 448 rows = upstream 200, carry 215, hook 33 | 3 notes + 1 landing | `[up-fp] files=448 deleted_lines=2800 heavy=12` (unchanged; no code moved) | notes `disposition-{tests,core,misc}-2026-09-24.md`; rows in the runtime and fork-hygiene queues |
| S0 · apply | lane MECH 2026-09-24, branch `seam/mech-apply-2026-09-24`: the decided dispositions applied — REVERT rows (2 kept, re-red gates; 2 website rows at next merge), adopt-upstream duplicates, the three § Seams defects (codex catalog always-None, auxiliary probe parallel, duplicate first-byte), the four dropped-PR rulings (encoding + P7 reverted, monkeypatch-undo kept for the fork tripwire, P6 refusal reverted with its seam moved to `agent_runtime/profile_processes.py`), movable carries (7 website pages, 2 CI jobs, 17 tool briefs, qa-artifacts ignore, kanban_db re-exports) | 12 | `[up-fp] files=408 deleted_lines=2612 heavy=11` (40 files byte-identical to base; ledger 448 → 408 rows) | DESIGN left: the background-completion default (no profile config seed), provider timing onto pre/post_api_request (no status sink), session_search/clarify/code_execution briefs |
| S1 | BUILT — `seam/s1-proof` tip `af093265e1`; cost +70 ms parser (median, A/B 2026-09-23) recorded as debt, waived by owner (note §4) | 1–2 | `[up-fp]` 461/2834 (two `hook-pending` carries: `plugins_manifest.py`, `plugin_compat.py`); main.py hunks 8 → 7 | pre-discovery manifest scan is the only branch; capture moves into `_harness_entry`; `_BUILTIN_SUBCOMMANDS` loses the fork's two names |
| S2 | planned | 1 | −2 | skills stay installed, not registered |
| S3 | planned | 5 PRs | −1 per merge | P1 first |
| S4 | landed on `main` via `seam/s45-landing` (branch tip `9fa433d74a`) | 8 fork + 2 `up/*` (P6 `up/profiles-delete-guard` @ `9b1d5506aa`, P7 `up/profile-home-generic` @ `1f4923c350`, both cherry-pick clean, no PR) | `[up-fp] files=448 deleted_lines=2800 heavy=12` after the S4+S5 landing (S4 alone: 459 / 2818 / 22) | ran before P1 on the owner's order. Adopted upstream: the root memo, `list_profile_names()` (dual-roster fixed). Moved: 14 names from `hermes_constants.py` + 3 from `profiles.py` → `agent_runtime/profile_home.py`, and `CONVERSATION_REQUEST_ASSEMBLED_STEP` → `agent_runtime/conversation_observability.py`. `hermes_constants.py` is +17/−1 (P7 only) and `profiles.py` +204/−29 (P6 + one carried orphan-mark call). Frozen-home ledger unchanged |
| S5 | landed on `main` via `seam/s45-landing` (branch tip `489b3ce373`, MOVE tip `aae22df30c`) | 1 conftest + 8 MOVE + 1 landing | `[up-fp] files=448 deleted_lines=2800 heavy=12` after the S4+S5 landing (S5 alone: 446 / 2816 / 13; the +2 files are S1's `hook-pending` carries S5 was cut before) | 189 fork tests + 1 fixture moved to `*_downstream.py` siblings out of 45 upstream files; conftests → `tests/_downstream/` (3 of 4 now upstream + 1 line); tests pinned by an upstream autouse/module fixture stay with a ledger reason; the 177 in-place-edit files are the owner's upstream-PR verdict (runtime queue) |
| S6 | DONE as a stage (owner ruling 2026-09-24) | 0 | `apps/desktop`: 4 files / 92 lines, all held (uninstall PR candidate, `register_command` widening) | no census, no plugin work; the fork does not edit upstream's electron app |
| S7 | on the read | 1 + installer | 0 | private on the operator's word |
