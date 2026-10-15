# Layout sheet — `agent_runtime/gateway_peers.py` (lane R4)

Base: `main` @ `28012c8f8a` · sha256 `90020d187da5e3b7d0c56c4d268ab6ed2a74961e8c0fd0b1f6a508d47d41f948` · 2,185 raw / 1,621 code / 43 top-level defs · longest `dial_peer` 172 (1089–1260) · chains 0/0 · `str==` 2 · `isinstance` 20 · owner doc `docs/agent-runtime-harness/09-multi-device-runtime.md` (Stage 6 peers, S2/S2c/S2d). 14 production importers (`gateway_announce`, `gateway_targets`, `media_proxy`, `peer_directory`, `serve_gateway_credentials`, `serve_gateway_peers_rpc`, `serve_rpc/{gateway_peers,peer}`, `serve_socket/client`, `harness_parts/gateway_commands`, `serve/handle_message`, `tools/agent_chat_{dispatch,remote,tool}`) taking 22 public names; 13 test files pinning 37 names, none private. The 134-line module docstring (trust vs cache, R5, the hashing limit, root-as-input) is the design and moves whole onto the package `__init__`.

**Package named after the file — `agent_runtime/gateway_peers/`**; every `from .gateway_peers import X` resolves through `__init__`. The file is already two stores (the docstring says so: `peers.json` trust, `peers_cache.json` cache — R-IP14, S2c) plus one ceremony and one dial; the skeleton is those four, and the docstring's "a label nothing checks is a comment" test (`PEER_ROW_TRUST_FIELDS` / `PEER_ROW_CACHE_FIELDS` partition the row) becomes the boundary between two modules instead of two frozensets in one.

## 1. Skeleton (owner ruling 2026-09-25: readability first; modules target 100–300, hard cap 500; no flow over three modules)

```
agent_runtime/gateway_peers/
  __init__.py       wiring   the module docstring (the design) + the map; re-exports the 22 importer names and the 37 test names
  models.py         models   PEER_STORE_*/PEER_PROOF_*/PEER_AUTH_*/REACHABILITY_*/PEER_EVENT_* words, the six frozen rows (PeerPairingCode, PeerCredential, PeerRecord, PeerAuth, PeerCacheRow, UsablePeer), the two field partitions, peer_store_path/peer_cache_path, clean_endpoints + _clean_fingerprint  (~220; a VOCABULARY + row-shape module)
  trust_store.py    stores   peers.json: the HMAC (peer_secret_verifier, peer_proof, verify_peer_proof), list/lookup, note_peer_seen, revoke_peer, record_peer, _row/_decode_peer/_read_peers/_write_peers (the ONE write door), revision + external-write tracking, _emit_peer_event  (~350)   entry: verify_peer_proof, lookup_peer, list_peers, record_peer, revoke_peer, note_peer_seen, peer_store_revision, note_peer_store_read
  ceremony.py       lanes    mint_peer_code, redeem_peer_code — the two-operator ceremony over pairing.json  (~180)   entry: mint_peer_code, redeem_peer_code
  dial.py           lanes    dial_peer + _dial_failure_word + LOCAL_POLICY — one outbound handshake over the candidate list  (~150)   entry: dial_peer
  cache.py          stores   peers_cache.json: read_peer_cache, cache_peer_hello, note_dial_result, cache_peer_roster, apply_peer_announce, usable_peers, _cache_row/_decode_cache/_read_cache_rows/_write_peer_cache, _clear_revoked_you, _rotation_notice, _touch_cache (the ONE write door), _CACHE_WRITE_LOCK  (~330)   entry: usable_peers, read_peer_cache, cache_peer_hello, cache_peer_roster, apply_peer_announce, note_dial_result
```

Per entry point, the modules an agent opens (the entry's module plus the modules of what it calls directly; `serve_gateway_auth`, `gateway_pairing_codes`, `serve_socket`, `gateway_identity`, `gateway_tls`, `gateway_endpoints` are stores below the package and are named in §1.1's edges, not counted):

| entry point | opens | count |
|---|---|---|
| `dial_peer` | `dial` → `trust_store` (lookup, proof) → `cache` (endpoints first, reachability after) | 3 |
| `redeem_peer_code` / `mint_peer_code` | `ceremony` → `trust_store` (the row write) → `cache` (`_clear_revoked_you`) | 3 |
| `record_peer` / `revoke_peer` / `note_peer_seen` | `trust_store` → `cache` → `models` | 3 |
| `verify_peer_proof` / `lookup_peer` / `list_peers` | `trust_store` → `models` | 2 |
| `apply_peer_announce` / `cache_peer_roster` / `usable_peers` | `cache` → `trust_store` (lookup) → `models` | 3 |

Two modules sit above the 300 target and under the cap, on purpose: `trust_store` and `cache` each hold ONE write door (`_write_peers` 1365, `_touch_cache` 2061) with every writer beside it — rule 13 — and splitting a store's writers from its door is the two-write-paths defect the rule exists to stop. The first draft had `proofs.py` (~90) as its own module; it is sub-100 and only makes sense beside the store that verifies against it, so the HMAC lives in `trust_store` (ruling 3a).

### 1.1 Section map → target modules

| lines | what is there | → module | layer (from imports) |
|---|---|---|---|
| 1–249 | the docstring 1–156, imports (`gateway_identity`, `gateway_pairing_codes` ×9, `serve_gateway_auth.{CREDENTIAL_TTL_SECONDS_INTRODUCED, StoreRefusal, _read_pairing, _store_lock, _write_pairing}`, `store_file_io` ×6), `__all__` 195 | `gateway_peers/__init__.py` | wiring |
| 256–429, 435–436, 499–553, 1268–1289, 1394–1441, 1445–1530 | the constants, `PeerPairingCode` 303, `PeerCredential` 327, `PeerRecord` 352, `PeerAuth` 416, `peer_store_path` 435, `clean_endpoints` 499, `_clean_fingerprint` 542, `PEER_ROW_TRUST_FIELDS` 1268, `PEER_ROW_CACHE_FIELDS` 1287, the cache words 1394–1441, `PeerCacheRow` 1445, `UsablePeer` 1506, `peer_cache_path` 1529 | `gateway_peers/models.py` — imports `gateway_identity.gateway_dir`, `store_file_io.stamp_passed` | models |
| 442–493, 559–745, 975–1047, 1292–1369, 1820–1894, 2133–2185 | `peer_secret_verifier` 442, `peer_proof` 455, `list_peers` 559, `lookup_peer` 574, `verify_peer_proof` 584, `note_peer_seen` 659, `revoke_peer` 695, `record_peer` 975, `_row` 1292, `_decode_peer` 1331, `_read_peers` 1359, `_write_peers` 1365, `_LAST_SEEN_REVISION` 1820, `peer_store_revision` 1845, `note_peer_store_read` 1863, `_note_write` 1891, `_emit_peer_event` 2133 | `gateway_peers/trust_store.py` — imports `models`, `cache` (for `_clear_revoked_you` from `record_peer`), `serve_gateway_auth._store_lock`, `store_file_io`, `events`/`hermes_time` (lazy), `serve_gateway_peers_rpc.publish_peer_event` (lazy) | stores |
| 748–972 | `mint_peer_code` 748, `redeem_peer_code` 829 | `gateway_peers/ceremony.py` — imports `models`, `trust_store`, `gateway_pairing_codes`, `serve_gateway_auth._{read,write}_pairing` | lanes |
| 1057–1260 | `LOCAL_POLICY` 1057, `_dial_failure_word` 1060, `dial_peer` 1089 | `gateway_peers/dial.py` — imports `models`, `trust_store`, `cache`, `serve_socket` (lazy), `gateway_identity`/`gateway_tls` (lazy), **and today `hermes_cli.harness_parts.gateway_commands` (lazy, 1077/1181 — upward; deleted by the gateway_commands MOVE, which lands next in this lane)** | lanes |
| 1533–1806, 1842, 1900–2130 | `read_peer_cache` 1533, `cache_peer_hello` 1550, `note_dial_result` 1591, `cache_peer_roster` 1638, `apply_peer_announce` 1679, `usable_peers` 1760, `_CACHE_WRITE_LOCK` 1842, `_cache_row` 1900, `_decode_cache` 1944, `_read_cache_rows` 1992, `_write_peer_cache` 1998, `_clear_revoked_you` 2005, `_rotation_notice` 2039, `_touch_cache` 2061 | `gateway_peers/cache.py` — imports `models`, `trust_store` (lazy: `lookup_peer`, `_emit_peer_event`), `store_file_io` | stores |

**The one cycle, and which module breaks it.** `trust_store.record_peer` clears `revoked_you` through `cache._clear_revoked_you` (963–970: "both credential writers now do"), and `cache._touch_cache`/`apply_peer_announce` read `trust_store.lookup_peer` and emit through `trust_store._emit_peer_event`. Drawn as module-level imports that is a cycle. **`cache.py` breaks it**: its two reaches into `trust_store` are lazy (inside the functions, as `_emit_peer_event`'s own reaches already are), and `trust_store` imports `cache` at module level. Alternative considered and refused: moving `_emit_peer_event` into `models` — it appends to the EventLog and publishes to the RPC hub, which is a store write, not a model. Everything else points down: `ceremony`/`dial` → `trust_store` → `cache` → `models`.

## 2. Routing sites → tables (the CHANGE commit)

W0-G5 holds no row for this file. Two rule-14 sites and one floor row:

| site (base line) | shape today | replacement | killing mutation |
|---|---|---|---|
| `PEER_AUTH_OK / UNKNOWN / REVOKED / BAD_PROOF / MALFORMED / EXPIRED` 288–296, spent by `verify_peer_proof` and read by `serve_gateway_credentials` | six module constants carrying free strings; `verify_peer_proof` is their one writer (a good shape already) | **not enum-ised** (batch-1 rule): `ok`, `unknown` and `expired` are fork-wide words (`turn_visibility.VisibilityState`, `RpcRefusal`), so a `StrEnum` here would make the gate's arm (c) count every `== "ok"` in the fork; the constants stay, `models.py` groups them as `PEER_AUTH_REASONS: tuple[str, ...]` beside the dataclass, and `PeerAuth.reason` is documented as one of them. The gate defect is rowed once for the class (report §rows) | replace `PEER_AUTH_EXPIRED` with `PEER_AUTH_REVOKED` in the expiry arm → `tests/agent_runtime/test_gateway_peers_store.py::test_an_expired_peer_is_refused_after_the_proof_with_its_own_reason` reds |
| `REACHABILITY_*` 1401–1403, `PEER_EVENT_*` 1432–1436 | the same shape, the same single writers (`note_dial_result`, the five store doors) | same treatment: grouped tuples in `models.py`, no enum | swap the two `PEER_EVENT_RECORDED`/`PEER_EVENT_REVOKED` spellings → `::test_every_store_door_emits_its_event_with_ids_and_never_a_secret` reds |

W0-G7 floor row (1):

| row | lines / depth | phases (comment map) | after |
|---|---|---|---|
| `dial_peer` 1089 | 172 / 3 | revocation + expiry guards BEFORE any socket 1131–1145 · verifier 1146 · identity 1162 · what this root advertises 1167 · cache endpoints FIRST, then trust 1187–1206 · the pin is always the trust row's 1195 · the attempt loop 1212–1249 · R-D20 policy word 1209/1251 · record 1255 | `Dial(record, cached, identity).guards → candidates → attempts → outcome`, ≤ 50 each; `candidates` is the one function that spells "cache first, trust second, pin always trust" and `::test_dial_order_is_cache_endpoints_then_trust_and_the_pin_is_always_trust` is its test |

## 3. Helper folds

| here | duplicate of | verdict |
|---|---|---|
| `_emit_peer_event` 2133 (the EventLog half) | `store_events.emit_store_event(event_log, event_type, payload, domain=…)` — the same append, the same "never raises" | FOLD the append: `_emit_peer_event` becomes `emit_store_event(EventLog(), event_type, payload, domain="gateway.peer")` followed by the RPC fan-out it alone does; **one behaviour difference, named**: `emit_store_event` drops `None`-valued keys and this one does not — the lane greps every `_emit_peer_event(` payload for a key that can be `None` (`store_root` is a kwarg, not a payload key) before folding, and keeps its own append if it finds one |
| `_row` 1292 | program §4 row `running_work/collect.row` lists this file among five `_row` copies | **NOT a fold** — this `_row` builds a `peers.json` row from typed fields; `running_work._row` builds a work-projection row; `realm_sync/drift._row`s build drift items. Same NAME, five bodies: the name arm is retired by renaming to `trust_store.peer_row`; the §4 row is amended to say so |
| `_unusable_reason` (`serve_gateway_peers_rpc` 129 = `gateway_commands` 2196) | W0-G3 `name_groups[30]` | this lane CREATES `cache.unusable_reason` (public; the predicate `usable_peers` explains) as a MOVED span from `serve_gateway_peers_rpc.py` (retarget-only edit there); the `gateway_commands` copy is deleted by that sheet's CHANGE |
| `_read_pairing` / `_write_pairing` / `_store_lock` (imported private from `serve_gateway_auth`, a fork module) | not a fold; a private cross-module import W0-G3 does not count and W0-G6 does not either (fork, not upstream) | the CHANGE makes them public in `serve_gateway_auth` (`read_pairing`, `write_pairing`, `store_lock`) — a rename in a file R3 owns (§8) |
| `iso_stamp` (imported) | `clock.now_iso` (created by the serve_rpc sheet) | NOT a fold: `iso_stamp` renders a GIVEN epoch (`note_peer_seen` stamps "one clock read" per `::test_one_event_is_stamped_from_one_clock_read`); `now_iso` reads the clock itself |

## 4. Upstream doors

`hermes_time.now` 2160 (lazy; public) — FIRST. Everything else is fork code. W0-G6 `private_upstream_imports` rows for this file: none. The `import_layers_grandfathered.json` `undeclared` row is closed by the MOVE (every module declares `__layer__`). No widening.

## 5. Dead code (verdict + the grep the lane runs)

No queue row names this file. `git grep -nw` over the 43 defs: every public name has an importer or a test (§ header); every private one an in-file caller. `PEER_CACHE_ROSTER_CAP` 1441 and `PEER_CACHE_CONTRACT` 1395 are read in-file (2 and 3 hits). Nothing filed.

## 6. Positive controls — land in the MOVE (ruling Q6)

No table replaces a routing site here (§2 converts nothing to a table), so no control is owed by Q6. The two rule-14 mutations in §2 are run and pasted in the CHANGE as the positive proof that the named tests reach the named arms.

## 7. MOVE hash-proof plan, then the CHANGE

1. **MOVE** `refactor(gateway_peers): gateway_peers.py → agent_runtime/gateway_peers/ (5 modules); unusable_reason moved in from serve_gateway_peers_rpc` — spans byte-identical with the sha256 table (one row per §1.1 span, plus the `_unusable_reason` span from `serve_gateway_peers_rpc.py`); `__init__` carries the docstring and re-exports the 22 + 37 names; `serve_gateway_peers_rpc.py` retargets its one call. **Killing mutation for the MOVE:** drop `cache` from `__init__`'s import list → `tests/agent_runtime/test_gateway_targets.py` (imports `read_peer_cache`, `usable_peers`) reds at import. `[ds-size]` −1.
2. **CHANGE** `refactor(gateway_peers): PEER_AUTH_REASONS/REACHABILITY/PEER_EVENT groupings; Dial phases; emit_store_event fold; peer_row; serve_gateway_auth pairing names public` — §2 + §3 with each red pasted.

## 8. Lane and what it must not touch

R4 (exec lane B2), FIRST of its three — `gateway_commands.md` lands after it and deletes the upward import from `dial.py`; `agent_create.md` is disjoint. Must not edit in parallel: `serve_gateway_credentials.py`, `gateway_targets.py`, `gateway_announce.py`, `peer_directory.py`, `media_proxy.py`, `serve_rpc/`, `tools/agent_chat_*` (all keep their paths through `__init__`); `serve_gateway_auth.py` receives exactly the three renames in the CHANGE (it is R3's file — the rename is coordinated with R3 as a "tree wins" one-liner, and R3's sheet for it does not exist yet, so this lane owns the edit); `serve_gateway_peers_rpc.py` receives exactly the one retarget in the MOVE.
