# Layout sheet — `hermes_cli/harness.py` (lane H2)

Base: `main` @ `78501db796` · 6,737 raw / 5,240 code / 164 top-level defs · longest `populate_parser` 1,768 (286–2053) · `str==` 28 · `isinstance` 11 · owner doc `docs/agent-runtime-harness/01-system-architecture.md`. Waits on H1 (`_load_command_parts` + `exec` at 6730–6737; 263 test patches on `harness.<name>`). Entry since seam Stage 1: `plugins/eternia-harness/__init__.py::_setup_harness_parser` → `build_cli_parser` (2146) → `populate_parser`; `harness_command` (2056) is the argparse `func=` root; `_harness_entry`/`_install_harness_entries` (2107–2143) are the plugin's entries. This file is **upstream-directory, fork-only**: nothing new goes at `hermes_cli/` top level; every target below is under `hermes_cli/harness_parts/`.

## 1. Section map → target modules

| lines | what is there | → module | layer |
|---|---|---|---|
| 1–188 | imports (14 `agent.charsheet`, 10 `agent.pet`, 6 `hermes_cli.auth`, 5 `agent.account_usage`, 4 `agent.credential_pool`, …), constants | `harness.py` head (≤ 60) + `harness_parts/_upstream_doors.py` (§6) | wiring |
| 189–279 | `_add_stage42_global_args` (82), `_add_coordinator_permission_args` | `harness_parts/parser/common_args.py` (~95) | wiring |
| 282–2058 | `build_parser` (2, DELETE §5), `populate_parser` (1,768), `harness_command` (3) | `harness_parts/parser/__init__.py`: `populate_parser` ≤ 40 lines iterating `PARSER_FAMILIES`; one `add_<family>(subs)` per family (§2) | wiring |
| 2066–2151 | `_capture_core_cache_fingerprint_home` (39), `_harness_entry`, `_install_harness_entries`, `build_cli_parser` | `harness.py` head — the plugin door stays in the entry file | wiring |
| 2154–2221, 2521–2562 | `_machine_root_config_paths`, `_cmd_roots_{list,set,unset,migrate}` | `harness_parts/roots_commands.py` (~120) | lanes |
| 2248–2462 | `_gateway_install_row` (76), `_gateway_identity_error`, `_cmd_gateway_id`, `_cmd_gateway_rename` (70) | `harness_parts/gateway_identity_commands.py` (~200) | lanes |
| 2473–2518 | eight `_cmd_gateway_*` 4-line trampolines onto `gateway_commands.cmd_*` | DELETE (§5); parser `func=` points at `gateway_commands.cmd_*` | — |
| 2565–2582 | `_cmd_persona_instance_detail` | `harness_parts/persona/inspect_commands.py` (H3's module; H2 lands it in `runtime_commands.py` if H3 has not landed — tree wins) | lanes |
| 2585–2674, 6521–6562 | `_cmd_skills_{catalog,publishable,inbox}`, `_rel_to_shared_skills`, `_cmd_skills_link_external`, `_cmd_skills_inventory` | `harness_parts/skills_commands.py` (~180) | lanes |
| 2677–3299 | `_resolve_promotion_source` (64), `_PromotionSourceError`, `_cmd_skills_promote` (96), `_canonical_packages_covered`, `_realm_publishes_skill`, `_prune_inbox_packages`, `_archive_content_hint` (53), `_cmd_skills_delete` (212), `_cmd_skills_restore` (74) | `harness_parts/skills_promotion_commands.py` (~620); `_cmd_skills_delete` → `SkillDelete` steps (resolve, guard, archive, prune, report) ≤ 150 each (rule 17) | lanes |
| 3302–3324 | `_cmd_prompt_context_show` | `harness_parts/prompt_context_commands.py` (~25) — or joins `runtime_commands.py`; tree wins | lanes |
| 3336–3566 | `_cmd_workspace_*` ×10, `_known_persona_ids`, `_validate_roster_persona`, `_workspace_agent_sync_warnings` | `harness_parts/workspace_commands.py` (~230) | lanes |
| 3574–3995 | `_cmd_realm_*` ×17, `_realm_sync_credential`, `_realm_sync_subtree`, `_realm_{skill,agent}_selection_envelope` | `harness_parts/realm_commands.py` (~420) | lanes |
| 3998–4163 | `_cmd_agent_list` (61), `_agent_definition_row` (65), `_cmd_agent_set_profile` | `harness_parts/agent_commands.py` (~170) | lanes |
| 4166–4406 | `_cmd_pets_{gallery,install,sprite,thumb}`, `_installed_pet_gallery_row`, `_pet_sheet_revision` (fold, §3), `_pet_row_frame_counts`, `_pet_state_rows`, `_pet_sprite_payload_for_launcher` | `harness_parts/pets_commands.py` (~240) | lanes |
| 4418–5538 | the characters lane: `_characters_*` helpers ×24, `_cmd_characters_*` ×20, `_CHARACTERS_AUTO_STEPS` (5201) + `_characters_auto_*` ×4 + `_cmd_characters_auto` (73) + `_characters_auto_steps` (73) | `harness_parts/characters/{commands,steps,auto,payloads}.py` (~1,100 total, each ≤ 350) | lanes |
| 5541–5580 | `_cmd_init`, `_cmd_install_harness_skills` | `harness_parts/runtime_commands.py` (joins file 52's lane) | lanes |
| 5583–5855 | `_credential_health` (40), `_credential_token_preview`, `_record_visibility_block`, `_provider_visibility_catalog`, `build_provider_visibility` (74), `_provider_visibility_{environment,api_keys,auth_logins}`, `_cmd_providers` | `harness_parts/provider_visibility.py` (~280) | policy |
| 5866–6518 | the usage lane: `_usage_provider_label`, `_usage_iso`, `_resolve_active_provider_id` (25 test patches), `_codex_usage_login_detected`, `_openrouter_usage_login_detected`, `_usage_lane_detected` (32), `UnknownUsageLaneError`, `_fetch_usage_lane` (46), `_usage_failure_reason`, `_serialize_usage_{window,lane}`, `_unavailable_usage_lane`, `_usage_lane_scope`, `_detect_usage_candidates`, `_fetch_usage_lanes`, `_stamp_usage_degraded`, `_usage_lanes_suppressed`, `build_account_usage` (51), `_render_account_usage_human`, `_parse_usage_iso`, `_empty_usage_envelope`, `_emit_usage_json`, `_cmd_usage` | `harness_parts/usage/{lanes,detect,serialize,commands}.py` (~660 total) — the provider ladder → table (§2) | policy + lanes |
| 6565–6713 | `_cmd_doctor` (149) | `harness_parts/doctor_commands.py` (~150) | lanes |
| 6716–6727 | `_cmd_serve`, `_cmd_serve_connect` trampolines | `harness.py` head (they are the two names the parser binds before `serve/` imports) | wiring |
| 6730–6737 | `_load_command_parts` + `exec` | DELETED by H1 | — |

Result: `harness.py` ≤ 150 raw (imports, plugin door, `harness_command`, the two serve trampolines), 15 new modules + the `parser/` and `characters/` and `usage/` packages; `runtime_commands.py` (945 raw today) absorbs `_cmd_init`/`_cmd_install_harness_skills` and is split in the same lane into `runtime_commands.py` + `work_commands.py` + `verify_commands.py` (program §3.2). The 09-21 H2 table stands; this sheet adds `agent_commands.py`, `pets_commands.py`, the `usage/` and `characters/` packages (the 09-21 table put pets and usage under `characters_commands.py` and the head — 1,100 + 660 lines cannot).

## 2. Routing sites → dispatch tables (the CHANGE commit)

| site (base line) | shape today | replacement | killing mutation |
|---|---|---|---|
| `populate_parser` 286–2053 | one 1,768-line function adding 34 families in sequence (`init` 292 · `roots` 296 · `gateway` 337 · `workspace` 511 · `realm` 588 · `flow` 758 · `checkpoint` 774 · `skills` 803 · `prompt_context` 892 · `board` 905 · `office` 983 · `level` 1058 · `map` 1091 · `persona` 1128 · `mission-chat` 1426 · `status` 1565 · `providers` 1577 · `usage` 1584 · `doctor` 1602 · `health` 1613 · `verify` 1617 · `config` 1623 · `migrate` 1629 · `observe` 1634 · `contracts` 1638 · `worktree` 1644 · `persona-instance` 1664 · `agent` 1722 · `install-harness-skills` 1796 · `snapshot` 1807 · `stream` 1810 · `serve` 1838 · `work` 1887 · `pets` 1917 · `characters` 1947) | `PARSER_FAMILIES: tuple[Callable[[subs], None], ...]` in `parser/__init__.py`, one `add_<family>(subs)` per family cut at the `subs.add_parser(` boundaries above (each ≤ 300; `persona` 1128–1425 and `mission-chat` 1426–1564 are the two that need a second cut at their own `add_subparsers`); `populate_parser` iterates the tuple | remove one family from the tuple → `tests/hermes_cli/test_cli_contract_dump.py` reds on the fixture diff (the contract fixture is the whole proof: byte-identical after the MOVE, and the table's ORDER is the fixture's order) |
| `_usage_lane_detected` 5965–5996 + `_fetch_usage_lane` 6019–6064 | `if provider_id == "openai-codex"` 5983 · `"anthropic"` 5985 · `"openrouter"` 5989 · `"nous"` 5991, then the SAME four again at 6046–6060 — two ladders over one vocabulary | `USAGE_LANES: Mapping[str, UsageLane]` where `UsageLane` is a small strategy object (`detect`, `fetch`, `label`); `_detect_usage_candidates` iterates the table; `UnknownUsageLaneError` is raised by the table lookup | swap `openrouter` and `nous` → `tests/hermes_cli/test_harness_usage*.py` reds on the openrouter fixture |
| `_characters_auto_plan` 5234 / `_characters_auto_steps` 5368 (chains at 5257 6 arms, 5398 4 arms — the two biggest `elif` chains in the file) | `for step in _CHARACTERS_AUTO_STEPS: if step == "turnaround" … elif "approve-direction" … elif "rows" … elif "compose"` mapping a step NAME to `_characters_step_*` twice (plan and run) | `CHARACTER_STEPS: Mapping[str, CharacterStep]` with `CharacterStep(name, requires_stage, run)`; `_CHARACTERS_AUTO_STEPS` becomes `tuple(CHARACTER_STEPS)` and the `--through` `choices=` reads it (2034) — one vocabulary, three readers become one | swap `rows` and `compose` → `tests/hermes_cli/test_characters_auto*.py` reds (compose before rows refuses) |
| `_cmd_doctor` 6565–6713 | two guard ladders on `args.fix/dry_run/yes` (6567, 6580) then the report assembly | `DoctorMode` Enum (`report`, `dry_run`, `fix`) resolved once by a table on `(fix, dry_run, yes)`; the confirmation refusal is one row | make `fix+no yes` resolve to `fix` → `test_harness_doctor*` confirmation test reds |
| `_resolve_promotion_source` 2677 (chain at 2718: `(candidate / "SKILL.md").is_file()` …) | filesystem shape probing in sequence | `PromotionSourceKind` Enum + `_SOURCE_PROBES: tuple[(kind, predicate)]` walked in order | reorder the two probes → `test_skills_promote*` reds on the directory case |
| `_cmd_realm_skills_set` 3886 / `_cmd_realm_agents_set` 3941 (chains 3902, 3957) | `if args.publish_all … elif args.publish_workspace … else` selecting `(mode, selection)` twice | `_SELECTION_MODES` table shared by both commands (`realm_commands.selection_from_args`) | swap `all`/`workspace` → `test_realm_skills_set*` reds |

Density goal at review: `str==` 28 → ≤ 6.

## 3. Helpers that unify

| here | duplicate of | authority |
|---|---|---|
| `_pet_sheet_revision` 4314 | `agent/charsheet/draft._sheet_revision` (09-21 §5) | `agent/charsheet/revisions.py` (C1's authority; H2 folds toward it — Q2 decides whether C1 runs; if not, `pets_commands.py` imports `draft._sheet_revision`) |
| `_usage_iso` 5876 / `_parse_usage_iso` 6437 | `serde` has no ISO helper; `serve_registry._now_iso` × 4 is the writing side | `agent_runtime/clock.{now_iso,parse_iso}` |
| `_characters_error` 4418 / `_gateway_identity_error` 2349 / `_set_model_error_payload` (H3) | one refusal-payload shape, three spellings | `refusals.refusal` (R4 creates; H2 folds its two) |
| `_known_persona_ids` 3474 / `_validate_roster_persona` 3490 | `persona_assignments` and `agent_create` both resolve persona ids | `harness_parts/_common.persona_ids(cfg)` (H1's leaf) |
| the 14 `_characters_*` payload builders | one `CharactersPayload` shape emitted by `_characters_emit` 4486 | `characters/payloads.py` |

## 4. Behaviour moves and their killing mutations (beyond §2)

- `harness_command` 2056 stays the `func=` root; **mutation:** make it return 0 on an unknown subcommand → `test_cli_contract_dump`'s "no command" case reds.
- The eight `_cmd_gateway_*` trampolines deleted and `func=` retargeted: **mutation:** point `gateway peers join` at `cmd_gateway_peers_list` → `test_gateway_peers_join*` reds.
- `_resolve_active_provider_id` (25 test patches) keeps its name and module path `harness_parts/usage/detect.py`; the patch retarget script rewrites the 25.

## 5. Dead code found while reading (rows filed in the dead-code queue)

| symbol | lines | evidence |
|---|---|---|
| `build_parser` 282–283 | 2 | pre-plugin entry; callers `scripts/dump_cli_contract.py` (as `build_harness_parser`) and `serve.py::_build_harness_parser` — both retarget to `populate_parser`; 70 test files name `build_parser` but 68 are upstream parsers of the same name (the census's substring inflation), the two fork ones retarget |
| `_cmd_gateway_{pair,introduce,devices_list,devices_revoke,peers_pair,peers_join,peers_list,peers_revoke}` 2473–2518 | 32 | each is `return gateway_commands.cmd_*(args)`; the only reader is the parser's `set_defaults(func=…)` |
| `_cmd_persona_instance_archive` (persona_commands 5591) | 2 | see the H3 sheet; the parser at 1335 binds it |
| `_capture_core_cache_fingerprint_home` 2066–2104 | 39 | called once at 2119 inside `_harness_entry`; one test. NOT dead — but it is the `core-cache-home-capture-timing.md` instrument living in the CLI entry; rowed as "move to `core_cache` (R3), not the entry file" |

## 6. Doors (upstream imports — the largest surface of the three sheets)

| import | count | class | door |
|---|--:|---|---|
| `agent.charsheet.*`, `agent.pet.*` | 14 + 10 | fork-only modules in an upstream directory (C1) | not doors; they move with C1 or stay as is (Q2) |
| `hermes_cli.auth`, `hermes_cli.auth_commands`, `hermes_cli.status`, `hermes_cli.status_auth` | 6 + 2 + 2 + 1 | FIRST — public credential/status reads | through `_upstream_doors.py`: `auth_state()`, `status_blocks()` |
| `agent.credential_pool`, `agent.account_usage` | 4 + 5 | FIRST — public | `_upstream_doors.credential_pool()`, `.account_usage()` |
| `hermes_cli.runtime_provider`, `profiles`, `provider_catalog`, `nous_account`, `models`, `flag_binding` | 2 + 2 + 1 + 1 + 1 + 1 | FIRST — public | `_upstream_doors.*` |

No `_private` upstream name is imported (W0-G6's arm is green on this file today); no widening PR is needed for H2.

## 7. Commits

1. **MOVE** `refactor(harness): harness.py → harness_parts/{parser,roots,gateway_identity,skills,skills_promotion,workspace,realm,agent,pets,characters,provider_visibility,usage,doctor} (head ≤ 150)` — spans byte-identical; contract fixture byte-identical; the 67 own-name patches retargeted by script.
2. **CHANGE** `refactor(harness): PARSER_FAMILIES, USAGE_LANES, CHARACTER_STEPS, DoctorMode; trampolines and build_parser deleted; helpers folded` — §2–§4 with each red pasted; `[ds-size]` 61 → 59 (this file and `runtime_commands.py`).
