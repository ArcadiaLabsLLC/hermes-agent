# Layout sheet — `hermes_cli/harness_parts/gateway_commands.py` (lane R4)

Base: `main` @ `28012c8f8a` · sha256 `c04c4cdf93db733fba5cba2f27dcfa2d3f6d41a1f71c2e3d7f4124da1f404e67` · 2,323 raw / 1,645 code / 35 top-level defs · longest `cmd_gateway_peers_join` 443 (1703–2145) · chains 0/0 · `str==` 20 · `isinstance` 19 · owner doc `docs/agent-runtime-harness/09-multi-device-runtime.md` (Stage 1 devices, Stage 6 peers, S2 introduce). 4 production importers: `parser/machine.py` (the module, eight `cmd_*` as `func=`), `gateway_identity_commands.py` (`_candidate_endpoints`, `_dial_host`, `_endpoint`, lazy at 94), `serve/boot_phases.py` (`_candidate_endpoints`, lazy at 401), and **`agent_runtime/gateway_peers.py` (`DIAL_LOCAL_POLICY`, `classify_dial_error`, `_candidate_endpoints`, lazy at 1077/1181) — a runtime module importing the CLI, the upward edge W0-G6 forbids** (`runtime-queue.md` § Fork-owned, the "reaches UP into the CLI namespace" row names the class). 6 test files pinning 14 names, seven of them private (`_candidate_endpoints`, `_first_inet_address`, `_linux_default_route`, `_macos_default_route_interface`, `_self_endpoints`, `_windows_default_route_address`, `_REFUSAL_CODES`, `_STORE_WRITE_REASONS`).

**The file is two things**, and the split IS the sheet: seven CLI verbs (330–558, 1214–2323), and an address/dial POLICY (564–1211: interface enumeration, the default-route probe, on-link classification, the candidate list) that the runtime's `dial_peer` already needs and reaches up for. The policy moves DOWN to `agent_runtime/`, which inverts the edge; the verbs become a package named after the file — `hermes_cli/harness_parts/gateway_commands/` — so `parser/machine.py`'s `gateway_commands.cmd_*` keeps resolving.

## 1. Skeleton (owner ruling 2026-09-25: readability first; modules target 100–300 code lines, hard cap 500)

Two packages, because the file is two things. Each tree is its package's `__init__` map, verbatim.

```
agent_runtime/gateway_endpoints/      the address & dial POLICY, moved DOWN out of the CLI (nothing here imports hermes_cli)
  __init__.py      wiring   the map; re-exports the six public names below
  candidates.py    stores   gateway_listen_config (moved from serve/gateway_listener), listener_endpoint + SOURCE_*, candidate_endpoints, dial_host — "where should the other side dial" (~130)   entry: listener_endpoint, candidate_endpoints, dial_host
  addresses.py     policy   ipv4/rfc1918/ranking, machine_addresses (interface enumeration), on-link tests, classify_dial_error + DIAL_* words (~220)   entry: classify_dial_error
  routes.py        stores   the per-platform default-route probes and their parsers (ROUTE_PROBES after the CHANGE) (~150)

hermes_cli/harness_parts/gateway_commands/   the seven operator verbs
  __init__.py      wiring   the map; re-exports the eight cmd_* (parser/machine.py reads them as attributes) and the test-pinned names
  refusals.py      policy   StoreRefusal → harness error (R-D6/R-D14), the operator sentences, GRANT_PAYLOAD_*, dial_target (~140)
  devices.py       lanes    pair, devices list, devices revoke, _install_and_certificate (~170)   entry: cmd_gateway_pair, cmd_gateway_devices_list, cmd_gateway_devices_revoke
  introduce.py     lanes    peers pair, introduce (Introduce phases after the CHANGE) (~275)   entry: cmd_gateway_peers_pair, cmd_gateway_introduce
  join_payload.py  policy   parse_join_payload, clean_candidates — the payload grammar (~110)
  join.py          lanes    peers join (Join phases after the CHANGE) (~280)   entry: cmd_gateway_peers_join
  peers.py         lanes    peers list, peers revoke (~120)   entry: cmd_gateway_peers_list, cmd_gateway_peers_revoke
```

Per entry point, the modules an agent opens to follow it (the entry's module plus the modules of what it calls directly, inside these two packages; the stores below them — `gateway_peers`, `serve_gateway_auth`, `gateway_identity`, `gateway_tls`, `serve_socket` — are named in §1.1's edges and not counted):

| entry point | opens | count |
|---|---|---|
| `harness gateway pair` / `devices list` / `devices revoke` | `devices` → `refusals` → `gateway_endpoints/candidates` | 3 |
| `peers pair` / `introduce` | `introduce` → `refusals` → `gateway_endpoints/candidates` | 3 |
| `peers join` | `join` → `join_payload` → `refusals` | 3 |
| `peers list` / `peers revoke` | `peers` → `refusals` | 2 |
| `candidate_endpoints` / `dial_host` / `listener_endpoint` (runtime callers: `dial_peer`, `boot_phases`, `gateway id`) | `candidates` → `addresses` → `routes` | 3 |
| `classify_dial_error` (runtime caller: `dial_peer`) | `addresses` | 1 |

Floor rule (ruling 3): the runtime package was first drawn as five modules of which three were sub-100 (`listen` 70, `classify` 90, `candidates` 60); they only make sense in pairs, so it is three — `candidates` (the listen config and the list it produces), `addresses` (enumeration and the on-link classification that reads it), `routes`. No module in either package is under 100.

### 1.1 Section map → target modules

| lines | what is there | → module | layer (from imports) |
|---|---|---|---|
| 1–98 | docstring, imports (`root_observability`, `harness_support` — both fork), `__all__` | `gateway_commands/__init__.py` | wiring |
| 114–242, 292–327 | `_REFUSAL_CODES` 114 (+ the module-level `for`/`del` at 151–153 folding `_STORE_WRITE_REASONS` in), `_refusal` 156, `_store_write_refusal` 206, `_StoreWriteRefusal` 230; `LISTENER_OFF_SENTENCE` 292, `NO_DIAL_HOST_SENTENCE` 305, `GRANT_PAYLOAD_KEYS` 314, `GRANT_PAYLOAD_MAX_BYTES` 327 | `gateway_commands/refusals.py` — imports `harness_support`, `store_file_io` | policy |
| 245–283 | `_endpoint` 245 — three sources (`live` sidecar / `config` / `unknown`) | `gateway_endpoints/candidates.py` as `listener_endpoint(store_root)`; its `gateway_listen_config` dependency moves with it — §1a | stores |
| 330–558 | `cmd_gateway_pair` 330, `cmd_gateway_devices_list` 440, `cmd_gateway_devices_revoke` 457, `_install_and_certificate` 512 | `gateway_commands/devices.py` | lanes |
| 564–603, 606–638, 830–956 | `MAX_CANDIDATE_ENDPOINTS` 564, `_UNOFFERABLE_PREFIXES`, `_WILDCARD_HOSTS`, `_RFC1918_CIDRS`, `_ipv4` 606, `_is_rfc1918`, `_shares_24`, `_address_rank` 830, `_machine_addresses` 870 (+ `_keep`) | `gateway_endpoints/addresses.py` | policy |
| 589, 603, 641–827 | `_DEFAULT_ROUTE_PROBE`, `_ROUTE_COMMAND_TIMEOUT_SECONDS`, `_run_route_command` 641, `_windows_default_route_address` 684, `_macos_default_route_interface` 724, `_first_inet_address` 735, `_linux_default_route` 757, `_default_route_address` 785 | `gateway_endpoints/routes.py` | stores (it spawns the OS route command) |
| 964–1085 | `DIAL_LOCAL_POLICY` 964, `DIAL_UNREACHABLE`, `_WSAEHOSTUNREACH`, `_HOST_UNREACHABLE_ERRNOS`, `_V6_*`, `_in_network` 989, `_shares_64`, `_is_on_link` 1013, `classify_dial_error` 1045, `LOCAL_POLICY_SENTENCE` 1081 | `gateway_endpoints/addresses.py` (with the enumeration row above, ~220) | policy |
| 1088–1160, 1202–1211 | `_candidate_endpoints` 1088, `_dial_host` 1129, `_self_endpoints` 1202 | `gateway_endpoints/candidates.py` (with `listener_endpoint` and `gateway_listen_config`, ~130) | stores |
| 1163–1199 | `_dial_target` 1163 — the refusal-rendering wrapper (`emit_harness_error`) | `gateway_commands/refusals.py` — the one part of the policy block that renders, so it stays CLI-side | policy |
| 1214–1564 | `cmd_gateway_peers_pair` 1214, `cmd_gateway_introduce` 1299 | `gateway_commands/introduce.py` | lanes |
| 1567–1700 | `_parse_join_payload` 1567, `_clean_candidates` 1672 | `gateway_commands/join_payload.py` | policy |
| 1703–2145 | `cmd_gateway_peers_join` 1703 | `gateway_commands/join.py` | lanes |
| 2148–2323 | `cmd_gateway_peers_list` 2148, `_unusable_reason` 2196 (§3 fold), `cmd_gateway_peers_revoke` 2220 | `gateway_commands/peers.py` | lanes |

**§1a — `gateway_listen_config` moves down with `_endpoint`.** `listener_endpoint` reads the `remote_gateway.*` config through `hermes_cli/harness_parts/serve/gateway_listener.py::gateway_listen_config` (26–60: `hermes_cli.config.load_config_readonly` and nothing else — no serve state). Left there, `gateway_endpoints/` would import the H4 package: the upward edge again, one hop over. So the function MOVES (byte-identical span) to `gateway_endpoints/candidates.py` (its only import is the public upstream `hermes_cli.config`, lazy), and `serve/gateway_listener.py` keeps the name by import and re-export (it is in that module's `__all__`; `test_gateway_pairing_verbs.py::test_a_live_listener_is_preferred_over_the_config` still patches it by the serve path — the MOVE keeps that spelling working through the re-export, and the CHANGE retargets the patch). That is the one coordinated one-liner in H4's package this lane makes (retarget + re-export, nothing else). The `runtime-queue.md` MOVE-A row (the keys' ruled home is the plugin manifest) is NOT closed by this move — the reader moves, the keys do not.

Edges after the MOVE, drawn: `gateway_endpoints/candidates` → `hermes_cli.config` (public, lazy), `serve_socket.read_socket_owner`, `addresses`; `addresses` → `routes`; `routes` → stdlib only; **`agent_runtime/gateway_peers` → `gateway_endpoints` (down — the upward import at 1077/1181 is deleted in the MOVE, since the names it reaches now live below it)**; `gateway_commands/refusals` → `harness_support`, `store_file_io`, `gateway_endpoints`; `devices`/`introduce`/`join`/`peers` → `refusals`, `join_payload`, `gateway_endpoints`, `gateway_peers`, `serve_gateway_auth`, `gateway_identity`, `gateway_tls`, `state_patches`, `serve_socket` (all down); `gateway_identity_commands.py:94` and `serve/boot_phases.py:401` retarget their three names to `agent_runtime.gateway_endpoints` (public spellings: `candidate_endpoints`, `dial_host`, `listener_endpoint`). No cycle remains: nothing in `agent_runtime/` imports `hermes_cli` on this path.

## 2. Routing sites → tables (the CHANGE commit)

| site (base line) | fixture row | replacement | killing mutation |
|---|---|---|---|
| `endpoint["source"] == "unknown"` 1404 (and `!= "live"` 423, 1283, 1554; `== "config"` 431, 1290) | `\|vocab\|unknown` — `unknown` is a fork-wide word only because `turn_visibility.VisibilityState` declares it; the endpoint source vocabulary {`live`, `config`, `unknown`} is THIS module's and is declared nowhere | **not enum-ised** (the decision rule from batch 1): `gateway_endpoints/candidates.py::SOURCE_LIVE / SOURCE_CONFIG / SOURCE_UNKNOWN` as plain module constants, read by `listener_endpoint` and the six compare sites by NAME; the gate's arm (c) counting a `turn_visibility` member here is the defect, rowed once for the class (report §rows) | replace `SOURCE_UNKNOWN` with `SOURCE_CONFIG` in `listener_endpoint`'s off arm → `tests/hermes_cli/test_gateway_introduce_verb.py::test_introduce_refuses_when_the_listener_is_off_with_peers_pairs_sentence` reds |
| `_REFUSAL_CODES` 114 + the `for _reason in _STORE_WRITE_REASONS` loop 151–153 | already a table (rule 12 satisfied); the loop is a module-level mutation of a dict literal | `_REFUSAL_CODES: Final[Mapping[str, str]]` built in one expression (`{**_FAMILIES, **{r: "store_unwritable" for r in STORE_WRITE_REASONS}}`) — a MOVE-adjacent edit, done in the CHANGE | drop the `store_unwritable` comprehension → `test_gateway_peer_verbs.py::test_every_peer_write_verb_reports_an_unwritable_store_the_same_way` reds |
| `sys.platform == "win32"` / `"darwin"` 656, 806, 810 | the platform arms of `_run_route_command` / `_default_route_address` — three arms on one name | `gateway_endpoints/routes.py::ROUTE_PROBES: Mapping[str, RouteProbe]` keyed by `sys.platform` prefix (`win32`, `darwin`, `linux`), each `(command, parse)`; `default_route_address` looks its platform up once | swap the `darwin` and `linux` parsers → `test_gateway_introduce_verb.py::test_the_macos_arm_reads_an_interface_name_and_then_its_first_inet` and `::test_the_linux_arm_prefers_src_and_falls_back_to_the_devices_address` red |

W0-G7 floor rows (2):

| row | lines / depth | phases (comment map) | after |
|---|---|---|---|
| `cmd_gateway_introduce` 1299 | 266 / 2 | flags 1355 · correlation 1376 · identity 1399 · endpoint 1404 · peer half 1423 · device half 1456 · first refusal's family 1496 · grant payload (one writer) 1507 · size ceiling 1520 · envelope 1537 | `Introduce.flags → correlation → identity → endpoint → mint_halves → grant_payload → envelope`, ≤ 50 each, in `introduce.py`; `mint_halves` is one loop over `(for_install_id, mint_peer_code)`, `(for_device_id, mint_pairing_code)` |
| `cmd_gateway_peers_join` 1703 | 443 / 3 | parse 1761 · attested pin BEFORE any dial 1764–1818 · correlation 1822 · identity 1843 · the dial over the candidate LIST 1849–1932 (two failure kinds) · hello validation 1992–2035 · recording 2053 · ack 2102–2142 | `Join.parse → attest → correlation → identity → dial → validate_hello → record → ack`; the dial loop's "certificate mismatch is terminal, a dial failure moves on" rule (1856–1864) is pinned by `test_gateway_peer_verbs.py::test_a_certificate_mismatch_stops_the_loop_instead_of_trying_the_next_address` and stays one function of ≤ 60 |

`str==` 20 → ≤ 6 at review (the `hello_ok` event guard and the route-table field parsers stay as boundary checks).

## 3. Helper folds

| here | duplicate of | verdict |
|---|---|---|
| `_unusable_reason` 2196 | `agent_runtime/serve_gateway_peers_rpc.py::_unusable_reason` 129 — W0-G3 `name_groups[30]`, same body, same vocabulary | FOLD to `agent_runtime/gateway_peers.unusable_reason` (public; owner of `usable_peers`, the predicate it explains); both callers import it — the peers sheet creates it, this lane deletes the copy |
| `_refusal` 156 | `name_groups[21]` with `mission_chat_workdir._refusal`; program §4 lists this file among the six `refusals.refusal` copies | **NOT a fold** — this one maps a `StoreRefusal` to a harness ERROR (exit code + family + `store_path`); the sync-lane `_refusal(key, code, message) -> dict` is a report row. The name collision is retired by renaming to `refusals.store_refusal_error`; the program §4 row is amended to five copies |
| `_endpoint` 245 | `name_groups[5]` with `mobile_core/.../turn_runner._endpoint` | retired by the move (`gateway_endpoints.listener_endpoint`) |
| `_self_endpoints` 1202 | a second NAME for `_candidate_endpoints` (its docstring says so) | the MOVE re-exports it (test-pinned); the CHANGE deletes it and retargets the one test — a "kept as a name rather than a body" that the name arm now counts |
| `_store_write_refusal` 206 | none | stays |

## 4. Upstream doors

None. Every import is fork code (`agent_runtime.*`, `hermes_cli.harness_support`, `hermes_cli.harness_parts.serve.gateway_listener`) or stdlib (`ipaddress`, `subprocess`, `socket`, `errno`, `json`). The only upstream name on the path is `hermes_cli.config.load_config_readonly` inside `gateway_listen_config` (public, FIRST) — it moves with that function (§1a) and stays a lazy public import. W0-G6 `private_upstream_imports` rows for this file: none. No widening.

## 5. Dead code (verdict + the grep the lane runs)

Eight second-instalment rows, all cold refusal ARMS (`dead-code-burn-down-queue.md`, lane R4):

| row | what the arm refuses | verdict |
|---|---|---|
| `cmd_gateway_pair [if @361]` | certificate not ok | KEEP — a guard; control §6 |
| `_install_and_certificate [if @531]`, `[if @545]` | identity / certificate not ok | KEEP — guards; §6 |
| `cmd_gateway_introduce [if @1520]` | grant payload over `GRANT_PAYLOAD_MAX_BYTES` — its own comment: "Unreachable at four endpoints … asserted anyway" | KEEP — an asserted ceiling; control by lowering the constant (§6) |
| `cmd_gateway_peers_join [if @1829]` | malformed `--correlation` | KEEP — `test_gateway_introduce_verb.py::test_introduce_stamps_the_correlation_on_the_envelope_and_refuses_an_unfit_token` pins the introduce twin; join's arm gets the same case (§6) |
| `[if @1992]`, `[if @2011]`, `[if @2024]` | hello refused / no peer secret / install id mismatch | KEEP — the three hello validations; §6 |

Nothing else: `git grep -nw` over the 35 defs finds a caller for each (the seven privates through `gateway_identity_commands`, `boot_phases`, `gateway_peers` and the tests). The rows close as KEEP-with-control in the CHANGE.

## 6. Positive controls — land in the MOVE (ruling Q6)

One parametrised case in `tests/hermes_cli/test_gateway_peer_verbs.py` driving `cmd_gateway_peers_join` with a fake `ServeSocketClient` whose hello answers (a) `{"event": "refused"}`, (b) `hello_ok` without `peered.peer_secret`, (c) `hello_ok` naming another install — asserting the reason word of each (`no hello_ok` / `no_peer_secret` / `install_id_mismatch`) and that no row was written; one case each for a broken identity and a broken certificate (monkeypatch `ensure_install_identity` / `ensure_certificate` to answer `ok=False`) across `pair` and `_install_and_certificate`; one case for the grant ceiling with `GRANT_PAYLOAD_MAX_BYTES` monkeypatched to 16; one join case with an unfit `--correlation`. These land BEFORE `ROUTE_PROBES` or the `SOURCE_*` names replace anything, and before the `Join`/`Introduce` phase objects exist — the phase split moves exactly the arms these controls reach.

## 7. MOVE hash-proof plan, then the CHANGE

1. **MOVE** `refactor(gateway): gateway_commands.py → harness_parts/gateway_commands/ (6 modules); address policy → agent_runtime/gateway_endpoints/ (3 modules, gateway_listen_config moved in)` — spans byte-identical with the sha256 table (one row per §1.1 span, one per §1.1 module span plus the moved `gateway_listen_config`); `__init__` re-exports the eight `cmd_*`, the six constants and the seven test-pinned privates (the runtime-side ones re-exported FROM `agent_runtime.gateway_endpoints`, so `from hermes_cli.harness_parts.gateway_commands import _candidate_endpoints` still resolves for one commit); `agent_runtime/gateway_peers.py:1077/1181` retargeted to `agent_runtime.gateway_endpoints` (the upward import deleted — this is a retarget, not an edit of a moved span); `gateway_identity_commands.py:94`, `serve/boot_phases.py:401`, `serve/gateway_listener.py` retargeted. **Killing mutation for the MOVE:** drop `join` from `__init__` → `parser/machine.py:270`'s `gateway_commands.cmd_gateway_peers_join` raises at parser build → `test_gateway_peer_verbs.py::test_every_peer_verb_is_reachable_through_the_real_argparse_tree` reds. The §6 controls land here. `[ds-size]`: −1 for this file; no new module is over 300.
2. **CHANGE** `refactor(gateway): SOURCE_* names, ROUTE_PROBES, _REFUSAL_CODES as one expression; Introduce/Join as phases; unusable_reason fold; store_refusal_error` — §2 + §3 with each red pasted; the eight §5 rows close; the seven privates drop their underscore in `gateway_endpoints` and the tests retarget.

## 8. Lane and what it must not touch

R4 (exec lane B2 in program §3.1c), AFTER `gateway_peers.md` lands in the same lane — that sheet creates `gateway_peers.unusable_reason` and is the module whose upward import this MOVE deletes, so the two land in one lane, peers first. Must not edit in parallel: `agent_runtime/serve_gateway_auth.py`, `gateway_identity.py`, `gateway_tls.py`, `state_patches.py`, `serve_socket/` (consumed by name); `hermes_cli/harness_parts/serve/` beyond the one re-export line in `gateway_listener.py`; `parser/machine.py` is not edited at all (the package keeps its attribute names).
