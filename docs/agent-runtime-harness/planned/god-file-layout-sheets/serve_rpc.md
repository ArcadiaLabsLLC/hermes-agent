# Layout sheet — `agent_runtime/serve_rpc.py` (lane R3)

Base: `main` @ `bf4377f226` · 4,703 raw / 3,518 code / 62 top-level defs · longest `_runtime_office_upsert` 333 (1234–1566) · chains 1/0 · `str==` 1 · `isinstance` 44 · owner doc `docs/agent-runtime-harness/03-transport-and-wire.md` (RPC), `06-office-and-board.md` (the office verbs). The `_METHODS` + `@method` registry (158–403) is the program's **reference implementation of rule 12** and is not converted — it is moved. 33 `@method` registrations (721–4593); 41 test files import the module by path; 12 of them pin 5 private handler names (`serve_rpc._runtime_office_*`).

**Package is named after the file — `agent_runtime/serve_rpc/`** (the H4 precedent `serve.py` → `serve/`), so every `from agent_runtime.serve_rpc import X` and `from .serve_rpc import ERR_*` (`chat_turn.py:680`, `persona_open_chat.py:112/211/275`, `scope_activation.py:485`, `serve_office_subscriptions.py:132`, `harness_parts/persona/lifecycle_commands.py:285`) keeps resolving through `__init__`. The 09-21 §2 R3 row's module list (`registry,office,persona,chat,peer,gateway,realm,media,discussion`) stands in grain; this sheet splits `office` in three (one module of 1,570 raw would cross the ceiling) and adds `protocol`, `params`, `dispatch`, `level`, `map`, `scope`.

## 1. Section map → target modules

| lines | what is there | → module | layer |
|---|---|---|---|
| 1–143 | module docstring, imports (`call_authorization` ×1 block, `store_file_io.iso_stamp as _now_iso` 138) | `serve_rpc/__init__.py` (the map; explicit import of every family so `method_names()` is unchanged) | wiring |
| 144–157, 188–278 | `RPC_CONTRACT_VERSION`, `JSONRPC_VERSION`, `ERR_*` ×6, `ok` 188, `err` 192, `notification` 208, `DEFERRED` 241, `is_deferred`, `deferred_reply` 250 | `serve_rpc/protocol.py` (~110) — imports nothing from the package | models |
| 279–362 | `RpcContext` (+ `push` 347) | `serve_rpc/protocol.py` | models |
| 158–187, 364–484 | `_METHODS`, `_METHOD_TIERS`, `TIER_*`, `method` 364 (+ `dec`), `_ensure_discussion_methods` 393, `_ensure_local_llama_methods` 399, `method_names` 405, `method_tier` 413, `method_tiers` 425, `manifest` 431 | `serve_rpc/registry.py` (~170); the two `_ensure_*` lazily import `discussions.rpc` / `local_llama_adapter.rpc` `register` — registration, so they move to `__init__` | models (`__init__` for the two) |
| 485–624 | `is_rpc_frame` 485, `_normalize_request` 498, `handle_request` 544 | `serve_rpc/dispatch.py` (~150) — the ONE reader of `_METHODS` | lanes |
| 625–684, 2278–2353, 2644–2676 | `_workspace_id_param`, `_CorrelationIdRefused` 637, `_correlation_id_param` 645, `_LevelExpectationRefused` 2278, `_level_expect_param` 2286, `_level_workspace_missing` 2317, `_level_workspace_id_or_error` 2340, `_map_expect_param` 2644, `_map_id_param` 2655, `_map_id_or_error` 2662, `CORRELATION_ID_INVALID_REASON` 634 | `serve_rpc/params.py` (~180) | policy |
| 685–1232 | `log_office_write` 685, `_runtime_office_get` 722, `_office_projection` 784, `_runtime_office_subscribe` 845 (325, depth 3), `_runtime_office_unsubscribe` 1173 | `serve_rpc/office_read.py` (~410) | lanes |
| 1233–1783 | `_runtime_office_upsert` 1234 (333), `_runtime_office_remove` 1570 (212) | `serve_rpc/office_actor_writes.py` (~410) | lanes |
| 1784–2277 | `_runtime_office_surface_update` 1785 (175), `_runtime_office_resolve_conflict` 1963 (293) | `serve_rpc/office_surface_writes.py` (~350) | lanes |
| 2275–2643 | `LEVEL_SHA256_MISMATCH_REASON`, `_runtime_level_get` 2355, `_runtime_level_set` 2394 (137), `_runtime_level_clear` 2534 | `serve_rpc/level.py` (~270) | lanes |
| 2641–2983 | `MAP_SHA256_MISMATCH_REASON`, `_runtime_map_list` 2677, `_runtime_map_get` 2709, `_runtime_map_set` 2751 (142), `_runtime_map_clear` 2896 | `serve_rpc/map.py` (~250) | lanes |
| 2984–3148 | `_runtime_agent_create` 2985, `_runtime_agent_retire` 3080 | `serve_rpc/agent.py` (~120) | lanes |
| 3149–3453 | `_runtime_persona_instance_open_chat` 3150, `_runtime_persona_prewarm` 3215, `_runtime_chat_message` 3290, `_runtime_chat_steer` 3370 | `serve_rpc/chat.py` (~180) | lanes |
| 3454–3542 | `_runtime_workspace_use` 3455, `_runtime_realm_use` 3495 | `serve_rpc/scope.py` (~60) | lanes |
| 3543–3824 | `MEDIA_CONTRACT`, `_runtime_media_index` 3547, `_runtime_media_get` 3622 (149, + `_proxied`), `_media_get_frame` 3773 | `serve_rpc/media.py` (~230) | lanes |
| 3825–4485 | `PEER_*` reasons/contracts, `_peer_ping` 3829, `_peer_agent_chat_execute` 3912, `_peer_media_get` 3999 (114), `_peer_announce` 4139 (104), `_peer_roster_list` 4278, `_peer_thread_read` 4360 (107) | `serve_rpc/peer.py` (~500) | lanes |
| 4486–4703 | `_runtime_gateway_peers_subscribe` 4487, `_runtime_gateway_peers_list` 4561, `_runtime_gateway_peers_roster` 4594 (110) | `serve_rpc/gateway_peers.py` (~170) | lanes |

Result after the MOVE: 16 modules, none over 500. Import edges (drawn, lazy included — W0-G6's `imports_of` walks every `Import` node): every handler module → `protocol` + `registry` + `params` (down); `dispatch` → `registry` (down); `__init__` → all (down). `serve_office_subscriptions.py:132` imports `notification` at module level while `office_read.py:996/1213` lazily imports `serve_office_subscriptions` back — the cycle exists today and stays lazy; it closes when R3 opens `serve_office_subscriptions` (program §3.2) and `notification` lives in `protocol.py`, which imports nothing. `chat_turn.py:680` ↔ `registry.manifest` 473 (`CHAT_TURN_METHOD_PARAMS`) is the same shape: both lazy, both stay.

## 2. Routing sites → dispatch tables (the CHANGE commit)

W0-G5 holds no row for this file (the registry IS the table). What the CHANGE converts is rule 14's other half — the reason vocabulary and the error translation:

| site (base line) | shape today | replacement | killing mutation |
|---|---|---|---|
| `*_REASON` constants at 634, 2275, 2641, 3908, 4135, 4265–4274 | eight free `str` reasons declared beside the handler that spends them; clients branch on `data.reason` (1128–1129) | `serve_rpc/reasons.py`: `RpcRefusal(StrEnum)` with the eight members; `err(...)` takes `reason: RpcRefusal \| None`; `params.py` refusals raise `ParamRefused(reason)` (one exception replacing `_CorrelationIdRefused` 637 and `_LevelExpectationRefused` 2278, which are the same 3-line shape) | swap the `sha256_mismatch` members of level and map → `tests/agent_runtime/test_level_rpc.py` reds on `data.reason` |
| the store-exception translation repeated at 1412–1523, 1628–1744, 1844–1935, 2057–2216 ("The same reason string every office method spends on this") | four hand-written `except StaleRevision / NotFound / ArchiveUnreadable / ClassKeyedPlacementRefused / SyncConflict` cascades, each mapping a store exception to `(code, reason, data)` | `serve_rpc/office_errors.py`: `OFFICE_ERRORS: Mapping[type[AgentRuntimeError], Callable[[exc], RpcError]]` walked by MRO; each handler is `params → store call → except AgentRuntimeError as exc: return office_errors.translate(exc, request)`; the two lane-specific arms (tombstone 1455–1466, prediction-behind 1487) stay as guards in the handler | swap the `StaleRevision` and `NotFound` rows → `tests/agent_runtime/test_serve_rpc_office_upsert.py` reds (4090 answered where 4001 is asserted) |
| `_runtime_office_subscribe` 1305–1312 (`fold_entities`: `None` / `list` of `str` / refuse) | the one routed chain the probe counted | `patch_coverage.parse_fold_entities_option` — H4 kept the serve-side arm's own parser because the contracts differ; HERE the RPC arm is the same contract as the store's, so it calls the parser and refuses on its typed reason | make the parser accept an empty string → `test_serve_rpc_office_subscribe.py` fold-negotiation case reds |

Density goal at review: `isinstance` 44 → ≤ 20 (param validation moves behind `params.py`'s typed readers; boundary checks stay).

## 3. W0-G7 floor rows (5) and the decomposition

| row | lines / depth | phases (from the comment map) | after |
|---|---|---|---|
| `_runtime_office_subscribe` 845 | 325 / 3 | params 1026 · watermark read 1058–1076 · registry admit 1125 · declaration echo 1154–1162 | `OfficeSubscribe.params → watermark → admit → reply`, ≤ 80 each; the watermark read (one reader, one question) is its own function |
| `_runtime_office_upsert` 1234 | 333 / 1 | correlation + revision guards 1344–1364 · store call · five translation arms 1412–1523 · reply 1558 | guards → `params.office_write_params` (one value object, shared with remove/surface_update); arms → `office_errors.translate`; handler ≤ 70 |
| `_runtime_office_remove` 1570 | 212 | same guards 1628–1649 · own reason 1707 · idempotent archived branch 1737–1744 | same shape; ≤ 70 |
| `_runtime_office_surface_update` 1785 | 175 | guards 1844–1873 · per-element string check 1854 · reply 1921 | ≤ 60 |
| `_runtime_office_resolve_conflict` 1963 | 293 / 2 | guards 2057–2077 · `no_conflict` 2159 · race arm 2172 · `ArchiveUnreadable` 2184–2188 · id refusals 2204 · edit-vs-remove tombstone 2216 | `ConflictResolve.params → take → translate`; ≤ 90 |

Nothing else in the file is over 150 or deeper than 4 (`_runtime_media_get` 149 is one line under — the `_proxied` closure lifts out in the MOVE so it does not GROW).

## 4. Helpers that unify

| here | duplicate of | authority |
|---|---|---|
| `_now_iso` = `store_file_io.iso_stamp` (138) | `_now_iso` ×4 (`chat_live_log` 814, `peer_directory` 411, `serve_registry` 1093, `serve_socket` 2962) | `clock.now_iso()` = `iso_stamp(time.time())` — this lane CREATES it in `agent_runtime/clock.py` (19 lines today, `elapsed_ms` only) and the serve_socket sheet folds the first copy; program §4 row |
| `_level_expect_param` 2286 / `_map_expect_param` 2644; `_level_workspace_id_or_error` 2340 / `_map_id_or_error` 2662 | one shape, two families | `params.expect_param(name)` / `params.id_or_error(name)` |
| `_CorrelationIdRefused` 637 / `_LevelExpectationRefused` 2278 | one 3-line exception, two spellings | `params.ParamRefused` (§2) |
| the four `except` cascades (§2) | — | `office_errors.translate` |

## 5. Dead code found while reading

None. The by-name census over this file is all `@method` false positives (program §5 struck 24); `log_office_write` 685, `method_tiers` 425, `is_deferred` 244, `_ensure_*_methods` 393/399 each have a live caller (`git grep -nw` → 10, 2, 1, 3 hits in-file or in `manifest`). No queue row names this file.

## 6. Doors

`tools.agent_chat_remote.call_peer_method` (4635, lazy; fork-only file — not in `tests/fixtures/upstream_manifest.txt` — so not a door). `utils`, `hermes_*`: none. W0-G6 private rows for this file: none. No widening.

## 7. Commits

1. **MOVE** `refactor(serve_rpc): serve_rpc.py → agent_runtime/serve_rpc/ (16 modules; registry unchanged)` — spans byte-identical with the sha256 table; `__init__` imports every family in the 721–4593 registration order so `manifest()` is byte-identical (`tests/agent_runtime/test_serve_rpc_method_tiers.py` + the `serve_rpc_manifest.expected.json` readers are the proof); the 12 test files pinning `serve_rpc._runtime_office_*` retargeted to the module that binds the name. **Killing mutation for the MOVE itself:** drop `office_read` from `__init__`'s import list → the manifest fixture diff reds (a method missing from `method_names()`).
2. **CHANGE** `refactor(serve_rpc): RpcRefusal, ParamRefused, OFFICE_ERRORS; office handlers as phases` — §2 + §3 + §4 with each red pasted; `clock.now_iso` created; `[ds-size]` 37 → 36.

## 8. Lane and what it must not touch

R3, first of R3's five (fewest importers among them, and `snapshot`'s hub imports it lazily only). In parallel it must not edit: `serve_office_subscriptions.py`, `chat_turn.py`, `persona_open_chat.py`, `scope_activation.py` (they keep importing through `serve_rpc/__init__`); `hermes_cli/harness_parts/serve/{handle_message,boot_phases}.py` (H4's package — retarget-only, no other edit); `office_store.py` (R1's file — this lane consumes `OfficeStore` through the name R1's package keeps).
