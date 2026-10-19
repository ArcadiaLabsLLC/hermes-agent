# 11 — Gate directory

**Every check this repository has, what it guarantees, and what runs it.** There is no
push gate (`Harness_Brain/30 — Decisions/0002`): a gate is a test or a script someone
runs. How and when to run them is `Harness_Brain/50 — Agent Handoffs/Running the
tests.md`; this page is the list. Owner-requested 2026-10-18, a navigation exception
like [10 — Command directory](10-command-directory.md).

This page cannot go stale silently: `tests/tooling/test_gate_directory_current.py` reds
when a path named here no longer exists, when a gate in the enumerated places
(`tests/tooling/test_*.py`, `scripts/check*`, `scripts/*_gate.py`,
`scripts/dump_*_contract.py`, and every test file carrying `pytest.mark.gate`) is
missing from it, or when a test file named here does not carry the mark. A fork gate
file says `pytestmark = pytest.mark.gate` (in a list with any other module mark); an
upstream test file takes no edit, so its mark is a file row in
`tests/_downstream/id_markers/fork_marks.py`. A new gate anywhere under `tests/` joins
this page by its mark, not by the directory it sits in.

Kinds: **fence** (a NEGATIVE guarantee, a source walk: "this is never written"),
**ratchet** (a count or list that may only shrink), **fresh** (a generated artifact
matches its generator), **runtime** (builds the thing and reads it), **claims** (a doc
or registry entry names something real).

## Runs and scopes

| run | command | role |
| --- | --- | --- |
| landing gate | `scripts/run_tests_bundled.sh tests` (`--scope fork`) | every fork test plus the upstream tests the change reaches; once per batch |
| release merge | `scripts/run_tests_bundled.sh --since-merge <merge> tests` | what the merge produced |
| dev loop | `scripts/run_tests_bundled.sh --affected` | never a gate; skips whole-tree source walkers |
| one red | `scripts/run_tests_bundled.sh --confirm-red <node>` | proves a red pre-existing |
| measurement | `scripts/run_tests_bundled.sh --scope features` | quiet-box diagnosis, never a gate (ADR 0016) |
| runner store | `scripts/run_tests_bundled_gate.py` | the gate store (green cache, durations, deps) the runner reads |
| CI | `.github/workflows/fork-gates.yml` | selected mutation claims plus the tombstone and docket gates |

## Structure (the god-file program and the fork's layering)

| gate | kind | guarantees |
| --- | --- | --- |
| `tests/tooling/test_downstream_size_ceiling.py` | ratchet | every fork production file ≤ 800 code lines, or grandfathered and shrinking |
| `tests/tooling/test_function_legibility_floor.py` | ratchet | no fork function over 150 lines or nested deeper than 4, beyond a shrinking list |
| `tests/tooling/test_fork_import_layers.py` | fence | the fork's import graph points down its layers (models → policy → stores → lanes → wiring) |
| `tests/tooling/test_no_ladder_routing.py` | fence | routing is data: no new `if x == "…"` / `isinstance` ladder |
| `tests/tooling/test_harness_namespace_is_thin.py` | fence | `hermes_cli.harness` has no exec'd parts and no re-export shims |
| `tests/tooling/test_refactor_stays_downstream.py` | fence | a `refactor(` commit never touches an upstream file |
| `tests/tooling/test_refactor_reach_census.py` | runtime | the reach census's static pre-filter strikes rows with a production reference |
| `tests/tooling/test_process_globals_declared.py` | ratchet | process-global state in fork modules is declared with its reset |
| `tests/tooling/test_function_local_imports_resolve.py` | fence | a deferred `from <fork module> import <name>` names something bound |
| `tests/tooling/test_seam_local_imports_resolve.py` | fence | a deferred fork import inside an upstream file resolves |
| `tests/tooling/test_plugin_imports_public_surface.py` | fence | `plugins/eternia-harness/` never imports the fork's edits to upstream files |
| `tests/tooling/test_fork_modules_do_not_import_pyyaml.py` | fence | YAML goes through `agent_runtime.yaml_io`, never `yaml` |
| `tests/tooling/test_no_secret_word_decisions.py` | fence | no "is this a secret?" decision by looking for a word |
| `tests/tooling/test_no_launcher_entry_id_literals.py` | fence | no hermes code names a Launcher entry id |
| `tests/tooling/test_no_launcher_tool_name_literals.py` | fence | no hermes code names a Launcher tool (the underscore spelling), by the vendored catalog |
| `tests/agent_runtime/test_launcher_catalog_fixture_parses.py` | runtime | every vendored Launcher catalog entry parses as the wire does; names follow the id rule |
| `tests/tooling/test_no_silent_package_patches.py` | fence | a monkeypatch on a package attribute reaches a reader |
| `tests/agent_runtime/test_duplicate_helper_bodies.py` | ratchet | one authority per helper body |
| `tests/agent_runtime/test_tombstone_registry.py` | fence | deleted symbols stay deleted (census ≥ 703; never grep-count) |
| `tests/agent_runtime/test_s41_dead_import_bindings.py` | fence | no import binding nothing reads |
| `tests/hermes_cli/test_declared_cli_cache_superset.py` | runtime | the declared-command cache's fingerprint stats every manifest the upstream plugin walk parses |

## One authority per value

| gate | kind | guarantees |
| --- | --- | --- |
| `tests/test_no_frozen_hermes_home.py` | ratchet | no new module-level value frozen against `HERMES_HOME` |
| `tests/agent_runtime/test_hermes_home_env_gate.py` | fence | only named authorities read `HERMES_HOME` from the environment |
| `tests/agent_runtime/test_skills_root_call_time_gate.py` | runtime | the skills root resolves at call time |
| `tests/agent_runtime/test_snapshot_contract_version_authority.py` | fence | one snapshot contract-version literal |
| `tests/agent_runtime/test_s55_registered_events_have_emitters.py` | fence | every registered event type has an emitter |
| `tests/agent_runtime/test_s56_runtime_config_reader_gate.py` | fence | every `RuntimeConfig` field has a production reader or a reasoned report-only entry |
| `tests/agent_runtime/test_no_kanban_dependency.py` | fence | only the native Work adapter imports public task APIs |
| `tests/agent_runtime/test_office_class_key_one_fence.py` | fence | one class-key guard, at the store's write chokepoint |
| `tests/agent_runtime/test_persona_roster_bypass_contract.py` | fence | the roster-check bypass is fenced by enumeration |
| `tests/test_path_identity_gate.py` | fence | no guard under `tools/` compares raw path strings |
| `tests/hermes_cli/test_config_read_guard_downstream.py` | fence | the fork's half of upstream's raw `config.yaml` read guard |
| `tests/hermes_cli/test_harness_flag_and_control_reachability.py` | fence | nothing on the harness surface is advertised and unreachable |
| `tests/hermes_cli/test_harness_json_root_observability.py` | fence | every `--json` harness verb says which root answered |
| `tests/hermes_cli/test_error_exit_code_producers.py` | fence | every exit code in the taxonomy has a producer |
| `tests/hermes_cli/test_flag_binding_boundary.py` | fence | an absent flag is not an empty one |

## Generated artifacts are fresh

| gate | kind | guarantees |
| --- | --- | --- |
| `scripts/dump_cli_contract.py --check` ↔ `tests/hermes_cli/test_cli_contract_dump.py` | fresh | the launcher's argv contract |
| `scripts/dump_payload_contract.py --check` ↔ `tests/hermes_cli/test_payload_contract_dump.py` | fresh | the launcher's character-payload keys |
| `scripts/dump_toolset_manifest.py` ↔ `tests/tools/test_toolset_manifest.py` | fresh | `tools/toolset_manifest.json` |
| `tests/agent_runtime/test_harness_tool_inventory.py` | fresh | the manual's in-turn tool inventory |
| `scripts/emit_harness_command_directory.py` ↔ `tests/scripts/test_emit_harness_command_directory.py` | fresh | `reference/harness-commands.md` |
| `tests/agent_runtime/test_harness_core_ratchet.py` | ratchet | 44 tools, 0 withheld, 0 requirement failures per persona |

## Docs, claims and registries name real things

| gate | kind | guarantees |
| --- | --- | --- |
| `scripts/doc_cite_adjacency.py` ↔ `tests/scripts/test_doc_cite_adjacency.py` | claims | a canon cite lands on the thing the sentence names (ruled scope `--exclude archive --exclude planned`) |
| `tests/tooling/test_work_queue_row_grammar.py` | claims | every `type: queue` row under `Harness_Brain/` is in the launcher's row grammar (ID, one line, exactly one status, valid BLOCKED reason) so the Mission Control board can read it |
| `scripts/work_row.py` ↔ `tests/tooling/test_work_row_script.py` | runtime | a session's by-ID row op commits by pathspec and pushes; a non-fast-forward exits 3 and touches nothing else; it never fetches, resets, stashes, pulls, merges or rebases |
| `tests/test_docket_stage_claims.py` | claims | a plan that says EXECUTED names a SHA in this history |
| `tests/test_coverage_claims_resolve.py` | claims | a coverage claim names a test that exists |
| `tests/scripts/test_mutation_claims_still_anchor.py` | claims | every registered mutation claim still anchors |
| `tests/tooling/test_upstream_reds_rows_resolve.py` | claims | every upstream-red marker row names an upstream test that exists |
| `tests/tooling/test_gate_directory_current.py` | claims | this page |
| `tests/test_byte_pinned_fixture_families.py` | fence | a `MANIFEST.sha256` fixture family is pinned `-text` |
| `tests/test_line_endings.py` | ratchet | no tracked text blob carries a CR; the count only falls |
| `tests/test_no_source_grep_assertions.py` | ratchet | the fork's source-grep test class stops growing |
| `tests/agent_runtime/test_no_midtest_monkeypatch_undo.py` | fence | no test calls `monkeypatch.undo()` |

## The suite and its runner

| gate | kind | guarantees |
| --- | --- | --- |
| `tests/scripts/test_upstream_skip_list.py` | claims | the skip list names upstream files only, unused rows cite ADR 0015, and the runner skips exactly them |
| `tests/test_no_shadowed_test_definitions_downstream.py` | fence | no test module defines one name twice in one scope (upstream's walk, through the shared parse) |
| `tests/tooling/test_session_chain_contract.py` | runtime | one test per promise the session chain (conftests, `tests/_downstream/`, bundle plugins) makes |
| `tests/tooling/test_registry_write_fence.py` | runtime | the registry-write fence is live in a test process |
| `tests/tooling/test_registry_write_fence_children.py` | runtime | a child a test spawns cannot write the registry either |
| `tests/tooling/test_registry_path_fence.py` | runtime | only the installer-owned root may add its `bin` to the user PATH |
| `tests/tooling/test_tool_registry_scope.py` | runtime | the per-test tool-registry scope restores registrations |
| `tests/tooling/test_post_merge_hook_worktree.py` | runtime | `.githooks/post-merge` repairs the install only from the primary checkout |
| `scripts/check_test_env_drift.py` ↔ `tests/scripts/test_check_test_env_drift.py` | runtime | the shared test venv matches the live install's pins |

## Upstream footprint and merges

| gate | kind | guarantees |
| --- | --- | --- |
| `scripts/upstream_footprint.py` ↔ `tests/scripts/test_upstream_footprint.py` | ratchet | the fork's footprint in upstream files only goes down; every raise cites an owner ruling |
| `scripts/upstream_sync_gate.py` ↔ `tests/scripts/test_upstream_sync_gate.py` | runtime | the weekly merge's sync gate |
| `scripts/check_carried_prs.py` ↔ `tests/scripts/test_check_carried_prs_downstream.py` | runtime | carried upstream-PR hunks have not drifted |
| `scripts/upstream_retirement_scan.py` ↔ `tests/tooling/test_upstream_retirement_scan.py` | fence | no fork import or patch target names an upstream module or name the merged release tag (the manifest's base) lacks; the scan's other arms (`hunks`, `twins`, `carried`) report only |

## The mutation gate

| gate | kind | guarantees |
| --- | --- | --- |
| `scripts/changed_line_mutation_check.py` ↔ `tests/scripts/test_changed_line_mutation_check.py` | runtime | every claimed test line still kills its mutation (`--list --base origin/main` is safe unattended; a real run takes `.mutation_gate.lock`) |

## Phone bundle

| gate | kind | guarantees |
| --- | --- | --- |
| `scripts/bundle_profile_gate.py` ↔ `tests/scripts/test_bundle_profile_gate.py` | fence | what the phone profile refuses in kept source and shipped distributions |
| `tests/agent/transports/test_sdk_free_phone_imports.py` | runtime | the phone's provider path loads with no provider SDK or pydantic |
| `scripts/bundle_vuln_scan.py` ↔ `tests/scripts/test_bundle_vuln_scan.py` | runtime | OSV ranges, waivers and the exit code |

## Lint checkers (`scripts/check` runs the blocking ones)

`scripts/check` runs every blocking lint CI runs, with the same pinned tools: the
workflow guards, ruff and the `scripts/code_health` ratchet, plus the case-collision,
lazy-deps, profile-archive and blob-size guards (`tests/scripts/test_code_health_cli.py`).

| checker | test | guarantees |
| --- | --- | --- |
| `scripts/check-case-collisions.py` | `tests/scripts/test_case_collision_check.py` | no two tracked paths differ only by case |
| `scripts/check-windows-footguns.py` | `tests/scripts/test_footgun_subprocess_encoding.py` | Windows footguns (subprocess encoding and others) |
| `scripts/check_bash_shebangs.py` | `tests/scripts/test_bash_shebangs.py` | tracked scripts and embedded payloads carry a valid shebang |
| `scripts/check_config_yaml_writers.py` | `tests/hermes_cli/test_config_yaml_comment_preservation.py` | `config.yaml` writers preserve comments |
| `scripts/check_no_tmp_literals.py` | `tests/scripts/test_check_no_tmp_literals.py` | no literal `/tmp` paths |
| `scripts/check_subprocess_stdin.py` | `tests/tools/test_subprocess_stdin_guard.py` | TUI-context subprocess calls pass `stdin=` |
| `scripts/check_profile_scope_patterns.py` | `tests/scripts/test_check_profile_scope_patterns.py` | advisory: a child env built from `os.environ` |
| — | `tests/scripts/test_no_machine_paths_in_fork_scripts.py` | fork scripts never hard-code one machine's paths |

## Cost

Measured from the gate store, 2026-10-18 (`.pytest_cache/hermes_gate/durations.json`,
seconds at `-j 8`): the gates add about 360 s of work to a cold landing gate (~45 s of
wall time). Eight whole-tree walkers are three quarters of it. They read and parse
through one shared cache, `scripts/source_cache.py` (one read and one parse per file
version per process; a tree is kept only by a walker that comes back to it, because a
process holding trees pays for them on every garbage collection). Alone, before → after
(wall seconds, one process each, 2026-10-18, a busy box): `test_upstream_skip_list`
64.3 → 64.5 (runner discovery, no parse), `test_s55_registered_events_have_emitters`
30.7 → 27.7, `test_fork_import_layers` 32.0 → 31.4, `test_no_ladder_routing`
18.6 → 19.3, `test_coverage_claims_resolve` 21.6 → 21.6, `test_no_frozen_hermes_home`
17.4 → 9.1 (a subprocess import probe, no parse; noise), `test_no_silent_package_patches`
17.6 → 16.0, upstream's shadow walk 19.7 → 11.4 (run by
`tests/test_no_shadowed_test_definitions_downstream.py`, a `def`-name pre-filter). All
eight in one process: 217.5 → 173.9. Most of what remains is not parsing: the skip
list's discovery and each layer case's census are fork-hygiene rows.
`--affected` never selects a whole-tree walker.

## Positive controls

A new gate lands with its killing mutation named and its red recorded in the commit
body; a control that has not been run is a belief. Adding a gate means marking its file
`pytest.mark.gate` and adding its row here in the same commit —
`test_gate_directory_current.py` reds otherwise.
