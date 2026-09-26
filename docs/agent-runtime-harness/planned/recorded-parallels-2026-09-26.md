# Recorded parallels — the verdict sheet (lane PAR-DESIGN, 2026-09-26)

Rule of record (owner 2026-09-23): adopt upstream's, or record the parallel with the symbol it
shadows, why it cannot be adopted, and what retires it. This sheet rules every recorded parallel
ONCE, from `upstream/main` (`d0288be5b33`, 165 commits past the ledger base `067fa1a257`) — a
verb here rests on upstream's code as read, never on the ledger's prose. Executable by an Opus
lane without the author. Inputs: `upstream-footprint-ledger.md` (rows containing `RECORDED
PARALLEL`, § "Fork modules that shadow an upstream symbol"), `harness-plugin-and-upstream-seams.md`
§1 rules 1 and 6, `scripts/upstream_footprint.py --json` (measured 2026-09-25: `files=178
deleted_lines=924 heavy=4`).

Verbs. **RESOLVER**: upstream's helper already calls through a seam the fork can bind; the parallel
deletes. **PR**: upstream needs one additive override point (≤10 lines); the fork line becomes one
call. **CARRY**: cannot be adopted; the reason and the retiring event are named.

## 1. Population and verdicts

`del` = deleted lines the diff row costs today (a fork-owned module costs 0 — it is not a diff row).

| # | upstream symbol (`upstream/main`) | fork parallel | what it changes | del | verb |
|---|---|---|---|---|---|
| 1 | `hermes_cli/auth.py:482` `_auth_file_path` | same file, +18/-1, reads `agent_runtime.profile_home.get_hermes_auth_home` | auth store resolves to the HEAD's home while `HERMES_HOME` is the persona profile | 1 | PR-A |
| 2 | `tools/async_delegation.py:97` `_db_path` | same file, +15/-1, reads `profile_home.get_hermes_background_work_home` | delegation `state.db` resolves to the operator-visible home | 1 | PR-A |
| 3 | `agent/skill_utils.py:418` `get_all_skills_dirs`, `:22` `EXCLUDED_SKILL_DIRS`, `:603` `normalize_skill_lookup_name` | same file, +9/-4, `profile_home.get_shared_skills_dir` | one writable shared root after the home dir; two excluded dir names; lookup walks all dirs, posix-spelled | 4 | PR-C |
| 4 | `agent/session_persistence.py:190` `_db_flush_row` | same file +5/-2; `agent_runtime/native_persistence.py` (24 lines) | persona chat-root rows projected before flush (`msg_idx` added to the signature) | 2 | PR-B |
| 5 | `agent/turn_context.py:620` `_stage_turn_user_message`, `:980` `build_turn_context` | same file +18/-8 | `reuse_current_user_message`: an already-persisted native user row is neither re-appended nor re-stamped | 8 | PR-B |
| 6 | `tools/mcp_tool_config.py:111` `_build_safe_env`, `:384` `_load_mcp_config` | same file +41/-1; `agent_runtime/mcp_environment.py` (64), `machine_roots.resolve_mcp_servers` | child `HERMES_HOME` injected; per-server env + `runtime_env`; machine-root tokens; servers DROPPED by platform | 1 | PR-B |
| 7a | `tools/tool_search.py:150` `is_deferrable_tool_name`, `:40` `ToolSearchConfig` | same file (part of +117/-16): `never_defer_tool_names`, config key `never_defer` | names that never defer (`agent_chat_*`) | (16) | PR-D |
| 7b | `tools/tool_search.py:489` `dispatch_tool_describe`, search top hits | same file: `ensure_tool_describe_present`, `tool_describe_schema`, `parameters` in top hits | describe always registered, serves every tool; top hits carry schemas | (16) | PR-D |
| 7c | `tools/tool_search.py:494` `names` list arg (and `queries`) | same file: legacy single `query` / `name` args | a second spelling of upstream's list door | (16) | RESOLVER |
| 8 | `agent/credential_pool.py:2124` `_select_unlocked` strategy branch (`:2141-2157`) | same file +9/-18; `agent_runtime/pool_rotation.py` (218), `PoolRotationMixin` leads the MRO | typed persisted cursor; `round_robin` no longer rewrites every `priority` + `_persist()`s per select; `least_used` counts durable | 18 | PR-E |
| 9 | `hermes_cli/gateway.py:5641` `_pm_runtime_venv_dir` (`pm.environments.selected_venv`) | same file: `resolve_managed_python`, `ManagedPythonUnavailable`, carried `_detect_venv_dir` (added-only, ~150 lines) | finds the launcher's out-of-checkout venv that pm's committed selection does not | 0 of the row's 19 | CARRY |
| 10 | `hermes_cli/local_runtime/presets.py:192` `generate_presets` → `preset_for_model` | `agent_runtime/local_llama_adapter/engine.py:44` `write_preset` | per-model load knobs (context, GPU layers, flash-attn, KV types, template); owner KEEP 2026-09-24 | 0 | PR-F |
| 11 | `hermes_cli/local_runtime/bootstrap.py:311` `ensure_local_runtime` binary pick (`engine.binary` → `LlamaServerSupervisor`) | `engine.py:79` serves `config["executable_path"]` | bring-your-own `llama-server` | 0 | PR-F |
| 12 | `bootstrap.py:44` `models_dir` / `:123` `staged_models` | `engine.py:254` `scan` over `config["model_roots"]` | extra read-only model roots | 0 | PR-F |
| 13 | `tools/environments/base_output.py:397` `_drain_fd_select`, `:425` `_drain_fd_windows` | `agent_runtime/subprocess_pumps.py` `_pump_fd` (226-line module) | poll-before-read pump for BOTH pipes, one line per sink append, explicit release | 0 | PR-G |
| 14 | `hermes_yaml.py:28` `safe_load` (YAML 1.1: bare `y`/`n` → bool, `1e3` → float) | `agent_runtime/yaml_io.py` `load` (111-line module; `dump`/`YAMLError` ARE upstream's) | reads pyyaml-written artifacts whose flow-graph `y:` keys are unquoted | 0 | CARRY |

## 2. Evidence per verb

**PR-A (rows 1, 2) — a per-store home.** Upstream owns ONE seam: `hermes_constants.py:18`
`_HERMES_HOME_OVERRIDE` ContextVar, read first by `get_hermes_home()` (`:111-118`). The fork already
binds it (`agent_runtime/profile_context.py:296 set_hermes_home_override(binding.profile_home)`) —
to the PROFILE home. Rows 1–2 need the auth store and the background-work store at a DIFFERENT home
in the same context (the head's, `profile_context.py:341`), and one variable cannot hold two homes;
both upstream helpers are `get_hermes_home() / <file>` with no store dimension. Not RESOLVER.
Shape (≤10 lines, `hermes_constants.py`): `_STORE_HOME_OVERRIDE: ContextVar[Mapping[str,str]]`,
`set_store_home_override(store: str, path) -> Token`, `reset_store_home_override(token)`,
`get_store_home(store: str) -> Path` returning the override or `get_hermes_home()`.
Then `auth.py:483` → `get_store_home("auth") / "auth.json"`; `async_delegation.py:98` →
`get_store_home("background_work") / "state.db"`. Fork after merge: `persona_profile_context`
binds both stores through the new setter; `get_hermes_auth_home` / `get_hermes_background_work_home`
stay as the fork's readers of `HERMES_AUTH_HOME` / `HERMES_HEAD_HOME` env and feed the setter; the
two diff rows delete. Upstream's `_global_auth_file_path` (`:495`) is unrelated (read-only fallback).

**PR-B (rows 4, 5, 6) — three trigger sites, no new plumbing.** `hermes_cli/plugins.py:930`
`register_hook` stores UNKNOWN names (warns); what is missing is only the trigger call and the
`VALID_HOOKS` entry. Row 4: `_db_flush_row(agent, msg, is_current_turn_user, msg_idx=0)` (the fork's
signature) and, after `row` is built, `row = run_hooks("transform_persisted_row", agent, msg, row,
msg_idx)`. Row 5: `build_turn_context(..., reuse_current_user_message=False)` exactly as the fork's
+18 (it is generic: "the caller staged this turn's user row already"); the fork line becomes the
kwarg. Row 6, three additive points: (i) `_build_safe_env` sets `env["HERMES_HOME"] =
str(get_hermes_home())` — an upstream BUG (`_SAFE_ENV_KEYS` passes `HOME` and not `HERMES_HOME`, so
a child under a redirected `HOME` resolves a third home), filed as a fix; (ii) `_build_safe_env(user_env,
*, server_name=None)` + `env = run_hooks("transform_mcp_child_env", server_name, env)`; (iii)
`_load_mcp_config` runs `servers = run_hooks("transform_mcp_servers", servers)` before
`_filter_suspicious_mcp_servers` (`:398`) — a transform may DROP a server, which `_interpolate_env_vars`
(`:306`, `${VAR}` only) cannot, so this is not an ADOPT. Upstream's 2026-09 drift on this file
(`_launcher_fallback`, +54/-16) touches command resolution only; no seam arrived.

**PR-C (row 3) — skills roots.** `get_all_skills_dirs` (`:418-427`) has three roots: home, create
dir, `get_external_skills_dirs()`; upstream classes every external root read-only (curator + sync),
and `register_skill` (`plugins.py:1011`) registers a read-only namespaced skill, never a root. The
shared root is writable and un-namespaced — no door. Shape: config `skills.extra_dirs` (writable,
listed after the home dir, 3 lines at `:422`), config `skills.excluded_dirs` unioned into
`EXCLUDED_SKILL_DIRS` at scan (2 lines), `normalize_skill_lookup_name` walking `get_all_skills_dirs`
and returning `.as_posix()` (the ledger's G2, 3 lines — a Windows correctness fix in its own
commit). The plugin seeds `skills.extra_dirs = [<shared root>]` at load (rule 10: upstream's door +
a plugin-set default).

**PR-D (rows 7a, 7b).** `defer_tools` is a whole-list door (`ToolSearchConfig:47`, `[]` = keep every
tool eager), but `is_deferrable_tool_name:160-162` defers every plugin/MCP tool UNCONDITIONALLY, so
no list value keeps `agent_chat_*` eager: `never_defer` is a real gap. Shape: field
`never_defer: frozenset = frozenset()` on `ToolSearchConfig`, parsed in `from_raw`, one early
`return False` in `is_deferrable_tool_name` (≤10 lines). 7b is a second commit on the same branch:
`tool_describe` registered whenever tool search is enabled, and `parameters` on the top N hits —
behaviour upstream may decline; if declined, 7b becomes CARRY with 7a merged.

**7c — RESOLVER.** Upstream's door is the list arg (`dispatch_tool_describe:494 names`,
`_string_list_arg`); the fork's single `query`/`name` is a second spelling of it. Deletes now, no
upstream involvement (the described-result shape difference the ledger cites is 7b's, not 7c's).

**PR-E (row 8).** ADOPT stays refused for the reason the ledger records and upstream's code confirms:
`:2151-2155` rewrites every `priority` and `_persist()`s on each `round_robin` select; `least_used`
counts in memory (`:2144`). Shape: extract `:2141-2157` verbatim into `def _pick_and_rotate(self,
available, *, count) -> PooledCredential` (a pure refactor; `_select_unlocked` becomes one call).
Then `PoolRotationMixin` overrides ONE method and the fork's -18 becomes 0; the MRO line and import
stay a `hook` row (+2/-0) until a strategy registry exists — not filed.

**PR-F (rows 10, 11, 12) — three config keys.** `ensure_local_runtime` hands `engine.binary` to
`LlamaServerSupervisor` (`bootstrap.py:356`): `config.get("executable_path")` first (2 lines).
`staged_models()` (`:123`) walks `models_dir()` only: extend over `config.get("model_dirs", [])`
(3 lines). `preset_for_model` merges `local_runtime.model_overrides[model_id]` into `entry.keys`
(4 lines). Upstream's drift adds `adopt_legacy_models` only. After merge `engine.py` shrinks to the
adapter's config projection; `write_preset`/`scan`/the `executable_path` branch delete.

**PR-G (row 13).** Upstream's drains ALREADY take `stop` (`:397`, `:425`, "the pipe is being
handed to another reader") and a duck-typed sink (`output.append(str)`), which is what the fork's
2026-09-25 row said upstream lacked. Two things remain: both names are private (rule 3), and each
drains one fd — the fork starts one per pipe, which is fine. Shape: `def drain_fd(proc, fd, sink,
decoder, stop=None)` public dispatcher (POSIX/Windows by `sys.platform`, ≤6 lines). Fork:
`_Pump.run` becomes `drain_fd(proc, fd, _LineSink(sink), decoder, self.stop)`; `_pump_fd` and its
Windows branch delete.

**CARRY (row 9).** `_pm_runtime_venv_dir` returns pm's committed selection or nothing, by design
("fail closed"); the launcher's venv is out of checkout and uncommitted, so no override point is
generic. Retires when the launcher's install moves onto pm bundles — the launcher's
hermes-environment design sheet (launcher commit `518f5a251`, 2026-09-26) is that event.

**CARRY (row 14).** `hermes_yaml.safe_load` is YAML 1.1 on purpose (`:24 yaml.version = (1, 1)`);
a bare `y:` key reads `True`, and every artifact published before 2026-09-26 has one. Retires by a
fork-only migration (§3 lane PAR-1): quote `y`/`n`/`1e3` scalars in every published artifact once,
report the count, then `load = hermes_yaml.safe_load` and the module's resolver deletes.

## 3. Grouping

Seven upstream PRs, each a branch `up/<name>` from `upstream/main` with its body at
`X:/wt/_holds/pr-bodies/<name>.md` (the `.gitattributes` row's pattern). PRs are HELD (owner
2026-09-24); the exec lane for a PR runs after its merge, and the fork does not pre-adopt through a
private name.

| PR | rows | files | test (upstream) |
|---|---|---|---|
| `store-home-override` | 1, 2 | `hermes_constants.py`, `hermes_cli/auth.py`, `tools/async_delegation.py` | `get_store_home("auth")` follows its override while `get_hermes_home()` does not move |
| `persisted-row-hooks` | 4, 5, 6 | `agent/session_persistence.py`, `agent/turn_context.py`, `tools/mcp_tool_config.py`, `hermes_cli/plugins.py` | each hook observed once per row/server/child; `HERMES_HOME` present in a stdio child's env under a redirected `HOME`; `reuse_current_user_message` appends nothing |
| `skills-extra-dirs` | 3 | `agent/skill_utils.py` | an `extra_dirs` skill is found, listed writable, excluded name skipped; lookup name posix on Windows |
| `tool-search-never-defer` | 7a, 7b | `tools/tool_search.py` | a plugin tool named in `never_defer` stays visible; describe present at N=0 deferred |
| `credential-pool-pick-and-rotate` | 8 | `agent/credential_pool.py` | existing pool suite unchanged (pure refactor) + one override test |
| `local-runtime-knobs` | 10, 11, 12 | `hermes_cli/local_runtime/{bootstrap,presets}.py` | each key observed at the supervisor / staged list / preset INI |
| `public-drain-fd` | 13 | `tools/environments/base_output.py` | `drain_fd` stops on `stop` with a live writer, on both platforms |

Exec lanes, sized by raw lines (fork lines touched; PR-gated lanes wait on the merge):

| lane | rows | gated on | raw lines |
|---|---|---|---|
| PAR-1 | 7c, 14 | nothing — runs now | `tool_search.py` legacy-arg lines (~25) + `yaml_io.py` (111) + migration script (~80) + artifacts under the realm publish roots + tests ≈ 0.4k |
| PAR-2 | 1, 2 | `store-home-override` | `profile_home.py` (314), `profile_context.py` (474), two diff rows, 5 tests ≈ 1.1k |
| PAR-3 | 4, 5, 6 | `persisted-row-hooks` | `native_persistence.py` (24), `mcp_environment.py` (64), `machine_roots.py` resolve half (~200), three diff rows, tests ≈ 0.9k |
| PAR-4 | 3, 7a, 7b | `skills-extra-dirs`, `tool-search-never-defer` | two diff rows (+126), plugin config seed, tests ≈ 0.6k |
| PAR-5 | 8, 13 | `credential-pool-pick-and-rotate`, `public-drain-fd` | `pool_rotation.py` (218), `subprocess_pumps.py` (226), one diff row, tests ≈ 0.7k |
| PAR-6 | 10, 11, 12 | `local-runtime-knobs` | `engine.py` (298), adapter config, tests ≈ 0.5k |

Row 9 has no lane: it closes when the launcher's install lands on pm bundles (delete
`resolve_managed_python`, `_detect_venv_dir`; `hermes update` is the proof).

## 4. Proofs and the `[up-fp]` arithmetic

Baseline (fixture, 2026-09-25): `files=178 deleted_lines=924 heavy=4`. Each landing appends one
`reasons` entry to `tests/fixtures/upstream_footprint.json` and lowers the three numbers to the
measured line; heavy stays 4 throughout (none of these rows is heavy).

| lane | killing mutation (apply, record the red, revert, paste into the commit) | `files` | `deleted_lines` |
|---|---|---|---|
| PAR-1 | migration: leave one `y:` unquoted → `test_flow_graph_publish.py` reds on `hermes_yaml.safe_load`; 7c: pass `{"name": "x"}` → the describe call must answer `not_found`/error, not a hit | flat | flat, or −k if the legacy lines sat inside the row's 16 (measure) |
| PAR-2 | bind store `"auth"` to the profile home instead of the head → `tests/agent_runtime/test_persona_head_auth_store.py` reds; bind `"background_work"` to ambient → `test_running_work.py` reds | 178 → 176 | 924 → 922 |
| PAR-3 | unregister `transform_persisted_row` → `test_persona_chat_wire_boundary.py` reds; drop the platform gate in `transform_mcp_servers` → `test_machine_roots_seams.py` reds; pass `reuse_current_user_message=False` from the persona turn → a duplicate user row | 176 → 173 | 922 → 911 |
| PAR-4 | remove the config seed → `test_skill_utils_downstream.py` reds; empty `never_defer` → `test_tool_visibility.py` reds | 173 → 171 | 911 → 891 |
| PAR-5 | mixin overrides `_select_unlocked` again (old seam) → `test_credential_pool_rotation_cursor.py` reds on the persisted `priority`; pass `stop=None` from `_Pump` → `test_agent_chat_dispatch.py` forced-release case hangs (bounded by its timeout) | flat (row becomes +2/-0 hook) | 891 → 873 |
| PAR-6 | drop `executable_path` from the supervisor call → `test_local_llama_adapter.py` reds | flat | flat |

End state when all seven merge: `files=171 deleted_lines=873 heavy=4` (upper bound; PAR-1 may
lower `deleted_lines`). Rows 9 and 14 leave no diff-row change; row 14's shadow-table line deletes
at PAR-1, row 9's at the launcher's pm-bundle landing.

## 5. Open questions, each decided

1. **PRs are paused (owner 2026-09-24).** Default: write all seven as held branches + bodies now
   (one Haiku lane, mechanical); exec lanes PAR-2..6 wait on the merge. Nothing pre-adopts a
   private upstream name to get ahead of a merge.
2. **Who calls `tool_describe` with a single `name`?** Default: PAR-1 greps the launcher
   (`EterniaLauncher/lib/features/mission_control/`) before deleting; a hit files one row in the
   launcher's `mission-control-queue.md` and PAR-1 still deletes (old-schema rule: delete at the
   chokepoint and report, never a tolerant keep-alive).
3. **Pool residual after PR-E (MRO line + import).** Default: stays a `hook` row at +2/-0; a
   strategy-registry PR is not filed — it is not ≤10 lines and the owner paused PRs.
4. **Pumps: upstream's post-exit idle bound ends a drain ~300 ms after the child exits; the fork's
   ended only on release.** Default: accept upstream's bound. The Windows hang was a BLOCKING
   `os.read`, which `PeekNamedPipe` polling retires; release still forces the stop.
5. **Migration scope for row 14.** Default: every artifact under the realm publish roots plus the
   launcher QA templates `test_launcher_qa_template_drift.py` reads; one run, a printed count, no
   tolerant read afterwards.
6. **Base drift.** `upstream/main` is 165 commits past the ledger base. Default: PR branches cut
   from `upstream/main`; every `[up-fp]` figure above is against the ledger base until the next
   merge lane runs `--refresh-manifest` — these lanes never do.
7. **7b declined upstream.** Default: 7b becomes CARRY with the retiring event "upstream ships
   always-on describe"; 7a still merges alone and PAR-4 lands the `never_defer` half.
