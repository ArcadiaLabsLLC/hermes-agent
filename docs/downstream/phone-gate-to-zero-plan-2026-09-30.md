# Phone profile gate → zero — the plan (2026-09-30, lane s2-plan)

Planning only; no code changed. Supersedes the "OPEN" remainder of the runtime-queue row
"Stage 2 — split `serve_rpc` dispatch…" (plan Stage 2 step 4's exit: *the phone profile passes
the profile gate*). The work list is the gate's own output, re-taken on `origin/main`
`c161bb7584` (`.lane-logs/s2-plan-gate.{log,json,md}` in the lane worktree; the per-module
breakdown used below is `.lane-logs/s2-plan-analysis.txt`). The prose report the row pointed at,
`docs/downstream/bundled-phone-gate-2026-09-28.md`, stays the running ledger — each lane re-takes
it with `--markdown` at its landing.

Design of record for what the phone must and must not do:
`EterniaLauncher/docs/embedded_hermes/planned/` — README table ("so do NOT build"),
`SPEC_2026-09-28.md` §4.4 and §7 (owner decisions 2, 4, 6), `PROFILE_MATRIX_2026-09-28.md`
("Bundled phone" column), `IMPLEMENTATION_2026-09-28.md` Stage 2 and Stage 5.

## 1. The finding list (gate, `c161bb7584`)

`python scripts/bundle_profile_gate.py --profile bundled-phone` → **REFUSED (164 findings)**,
1698 first-party modules kept, targets `android_arm64` + `ios_arm64`.

| kind | findings | what |
|---|---:|---|
| `subprocess_call` | 149 | 149 spawn sites in **85 kept modules** (78 upstream files, 7 fork files) |
| `native` | 6 | `cffi`, `cryptography`, `pillow-heif` — each on both targets |
| `process` | 4 | `psutil` (both targets); `termios` + `tty` imported unguarded by `hermes_cli.secret_prompt:90-91` |
| `unproven` | 4 | `psutil` (android: a git source, no wheel in `uv.lock`), `ruamel-yaml-clib` (not in `uv.lock`) — both targets |
| `pinned` | 1 | `tools.skills_hub`, pinned by `tools.skills_hub_clawhub:13` (kept through `tools.skills_hub_search`) |

Not counted by the gate: the 706 lazy unguarded imports into switched-off modules (the "risk
register"); every switch-off below adds to it. Its mechanism is RULED (owner 2026-09-30, the
"phone packager ships switched-off modules that directory scans then import" row in the runtime
queue, `ff9cbca51f`): the packager's forced set — every pinned and lazily-imported switched-off
module — ships in a **phone-only sibling tree** that the embedded entry appends to
`tools.__path__` / `plugins.__path__`, so those imports resolve while upstream's directory scans
(`tools/registry.py::discover_builtin_tools`, the plugin loader) never see them; upstream
untouched. That is lane G6 below, and it is also the mechanism for the gate's `pinned` row.

## 2. Buckets by root cause, and the one mechanism per bucket

Mechanisms, preferring what exists:

- **M1 profile switch** — `packaging.switched_off_modules` / `toolsets.disabled` in
  `bundled-phone.yaml`. Zero code. Legal only when no KEPT module imports the module at module
  level (else the gate reports it `pinned`) and the phone turn path never reaches it (the e2e
  `tests/agent_runtime/test_embedded_phone_session.py` runs with every switched-off prefix absent
  and records every import of one).
- **M2 stand-in table (module level)** — `agent_runtime/loop_tool_lifecycles.py::_LOOP_NAMES`: a
  switched-off module replaced in `sys.modules` by a placeholder carrying exactly the names kept
  code imports; the gate proves it in a child interpreter (`placeholder_seams`). Exists.
- **M3 spawn-site stand-ins (function level) — NEW, one fork module.** For a kept module the phone
  NEEDS (`hermes_cli.config`, `agent.anthropic_adapter`, `hermes_constants`, …) whose one or two
  functions start a process, the phone entry rebinds those named functions on their module to a
  loud `not_shipped` stand-in (the same callable `loop_tool_lifecycles.not_shipped` already hands
  out), before the loop is imported. The gate learns a `spawn_seams()` probe beside
  `placeholder_seams()`: in a child interpreter with the phone's absences, placeholders and shim in
  place, import each table module, and a `subprocess_call` finding whose enclosing `def` is bound
  to a stand-in (marker attribute on the callable) is answered, not counted. Fork code in a fork
  module; upstream bytes untouched; not process-wide (never `subprocess.Popen` itself — the
  rule the profile header states); proven at run time, never by reading the table. Owner nod
  wanted on the principle (§5 D1); the fallback per module is an upstream door (M6).
- **M4 omitted distribution** — `packaging.omitted_distributions` (+ `placeholder_distributions`
  for a requirement with a pure fallback). Legal when every import site in kept code is guarded
  (or a `stand_in` answers it). Exists.
- **M5 fork edit** — the 7 fork modules: move the spawn into a sibling module that is switched
  off, imported lazily behind the switch that already decides it.
- **M6 upstream door** — a PR upstream that moves a spawn out of a module the phone needs into a
  module it does not; the fork carries the same thin seam until merge (restoring upstream bytes
  is the merge's job).
- **M7 sibling tree (RULED, owner 2026-09-30)** — the packager's forced set (pinned +
  lazily-imported switched-off modules) ships under a phone-only sibling root the embedded entry
  appends to `tools.__path__` / `plugins.__path__`; imports resolve, directory scans never see
  it, upstream untouched. Fork code (`scripts/bundle_profile_package.py`, the entry); the gate
  reads the packager's plan to answer `pinned`.

### Bucket A — omittable compiled / process-table distributions (12 findings)

| subject | findings | how it is reached (kept sites) | mechanism | the phone loses | allowed? |
|---|---:|---|---|---|---|
| `pillow-heif` | 2 | `agent.image_routing:448`, `tools.vision_tools_image_prep:211` — both guarded | M4, one row, zero code | HEIC / AVIF decode (iPhone camera output!) | Matrix admits Pillow only. **D2**: the host transcodes HEIC→JPEG/PNG before an image reaches Hermes (Launcher owns the picker) — recommended |
| `ruamel-yaml-clib` | 2 | requirement of `ruamel-yaml` (pure wheel); the C accelerator has a pure fallback inside ruamel | `placeholder_distributions` (the `av` precedent), zero code | nothing (slower YAML) | yes |
| `psutil` | 4 (process ×2, unproven ×2) | 34 kept sites, 28 guarded; unguarded: fork `agent_runtime/discussions/native.py:155`, `agent_runtime/conversations/native_peer.py:124`; upstream `hermes_constants_scratch:63,84` (drop, Bucket D1), `agent/transports/codex_app_server.py:67` (drop, D1), `hermes_cli/process_identity.py:432` (`_kill_process_tree_windows`, Windows-only) | M4 after guarding: 2 fork guards (M5), 1 one-line seam in `process_identity` (M6 with fork carry). **No psutil shim**: 28 guarded sites have ImportError fallbacks a shim would defeat | pid liveness via psutil → stdlib fallbacks (`pid_exists_stdlib`) | yes — a phone has no sibling processes |
| `cryptography` + `cffi` | 4 | `agent.secret_sources.bitwarden:118-119` unguarded (drop, D1); fork `agent_runtime/gateway_tls.py:313-316,369-370` (`_mint`, `_der_from_pem`) unguarded; `agent.vault_store:248,276` (Fernet) unguarded | M4 after: gateway_tls guard (M5 — phone never mints a gateway cert: service mode absent) + vault decision **D3** (drop `agent.vault_store` + `agent.vault_backends.*`, or M6 guard the two Fernet imports) | local Fernet secrets vault (`hermes vault`, `tui_gateway.methods_vault`) | Spec §7.6: Hermes owns credentials, the OS stores them — the host store binding is the phone's vault; dropping is consistent, owner confirms |

### Bucket B — pty imports (2 findings)

`hermes_cli.secret_prompt::_masked_secret_prompt_posix` imports `termios`/`tty` unguarded.
Eager importers (`hermes_cli.config`, `cli_output`, `auth_commands`, `plugins_cmd`) import
exactly one name, `masked_secret_prompt`. Mechanism **M2**: switch the module off, table entry
`{"hermes_cli.secret_prompt": _loud("masked_secret_prompt")}`; the existing probe proves it. Loses:
an interactive masked prompt — a phone has no tty. Allowed. (M6 later: guard the two imports
upstream and retire the entry.)

### Bucket C — pinned switched-off modules (1 finding) — mechanism RULED: the sibling tree (M7)

`tools.skills_hub` is pinned by `tools.skills_hub_clawhub:13` (a module-level import), kept
through `tools.skills_hub_search` ← lazily `tools.skills_hub_official`,
`tools.connectors.catalog_tool`. Owner 2026-09-30 (`ff9cbca51f`, the packager row): the
packager's forced set — pinned AND lazily-imported switched-off modules, 282 at the last
measurement — ships in a phone-only **sibling tree** the embedded entry appends to
`tools.__path__` / `plugins.__path__`; the scans never see it, upstream is untouched. **M7** is
that: `scripts/bundle_profile_package.py` writes the forced set under a sibling root
(`<bundle>/phone_forced/tools/…`, `…/plugins/…`), `EmbeddedServe.start` appends it, and the gate
counts a `pinned` module as answered when the packager's plan places it in the sibling tree
(proven from the plan, the same way `placeholder_seams` is proven from the entry). The hub's
spawning sibling `tools.skills_hub_github` (1 site) is D1 — switch-offs and the sibling tree
compose: a module the phone never imports is switched off; one an upstream kept module imports
unguarded ships in the sibling tree. Loses nothing the matrix grants (hub install is desktop —
Spec §7.4); the skills-hub tool itself stays unregistered because the scans do not see the tree.

### Bucket D — spawn calls in kept modules (149 sites, 85 modules)

Sub-bucketed by whether the phone needs the MODULE (the per-module importer data is in
`.lane-logs/s2-plan-analysis.txt`: `eager<-` = kept module-level importers, i.e. what would pin
it; `lazy<-` = kept lazy importers).

**D1 — modules the phone never runs, reached lazily or only from other D1 modules → M1 (93 sites, 50 modules).**

| family | modules (sites) | switch-off, plus | loses on the phone | allowed? |
|---|---|---|---|---|
| messaging-gateway runner | `gateway.run`(1) `run_inbound`(1) `run_shutdown`(3) `slash_commands`(2) `shutdown_forensics`(2) `status`(2) | prefixes `gateway.run`, `gateway.slash_commands`, `gateway.shutdown_forensics`, `gateway.status` (77 lazy importers → register; none eager) | the gateway process, its status/restart | matrix: service mode "—" |
| package manager | `pm.client environment extras features package packages plugin_eviction progress recovery runtime runtime_stage`(18) + eager siblings `pm._uv install operations registry workspace native_build` | `pm/__init__` stays (a lazy `__getattr__` facade; `from pm import install_hint` in kept code still imports only the package) | installs, `install_hint` text on an SDK miss (moot under the shim) | `security.allow_lazy_installs: false` already |
| upstream kanban + git tooling | `hermes_cli.kanban_db`(1) `kanban_db_dispatch`(2) `kanban_db_workspace`(3) `kanban_pr_acceptance`(1) `gitlock`(10) `worktree_ops`(3) `git_credentials`(5) `github_api`(1) `update_cmd_check`(1) `source_check`(1) `source_releases`(4) `goals`(1) `quiet_single_query`(1) | prefixes `hermes_cli.kanban`, `hermes_cli.gitlock`, `hermes_cli.worktree_ops`, `hermes_cli.git_credentials`, `hermes_cli.github_api`, `hermes_cli.update_cmd_check`, `hermes_cli.source_`, `hermes_cli.goals`, `hermes_cli.goal_command`, `hermes_cli.quiet_single_query`; toolset `kanban` disabled | upstream's kanban board and goal gates (not the fork's Mission Board) | no git binary on phones (matrix) |
| desktop CLI helpers | `commands_completion`(1) `profiles_service_cleanup`(3) `tools_config_cua`(2)+`tools_config`, `tools_config_post_setup` `mcp_catalog`(1)+`mcp_picker`,`curses_ui` `plugin_catalog`(1)+`plugins_cmd_catalog` `hermes_constants_scratch`(1) | — | `/` project-file completion, systemd cleanup, CUA driver setup, MCP/plugin catalog pickers, git-worktree scratch release | all desktop flows |
| process-starting integrations | `agent.transports.codex_app_server`(2)+`codex_app_server_session` `agent.proxy_sources.iron_proxy`(2)+`hermes_cli.proxy_cli` `agent.secret_sources.command`(1) + `.bitwarden`, `.onepassword` (registry loop is per-source `except Exception`) `tui_gateway.host_supervisor`(2) `tools.bot_mode_dm`(2) `tools.env_probe`(1) `tools.async_delegation_recovery_hints`(1) | — | Codex app-server transport (raw-HTTP Codex stays), Iron proxy daemon, CLI-backed secret sources, compute-host bridge, bot-mode DM child, env probe (switch already off), git forensics on an abandoned delegation | yes |
| file-edit tooling | `tools.checkpoint_manager`(2)+`checkpoint_maintenance`,`checkpoint_manager_profile_rename` `tools.file_operations_lint`(1) `file_operations_search`(1)+`tools.file_operations` (eager<- only the already-off `tools.file_tools`) | — | git checkpoints of edits, `rg`, node linter | no file toolset on phones |
| memory plugin spawners | `plugins.memory.byterover`(1) `plugins.memory.mem0._setup`(3) `plugins.memory.openviking`(1) | plugin subtrees stay data-less (loader "No `__init__.py`") | Byterover CLI, mem0's docker/ollama setup, OpenViking's local server (+ its psutil) | memory providers over HTTP stay |
| skills hub | `tools.skills_hub_github`(1) — Bucket C | | | |

Decision rule for the lane: **if switching a module off makes the gate print it `pinned`, do not
fight it — move that module to D2 (M3) and say so in the commit.** `source_check` is the likely
case (`hermes_cli.banner` imports it eagerly; banner's own importers were not kept in this run).

**D2 — modules the phone needs, with one to four spawning functions → M3 (35 sites, 22 modules).**

| module | functions (sites) | the phone loses |
|---|---|---|
| `agent.anthropic_adapter` | `_detect_claude_code_version` (1) | Claude Code version sniff (desktop credential mirroring) |
| `agent.anthropic_credentials` | `_find_claude_code_keychain_item`, `_mirror_claude_code_credentials_to_key` (4) | macOS keychain mirroring (`auth.adopt_external_logins` is already off) |
| `agent.command_token_source` | `_mint` (1) | command-minted provider tokens |
| `agent.context_references` | `_run_quiet` (1) | `git diff` / `rg --files` @-references |
| `agent.deadline` | `kill_process_tree` (1) | nothing (no children) |
| `agent.secret_sources.base` | `run_cli` (1) | CLI secret sources (their modules are D1) |
| `agent.shell_hooks` | `_spawn` (1) | user shell hooks on events (webhooks over HTTP stay) |
| `agent.skill_preprocessing` | `run_inline_shell` (1) | `!cmd` skill preprocessing |
| `gateway.platforms.base` | `transcode_to_ogg_opus`, `_detect_macos_system_proxy` (2) | ffmpeg voice-note transcode, `scutil` proxy detection |
| `hermes_bootstrap`… | — see D4 | |
| `hermes_cli._early_recovery` | `git`, `_paths_git_wrote`, `relaunch_after_restore` (4) | checkout recovery (wheel install: nothing to recover) |
| `hermes_cli._subprocess_compat` | `_user_safe_directories`, `posix_is_zombie`, `_legacy_kill_process_tree` (3) | git safe-directory probe, zombie check |
| `hermes_cli.config` | `edit_config` (1) | `$EDITOR` |
| `hermes_cli.copilot_auth` | `_probe_gh_cli_token` (1) | `gh` token probe (Copilot device flow stays) |
| `hermes_cli.profiles` | `_run`, `check_alias_collision`, `seed_profile_skills` (3) | alias collision probe, skill seeding by copy command |
| `hermes_cli.sqlite_runtime` | `probe_sqlite_runtime` (1) | probing ANOTHER interpreter's SQLite (the phone has one) |
| `hermes_cli.stderr_timestamp` | `main` (1) | a `__main__` wrapper (kept only because `tools.mcp_tool_config` imports the module) |
| `hermes_cli.version_info` | `_git_version_info`, `_run_git` (2) | git build stamp (identity comes from the wheel stamp — matrix) |
| `hermes_constants` | `_run_version_probe` (1) | `node --version`-style probes |
| `plugins.memory.honcho.client` | `_git_repo_name` (1) | repo-derived Honcho workspace name |
| `tools.tts_command_provider` | `run_command_provider`, `terminate_command_process_tree` (2) | command TTS provider (OS speech on phones) |
| `tools.tts_tool_delivery` | `_ffmpeg_run` (1) | ffmpeg audio conversion |
| `tools.vision_tools_image_prep` | `_rasterize_svg_to_png` (1) | SVG rasterization via rsvg/inkscape |

Every loss above is a desktop affordance the matrix marks "—" or that needs a binary a phone
does not have; none is on Spec §7.2's tool list.

**D3 — the seven fork modules → M5 (11 sites).**

| module | sites | the fork edit |
|---|---:|---|
| `agent_runtime.git_cmd` | 1 | becomes the ONE fork git chokepoint: switched off on the phone, `run_git` in the M2 table as a loud stand-in (realm sync then fails loudly — the `unswitched` gap the yaml already records) |
| `agent_runtime.build_identity` | 1 | `code_tree_for` calls `git_cmd.run_git` |
| `agent_runtime.repo_context` | 6 | `_git_output`, `_run_git_quiet`, `worktree_patch_size`, `_remove_harness_worktree` all through `git_cmd.run_git` |
| `agent_runtime.store_file_io` | 1 | `narrow_windows_acl`'s `icacls` → new `agent_runtime/store_file_io_windows.py`, switched off, imported lazily under `os.name == "nt"` |
| `agent_runtime.provider_signin` | 1 | the sign-in child's `Popen` → new `agent_runtime/provider_signin_child.py`, switched off, imported behind `auth.subprocess_signin` (the switch that already decides it) |
| `agent_runtime.gateway_endpoints.routes` | 1 | `run_route_command` → new `agent_runtime/gateway_endpoints/route_command.py`, switched off, lazy |
| `tools.agent_chat_dispatch.local` | 1 | `_spawn_child` → new `tools/agent_chat_dispatch/local_child.py`, switched off, imported behind `conversations.subprocess_worker` (the in-process peer is the phone's path) |

**D4 — sites no rebinding can name → M6 with fork carry (6 sites, 3 modules incl. `hermes_cli.venv_sync`).**

- `hermes_bootstrap:548-549, 584-585` run at MODULE level (the venv / ABI relaunch under
  `if not _pm_repair:`), eagerly imported by `agent.process_bootstrap` (which 9 kept modules import)
  and `tui_gateway.entry`. Door: the block becomes `hermes_cli.venv_sync.relaunch_if_needed(...)`
  (one call, no spawner name at the site; `venv_sync` is then switched off, taking its own site
  with it: −5). Upstream benefits (the relaunch stops running on import for every embedder).
- `tui_gateway.methods_prompt:844` is inside the `@method("pdf.attach")` handler named `_`.
  Door: the handler moves to `tui_gateway/methods_pdf.py` (a natural split; switched off on the
  phone: −1). Loses PDF attach via `pdftoppm` — not on Spec §7.2's list.

**D5 — two sites that need an owner decision (2 sites).**

- `plugins.web.ddgs.provider::_spawn_worker` (1): DuckDuckGo search runs ONLY through a worker
  subprocess (bounded memory/time, `_run_ddgs_search_bounded`). Web search is Spec §7.2 first
  batch. **D4**: (a) switch `plugins.web.ddgs` off on the phone and ship the HTTP-API web
  providers only [recommended: "enable, never reimplement"], or (b) a fork seam that runs
  `_run_ddgs_search` in-process on the phone (changes upstream's isolation posture).
- `tui_gateway.server::_SlashWorker.__init__:291` spawns `python -m tui_gateway.slash_worker` per
  session — the in-process gateway the phone RUNS. **D5**: slash commands on the phone need an
  in-process slash runner (the same class of seam as the in-process conversation worker,
  `agent_runtime/conversations/in_process_peer.py`) behind `conversations.subprocess_worker`,
  after which `_SlashWorker.__init__` is an M3 class-attribute stand-in. Owner picks the slash
  command set the phone supports, or rules "no slash commands on phones" (then M3 alone).

### Counts

| bucket | findings | mechanism | after |
|---|---:|---|---:|
| start | 164 | | 164 |
| G1: D1 switch-offs + A(`pillow-heif`, `ruamel-yaml-clib`) | 93 + 4 | M1 / M4 | 67 |
| G2: D3 fork seams + A(`psutil`) + B | 11 + 4 + 2 | M5 / M4 / M2 | 50 |
| G3: D2 stand-ins | 35 | M3 | 15 |
| G4: D4 doors | 6 | M6 + carry | 9 |
| G6: C sibling tree (`pinned`) | 1 | M7 (ruled) | 8 |
| G5: D5 + `agent.vault_backends.base` (2) + A(`cryptography`/`cffi`, 4) | 8 | owner-gated | 0 |

(Arithmetic: 149 spawn sites = 93 D1 + 35 D2 + 11 D3 + 6 D4 + 2 D5 + 2 `vault_backends.base`;
164 = 149 + 6 native + 4 process + 4 unproven + 1 pinned.)

The numbers are this tree's; a lane takes its own before-count from the gate and reports the
delta, not these figures.

## 3. The "Nine Stage 2 rows … wait on five widening PRs" row — PR map (2026-09-30)

`gh pr list --repo NousResearch/hermes-agent --author @me --state open` (49 open) and
`gh pr view` on the four numbers the row names:

| ask (rows) | PR | state |
|---|---|---|
| `register_command` gateway context + `busy_policy` (`/queue-status`, 4 rows) | #123976 | **CLOSED 2026-09-27, unmerged** — no open door; re-open or re-cut owed |
| terminal command-guard hook consulted by `_check_all_guards` (envelope gate, 1 row) | #123977 | OPEN, mergeable |
| per-call usage ledger / cost on `post_api_request` + Codex app-server (`usage_ledger`, 3 rows) | #123978 | OPEN, mergeable |
| tool-schema transform hook (wire briefs, 1 row) | none | REFUTED 2026-09-26 (upstream `llm_request` middleware); #124210 adds persisted-row / MCP transform hooks and #128643 chains request middleware — adjacent, not this ask |
| `register_toolset` / `add_to_toolset` (bundle membership, `harness_core`, 1 row) | #123979 | OPEN, mergeable |

Also relevant to THIS plan: #128843 `config_switch` + distribution switches (`mcp`, `terminal`,
`gateway`, `voice`, `git probe`) is the upstream home for the phone switches the manifest's
`KEYS_READ_OUTSIDE_DEFAULTS` reads — when it merges, those readers' fork carries go.

## 4. Lanes — Opus, disjoint files, in this order

Rules once: one MOVE, one CHANGE per commit; run the gate once before and once after (background,
log, `EXIT=$?` appended; `timeout` ≥ 900 s — the gate takes ~10 min on this box); touched tests
only, never the suite; re-take `docs/downstream/bundled-phone-gate-2026-09-28.md` with
`--markdown`; the killing mutation is applied, its red pasted into the commit body, reverted.

### Lane G1 — profile switch-offs (M1 + zero-code M4)
- Rows: Bucket D1 (all seven families, `tools.skills_hub_github` included); Bucket A `pillow-heif` (needs **D2** — land
  without it only if the owner has answered) and `ruamel-yaml-clib`.
- Files: `agent_runtime/bundle_profiles/bundled-phone.yaml`;
  `tests/agent_runtime/test_embedded_phone_session.py` (the e2e must stay green with the new
  absences — it is the proof the turn path reaches none of them);
  `docs/downstream/bundled-phone-gate-2026-09-28.md`.
- Mechanism: M1, `omitted_distributions` (`pillow-heif`), `placeholder_distributions`
  (`ruamel-yaml-clib`).
- Done-test: gate **164 → 67** (`pinned` stays 1 — that is G6; `native` 3 → 2); phone e2e green;
  `tests/scripts/test_bundle_profile_gate.py` green.
- Killing mutation: delete the `gateway.status` line from `switched_off_modules` → the gate's
  `subprocess_call` count rises by 2 (its two sites) — record the red.

### Lane G2 — fork spawn seams (M5 + M2 + M4 `psutil`) — after G1 lands
- Rows: Bucket D3 (all six); Bucket A `psutil`; Bucket B.
- Files: `agent_runtime/git_cmd.py`, `build_identity.py`, `repo_context.py`,
  `realm_sync/git.py`, `store_file_io.py` + new `store_file_io_windows.py`, `provider_signin.py`
  + new `provider_signin_child.py`, `gateway_endpoints/routes.py` + new
  `gateway_endpoints/route_command.py`, `tools/agent_chat_dispatch/local.py` + new
  `local_child.py`, `discussions/native.py`, `conversations/native_peer.py`,
  `loop_tool_lifecycles.py` (table: `agent_runtime.git_cmd`, `hermes_cli.secret_prompt`),
  `hermes_cli/process_identity.py` (one-line guard — the thin seam; the PR is G4's),
  `bundled-phone.yaml` (its `switched_off_modules` and `omitted_distributions` sections only —
  G1 has landed), `tests/agent_runtime/test_loop_tool_lifecycles.py`, the touched modules' tests,
  the gate doc.
- Done-test: gate **67 → 50** (`process` and `unproven` rows empty, `native` 2 → 2); realm-sync
  tests still pass on desktop (the chokepoint changes no desktop behaviour).
- Killing mutation: remove `run_git` from the `agent_runtime.git_cmd` table entry → the gate
  prints `pinned: agent_runtime.git_cmd` (build_stamp imports it at module level) — record it.

### Lane G3 — spawn-site stand-ins (M3, the new mechanism) — parallel to G2, disjoint files
- Rows: Bucket D2 (22 modules, 35 sites); **D1** (principle) answered first.
- Files: new `agent_runtime/spawn_stand_ins.py` (table `module -> function names`,
  `ensure_spawn_stand_ins()`, marker on the stand-in, `__layer__ = "lanes"`); `scripts/bundle_profile_gate.py`
  (`spawn_seams()` child-interpreter probe modelled on `placeholder_seams`; enclosing-`def` lookup
  by AST; findings answered are listed under the table like the placeholder seams are);
  `hermes_cli/harness_parts/serve/in_memory.py` (`EmbeddedServe.start` calls it beside
  `ensure_lifecycle_placeholders` / `ensure_provider_sdk_shim`); new
  `tests/agent_runtime/test_spawn_stand_ins.py`; `tests/scripts/test_bundle_profile_gate.py`
  (a spawn in a rebound function is answered; in a plain function is not; a table row whose
  function does not exist FAILS the probe, never silently passes); the gate doc.
  No yaml change: the modules stay kept.
- Done-test: gate **50 → 15**; `test_the_loop_placeholders_are_registered_before_the_serve_thread`
  gains a sibling for the stand-ins; desktop `ensure_spawn_stand_ins()` is a no-op (asserted:
  with `agent.provider_sdks` on / the desktop profile, nothing is rebound).
- Killing mutation: (1) delete the `hermes_constants: _run_version_probe` row → gate +1;
  (2) in the probe, accept any callable instead of the marker → the new gate test's "plain
  function is not answered" case reds. Record both.

### Lane G4 — upstream doors with fork carry (M6) — after G1
- Rows: Bucket D4 (both); the `process_identity` guard PR (G2 carries the seam); the
  `secret_prompt` termios guard PR (retires G2's table entry later); the `vault_store` Fernet
  guard PR only if **D3** keeps the vault.
- Files: `hermes_bootstrap.py` (the relaunch block → one call), `hermes_cli/venv_sync.py`
  (`relaunch_if_needed`), `tui_gateway/methods_prompt.py` → new `tui_gateway/methods_pdf.py`
  (+ its registration where `methods_prompt` is imported), `bundled-phone.yaml`
  (`hermes_cli.venv_sync`, `tui_gateway.methods_pdf` switched off), PR branches cut from
  `upstream/main` for each door (the fork commit names the PR number), the gate doc.
- Done-test: gate **15 → 9**; `tests/hermes_cli` bootstrap/venv_sync tests green; a desktop
  `hermes` still relaunches (the moved block is behaviour-identical — assert with the existing
  relaunch tests).
- Killing mutation: put one `subprocess.call` back at `hermes_bootstrap` module level → gate +1
  and `pinned`-free; record.

### Lane G6 — the sibling tree (M7, ruled) — after G3 lands (shares `in_memory.py` with it)
- Rows: Bucket C; the runtime-queue row "The phone packager ships switched-off modules that
  directory scans then import…" (OWNER 2026-09-30: option (1)) — this lane closes that row.
- Files: `scripts/bundle_profile_package.py` (`first_party_plan`'s forced set lands under a
  sibling root, e.g. `<bundle>/phone_forced/{tools,plugins}/…`, never under the scanned
  `tools/` / `plugins/`), `hermes_cli/harness_parts/serve/in_memory.py` (`EmbeddedServe.start`
  appends the sibling root to `tools.__path__` / `plugins.__path__` when it exists),
  `scripts/bundle_profile_gate.py` (a `pinned` module the packager's plan places in the sibling
  tree is answered — read from the plan, listed under the table like the placeholder seams),
  `tests/scripts/test_bundle_profile_package.py`, `tests/scripts/test_bundle_profile_gate.py`,
  `tests/agent_runtime/test_embedded_phone_session.py` (`_stage_phone_wheel` stages the sibling
  tree; the five scan-import attempts the row records go to zero), the gate doc.
- Done-test: gate **9 → 8** (`pinned` row empty); the e2e's switched-off import recorder shows
  NO import from `tools/registry.py::discover_builtin_tools` or the plugin loader of a forced
  module; desktop packaging (`bundled-desktop`) byte-identical.
- Killing mutation: stage the forced set under the scanned `tools/` again → the e2e recorder
  reports `tools.terminal_tool` imported by `discover_builtin_tools`; record the red.

### Lane G5 — owner-gated remainder — after D2–D5 are answered
- Rows: Bucket D5 (both); Bucket A `cryptography`/`cffi` (with the D3 vault decision);
  `pillow-heif` if G1 landed without D2.
- Files: `bundled-phone.yaml`; `agent_runtime/gateway_tls.py` (guard `_mint` /
  `_der_from_pem`); per D3 either `switched_off_modules` (`agent.vault_store`,
  `agent.vault_backends`) or G4's Fernet PR; per D4 `plugins.web.ddgs` switch-off or an in-process
  seam; per D5 new `agent_runtime/conversations/in_process_slash.py` + a `_SlashWorker.__init__`
  row in G3's table; the gate doc.
- Done-test: gate **8 → 0, PASS**, exit code 0 (G6 landed); phone e2e green with every new absence;
  `tests/agent_runtime/test_bundle_profile_switches.py` green.
- Killing mutation: remove the `_SlashWorker.__init__` table row → gate REFUSED (1). Record.
- Needs a real device: nothing here — the gate and the e2e run on desktop CI. The FIRST run of the
  packaged wheel on a phone (Stage 3 exit) is where a stand-in that the turn path does reach
  will surface; the e2e's switched-off import recorder is the desktop proxy.

## 5. Owner decisions needed (mark, do not guess)

- **D1 — function-level stand-ins on upstream modules (M3).** Rebinding a named function on a
  kept upstream module to a loud stand-in, from a fork module, at the phone entry, proven by the
  gate at run time. Yes → G3 as written. No → each D2 module becomes an upstream door (extract
  its spawning helpers into a sibling module) — ~20 PRs, and zero waits on their merges.
- **D2 — HEIC/AVIF on phones.** Omit `pillow-heif` and have the Launcher's picker transcode
  (recommended), or admit a compiled `pillow-heif` (no iOS wheel exists today), or accept "HEIC
  photos are refused on the phone".
- **D3 — the secrets vault on phones.** Drop `agent.vault_store` + `agent.vault_backends.*`
  (the host store binding is the phone's vault; `vault.*` RPCs answer unavailable) — recommended
  and consistent with Spec §7.6 — or keep it and guard the two Fernet imports upstream.
- **D4 — DuckDuckGo on phones.** Drop the `ddgs` provider on the phone (HTTP-API providers only)
  or seam its worker in-process.
- **D5 — slash commands on phones.** Build the in-process slash runner (the phone's session build
  spawns `python -m tui_gateway.slash_worker` today, which a phone cannot), or rule "no slash
  commands on the phone" for Stage 2.
- RULED, not open: the packager forced set / lazy-site register ships as the sibling tree (owner
  2026-09-30, `ff9cbca51f`) — lane G6. Every G1 switch-off lengthens the forced set G6 stages.
