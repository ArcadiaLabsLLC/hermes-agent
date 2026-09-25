# Layout sheet — `agent_runtime/config.py` (lane R3 · exec lane 2B-C)

Base: `main` @ `28012c8f8a` · 1,212 raw / 902 code / 43 top-level defs · longest `describe_runtime_default_authority` 72 · chains 0/0 · `str==` 5 · `isinstance` 33 · sha256 `0112a37640925c1ea740aec993c9dd425b05c158787c121492b7bfeda35c0682` · owner doc `docs/agent-runtime-harness/01-boot-and-config.md`. **57 production importers, 64 test files** — second only to `store` — across `agent_runtime/`, `hermes_cli/harness_parts/`, `gateway/`, `plugins/`, `tools/`. Importers take `AgentRuntimeConfig`, `load_agent_runtime_config`, `load_root_runtime_config`, `harness_root_config_path`, `ensure_persisted_personas` (25 production readers), `persona_records_from_config`, `chat_lane_restore_toolsets`, `mission_chat_workdir`, the `mission_chat_*` / `resolve_mission_chat_*` knobs, `describe_runtime_default_authority`, `scan_misplaced_root_only_keys`, `ROOT_ONLY_CONFIG_KEYS`, the bounds constants; tests import `_mcp_admission_config` ×3, `_mission_chat_config`, `_event_log_config`.

**Package `agent_runtime/config/`** (the flat siblings `runtime_config.py` — the dataclasses — and `dispatch_session_policy.py` stay where they are).

## 1. Skeleton (owner rulings 2026-09-25) — this text IS the package `__init__` map

```
agent_runtime/config/
  __init__.py          wiring  the map; re-exports every name in the header + the three test-pinned parsers
  schema.py            models  VOCABULARY/TABLE module (floor-exempt): AgentRuntimeConfig, the bounds constants, ROOT_ONLY_CONFIG_KEYS, TOOL_PERMISSION_DEFAULT_MODE_UNKNOWN
  sections.py          policy  the ten section parsers (read_model … terminal_envelope) + the coercers they share (_positive_int, _clamped_*, _optional_*, _string_list, _clean_config_str, _compaction_threshold_tokens); after the CHANGE, SECTION_PARSERS — the table the loader iterates
  loader.py            stores  load_agent_runtime_config / load_root_runtime_config / harness_root_config_path, the model-authority resolution, and the two provenance reports over the same files: describe_runtime_default_authority, scan_misplaced_root_only_keys
  knobs.py             policy  the per-turn ROOT-config readers: chat_lane_restore_toolsets, mission_chat_workdir, the mission_chat_* knobs and the two resolve_* precedence chokepoints
  persona_records.py   stores  persona records from config: persona_records_from_config, ensure_persisted_personas (the store merge), persona_skill_sources, the ${roots.…} expansion
```
Entry points and the modules an agent opens: `load_root_runtime_config` (every policy reader) → `loader.py` → `sections.py` — **2** (+ `schema`); a knob such as `mission_chat_default_max_seconds` (`chat_request`, `profile_runner`) → `knobs.py` → `loader.py` → `sections.py` — 3; `ensure_persisted_personas` (`persona_assignments`, `agent create`, `snapshot`) → `persona_records.py` → `loader.py` — 2; `harness doctor`'s two config sections → `loader.py` — 1. Layers: `knobs`, `persona_records` → `loader` → `sections` → `schema`; `persona_records` reaches `.store`, `.models`, `.machine_roots` lazily.

### 1.1 Section map → target modules (sizes are raw / est. code; the 100/300/500 bars are on code lines)

| lines | what is there | → module | raw / code | layer |
|---|---|---|---|---|
| 1–23 | imports, `logger` | `__init__.py` | ~30 / 20 | wiring |
| 25–69, 323–374, 1095–1098 | `MISSION_CHAT_*`, `MCP_ADMISSION_MAX_TOOL_CALLS_CEILING`, `AgentRuntimeConfig`, `ROOT_ONLY_CONFIG_KEYS`, `TOOL_PERMISSION_DEFAULT_MODE_UNKNOWN` | `config/schema.py` (`runtime_config.RuntimeConfig`) | ~110 / 45 | models |
| 72–78, 679–786, 697–1212 (the parsers), 1173–1212 | `_clean_config_str`, `_string_list`; `_read_model_config`, `_persona_chat_config`, `_mission_chat_config`, `_compaction_threshold_tokens`, `_event_log_config`, `_supervision_config`, `_coordinator_permission_config`, `_mcp_admission_config`, `_tool_permission_config`, `_terminal_envelope_config`; `_positive_int`, `_clamped_positive_int`, `_clamped_positive_float`, `_optional_int`, `_optional_float` | `config/sections.py` (`runtime_config`, `permission_modes`, `dispatch_session_policy`, `yaml`) | ~330 / 220 | policy |
| 80–320, 377–490 | `_top_level_model_authority`, `_resolve_default_authority`, `load_agent_runtime_config`, `_override_state`, `_RUNTIME_DEFAULT_PERSONA_ALIASES`, `describe_runtime_default_authority`, `harness_root_config_path`, `load_root_runtime_config`; `_profile_config_paths`, `_key_present`, `scan_misplaced_root_only_keys` | `config/loader.py` (`hermes_constants`, `parse_cache` lazy, `redaction_mode`) | ~360 / 230 | stores |
| 493–527, 811–1027 | `chat_lane_restore_toolsets`, `mission_chat_compaction_threshold_tokens`, `mission_chat_clarify_token_binding`, `mission_chat_dispatch_session_policy`, `mission_chat_default_max_seconds`, `resolve_mission_chat_max_seconds`, `mission_chat_dispatch_max_seconds`, `mission_chat_dispatch_max_concurrent`, `resolve_mission_chat_dispatch_max_seconds`, `mission_chat_workdir` | `config/knobs.py` | ~250 / 160 | policy |
| 530–676 | `_expand_machine_root_tokens`, `persona_records_from_config`, `persona_skill_sources`, `ensure_persisted_personas`, `_persona_from_overrides` | `config/persona_records.py` (`personas.PROFILE_ROLE_SENTINEL/validate_toolsets`; lazy `store`, `models`, `machine_roots`) | ~150 / 110 | stores |

Result: 5 modules + the map, none over 230 code lines. Edges: all down. No lazy cycle: `state_patches` and `terminal_envelope` import THIS package (lazily or at module level) and it never imports them; `store` is reached lazily from `persona_records` only.

## 2. Routing sites (rule 12)

| site (base line) | shape today | replacement | killing mutation |
|---|---|---|---|
| `load_agent_runtime_config` 131–139 | ten hand-written `x = _x_config(raw.get("x") or {})` calls, one per section | `sections.SECTION_PARSERS: Mapping[str, Callable[[dict], Any]]` (`{"read_model": _read_model_config, …}`) iterated once by the loader into the dataclass kwargs — rule 12's table replacing a by-hand list that grows with every section | drop the `mission_chat` entry → `tests/agent_runtime/test_config.py`'s mission_chat cases red (the dataclass default fills in silently — which is exactly why the table's keys must be pinned by a test that asserts every `RuntimeConfig` field with a parser has a table row) |
| `_override_state` 176–190 → `harness_doctor._model_authority_report` 477/481 | four free strings (`absent` / `override_only` / `redundant` / `shadowing`) returned here, compared as literals in ANOTHER file | constants `OVERRIDE_STATE_*` in `loader.py`; the doctor imports them (single-reader rule; **no Enum** — the words ride the doctor's JSON and the launcher's Model Authority panel; fork-hygiene row, lane R4 2026-09-25) | swap `redundant` and `shadowing` in `_override_state` → `test_harness_doctor.py`'s model-authority notice case reds |
| the six `mission_chat_<knob>(cfg)` readers 811–966 | one shape six times: `cfg` given → `getattr(cfg.mission_chat, name, default)`; else `load_root_runtime_config().mission_chat.<name>` with `except → default` | `_root_knob(cfg, name, coerce)` in `knobs.py`; each reader becomes 2 lines — a fold, behaviour-identical | make `_root_knob` ignore a supplied `cfg` → `test_config.py`'s explicit-config knob cases red |
| the `alice_supervisor ⇄ neko_supervisor` key lists 518–522, 1013–1017 | the alias spelled inline twice (and once more as `_RUNTIME_DEFAULT_PERSONA_ALIASES` 196; a fourth in `terminal_envelope._ROLE_ALIASES`) | `personas.persona_id_aliases(persona_id)` — the owner lane 2B-B's `terminal_envelope` sheet creates ("tree wins": whichever lands first); the three copies here fold onto it | drop the reverse direction from the owner → `test_config.py`'s alias case (`chat_lane_restore_toolsets` keyed on the other spelling) reds |

`isinstance` 33 → ≤ 25 at review (the `raw if isinstance(raw, dict) else {}` prologue repeated in nine parsers becomes one `_mapping(raw)` in `sections.py`).

## 3. Helper folds

| here | owner | verdict |
|---|---|---|
| `_positive_int(value, default)` 1173 | `serde.positive_int(value, *, default=)` — same signature; fixture row `_positive_int: config, mcp_admission` | FOLD **with one named difference**: the owner refuses `bool` (`True` is not a count); this one accepts it (`int(True) == 1`). A `lock_acquire_timeout_seconds: true` stanza would move from 1 s to the 15 s default — a typo class the owner is right about. Stated in the commit |
| `_optional_int` 1195 | `serde.positive_int(value)` (default `None`, bool refused, `> 0`) — identical; fixture row `_optional_int: config, tool_permissions` | FOLD; `tool_permissions` folds in its lane |
| `_optional_float` 1205 | `serde.positive_float` — identical except the owner also refuses `inf`/`nan` | FOLD; the difference is named (an `inf` budget was never a budget) |
| `_clean_config_str` 72 | fixture row `== mission_chat_outcome._text`; `serde.optional_text` coerces NON-strings (`str(value).strip()`), this refuses them | NOT a fold onto `optional_text`; both copies fold onto a new **`serde.optional_str(value)`** (str-only, strip, empty → `None`) — this lane creates it, `mission_chat_outcome` folds in its lane |
| `_string_list` 679 | — | stays in `sections.py` (YAML-list-or-scalar is a config-only shape) |
| `_clamped_positive_int/_float` 1181/1186 | — | stay (two-line bounds over the serde owners) |

## 4. Doors

`hermes_constants.get_config_path`, `get_default_hermes_root` (public), `yaml`. W0-G6 private rows: none. No widening. **The monkeypatch seams named `config`** in the test corpus (`setattr(config, "get_hermes_home"/"connectors_available"/"is_managed"/"read_user_config_raw"/"load_gateway_config"/"load_config", …)) are `hermes_cli.config` (upstream), not this module — the lane confirms each fixture's alias before retargeting anything; the three `_*_config` parser imports are the only test pins on this file.

## 5. Dead code found while reading

| symbol | evidence | verdict |
|---|---|---|
| `mission_chat_compaction_threshold_tokens` 811 | dead-code queue row (line 45): 0 hits; `git grep -n "mission_chat_compaction_threshold_tokens(" -- '*.py' ':!tests/'` → `agent_runtime/profile_runner/execute.py:507` | **REFUTED** — live; row deleted with the closing commit named |
| `persona_skill_sources` 614 | 1 production reader, 1 test | live |
| `TOOL_PERMISSION_DEFAULT_MODE_UNKNOWN` 1098, `MCP_ADMISSION_MAX_TOOL_CALLS_CEILING` 53 | read in-file (+1 test) | live |

Nothing to delete.

## 6. Positive controls (ruling Q6)

1. Before `SECTION_PARSERS`: a test that builds `AgentRuntimeConfig` from a YAML naming every section with a non-default value and asserts each field is non-default — the table's coverage pin (a missing row is silent otherwise).
2. Before `OVERRIDE_STATE_*`: `test_harness_doctor.py` must assert BOTH a `shadowing` notice and a `redundant` notice (two fixtures); if one is absent, add it (the swap is green against a one-state fixture).
3. `_root_knob`: `test_config.py` covers the explicit-`cfg` path for at least one knob; add the load-fault path (unreadable root → the built-in default, with the `logger.debug`) for one knob so the fold's `except` arm is exercised.

## 7. Commits and the MOVE hash proof (one MOVE, one CHANGE — program §3.1d)

1. **MOVE** `refactor(config): config.py → agent_runtime/config/ (5 modules)` — spans byte-identical with one sha256 row per §1.1 range (`git show 28012c8f8a:agent_runtime/config.py | sed -n 'A,Bp' | sha256sum`); `__init__` re-exports every header name + the three parsers tests import; controls §6.2–6.3; `__layer__` per §1.
2. **CHANGE** `refactor(config): SECTION_PARSERS; OVERRIDE_STATE_*; _root_knob; personas.persona_id_aliases; serde folds (positive_int, positive_float, optional_str)` — reds pasted; `[ds-size]` −1.

## 8. Lane and what it must not touch

Exec lane 2B-C (with `harness_doctor`, `persona_instance_sync`, `agent_chat_dispatch`), FIRST of the four: `harness_doctor` imports it and lands next. Must not edit in parallel: `runtime_config.py`, `permission_modes.py`, `dispatch_session_policy.py`, `personas.py` (except the `persona_id_aliases` owner if 2B-B has not landed it), `state_patches/` and `terminal_envelope/` (lanes 2B-A/2B-B — they import through `config/__init__`), `harness_parts/` (H2/H3/H4 packages — retarget-only).
