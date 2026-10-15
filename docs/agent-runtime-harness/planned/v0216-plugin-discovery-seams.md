# v0.21.6 — plugin discovery leaves the credential path; process-env defaults leave `register()`

> **Status: BUILT 2026-10-10** on `plan/v0216-discovery-design` (P1 `change(provider-access)`, P2
> `change(process-env)`). Review deviations: P1 registers the harness whenever it is missing (not
> only on an empty registry) and adds no binder calls (the port's bound-read registration covers
> them). P2 review gap: upstream's kanban dispatcher runs in upstream's messaging gateway, NOT in the
> serve tree (§2.3 rule 2 was wrong about that); owner 2026-10-10: that gateway is not run, and a
> persona gateway will be fork-composed, so it applies the table like the serve. Q1/Q2 answered as
> recommended.
>
> Original status: **DESIGN, not built** (lane `plan/v0216-discovery-design`, 2026-10-10, cut from
> `fix/v0216-fork-reds`). Two fork weaknesses the v0.21.6 release merge exposed as upstream reds.
> Every number in §0 was measured on the operator's PC on 2026-10-10 (test venv
> `~/.venvs/hermes-test`, fresh subprocess per phase, three runs); nothing here is attributed
> without a receipt. Canon this touches when it ships: doc 02 (the `get_hermes_auth_home()`
> paragraph under "The snapshot core"), doc 03 ("Provider access follows the service's captured
> auth owner"), and the `hermes_cli/auth.py` / `hermes_cli/plugins.py` rows of
> [`upstream-footprint-ledger.md`](upstream-footprint-ledger.md). No upstream file is edited by
> either problem's fix.

## 0. Receipts

### 0.1 What a first credential read pays (unbound process, empty home, 58 manifests)

| phase (fresh process each) | ms, 3 runs | notes |
| --- | --- | --- |
| `import hermes_cli.auth` | 988 / 1107 / 1118 | import tax; not this plan's subject |
| `collect_directory_manifests()` | 161 / 181 / 187 | 58 manifests — the manifest-only floor |
| `discover_declared_cli_commands()` | 180 / 227 / 186 | the Stage-1 "materialise one plugin" seam |
| `discover_plugins()` cold | 913 / 823 / 822 | log: `58 found, 53 enabled, elapsed_ms=899/809/809` |
| `discover_plugins()` warm | 0.04 / 0.03 / 0.03 | idempotent re-entry is free |
| `_auth_file_path()` first call | 788 / 846 / 749 | second call 0.07 ms; **writes two env keys** (§2) |
| `_auth_file_path()` first, `HERMES_AUTH_HOME` bound | 760 / 751 / 755 | returns the bound store (correct) |

The enabled count is config-dependent: the same tree reports `21 enabled, elapsed_ms=279` under
`tests/hermes_cli/test_anon_surfaces.py` and `53 enabled, elapsed_ms=654` under
`tests/hermes_cli/test_model_info_probe_timeout.py` (both from the `scripts/run_tests.sh` logs,
2026-10-10). The work order's "1.4–1.6 s" was not reproduced on this box; the plan uses the
measured 0.65–0.9 s. Script: `measure_discovery.py` in the lane's scratchpad (receipt only; not
committed — the gate in P1-S3 re-measures with a committed test).

### 0.2 Which call runs discovery in each red (a pytest plugin wrapping `discover_plugins` printed the first stack)

| red (upstream test, green on tag v0.21.6) | first `discover_plugins()` reached through | problem |
| --- | --- | --- |
| `test_model_info_probe_timeout.py::…exceeds_its_budget` (1.01 s > 0.9 budget) | `web_routers/models.get_model_info` → `providers.get_provider_profile` → `runtime_provider.load_config` → **`agent.provider_access.provider_configuration` → `current_access`** | 1 |
| `test_anon_surfaces.py::test_keepalive_does_not_start_for_free_tier` (8 `plugin-load:*` threads captured by the test's `Thread` double) | `nous_auth_keepalive.start_nous_auth_keepalive` → `auth.get_provider_auth_state` → `_load_auth_store` → `_auth_file_path` → **`provider_credential_file` → `current_access`** | 1 |
| `test_profiles_describe_secret_scope.py` (`os.environ` gained `HERMES_KANBAN_CLAIM_TTL_SECONDS=2700`) | `methods_profiles._describe_toolsets` → `tools_config._get_platform_tools` → **upstream's `plugins._nowait_plugin_set` → `discover_plugins`** (33 calls in the test) | 2 only |

The third red is NOT reached through the provider-access port: upstream's own describe path
blocks on discovery. Problem 1's fix does not green it; Problem 2's does. The two problems are
independent and land as two CHANGE commits.

## 1. Problem 1 — the provider-access port runs plugin discovery on every first read

### 1.1 Root cause

`agent/provider_access.py::current_access()` (fork-owned) calls `discover_plugins()` before
reading its registry, so all three port reads — `provider_credential_file` (behind upstream's
`_auth_file_path`, fork seam in `hermes_cli/auth.py`), `provider_secret`
(`_resolve_api_key_provider_secret`, `anthropic_credentials`, `auxiliary_client`,
`credential_pool`, `model_switch`, `runtime_provider_custom`) and `provider_configuration`
(`runtime_provider.load_config`, `inventory`, `credential_pool`) — pay full plugin discovery the
first time any of them runs in a process. Upstream's own registries (`web_search_registry`,
`image_gen_registry`, `video_gen_registry`) never discover on read; the lazy discovery on the
credential path is a fork invention, and it sits on the hottest, earliest path in every process.
v0.21.6 made it visible by raising the bundled plugin count (58 found; 53 load with an empty
config) so the discovery that was 279 ms with 21 plugins is 650–900 ms, and upstream tests that
assume a credential read has no plugin side effects (a budget, a `threading.Thread` double) red.

The port's only registrant is the harness (`agent_runtime/provider_access.py::SharedProviderAccess`,
registered by `plugins/eternia-harness/__init__.py::register`). Its whole policy is
`(bound_home or profile_home) / name` where `bound_home` is
`agent_runtime.profile_home.get_hermes_auth_home()` — a ContextVar-then-env read that needs no
plugin. The constraint ("a process with `HERMES_AUTH_HOME` bound must never read the wrong
`auth.json`") is therefore satisfiable without discovery: the binding fact and the registrant are
both the fork's own, and both are reachable by one import.

### 1.2 Options considered

- **A. Start background discovery earlier in every process** — hides latency on the CLI only;
  the serve/test processes still pay inline, the `Thread` double still captures the loaders. Rejected.
- **B. Manifest-declared provider access, materialised alone like `cli_commands`** — 180–230 ms
  manifest scan per process (§0.1) plus the harness's whole `register()` with its side effects;
  widens `PluginManifest` (upstream `plugins_discovery.py`). Rejected.
- **C. Hardcode `if HERMES_AUTH_HOME: return bound/name` in the port** — makes the registry
  theatre; the generic door (`register_provider_access`, PR #128648 candidate) would resolve
  nothing. Rejected.
- **D4. Discover only when `plugins.enabled` is non-empty** — keeps the third-party pre-discovery
  guarantee, but the operator's root `config.yaml` lists `homeassistant`, so every root-home
  process would still pay. Kept as the fallback if the owner answers Q1 "no".
- **D (chosen). The port reads its registry as-is and never discovers; the harness registers its
  access at BIND time, not only at plugin-load time.**

### 1.3 Chosen design

1. `agent/provider_access.py::current_access()` — delete the `discover_plugins()` call. Read
   `_registry.list_providers()`. When the list is EMPTY and `get_hermes_auth_home()` answers
   (ContextVar or env — the one fact that can make a provider authority bound), call
   `agent_runtime.provider_access.ensure_shared_provider_access_registered()` (function-local
   import; precedent `agent/anthropic_credentials.py`'s `agent_runtime.host_store` seam) and read
   again. The "exactly one bound authority" rule and the no-fallback-on-error rule are unchanged.
   Module docstring changes from "supplied by the active profile's plugins" to "supplied by
   whatever is registered; plugins register when they load, and this port never loads them".
2. `agent_runtime/provider_access.py::ensure_shared_provider_access_registered()` — idempotent:
   `get_provider("eternia-harness") is None` → `register_provider(SharedProviderAccess())` in the
   global (unscoped) table. Returns whether it registered.
3. The in-process binders call it before binding: `agent_runtime/profile_context.py`
   (`persona_profile_context`, beside `set_hermes_auth_home_override`) and
   `agent_runtime/conversations/in_process_peer.py::_dispatch_scoped`. The child entry
   `agent_runtime/conversations/worker_entry.py::main` calls it beside
   `bind_desktop_host_store_or_exit()` ("before the engine reads a credential"). Layers point down:
   `stores`/`lanes`/`wiring` → `stores`. `profile_home.py` (`models`) is NOT touched — it may not
   import `stores`.
4. `register()` KEEPS `ctx.register_provider_access(SharedProviderAccess())`: that is upstream's
   registry door (scoped entry, leased, restored on unload). Two writers of one registration, same
   object type, same name, is the one accepted duplication; the registry's same-name overwrite and
   the unload lease make the order irrelevant. Recorded here so no one "fixes" it.
5. Children that inherit `HERMES_AUTH_HOME` through env but enter through upstream's `hermes` main
   (a terminal child, `hermes_cli/auth_noninteractive.py`) hit rule 1's env branch on their first
   read: bound store, no discovery, no race with `start_background_plugin_discovery`.
6. `tests/agent/test_provider_access.py::test_discovered_access_is_profile_scoped_and_unloads`
   (a user plugin supplying access) changes to call `get_plugin_manager().discover_and_load()`
   per home before reading — the contract the module now states. This is Q1.

### 1.4 Stages

**P1-S1 — the port stops discovering** · files: `agent/provider_access.py`,
`agent_runtime/provider_access.py`. Gate: new fork test
`tests/agent/test_provider_access_no_discovery_downstream.py` — (a) `hermes_cli.plugins.discover_plugins`
monkeypatched to a sentinel that raises; unbound, empty registry →
`provider_credential_file("auth.json", home) == home / "auth.json"`, `provider_secret` is `None`,
`provider_configuration(p) is p`; (b) same sentinel, `HERMES_AUTH_HOME` set in env →
`provider_credential_file("auth.json", home) == bound / "auth.json"` and the registry now holds
exactly one `eternia-harness` entry; (c) same, bound via `set_hermes_auth_home_override` →
same answer. Killing mutation: restore the `discover_plugins()` line → (a) red on the sentinel.
Second mutation: delete the env branch → (b) red (profile path returned).

**P1-S2 — the binders register** · files: `agent_runtime/profile_context.py`,
`agent_runtime/conversations/in_process_peer.py`, `agent_runtime/conversations/worker_entry.py`,
`tests/agent/test_provider_access.py` (rule 6). Gate: `tests/agent_runtime/test_shared_provider_credentials.py`
unchanged and green (it binds the ContextVar only and asserts `_auth_file_path() == owner/auth.json`),
plus a new case in the S1 file: `persona_profile_context(...)` entered with the sentinel in place
→ the registry holds the harness entry before any read. Killing mutation: drop the `ensure_…` call
in `profile_context` → red. `tests/tooling/test_fork_import_layers.py` stays green (no upward import).

**P1-S3 — the reds and the receipt** · files: none beyond S1/S2; the commit body carries:
`scripts/run_tests.sh tests/hermes_cli/test_model_info_probe_timeout.py` and
`scripts/run_tests.sh tests/hermes_cli/test_anon_surfaces.py` green; the S1 gate file extended
with a subprocess timing case: fresh interpreter, hermetic home, unbound →
`_auth_file_path()` first call ≤ 20 ms and the process never logged `Plugin discovery complete`
(positive runtime proof; today's 749–846 ms is the red). Killing mutation: the S1 line again.

## 2. Problem 2 — `register()` writes process env, so any discovery leaks it

### 2.1 Root cause — and this is the third instance of one class

`plugins/eternia-harness/__init__.py::register` calls `default_kanban_claim_ttl()`
(`os.environ.setdefault("HERMES_KANBAN_CLAIM_TTL_SECONDS", "2700")`) and
`default_no_venv_lazy_installs()` (`setdefault("HERMES_DISABLE_LAZY_INSTALLS", "1")`). Plugin load
happens whenever discovery happens — at boot, or lazily inside whatever upstream code path blocks
on `discover_plugins()` first — so a plugin-time env write lands at an unpredictable point in any
process and is visible to any `os.environ` snapshot taken around that point. Instances:

1. `tests/cron/test_cron_kanban_env_isolation.py::TestRunJobKanbanIsolation::test_environment_is_left_untouched`
   and `::test_concurrent_jobs_do_not_corrupt_worker_identity` — red since h10b-fix (2026-09-29),
   carried as `_fork_replaces` rows in `tests/_downstream/id_markers/fork_marks.py` pointing at
   `tests/cron/test_cron_kanban_env_isolation_downstream.py`.
2. `tests/tui_gateway/test_profiles_describe_secret_scope.py` — red on pre-merge `8fa3de2c31` and on
   v0.21.6: upstream's `_nowait_plugin_set` discovers inside `profiles.describe`, `register()` runs,
   `dict(os.environ) == environ_before` fails on `HERMES_KANBAN_CLAIM_TTL_SECONDS` (§0.2). Only one
   key shows because the hermetic conftest already sets `HERMES_DISABLE_LAZY_INSTALLS=1`; outside
   the suite both keys leak (§0.1 last column).
3. `HERMES_DISABLE_LAZY_INSTALLS` itself: its consumer `hermes_cli/venv_sync.py` runs at bootstrap,
   BEFORE any plugin loads, so the plugin-time default never protected the process that wrote it —
   only children that inherit `os.environ`. The write was in the wrong process from the start.

The class: **a process default written at plugin-load time.** The doors stay (owner 2026-09-29:
"the env stays" is about the variable upstream reads, not about who writes it, and the operator's
own value still wins); the WRITER moves to where the fork composes a process.

### 2.2 Options considered

- **a. Write the TTL from `on_kanban_dispatch_tick`** — the hook fires in the dispatcher AFTER
  each tick, once `_dispatch_tick_lock` is released (`hermes_cli/kanban_db.py`, the
  `on_kanban_dispatch_tick` fire site), so the first tick's claims get 15 min and the workers it
  spawned inherit nothing. Rejected.
- **b. An upstream config key `kanban.claim_ttl_seconds`** — no door exists
  (`kanban_db._resolve_claim_ttl_seconds`: explicit > env > default); a held PR row, months. Rejected
  as the fix; filed as the eventual retirement.
- **c. Scope the write by detecting a "describe"/read-only context** — a second heuristic on top of
  the first. Rejected.
- **d (chosen). One fork-owned table of harness process-env defaults, applied by the fork's
  process composers; `register()` touches nothing outside its registries.**

### 2.3 Chosen design

1. New fork-owned `agent_runtime/process_env_defaults.py` (`__layer__ = "policy"`):
   `HARNESS_PROCESS_ENV_DEFAULTS: Mapping[str, str] = {"HERMES_KANBAN_CLAIM_TTL_SECONDS": "2700",
   "HERMES_DISABLE_LAZY_INSTALLS": "1"}` with the two docstrings moved from the plugin, and
   `apply_harness_process_env_defaults(environ: MutableMapping[str, str] = os.environ) -> tuple[str, ...]`
   (setdefault each; returns the keys it wrote). `KANBAN_CLAIM_TTL_SECONDS = 45 * 60` moves here.
2. Appliers — the fork's process composers, nothing else:
   `hermes_cli/harness_parts/serve/commands.py::_cmd_serve` as its first statement (the serve
   hosts the gateway-embedded kanban dispatcher and spawns every harness child; children inherit
   through `build_subprocess_env(base=None)` = `os.environ.copy()`); and
   `agent_runtime/conversations/worker.py::start_worker` on the `environment` dict it already
   composes (explicit, not inheritance-dependent). `worker_entry.main` is NOT an applier: the
   parent already composed its env; two writers for one child would be the weakness again.
3. `plugins/eternia-harness/__init__.py`: `default_kanban_claim_ttl`, `default_no_venv_lazy_installs`
   and `KANBAN_CLAIM_TTL_SECONDS` are deleted; `register()` loses the two calls. Process env is
   never written from plugin code — that is the rule the S2 gate enforces for the class.
4. `tests/_downstream/id_markers/fork_marks.py`: the `_fork_replaces` block for the two
   `TestRunJobKanbanIsolation` tests is deleted (an unmatched/unneeded row is coverage theatre; the
   upstream tests pass again). `tests/cron/test_cron_kanban_env_isolation_downstream.py` re-points
   at `apply_harness_process_env_defaults` (adds exactly the two keys; the operator's value wins).
5. The old register-defaults test in `tests/agent_runtime/test_background_completion.py` is replaced
   by `tests/agent_runtime/test_background_completion.py::test_register_writes_no_process_env` and the S2 gates below; the middleware test in that file is unchanged.

### 2.4 Stages

**P2-S1 — the table and its appliers** · files: `agent_runtime/process_env_defaults.py` (new),
`hermes_cli/harness_parts/serve/commands.py`, `agent_runtime/conversations/worker.py`,
`tests/cron/test_cron_kanban_env_isolation_downstream.py`. Gate: the re-pointed downstream test —
`apply_…(env)` on a copy without the keys adds exactly `{TTL: "2700", LAZY: "1"}` and nothing else;
with `TTL=60` preset it adds only `LAZY`; `kanban_db._resolve_claim_ttl_seconds()` reads 2700 under
the applied env and 60 under the preset. New `tests/agent_runtime/test_process_env_defaults_downstream.py`:
`start_worker`'s composed env (spawn monkeypatched to capture `env=`) carries both keys. Killing
mutation: remove one key from the table → first test red; remove the `start_worker` call → second red.

**P2-S2 — the plugin writes no env; the class gate** · files: `plugins/eternia-harness/__init__.py`,
`tests/agent_runtime/test_background_completion.py`, `tests/_downstream/id_markers/fork_marks.py`.
Gate 1 (unit): `register(_NullCtx())` with `dict(os.environ)` snapshotted before → equal after.
Gate 2 (the class, positive at runtime): a subprocess with a hermetic `HERMES_HOME`, snapshot
`os.environ`, `discover_plugins()`, snapshot again → equal (upstream's `.env` re-pull writes
nothing in an empty home). Killing mutation: re-add one `os.environ.setdefault` in `register()` →
both red. Receipt in the commit body: `scripts/run_tests.sh tests/tui_gateway/test_profiles_describe_secret_scope.py`
green AND `scripts/run_tests.sh tests/cron/test_cron_kanban_env_isolation.py` green bare (the
upstream file whose marker rows this stage deletes).

**P2-S3 — the retirement row** · no code. One row in `runtime-queue.md` § Upstream-owned: an
upstream config door for the kanban claim TTL (`kanban.claim_ttl_seconds`) retires the env default
entirely; a caller-side memo until then. Filed by the landing (§5).

## 3. Landing

- Two CHANGE commits, one per problem, no MOVE; each carries its killing mutations' reds in the body.
  Problem 2 may land first (it alone greens two of the three reds and the upstream cron pair);
  Problem 1 greens the other two. Nothing in either touches an upstream file, so the `[up-fp]`
  footprint and `tests/scripts/test_upstream_footprint.py` are unchanged; `hermes_cli/auth.py`'s
  ledger row gets one sentence ("the fork seam no longer runs discovery") when P1 lands.
- Lane runs (background, log, exit code unpiped): the test files that import a touched module —
  `tests/agent/test_provider_access*.py`, `tests/agent_runtime/test_shared_provider_credentials.py`,
  `tests/agent_runtime/test_background_completion.py`, `tests/agent_runtime/test_process_env_defaults_downstream.py`,
  `tests/cron/test_cron_kanban_env_isolation*.py`, the three reds, plus
  `tests/tooling/test_fork_import_layers.py` and `tests/_downstream/`'s marker gate
  (`tests/scripts/test_upstream_skip_list.py` is unaffected: none of the three is listed).
- Landing runs `scripts/run_tests_bundled.sh tests` once for the batch, and
  `changed_line_mutation_check.py` for the three new gate files.
- Canon fold-in at landing: doc 02's `get_hermes_auth_home()` paragraph gains "the provider-access
  port registers the harness at bind time; it never runs discovery"; doc 03's provider-access
  sentence cites it. This file then moves to `archive/` with the §0 receipts (they are evidence).

## 4. Owner questions

- **Q1 (P1, rule 6).** The port stops discovering. A third-party plugin that registers provider
  access is found only after something loads plugins (CLI start, agent start, an explicit
  `discover_plugins()`); a credential read before that sees the native path. No such plugin
  exists; upstream has no such port. Recommended: accept. If not, D4 (discover when
  `plugins.enabled` is non-empty) is the fallback, at the cost that root-home processes on this
  operator's config (`enabled: [homeassistant]`) keep paying full discovery.
- **Q2 (P2, rule 2).** `hermes kanban claim` / `hermes kanban dispatch` run from an operator shell
  OUTSIDE the serve's process tree gets upstream's 15-minute claim TTL (today 45 min through the
  plugin-time env). Inside the serve tree (gateway-embedded dispatcher, its workers, cron jobs,
  conversation workers) nothing changes. Recommended: accept; the alternative is a carry in
  `hermes_bootstrap.py` (upstream file, +1 footprint line) and that carry is the class again.

## 5. Queue rows to file at landing (verbatim; the lane stands in a worktree and does not write the queue)

`runtime-queue.md` § Fork-owned, "Filed on arrival — <date> (lane v0216-discovery)":

- **a credential read ran plugin discovery** · provider-access port on the hot path of every
  process; 650–900 ms on first read, two upstream reds · `planned/v0216-plugin-discovery-seams.md` §1 · P1-S1..S3
- **plugin-time process-env writes are a class** · third upstream red (cron env isolation
  2026-09-29, describe secret scope v0.21.6); the writer moves to the process composers ·
  `planned/v0216-plugin-discovery-seams.md` §2 · P2-S1..S2

`runtime-queue.md` § Upstream-owned:

- **`_nowait_plugin_set` blocks `profiles.describe` on full discovery** · `hermes_cli/plugins.py`
  (upstream; `get_plugin_toolset_keys_nowait` falls through to `discover_plugins()` when no
  background scan is in flight) — a describe in a fresh serve pays 650–900 ms; caller-side memo only ·
  §0.2 · unowned
- **kanban claim TTL has no config door** · `kanban_db._resolve_claim_ttl_seconds` reads env only;
  an upstream `kanban.claim_ttl_seconds` retires the harness default · §2.2 b · held PR row

`fork-hygiene-queue.md`:

- **`fork_marks.py` rows for `TestRunJobKanbanIsolation` retire with P2** · run
  `tests/cron/test_cron_kanban_env_isolation.py` bare at landing and delete the two rows in the
  same commit · §2.3 rule 4 · P2-S2
