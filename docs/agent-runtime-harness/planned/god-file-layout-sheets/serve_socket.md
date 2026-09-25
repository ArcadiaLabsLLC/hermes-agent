# Layout sheet — `agent_runtime/serve_socket.py` (lane R3)

Base: `main` @ `bf4377f226` · 2,967 raw / 2,194 code / 33 top-level defs · longest `ServeSocketServer._handshake` 127 (1902–2028) · chains 0 · `str==` 6 · `isinstance` 17 · owner doc `docs/agent-runtime-harness/03-transport-and-wire.md` and `09-multi-device-runtime.md`. **No W0-G7 row** — the only Wave 2 file already under the floor; three methods sit AT depth 4 (`_accept_loop` 1669, `_serve_connection` 1794, `SocketConnection.close` 1329), so the MOVE may not add a level. 10 production importers taking 13 public names (the constants, the two classes, the client, `HelloAuthOutcome`, `read_socket_owner`, `SocketOwnerLock`); 19 test files, **0 private pins**. A 222-line protocol docstring (1–222) is the Q3 class: relocate, do not split for it.

**Package `agent_runtime/serve_socket/`** (named after the file; `core_cache.py:235` imports two filename constants at module level — they survive through `__init__`). The 09-21 R3 row (`server, client, owner_lock, frames` — "three classes, three files") stands; this sheet adds `constants`, `hello`, `connection`, `handshake`, `target`, `wire`.

## 1. Section map → target modules

| lines | what is there | → module | layer |
|---|---|---|---|
| 1–222 | the protocol docstring (hello v3, reject reasons, drain, TLS pin) | `serve_socket/__init__.py` map ≤ 60; the protocol prose → `docs/agent-runtime-harness/03-transport-and-wire.md` § socket (rule 7) | wiring |
| 223–430 | imports (`serde.write_json_atomic` 223), `SOCKET_HOST` 281, `SOCKET_LOCK_FILENAME`/`SOCKET_OWNER_FILENAME`, `DEFAULT_MAX_*`, `HELLO_*` limits, `HELLO_CONTRACT_VERSION` 319, `NONCE_BYTES`, `HELLO_PROOF_ALGORITHM`, **`REJECT_*` ×13 (328–347)**, `AUTH_FAILURE_REJECT_REASONS` 355, budgets/timeouts 368–384, `LOCK_OUTCOME_*` 386–387, `SOCKET_OWNER_DRAINING_KEY`, drain waits 404–408 | `serve_socket/constants.py` (~180): `RejectReason(StrEnum)` with the 13 members, `LockOutcome(StrEnum)` — rule 14; `AUTH_FAILURE_REJECT_REASONS` becomes a `frozenset[RejectReason]` | models |
| 431–499, 500–999 | `socket_lock_path` 431, `socket_owner_path`, `SocketLockResult` 440 (+ `acquired`, `payload`); `SocketOwnerLock` 500 (`__init__`, `path`, `acquire` 601 (85, depth 3), `_owner_is_leaving`, `_owner_register_row_exists`, `_wait_for_drain`, `_try_lock` 758, `_classify_owner`, `_note`, `publish_owner`, `mark_draining`, `release` 887); `read_socket_owner` 932, `_read_owner_record`, `_owner_pid_alive`, `_text_or_none` 993 | `serve_socket/owner_lock.py` (~420) | stores |
| 2844–2882 | `_LockUnavailable` 2844, `_lock_first_byte` 2848, `_unlock_first_byte` 2876 | `agent_runtime/file_locks.py` (program §4: `persona_chat_continuity._try_lock/_unlock`, `mission_chat_turns._lock_fd_*`, and this — "R2 creates, R1/R3 fold"); this lane CREATES it if R2 has not (tree wins), with `try_lock_exclusive(fd)` / `unlock(fd)` | models |
| 1000–1195 | `HelloRateLimiter` 1000, `ServeHelloProtocolError` 1041, `ServeCertificatePinMismatch` 1063, `hello_proof` 1081, `verify_hello_proof` 1109, `HelloAuthOutcome` 1140 | `serve_socket/hello.py` (~170) | policy |
| 1196–1372 | `SocketConnection` 1196 (`emit` 1250, `try_emit`, `payload` 1287, `close` 1329 depth 4) | `serve_socket/connection.py` (~150) | stores |
| 1373–1901, 2159–2245 | `ServeSocketServer.__init__` 1384 (106), `port`, `started_at`, `bind` 1501, `start_accepting`, `begin_drain`, `broadcast` 1557, `close`, `connections`, `connections_payload` 1628, `_accept_loop` 1669 (124, depth 4), `_serve_connection` 1794 (107, depth 4); `_drop_connection` 2159, `_close_listener`, `_signal_wakeup`, `_close_wake_read`, `_emit_log` | `serve_socket/server.py` (~460) | lanes |
| 1902–2158 | `_handshake` 1902 (127), `_authenticate_hello` 2030, `_wrap_tls` 2067, `_read_loop` 2085, `_reject` 2118 | `serve_socket/handshake.py` (~200) — functions taking the server; keeps `server.py` under 500 rather than at 650 | lanes |
| 2246–2354 | `SocketTarget` 2246, `resolve_socket_target` 2279 (60), `_target_from_row` | `serve_socket/target.py` (~90) | stores |
| 2355–2791 | `ServeSocketClient` 2355 (`connect`, `_wrap_tls` 2398, `hello` 2437, `device_hello` 2482, `peer_hello` 2530 (73), `peer_join_hello` 2604, `_challenge`, `pair_hello` 2694, `send`, `set_timeout` 2734, `read_frame`, `close`, context manager) | `serve_socket/client.py` (~330) | lanes |
| 2792–2843, 2884–2967 | `_LineTooLong`, `_LineReader` 2796 (`read_line` 2804 depth 3), `_parse_object`, `_client_text`, `_peer_text`, `_reached_at` 2912, `_is_fatal_accept_error`, `_int_or_none`, `_os_error_token` 2952, `_now_iso` 2962 | `serve_socket/wire.py` (~110) | models |

10 modules + `file_locks`, none over 460. Edges: `server`/`handshake`/`client` → `hello`, `connection`, `constants`, `wire` (down); `owner_lock` → `constants`, `wire`, `file_locks` (down). Lazy reaches to `serve_registry` (728, 986, 2306), `serve_gateway_auth.device_proof` 2507, `gateway_peers.peer_proof` 2573 — none imports back at module level (`gateway_peers` imports `ServeSocketClient` lazily); `serve_gateway_credentials.py` (H4's new module, `lanes`) imports `HelloAuthOutcome`/`REJECT_BAD_PROOF` → from `hello.py`/`constants.py`, both lower. No cycle.

## 2. W0-G5 ladder site → the existing authority (the CHANGE commit)

| site (base line) | fixture row | replacement | killing mutation |
|---|---|---|---|
| `_os_error_token` 2952–2960 | `\|isinstance\|exc` — `PermissionError` / `FileNotFoundError` / `NotADirectoryError` / else `type(exc).__name__` | **`store_file_io.os_error_reason(exc)` already exists (85)** — the fork's one OS-error → reason mapping; this lane folds onto it and deletes the copy (rule 15, before rule 12: the table exists, it is just not being read) | make `os_error_reason` return `type(exc).__name__` for `PermissionError` → **no test reaches this token today** (`git grep -nw _os_error_token` → 1 def + 1 call at the accept-loop's bind failure; 0 test files). The CHANGE lands a positive control first: a bind on an unwritable root must reject with `permission_denied` — `tests/agent_runtime/test_serve_socket_lane.py` gains the case |

Rule 14 in the same commit: the 13 `REJECT_*` strings → `RejectReason`; `SocketConnection._reject` and `ServeSocketClient` read the enum. **Killing mutation:** add a `REJECT_FOO` member that `RejectReason` does not carry → the hello-contract fixture in `test_serve_socket_child_e2e.py` reds (the reject vocabulary is part of `HELLO_CONTRACT_VERSION` 3).

## 3. W0-G7 floor rows

None. The three depth-4 methods (`_accept_loop`, `_serve_connection`, `SocketConnection.close`) are AT the limit; the CHANGE lifts one loop body out of each (`_accept_loop`'s per-accept body → `_admit_socket`, `_serve_connection`'s read loop is already `_read_loop`, `close`'s shutdown ladder → `_shutdown_quietly`) so a later edit has room. `ServeSocketClient`'s five `*_hello` methods (2437–2727) are five frames of one shape (build hello dict, send, read reply, classify) → `HelloKind(StrEnum)` + one `_hello(kind, fields)`; each public method ≤ 10 lines.

## 4. Helpers that unify

| here | duplicate of | authority |
|---|---|---|
| `_now_iso` 2962 | `chat_live_log` 814, `peer_directory` 411, `serve_registry` 1093 (program §4: "`clock.now_iso` new, four copies") | `clock.now_iso` — the serve_rpc sheet creates it (R3, first); this lane folds the first copy and `serve_registry`'s when that file is opened; `chat_live_log`/`peer_directory` are R2/R4 folds |
| `_int_or_none` 2945 | `serde.safe_int` 179 (`tools/checkpoint_manager`, `tools/computer_use/cua_backend_parse` copies are UPSTREAM — left) | `serde.safe_int` |
| `_text_or_none` 993 | `serde.optional_text` 137 | `serde.optional_text` |
| `_try_lock` 758, `_lock_first_byte` 2848 | `persona_chat_continuity._try_lock` 821, `mission_chat_turns._lock_fd_*` | `file_locks.try_lock_exclusive` (§1) |
| `_os_error_token` 2952 | `store_file_io.os_error_reason` 85 | `store_file_io` (§2) |
| `_write_json_atomic` | already `serde.write_json_atomic` (223) | — (done before this lane) |

## 5. Dead code found while reading

| symbol | lines | evidence |
|---|---|---|
| `ServeSocketClient.set_timeout` 2734 | 21 | queue row line 62 (reach census 0 hits): NOT dead — `media_proxy.py:215` and `tools/agent_chat_dispatch.py:827` call it; untested live; the positive control (a timeout that fires) lands with the MOVE |
| `socket_lock_path` 431 | 2 | 3 in-file references + 3 tests — keep |
| `HelloRateLimiter` 1000 | 40 | 7 in-file references, 1 test — keep |

Nothing new. `SocketLockResult` (0 test files) is the typed outcome the lock returns — keep; a test naming it is the positive control for the `LockOutcome` enum.

## 6. Doors

None — the module imports only fork modules (`serde`, `serve_registry`, `serve_gateway_auth`, `gateway_peers`) and the standard library. W0-G6 private rows: none.

## 7. Commits

1. **MOVE** `refactor(serve_socket): serve_socket.py → agent_runtime/serve_socket/ (10 modules; protocol prose to 03-transport-and-wire)` — spans byte-identical; `__init__` re-exports the 13 importer names; no test pins to retarget. **Mutation:** drop `HELLO_CONTRACT_VERSION` from `__init__` → `harness_parts/serve/gateway_listener.py`'s import reds at boot.
2. **CHANGE** `refactor(serve_socket): RejectReason/LockOutcome enums; os_error_reason, safe_int, optional_text, now_iso, file_locks folds; HelloKind; depth-4 bodies lifted` — one ladder row deleted; `[ds-size]` −1.

## 8. Lane and what it must not touch

R3, second of five (after `serve_rpc` — which creates `clock.now_iso` — and before `core_cache`, whose module-level import of two constants here is the reason for that order). Must not edit in parallel: `serve_registry.py`, `serve_gateway_auth.py`, `gateway_peers.py`, `media_proxy.py`, `tools/agent_chat_dispatch.py` (importers — paths survive); `persona_chat_continuity.py`, `mission_chat_turns.py` (R1/R2 — their lock copies fold in their own lanes toward `file_locks`); `hermes_cli/harness_parts/serve/*` (H4's package — retarget-only).
