# The `harness` parser without the plugin load (plan)

Status: PLAN — written 2026-11-12 by lane w1112b-hm-queue. Row: runtime-queue
`RT-HARNESS-PARSER-PLUGIN-LOAD-TWICE` (task `TASK-CONSOLE-SMOOTH-AND-FAST`). NOT BUILT: S1–S2 need no owner
decision; the build's acceptance is a serve boot timed on a quiet box, which a feature lane beside twelve
others cannot produce (`EterniaLauncher/docs/agent_context/WORK_TRACKING.md`: performance runs in its own lane).

## In plain English

Before `hermes harness serve` can even read its own command line, hermes loads the whole harness plugin
— every start-up migration, every hook, the process watcher — only to learn what flags `harness` takes,
and then throws that load away. A moment after the serve is ready, plugin discovery loads the same plugin
again. The fix is to let the command line be built from the parser alone, and to run the start-up work
once, on purpose, just before a harness command runs.

## Evidence (Linux dev box, 2026-11-12, `~/.venvs/hermes-test`, isolated `HERMES_HOME`, box busy at load 26–42)

- After `RT-HARNESS-SERVE-SKIP-UPSTREAM-PARSERS` (`76631ba613`) the parser `main()` builds for
  `hermes harness …` holds two commands, and what is left of the build IS this load: build 0.49 s in the
  box's fast minutes, 1.35 s in its slow ones (same hour, same tree; the whole-tree control moved 0.76 s →
  1.73 s with it).
- One process, slow minutes, three runs: `PluginManager._load_plugin` (import + `register(ctx)`)
  1.05–1.15 s and 340–383 modules; inside it `install_process_presence()` 0.35–0.41 s,
  `seed_all_persona_profiles` 0.06–0.08 s, `migrate_retired_provider_id_once` ≤ 1 ms (its marker is set);
  `hermes_cli.harness` import + `build_cli_parser` 0.10–0.17 s (`harness_parser_ms`); `unload` 1 ms. So about
  0.9 s of the load is neither the parser nor a migration. The row's 2026-11-10 figures (693 ms, 240 ms,
  1,746 ms) were read at 100 % CPU with the provider-id marker not yet set.
- Not measured: how much of those 340 modules the serve imports anyway before `ready`. That number decides
  what S3 is worth and needs a real serve boot.

## What the transient load does today

`hermes_cli/plugins_declared_cli.py::_materialize_declared_cli_command` runs `manager._load_plugin(manifest)`,
calls the registered `setup_fn`, then `manager.unload(key)`. The unload disposes what `ctx` registered
(hooks, middleware, tools, prompt sections, the provider-access object, the CLI commands). It does NOT undo
what `plugins/eternia-harness/__init__.py::register` did outside `ctx`:

| left behind after the unload | kind |
|---|---|
| `migrate_retired_local_llama_id`, `migrate_legacy_persona_toolsets`, `retire_legacy_harness_blocks`, `seed_persona_profile_defaults`, `migrate_legacy_office_schema`, `migrate_shared_character_assignments`, `retire_persona_assignment_store` | disk: idempotent start-time migrations |
| `bind_mission_chat_door()` | process global |
| `ensure_harness_core()` | process global (toolset registry) |
| `install_process_presence()` | process global, imports `tools.process_registry` |
| `add_registry_spelled_filesystem_reads()` | process global |

Every `hermes harness <verb>` process therefore gets all of the table at PARSE time — `--help` and a
mistyped verb included — and a verb may be leaning on any row of it without saying so.

## Design

- **S1 — the manifest names the parser.** A `cli_commands:` row may carry `setup: "<module>:<function>"`
  (`hermes_cli/plugins_manifest_cli_commands.py::cli_command_entry`, fork-owned; a bad value skips the row
  as a bad name does). `_declared_descriptors` then builds a stub that imports that one function and calls it
  on the parser: no `_load_plugin`, no `register(ctx)`, no unload. A row without `setup:` keeps today's
  transient load. `plugins/eternia-harness/plugin.yaml` names a new importable
  `hermes_cli/harness_cli_setup.py::setup_harness_parser` (the body of the plugin's `_setup_harness_parser`,
  boot-clock mark included — the plugin's own copy calls it, so `register_cli_command` is unchanged).
- **S2 — the start-time work runs once, before the verb.** The table above moves, as one function
  `agent_runtime/harness_start_time.py::run_start_time_setup()`, out of `register` (MOVE commit), guarded once
  per process and per resolved `HERMES_HOME`; `register` calls it, and so does
  `hermes_cli/harness.py::_harness_entry` before the handler. Every verb keeps exactly what it has today, a
  few milliseconds later in the same process; only `--help` and a parse error stop running migrations.
  The serve's post-ready discovery no longer repeats them (the "twice" in the row's name).
- **S3 — the serve runs only the migrations before `ready` (measure first).** `harness serve`'s entry asks
  for the migrations alone and leaves the four process globals to the post-ready `register(ctx)`. Build it
  only if the quiet-box boot shows the serve does not import `tools.process_registry` and the door's
  modules before `ready` anyway, and only with the pre-ready path read for each global (a chat frame
  admitted before discovery needs the door). Its proof is an operator boot's receipts, per
  `Harness_Brain/50 — Agent Handoffs/Touching serve and boot.md`.

## Decisions

1. **Do non-serve verbs keep the start-time migrations?** Yes — S2 keeps them for every verb, so the row's
   "behaviour decision per verb" does not arise and no owner decision is needed. (The alternative — serve
   only — would let `hermes harness persona list` read an un-migrated store after an update.)
2. **Is S3 an owner decision?** No: it changes nothing a user sees if its proof holds, and is not built if
   it does not.

## Acceptance

- `tests/hermes_cli/test_plugin_declared_cli_commands.py`: a `setup:` row attaches with no plugin marker
  written (mutation: ignore `setup:` → the marker appears); a row without it still loads its plugin.
- A harness verb's handler sees the migrations done and the door bound with no `discover_plugins`
  (mutation: drop the `_harness_entry` call → red); two `register(ctx)` calls run each migration once.
- `python scripts/dump_cli_contract.py --check` unchanged; the boot timeline's `harness_parser_ms` keeps its
  meaning (harness import + tree build).
- Quiet box, A/B on one tree (`setup:` row present / removed), ten boots each: serve `ready` time and
  `harness_parser_ms` from the boot timeline line. Expected from the evidence above: about the load minus
  the parser and the migrations with S3, the cost of nothing but the hook registrations without it.
