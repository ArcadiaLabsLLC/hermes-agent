# 03 — Transport and Wire

How a shape leaves this process. The runtime speaks four transports — an argv
lane, a JSON-RPC method lane, an op lane carrying a push subscription, and MCP —
and one warm serve process answers all of them. This is the current,
code-verified contract for each: the frames, how a consumer negotiates what it
can fold, and which parts of the wire are pinned byte-for-byte across the repo
boundary. The old goal/task mission lane remains removed.

## Native conversation methods

`agent_runtime/conversations/rpc.py` registers `runtime.conversation.*` on the
existing authenticated JSON-RPC lane, at console tier. Capabilities, open,
send, read, Stop, questions, model facts/selection and skill inspection are
focused conversation operations, not a universal Work/Observation protocol.
`execution_identity.py::execution_identity` identifies the executing checkout;
the native dispatch guard requires the selected executable's matching identity.
The actor credential, client account scope, profile/home and session must also
match. Sharing a profile store does not permit switching installations.

`open`'s `cwd` is optional (capability `minted_chat_folder`). Omitted, the service mints the route's
chat folder `<store_root>/chat_folders/profile-<profile>/<route_id>/` (`paths.chat_folder`) and stores
it on the route; a resume that omits it is checked against the same path. A given `cwd` must be an
existing absolute directory and is stored as before. Plan:
[chat-folder-in-namespace](archive/chat-folder-in-namespace-2026-10-26.md) §2.2.
`hermes harness conversation chat-folder migrate [--apply] --json`
(`conversations/chat_folder_migration.py`, §2.4) moves routes off the launcher's
`eternia_launcher/agents/workspaces/<hash>` folders: dry run by default, an empty folder removed, a
non-empty one moved, the route's `cwd` rewritten — or, for a route `migrate_conversation` bound, the
folder moved to the persona chat's and the route row deleted. A route with unsettled work or a live
worker is skipped. The operator applies it after the launcher stops passing its AppData folder.

`ConversationStore` persists dispatch identity before execution. Duplicate
requests return their existing receipt; uncertain outcomes are never silently
replayed. Native worker messages stay behind `NativePeer`; consumers receive
bounded event projections, not provider credentials or raw diagnostics.

Provider access follows the service's captured auth owner; tools, skills and
history stay profile-scoped. Model facts expose provider labels, current/default
model IDs, `can_save_model_default` and `model_selection_required`;
`runtime.operator.conversation.models` also carries `image_input_mode` (`native`: the model sees an
attached image; `text`: an auxiliary vision model describes it first; null: no model resolved), the
turn's own `decide_image_input_mode` under the persona's profile config. The `.model`
operation changes only the session unless `save_default: true` is explicit;
both identities must be confirmed before success. Existing config/model and
compute owners perform the write. [Shared-provider evidence](../downstream/shared-provider-authority-2026-09-29.md).

Each admitted send carries its permission: the service resolves
`permission_options_for_subject("profile:<name>", session_id=<route id>)` — the
operator lane's resolver — and calls the worker method `eternia.permission.bind`
(`conversations/worker_permissions.py`) with the turn's execution id and MODE
before `prompt.submit`; the worker derives the block from its own Launcher
catalog and binds it for that turn through `worker_app_functions.bind`. A turn
whose mode never arrived binds `read_only` and logs `permission_bind_missing`
(owner ruling 2026-10-15: read-only unless allowed); a turns-bounded grant is
spent only by a turn that reached `streaming`.

`agent_runtime/discussions/rpc.py` exposes the same discussion service to both
consumers. Non-spatial room admission uses explicit workspace and persona-instance
identities; spatial placement remains separate.

## Operator text admission

The method-lane manifest (`ready` / `hello_ok` / `version`, `rpc.limits`) carries
`operator_text: {max_length, unit}` from `agent_runtime/operator_message.py`
(`operator_text_admission`): the length every operator-text door admits and the unit
it counts (`unicode_code_point`, Python `len`). A composer resolves its own limit
from that value and product entitlements and refuses before send; the server refusal
(`message_invalid`) stays final. No client copies the number.

`rpc.limits.files` (RT-MISSION-CHAT-MESSAGE-TAKES) is
`agent_runtime/operator_files.py::files_limits()` = the native conversation lane's
`conversations/prompt.py::files_capability()` — `{max_count, max_file_bytes,
max_total_bytes, media_types}`, one owner of the number (D2.01). It bounds the `files`
param of `runtime.chat.message` below; the console reads it the way the native lane reads
`capabilities.files`.

## Operator model selection

The existing `runtime.operator.conversation.model.select` also accepts
`scope: "conversation", use_agent_default: true` with no `model_id`. It clears
only that session's model pin through the existing session-store owner; it does
not save an instance/profile default. Ordinary model picks still use
`scope: "conversation", model_id: <catalog id>`, and explicitly saving an agent
default still uses `scope: "agent_default"`. Model facts advertise
`can_reset_model_override` and report `model_is_default` so consumers can gate
the reset and confirm inheritance. The same ownership, console tier, idle-turn
and root-lease checks cover every selection. Managed installations may reset a
chat while default writes remain unavailable.

## Operator thinking capability facts

`_chat_effective_model_payload` projects `reasoning_capabilities` for the same
profile-scoped provider/model cascade as the next turn. Both operator model
RPC reads carry it in `facts`; persona-instance summaries and model/provider/
API-mode patches carry the same value. It records provider, model, API mode,
supported/unsupported/unknown state, nullable exact levels, inherited default,
provider default, descriptions, source and unmapped provider levels.
Missing information stays missing; the legacy boolean is a compatibility
projection of supported nonempty levels.

Serving-catalog facts take precedence over reference metadata. Existing provider
hooks and native wire vocabularies remain the authorities. Already-fetched
Codex, Copilot and OpenRouter-shaped catalogs populate the existing reasoning
cache, scoped by profile, auth-owner revision, endpoint and secret fingerprints.
Inspection neither resolves credentials nor fetches/warms catalogs. Supported
native IDs are ordered by the existing effort ladder; new unmapped terms remain
inspectable and cannot be sent as invented choices. No Launcher model allowlist
or default is required. [Verification](../downstream/reasoning-capabilities-2026-10-12.md).

## Launcher generated-output invocation identity

`agent_runtime/launcher_invocation.py` binds runtime-owned placement coordinates;
`LauncherLink.request` in `agent_runtime/launcher_app_functions.py` stamps them
as `params._meta.invocation`, after stripping model-supplied metadata. Fields are
`channel`, `session_id`, `turn_id` and optional `client_scope`,
`persona_instance_id` and `profile` (the operator lane stamps the last two; the
Launcher's `InvocationOrigin.fromJson` reads the first four and ignores the rest
until it needs them). `params._meta.origin` is a separate word — `local` or
`paired_device`, who started the turn — and never carries ids: the Launcher's
reach check fails closed on anything else.

The wire lane itself (`agent_runtime/launcher_client_requests.py`) asks
`launcher.app_functions.list` ONCE per admitted connection: the catalog is
cached by sink and forgotten on the serve's one disconnect path
(`_on_connection_closed` → `forget_launcher_connection`) and on a
`runtime.client.capabilities` re-declaration, so a reconnect lists afresh. A
connection that closes with requests open has them failed at once with
`data.refusal: connection_closed`; nothing is resent on the next connection.
The Launcher's eight typed refusals and the confirmation outcome reach the model
through `agent_runtime/launcher_app_function_answers.py` (one reading: `retry`
and `detail` per word, `confirmed: true|false` on a `confirm` entry), and a
session held at `read_only` blocks every entry the Launcher marks
`requires_confirmation` through the same `permission_options_for_chat`
chokepoint that blocks `READ_ONLY_BLOCKS`.

- `conversation`: `conversations/service.py` supplies the admitted native route,
  turn and account scope; `conversations/app_functions.py` carries them across
  the worker relay without changing execution, deduplication or tool ownership.
- `operator`: `GPTPersonaRuntime.mission_chat_reply` binds the root chat session
  and runtime turn, never the caller's request ID.
- `discussion`: `discussions/app_functions.py` binds the admitted Launcher
  connection; `room_commands.py` activates a queued message's connection only
  after preceding work settles. `profile_turns.py` and `native.py` stamp the run
  and logical public task ID. Read/replay cannot retarget pending work. End and
  shutdown release connection references; source restarts do not replay effects.

The optional metadata is a reference, not generated content or another history.
Launcher persists it beside its existing document record and mounts its one
GenUI editor. Calls outside a bound invocation remain valid library operations.
`test_launcher_app_functions`, `test_native_app_functions`,
`test_discussion_app_functions` and `test_persona_runtime_fake` prove wire
provenance, native relay, logical task identity and operator context.

## Existing operator conversation attachment

`agent_runtime/serve_rpc/operator_conversation.py` registers three exact-target
methods: `runtime.operator.conversation.read` at read tier, and `.message` and
`.stop` at console tier. All validate installation, workspace, instance and
existing session; none selects a default or creates a conversation worker.
Read projects SessionDB, the turn journal, admission receipts and clarify tickets.
Message calls the existing `perform_chat_turn`; Stop targets its exact admitted
execution. See [turn ownership](05-chat-turn-lane.md#existing-operator-conversations).
A settled turn's history row carries `turn_outcome` and its `executions[]` entry
`left_behind` — the same stored block, copied, absent when nothing was recorded
([what the turn left behind](05-chat-turn-lane.md#7-turn-durability-and-the-run-budget)).

## 1. The serve process model

`hermes harness serve --ndjson` is one warm process replacing the per-call CLI
spawns the Launcher bridge otherwise pays a ~3s import tax on
(hermes_cli/harness_parts/serve/__init__.py:1-7). Requests arrive as NDJSON, one frame
per line, and dispatch into the **existing** harness argparse tree unchanged:
`dispatch_argv` (hermes_cli/harness_parts/serve/argv_lane.py:233) builds a fresh parser per request
(`_build_harness_parser`, hermes_cli/harness_parts/serve/argv_lane.py:141) and calls the same `_cmd_*` handler the CLI
would, including the harness error-envelope contract — argv arrives verbatim as
the bridge already builds it, which keeps the per-call CLI fallback
byte-identical to the served path. **`ready` is a BOOT frame, not a request
frame** — classified as boot in the protocol block (`serve.py`) and emitted
exactly once per process, at its single emit site. What rides a REQUEST is `line` × N,
`exit` and `stderr` (`:31-37`), plus a typed `error` frame when argv parsing or
dispatch fails (`:1346`, `:1355`). Handlers `print()` directly and streaming
turns emit deltas live, so stdout/stderr are swapped once for contextvar-dispatching
proxies (`_LineFrameProxy`, `:706`), one write lock keeps frames atomic, and
writes from handler-spawned threads carry `"id": null`.

**A parse failure is raised from the parser and nowhere else** (RL-24,
2026-09-06). `argv_parse_failed` is a word the LAUNCHER acts on — its
stale-child fallback re-runs that argv on a fresh CLI, which is safe only
because the frame is supposed to mean "the parser refused this before a handler
was bound". Until this stage `parser.parse_args(argv)` and `func(args)` shared
one `SystemExit` path in `dispatch_argv`, so a handler calling `sys.exit()`
AFTER its effect landed reported the parser's word and had the effect replayed.
Three exits now, three frames, all on the request's own sink and all followed by
the usual `exit` frame with the same code:

| escape | frame | means |
| --- | --- | --- |
| `argv[0] != "harness"` | `error: argv_root_unsupported`, `root: <word>` | refused BEFORE a parser was built |
| `SystemExit` from `parse_args` | `error: argv_parse_failed` (unchanged bytes) | nothing ran; replay is safe |
| `SystemExit` from the handler | `error: handler_exit`, `code: <int>` | it ran; terminal for this attempt |

`HandlerExit` and `ArgvRootUnsupported` (`serve.py`) are `SystemExit`
subclasses, so every non-serve caller of `dispatch_argv` keeps the process
behaviour it had; the request loop orders their `except` arms above the generic
one. The root refusal is R-C11's runtime half: `hermes profile delete <p> --yes`
is a real CLI verb, this lane owns the harness parser only, and an argparse
`invalid choice` was indistinguishable from a stale child — so the launcher
replayed the identical argv the identical way, forever. A consumer that has
never heard of the two new words decodes them as it does today (an unknown
`error` kind is ignored and the `exit` frame settles the request); only
`argv_parse_failed` may be replayed.

**Chat turns AND long runs are marked at the argv boundary, and the mark is a
safety contract.** Two tuples, one derivation: `_CHAT_TURN_COMMANDS` is
`mission-chat message|steer` and `_LONG_RUN_COMMANDS` is
`characters turnaround|rows|auto` (both in `serve.py`, beside each other);
`_ArgvRequest.__init__` matches the argv tail against each and sets
`is_chat_turn` / `is_long_run`. The `ping` reply counts both (`_busy_frame`:
`chat_turns` and `long_runs`) because the Launcher supervisor must never recycle
serve while either is in flight, and a drain deadline expiring with
`held_by_chat_turns > 0` **or** `held_by_long_runs > 0` emits a NON-terminal
`drain_timeout`, keeps serving, and re-arms (`_drain_monitor`: the `expiry`
frame's `held_by_chat_turns` / `held_by_long_runs`, `"terminal": not
(chat_turn_ids or long_run_ids)`, and the keep-serving re-arm on the branch
below it; contract in the `drain` block of the module docstring).
Recording safety outranks restart latency.

Both counts are reported, never merged: `held_by_chat_turns` keeps its exact
name and meaning (the launcher decodes the sibling `chat_turns` off the `busy`
frame by name), and `held_by_long_runs` is additive beside it because the WAIT
differs — a chat turn ends in seconds, a `characters rows` batch may be fifteen
minutes from done. The long-run hold is only bounded because the generation is:
`agent/charsheet/pipeline.py::PROVIDER_TIMEOUT_SECONDS` puts a deadline on every
provider call, which is what stops one wedged image backend from holding a drain
open forever. A long run being a generation is also why a sandboxed
proof of this lane needs the draftsman seam: `HERMES_CHARSHEET_DRAFTSMAN=fake`
(RL-26, `agent/charsheet/fake_draftsman.py`) is the declared, default-off way a
SPAWNED serve runs `characters turnaround|rows|auto` to real, committed
revisions with no provider call, and every `characters` `--json` result it draws
says `"draftsman": "fake"`. Cancel semantics are unchanged — a RUNNING generation still
answers `cancel_denied`, and a running `harness stream` request is still the sole
exception to "running requests cannot be cancelled", cooperatively cancelled and
releasing its pool worker (`is_runtime_stream`, `:835`, used `:2952`).

**A standing subscription is not work, and the pump is silent about it**
(RL-13, 2026-09-05). `busy` carries five counts: `chat_turns`, `long_runs`,
`pending` (everything in flight — unchanged name, unchanged meaning), plus the
additive `subscriptions` (the `is_runtime_stream` subset) and `work`
(`pending − subscriptions`). The split exists because an attached launcher holds
TWO infinite `harness stream` requests for the life of the attachment, so
`pending` on an IDLE runtime is 2 and never 0 — measured on the live service,
which announced `{"event":"busy","chat_turns":0,"long_runs":0,"pending":2}`
every five seconds while doing nothing. `_liveness_pump` now emits (to stdout
AND `_broadcast_lanes`) only when `work > 0`; `ping` always answers with all
five, because a supervisor that ASKS needs to see the subscriptions it is
holding. `_report_quiet_requests` still receives the whole pending list and
does its own exclusion. Pinned in
`tests/agent_runtime/test_serve_request_silence.py` (DEFECT D).

**Two transports, one dispatcher.** `serve_loop` is transport-agnostic. One
serve per root owns a localhost socket, decided by an OS-held exclusive lock
(`agent_runtime/serve_socket/`); the loser runs stdio-only and says so on
`ready`. **A DEAD owner is not an owner** (R-L2, 2026-09-04). The identity
sidecar `serve_socket.owner.json` outlives its process — a killed serve never
gets to unlink it — so `SocketOwnerLock.acquire` proves the pid with
`serve_registry.pid_alive`, the same probe that classifies a registry row
`stale_dead_pid`, before believing the file. Proven gone → the lane is taken
and the block carries `took_over_from` plus the corpse's `owner_started_at`,
with one `serve_socket_owner_takeover` line on the service log; a probe that
cannot answer is never read as a takeover; a LIVE owner is refused exactly as
before. The OS lock is not the stale part — the kernel releases it when the
holder dies — so the only shape needing a retry is a held lock whose sidecar
names a corpse, and that retry is bounded at one. Measured cost of the missing
rule: a launcher respawn that did not await the old child's exit left the
replacement stdio-only for a whole session, and therefore with no LAN listener.

**A LEAVING owner is not a serving owner, and a contender waits for it**
(RS-3/RS-4, 2026-09-07). R-L2 with the pid ALIVE: a build-behind restart drained
the runtime, the replacement asked for the lock 14 s into that drain, and was
refused by a process whose listener had already closed. The order is not the
defect — `_finish_drain` in `hermes_cli/harness_parts/serve.py` releases the
socket lock and only then unregisters its row — but the release is the last act
of a shutdown that first waits out every in-flight request, so for that whole
window the holder is alive, holding, and finished. Two facts now let a contender
read that from outside the process. First, the drain ANNOUNCES itself:
`SocketOwnerLock.mark_draining` (`agent_runtime/serve_socket/`) stamps
`draining_at` on the owner sidecar as the first act of the drain, before the
listener closes, additively — the port an already-attached client is using stays
on the record. Second, the moment the registry stops advertising the runtime is
one line, `serve_instance_unregistered` (`reason` = `drain` | `drain_abandoned` |
`shutdown`), on the same service log as `serve_socket_owner_takeover`; the
drain's terminal frame is published BEFORE the teardown it accounts for, so
nothing used to date the row's removal. Given either proof — `draining_at`, or a
live owner with no `serve_instances/<pid>.json` — `SocketOwnerLock.acquire`
polls the lock every `SOCKET_LOCK_DRAIN_POLL_SECONDS` (250 ms) for at most
`SOCKET_LOCK_DRAIN_WAIT_SECONDS` (25 s, derived from the launcher's 20 s
`drainDeadline` in
`EterniaLauncher/lib/features/mission_control/data/mission_control_serve_session_io.dart`
plus margin, and named once so the two repos cannot drift) and takes the lane
when it frees: `acquired`, `took_over_from`, `waited_for_drain_ms`. An owner
that is alive and SERVING is refused on the first attempt without a poll, as
before; a wait that expires degrades exactly as before and carries the number.
Pinned by `tests/agent_runtime/test_serve_socket_drain_wait.py` (all four arms)
and `tests/hermes_cli/test_harness_serve_drain_order.py::test_drain_releases_the_lock_before_it_drops_the_row`.

The handshake is challenge-response and the SERVER speaks first —
`server_hello` carries a 64-hex nonce and `hello_contract: 3`, and the client
answers `HMAC-SHA256(key=<per-root token>, msg="v3|<the port it DIALLED>|<nonce>")`.
**The token never travels**: it is the HMAC key, never a field, so a captured
transcript is unreplayable. **The proof is bound to the port**, which is what
makes it un-RELAYABLE — a fresh nonce stops replay but not a live relay, and the
port is the one value each end takes from its own socket rather than from
anything the other one claims. `serve_socket.hello_proof` is the authority;
prose that disagrees with it has been wrong before (this file and two module
docstrings all said `msg=<nonce>` and contract 2 until 2026-08-27 — which costs a
client author an afternoon, because a proof over the wrong message is refused
`bad_proof`, byte-identical to holding a bad credential).
Only authentication failures (`bad_proof`, `hello_required`, `hello_malformed`)
charge the rate limiter; server-state reasons never do, because charging them
made a blocked window extend itself forever.

**Discovery reads rows, and rows only** (RL-16, 2026-09-05). Since the
end-reason sidecar joined `serve_instances/`, that directory holds two file
shapes — `<pid>.json` (the row) and `<pid>.ended.json` (why the runtime that
wore that pid ended). `serve_registry.list_serve_instances` filters the suffix,
and it is the ONE scan every consumer on this lane is built on:
`resolve_socket_target` (hence `harness serve connect` and the launcher's
`local_serve_attach`), `prune_stale_serve_instances`, and `harness status`'s
`serves=<live>/<entries>`. A sidecar read as a row is a record with no pid, no
port and no identity baseline, which classifies `unknown` — the fail-safe
direction, and therefore a defect that reports nothing. **Nothing about the
sidecar is on the wire**: no frame carries it, no op returns it, `ops` and `rpc`
did not move, and the launcher reads the FILE beside the stale row it already
found. The record's shape and its closed vocabulary are in
`02-runtime-data-and-shapes.md`; which ending writes which word is in
`04-boot-and-lifecycle.md`.

### 1.1 The gateway listener — the same lane, bound beyond loopback

Since the remote gateway's Stage 1 a serve can open a SECOND listener. It is the
same `ServeSocketServer` class with three constructor arguments filled in, not a
second implementation, because the hardened parts of that class are exactly the
parts a copy would get wrong (the accept loop that announces its own death, the
pre-auth bound that counts peers who have proven nothing, the two limiters and
the rule that server-state refusals never charge the auth one). Config, under
the plugin manifest (`plugins.entries.eternia-harness.settings.*`, declared in
`plugins/eternia-harness/plugin.yaml`'s `config_schema`, read only by
`agent_runtime/harness_settings.py`): `remote_gateway_listen` (a HOST STRING;
`false` is off, and boolean `true` is REFUSED — an operator opening a LAN port
has to say which interface) and `remote_gateway_port` (0 = ephemeral; usually
pinned, because a firewall rule and a paired phone both need a number that
survives a restart). The legacy top-level `remote_gateway.listen` / `.port` are
still read when the new key is absent, for the transition the module docstring
states. The rest of this section says `remote_gateway.listen` for the setting
in either spelling. **Off by default, forever.**

| | loopback lane | gateway lane |
|---|---|---|
| host / port | `127.0.0.1`, ephemeral | operator-chosen, usually fixed |
| link | plaintext | TLS, self-signed per-install cert, client PINS the fingerprint (R1) |
| credential | the per-root `serve_auth` token | a per-DEVICE token (`gateway/devices.json`) or a per-INSTALL secret (`gateway/peers.json`) |
| `connection.transport` | `socket` | `gateway` |
| caller kind | `local_console` | `device`, carrying its stored tier — or `peer`, carrying an allowlist |
| ops | every op minus `shutdown` | that, minus `drain` |
| argv lane | yes | **no** |

The device hello names `device_id` and proves
`HMAC-SHA256(key=sha256(device token), msg="gwv1|<port>|<device_id>|<nonce>")`
(`serve_gateway_auth.device_proof`). A hello naming `pairing_code` instead
redeems a short-TTL code minted by `harness gateway pair`, and is admitted as
the device it just created with the token riding that one `hello_ok` and never
again. Every credential failure on this lane — no id, unknown id, revoked row,
wrong proof, wrong code — collapses into ONE `bad_proof` rejection, so a peer
that has proven nothing cannot enumerate device ids by watching the reason
change.

**Neither door accepts the other's credential**, in both directions: the root
token is refused on the gateway lane, a pairing code is refused on loopback.

**One live row per account device** (RL-23, 2026-09-06). A redeem used to write
a row and revoke nothing, so a launcher re-pairing on a backoff left a live
credential per attempt — five rows on this machine for one Mac, fourteen on the
Mac for this one, every one of them able to open the door. A redeem whose
pending entry named an `account_device_id` now revokes every non-revoked row
carrying that same label IN THE SAME WRITE, stamping `revoked_reason:
"superseded"` and `superseded_by: <the new device id>` (both additive; absent on
every earlier row and on every hand-run `harness gateway revoke`, and absent
reads as "nobody said"). No reader ever observes two live rows for one device.
An UNLABELLED row supersedes nothing — `harness gateway pair` names no device,
because a phone has no id until it redeems, so treating the absent label as a
key would collapse every manually paired device into one. The far side's old
credential still verifies as a signature and its row is revoked, so the door
answers `device_revoked` — the honest word, and a different sentence from
`unknown_device`, though the WIRE still collapses both into one `bad_proof`.
`note_device_seen` and the verifier path are untouched.
`serve_gateway_auth.prune_revoked_devices` deletes revoked rows thirty days past
their `revoked_at` at serve boot, beside the two `serve_instances` prunes; a live
row is never a candidate at any age, and an unreadable `revoked_at` is kept.

**The argv lane is unreachable from a device**, and that refusal is what makes
the tier gate real rather than decorative: `authorize_call` gates the METHOD
lane, while `{"argv": ["harness", …]}` reaches the CLI dispatcher where no tier
declaration exists. Without it a `read`-tier device refused
`runtime.agent.retire` sends the same verb as argv and is obeyed. It is a
REFUSAL rather than a second gate because gating argv means deciding a tier for
every CLI verb in this repo and keeping that map correct forever — the
duplicated-authority shape this stack keeps retiring.

**The loopback lane is byte-identical whether or not the gateway lane is up**,
and that is asserted directly rather than inferred: two steady-state boots
compared field by field on `ready` and on a loopback client's `hello_ok`
(`tests/agent_runtime/test_serve_gateway_lane.py`).

A `gateway` block rides `ready` / `hello_ok` / `version` on the same "states its
own outcome" rule as `socket`, and since R-L1 (2026-09-04) it has **four**
outcomes rather than three, because "there is no listener" had four causes and
one word:

| outcome | means | carries |
|---|---|---|
| `listening` | the door is open | `host`, `port`, `started_at`, `cert_fingerprint` |
| `disabled` | `remote_gateway.listen` is off. The default, forever | — |
| `socket_unavailable` | **the config asked for a listener and the socket lane is why there is none** | `reason` (the `socket` block's own outcome, verbatim: `disabled` \| `lock_held_by` \| `error:<token>`), `pid`, `owner_started_at`, plus the `host`/`port` that were asked for |
| `error:<Type>` | the bind or the certificate failed | `host`, `port` |

Never absent, and the capability list (R-IP16) rides every one of them.
`gateway_block_when_no_listener` (`hermes_cli/harness_parts/serve.py`) is the
one place the first three are decided, and config-off wins over
socket-unavailable: `disabled` is the actionable answer, while
`socket_unavailable` on a runtime nobody asked to listen would send a launcher
chasing a lock for a door it was never told to open.

**Why `socket_unavailable` had to exist.** The LAN listener is deliberately
coupled to the loopback lane — the serve that owns a root's socket is the serve
that opens that root's doors, or two serves bind one operator-chosen port and
the second loses that race too — so every way the socket lane fails is a boot
with no listener. Until R-L1 all of them said `disabled`, the word for "the
operator never asked", and on 2026-09-04 the launcher had *just* asked: it wrote
`remote_gateway.listen` correctly, respawned, the replacement lost the
socket-owner lock to a dead pid, and the greeting told it the feature was off.
The launcher rendered `unsupported` and the operator got a grey switch.
`socket_unavailable` also means the launcher's `unsupported` shrinks to its true
meaning — a runtime that predates this block.

Note that `socket_unavailable` can only ride `ready` and a stdio `version`
reply: in that state there is no loopback listener to greet on, so no `hello_ok`
exists to carry it. That is precisely why `ready` has to be complete.

**Operational note — the Windows firewall.** The port is operator-chosen, and on
Windows the first bind beyond loopback raises the Defender Firewall prompt
naming the PYTHON interpreter (not `hermes`), because the listener is a socket
in that process. Allowing it on Private networks is what a LAN pairing needs;
Public is the wrong answer and is what the dialog defaults to on some networks.
An operator who dismisses the prompt gets a listener that binds successfully and
is unreachable from every other machine — `ready` will say `listening` and be
telling the truth, which is why the firewall is named here rather than inferred
from a connection failure. A pinned `remote_gateway.port` is what makes a
`netsh advfirewall` rule writable in advance; an ephemeral port cannot have one.
**Undriven by any test in this repo.** It is driven from the product side
since S3-FW (2026-09-03): the launcher's host-firewall lane probes the rule,
escalates once, confirms it and retries (`EterniaLauncher/lib/core/services/host_firewall/`),
and the sentence this paragraph carried until 2026-09-06 — "and by nothing
else either" — is false. What is still honest is the Stage 1 gap in
[archive/remote-gateway.md](archive/remote-gateway.md): no test on THIS side
binds beyond loopback. The whole lane is drawn in
[09 — Multi-device runtime](09-multi-device-runtime.md).

### 1.2 The peer hello — the same door, a second kind of caller

Since the remote gateway's Stage 6 the gateway listener admits a second
credential: a paired INSTALL, not a paired device. `gateway/peers.json`, beside
`devices.json`, one row per edge — `{peer_install_id, display_name, endpoints,
cert_fingerprint, secret_verifier, approved_at, last_seen, revoked,
revoked_at}`.

The peer hello names `peer_install_id` — **the DIALER's own install id**, the
name it asks to be recognised under — and proves
`HMAC-SHA256(key=secret_verifier, msg="pwv1|<port>|<peer_install_id>|<nonce>")`
(`gateway_peers.peer_proof`). A hello naming `peer_code` instead redeems a
short-TTL code minted by `harness gateway peers pair` on the OTHER install, and
carries the joining install's own name, endpoints and fingerprint so the edge
can be dialled back; the minted secret rides that one `hello_ok` in a `peered`
block and never again.

**Both ends store `sha256(secret)` and key the HMAC with it directly.** That is
the difference from the device lane, where a phone holds a token and digests it
per connection, and it is what makes the edge symmetric: either install can dial
the other with the row it already holds. The install id in the message is what
that symmetry then requires — with one key and one nonce, A's proof to B and B's
proof to A would otherwise be identical bytes and a relay could bounce one back.
The `pwv` prefix (against the device lane's `gwv`) means a device proof does not
verify as a peer proof even at equal contract numbers.

**Exactly one credential per hello, counted rather than ranked.** A frame naming
two of `pairing_code` / `peer_code` / `peer_install_id` / `device_id` is refused
(`serve.py::_credential_kind`); the sole exception is a join's `peer_code` plus
`peer_install_id`, where the code is the credential and the id is the name being
claimed under it. Counting rather than a precedence, because a rule like "a peer
beats a device" is one refactor away from picking the more privileged one.
Neither door accepts the other's credential in ANY direction: the root token is
refused on the gateway lane, a pairing code on loopback, a device credential on
the peer field, a peer credential on the device field, and each code in the
other ceremony's verb.

**A peer holds an ALLOWLIST, not a tier** (`call_authorization.PEER_METHOD_ALLOWLIST`
— `{peer.ping, peer.agent_chat.execute}` since gateway Stage 7, seven at HEAD
with `peer.media.get` (P4), `peer.roster.list` / `peer.thread.read` (S2b,
read-only by R-IP9), `peer.announce` (S2c) and `peer.agent_chat.cancel` (D1.07,
the execute's Stop); the set and each member's
reason are in [09](09-multi-device-runtime.md)), and the arm
runs BEFORE the read-tier arm — which is open to
every caller, so a peer evaluated after it would inherit the whole read surface.
This is where canon 06's exclusion ("agents never mint or retire agents on
another install") stops being a sentence: `runtime.agent.create` and
`runtime.agent.retire` are absent from the peer surface because EVERYTHING is
absent unless it is in the set, and a test iterates the whole registry against
it rather than naming those two. A peer is refused every other method with the
same typed `data.reason: "scope_denied"`, and inherits Stage 1's two door
refusals (`drain`, the argv lane) because both key on the LANE and not on the
device stamp.

The four operator verbs are `harness gateway peers pair | join | list | revoke`.
**Every edge is approved on both sides (R5)** — not by a flag on a row but
because neither half of the ceremony can be performed by the other install: A
never learns B's address until B dials, and B cannot mint a code in A's store.
Revocation is likewise one-sided; reaching across would be one install writing
into another's credential store.

**Peer dialling reads endpoints from the PAIRING RECORD and never from a
registry file** (`gateway_peers.dial_peer`): the serve registry names ports on
the local machine, so a cross-machine read of it is not stale but impossible.
Staleness is R8's retry posture, built in Stage 7. Acceptance:
`tests/agent_runtime/test_gateway_peer_two_roots_e2e.py` — two real serve
children, two isolated roots, both CLI verbs, `peer.ping` A→B.

### 1.3 What an edge CARRIES — cross-install chat (gateway Stage 7)

An agent on install A addresses an agent on install B by qualifying the target
it already knows how to write: `@install_name/persona_or_instance`
(`agent_runtime/gateway_targets.py`, ruling R4). **Unqualified is local,
forever**, and that is a property of the parser rather than a default — a value
with no `/` never reaches the peer resolver at all. Ids outrank display names
and an ambiguous name is refused with both candidate ids, because names default
to the hostname and two roots on one machine really do collide.

**The dispatch row lives on the SENDER install.** `agent_chat_send(wait=false)`
records it exactly as it does for a local target, and the supervisor
(`tools/agent_chat_dispatch`) substitutes a peer-tier call for the child
PROCESS it would otherwise spawn — `peer.agent_chat.execute`, whose ack is an
ACCEPT and whose turn's frames ride the per-request lane the local launcher
already reads. B records the executed turn in its own chat store like any
inbound agent message. There is no distributed row and no two-phase state.
Cross-install sends are the DETACHED lane only: `wait: true` on a qualified
target is refused `remote_requires_detached`.

**Who asked comes off the CONNECTION.** B derives the calling install from
`context.caller.peer_install_id` — set only for a connection whose peer HMAC
verified — and lowers it to `--requested-by peer:<install_id>`. There is no
params key by which a peer names a different install; a correlation token
arrives by the other route precisely because a token is correlation and never
identity.

**Transport retries, an answer settles** (R8). A failed dial costs one of
`MAX_DELIVERY_ATTEMPTS` with a bounded per-attempt dial timeout; an install that
ANSWERED with a refusal settles the row immediately. The cap converges to a
terminal `error` completion carrying `peer_unreachable` — delivered, not
`dropped`, because "the other machine is not answering" is the fact the sender
most needs. Retrying is safe because `turn_request_id` is derived from the
dispatch id: B's reservation replays rather than running the agent twice.
Acceptance: `tests/agent_runtime/test_gateway_peer_cross_install_chat_e2e.py`.

**Known gap:** the relay chain does not cross an install boundary (it would be
an assertion the far side cannot check), so a cross-install dispatch is a fresh
chain root on B and **A→B→A across two installs is not detected as a cycle**.

### 1.4 The socket lane — the protocol, as `serve_socket.py`'s module docstring stated it

Relocated verbatim by lane R3's MOVE (the single-file module became the `agent_runtime/serve_socket/` package; ruling Q3: prose relocates, it is never a reason to split). The package map is `agent_runtime/serve_socket/__init__.py`; `hello_proof` in `agent_runtime/serve_socket/hello.py` stays the authority for the proof this prose describes.

The socket lane: one durable, multi-client serve per runtime root.

#### What this module owns

Transport mechanism only — bind, accept, authenticate, frame, count, close —
plus the ONE-OWNER lock that decides which serve gets to run the lane for a
root. It owns no protocol policy: every authenticated line is handed to the
injected ``dispatch_line`` callback, which is the SAME dispatcher the stdio
lane feeds. One dispatcher, N transports; a second copy of the op table is
exactly the duplicated-authority shape this stack keeps retiring.

#### Why localhost TCP and not a named pipe

A Windows named pipe would give a real ACL — the correct control — but only
through ``pywin32``, a dependency this runtime does not have and will not take
on for one transport slice. Loopback TCP on an EPHEMERAL port is available
everywhere Python is, keeps macOS/Linux on the same code path, and is reachable
by any local process — which is precisely why the hello handshake below is
mandatory and why the per-root token landed one slice EARLIER than this file
(``agent_runtime/serve_auth.py``). ``SO_REUSEADDR`` is deliberately NOT set: on
Windows it permits a second process to bind a port already in use, which would
turn "the address is taken" into a silent hijack.

#### Auth is first, and the token never travels

The SERVER speaks first. On accept it writes exactly one frame::

    {"event":"server_hello","nonce":"<64 hex chars>","boot_id":…,
     "contract":<frame schema>,"hello_contract":3,"algorithm":"hmac-sha256"}

and the client answers::

    {"op":"hello","client":…,"client_build":…,
     "proof":"<hex HMAC-SHA256(key=token, msg="v3|<dialled port>|<nonce>")>"}

**The message is not the bare nonce**, and the two spellings above were wrong in
both halves until 2026-08-27: this block said ``hello_contract`` 2 and
``msg=nonce`` while :data:`HELLO_CONTRACT_VERSION` has been 3 and
:func:`hello_proof` has bound the PORT since the relay defence landed. A client
written against the prose computes a proof over the wrong message and is refused
with ``bad_proof``, which is the least debuggable possible failure — it looks
exactly like a wrong credential. Found by the launcher's socket client actually
being built against it (launcher `527940a0e`). :func:`hello_proof` is the
authority; this paragraph is a description of it and must be re-read against it,
never trusted over it.

Before that proof is verified a connection can do exactly nothing: no ops, no
subscription, no answers. A wrong or missing proof gets ONE typed
``hello_rejected`` frame and the connection is closed.

Why a proof and not the token (the hardening this replaced)
    The first cut sent ``{"op":"hello","token":<raw>}``, and discovery could
    hand a client a target it had itself classified ``stale_dead_pid`` — so a
    local impostor that bound the dead serve's port harvested the real token in
    cleartext, live-proven. Two independent halves close that: discovery
    returns LIVE rows only (:func:`resolve_socket_target`, with a non-live row
    reachable exclusively through an explicit ``allow_stale=True`` that carries
    the classification so the caller must refuse it by name), and the token
    itself never traverses the wire at all. A stolen transcript is unreplayable
    — the nonce is fresh per CONNECTION — and an impostor server learns only
    one HMAC, bound to the port the victim DIALLED, which therefore does not
    verify at the real service's port. That binding is load-bearing and was not
    in the first pass: freshness alone stops replay but not a live relay, since
    an impostor can dial the real service, adopt its nonce as its own
    challenge, and forward the answer. Binding to anything the greeting merely
    asserts (`boot_id`, a claimed port) would be binding to a number the
    impostor echoes; the dialled port is the one value each end knows from its
    own socket. The token value still appears in no frame, no log line, no
    error, and no registry entry; the proof is the only derived artifact.

    ``hello_contract`` is versioned on the ``server_hello`` frame precisely so
    the future Launcher client asserts the handshake it was written against
    instead of proceeding on hope. There is no compatibility shim: the socket
    lane has no other clients yet, and a shim that accepted the old token hello
    would keep the cleartext lane open forever.

Repeated AUTH failures trip a rate limiter, so a local process cannot grind the
256-bit secret by reconnecting. Capacity, drain, and handshake-timeout
rejections are NOT auth failures and never touch that limiter — charging them
to it produced a permanent self-sustaining lockout (a ``rate_limited``
rejection re-armed its own window, so 12 polite retries with the RIGHT
credential over 12s never recovered). Handshake timeouts have a throttle of
their own, and pre-hello connections have a bound of their own: counting only
AUTHENTICATED peers against ``max_connections`` let 64 silent sockets sit on
the runtime's threads without a single rejection.

#### Two listeners, one implementation (Stage 1)

This class binds the LOOPBACK lane, and — when an operator opts in — a second
GATEWAY listener bound beyond loopback. They are the same class with three
constructor arguments filled in, deliberately, because the hardened parts here
are the parts a second copy would get wrong: the accept loop that announces its
own death, the pre-auth bound that counts peers who have proven nothing, the two
rate limiters and the rule that server-state refusals never charge the auth one,
the lingering close that keeps a rejection frame alive. A second listener class
would be a second place all of that has to stay true.

The three arguments, all defaulted to what the loopback lane has always done, so
a server constructed without them is byte-identical to the one that shipped:

* ``port`` — 0 (ephemeral) by default; pinned for an operator who has to write a
  firewall rule and tell a phone a number that survives a restart.
* ``ssl_context`` — ``None`` by default. The loopback lane stays PLAINTEXT and
  that is the local trust model unchanged: a local process that could read the
  token file gains nothing from a TLS layer, and adding one would cost every
  local client a handshake to protect a wire that never leaves the machine. The
  gateway lane is wrapped (R1: encrypt, self-signed per-install certificate,
  fingerprint pinned by the client).
* ``authenticator`` — ``None`` means the per-root token, i.e. the code that was
  inline here before the seam existed. The gateway lane injects a per-DEVICE
  check (``serve_gateway_auth.py``), which is the only way a connection ever
  gets a ``device_id``/``device_tier`` stamp, which is in turn the only way
  ``call_authorization`` mints a ``device`` caller.

What the gateway lane does NOT get is a second dispatcher, a second op table, or
a second hello contract. It answers the same ``server_hello``, over the same
frame vocabulary, into the same ``dispatch_line`` callback. Where it must differ
— the credential, the encryption, the ops it is offered — it differs by an
argument, not by a branch.

#### One owner per root

Two serves can legitimately run against one root (a launcher restart overlaps
its replacement; a QA lane spawns its own). Only one may own the socket, or
"connect to the service for root X" has two answers. The winner is decided by
an OS-held exclusive lock on ``<store_root>/serve_socket.lock``, held for the
process's lifetime, following the same ``msvcrt.locking`` / ``fcntl.flock``
pattern as ``agent_runtime/locks.py``. The loser does not fail: it runs
stdio-only and SAYS SO on its ready frame
(``socket: {"outcome": "lock_held_by", "pid": …}``). A silent degrade here
would be indistinguishable from a socket that never worked.

**It retries in exactly one case, and the case is written down** (RS-4,
2026-09-07). This paragraph used to end "and does not retry", and that was the
rule the operator's restart broke: a build-behind restart drained the old
runtime, the replacement asked for the lock 14 s into that drain, and the old
owner was alive and holding it — because the lock is released at the END of a
drain, after the in-flight work. The replacement degraded permanently against a
process that was about to let go. So a contender that can PROVE the holder is
leaving — ``draining_at`` on the sidecar, or a holder with no registry row —
polls the lock every :data:`SOCKET_LOCK_DRAIN_POLL_SECONDS` for up to
:data:`SOCKET_LOCK_DRAIN_WAIT_SECONDS` and takes the lane when it frees,
reporting ``took_over_from`` and ``waited_for_drain_ms``. A holder that is alive
and SERVING is refused immediately, without one poll, exactly as it always was;
a wait that expires degrades exactly as today and carries the number.

The holder's identity lives in a sidecar, ``serve_socket.owner.json``, and not
in the lock file itself: on Windows ``msvcrt.locking`` is a MANDATORY lock, so
a loser cannot read the bytes of the file it just lost. The sidecar is also
where a leaving owner announces itself: :meth:`SocketOwnerLock.mark_draining`
stamps ``draining_at`` on it as the FIRST act of the drain, before the listener
closes, so no window exists in which the lane refuses new connections while
still advertising itself as healthy.

**A DEAD owner is not an owner** (R-L2, 2026-09-04). The sidecar outlives its
process — a killed serve never gets to unlink it — and until this stage a boot
that found one simply believed it. On the operator's machine that cost a whole
session: the replacement serve read a sidecar naming a corpse, answered
``lock_held_by``, ran stdio-only, and therefore never opened the LAN listener
the operator had just enabled. :class:`SocketOwnerLock` now proves the pid with
the same probe the registry uses for ``stale_dead_pid``
(``serve_registry.pid_alive``) and, when it is provably gone, takes the lane and
says so: ``took_over_from`` and ``owner_started_at`` on the block, and one
``serve_socket_owner_takeover`` line on the service log. A LIVE owner is refused
exactly as before.

#### Fingerprint exclusion (load-bearing)

``serve_socket.lock`` and ``serve_socket.owner.json`` MUST NOT be added to any
freshness fingerprint — not serve's ``_FINGERPRINT_ROOT_FILES`` /
``_FINGERPRINT_STORE_DIRS``, not ``stream._scope_fingerprint``, and they MUST BE
PRESENT in ``core_cache._EXCLUDED_STORE_ENTRIES``. They appear at
the first socket boot and vanish on every clean exit, which inside a
fingerprint would cold the read-model cache exactly when a fresh runtime is
warming up and make the stream emit ``state.reconciled`` on every restart. Same
standing precedent as ``dispatch_delivery.DRAIN_STATE_FILENAME``,
``paths.SERVE_AUTH_TOKEN_FILENAME``, and ``serve_instances/``.

The sentence above names TWO obligations because there are two fingerprint
designs in this runtime with OPPOSITE defaults, and one doctrine written for the
first silently fails to bind the second. Serve's read-cache key and
``stream._scope_fingerprint`` are ALLOWLISTS — a file nobody enumerates is
already out, so "do not add these" is satisfied by inaction.
``core_cache.build_input_fingerprint`` is a DENYLIST walk of the whole store
root — everything not named in ``_EXCLUDED_STORE_ENTRIES`` is IN, so the same
words there require an action, and until 2026-08-18 nobody had taken it: both
files sat inside the read-model core's key and cost it a hit on every boot. A
new store-root writer has to satisfy both halves; naming only the allowlists is
how this one was missed.

#### Root as INPUT

Every entry point takes ``store_root``. This module never resolves a root and
never reads ``HERMES_HOME``: multiple roots coexist on this machine, and a
transport free to re-derive its own root could bind a socket for one root while
answering from another — silently, because both answers would be well-formed.

## 2. Capability advertisement — `rpc` and `ops`

A durable service outlives the install it was started from, so "what does the
thing I am attached to carry" must be answerable at any time. Two manifests ride
`ready` (stdio), `hello_ok` (socket), and the re-askable `version` reply:
`"rpc"` from `serve_rpc.manifest()` (`agent_runtime/serve_rpc/`) and `"ops"`
from `ops_manifest(transport=…)` (`serve.py::ops_manifest`),
`{"contract", "transport", "ops", "subscribe_lanes", "service"}`.

`service` is read two ways and both are deliberate (L-h, 2026-09-05). Its
PRESENCE says this runtime understands `--service` at all — a hermes predating
the flag carries no `service` key anywhere, which is the launcher's membership
gate for falling back to the stdio-pipe transport — and its VALUE says whether
this process is running as one. The same fact, plus `starter_pid` (the parent at
BOOT; a detached service is reparented the moment its starter exits), rides all
three greeting frames as top-level keys beside `pid` and `boot_id`, and the
registry row. The contract integer did not move: an added key on an existing
block is the set-plus-integer rule these manifests already use.

`ops` answers PER TRANSPORT because the answer genuinely differs, and there are
now three answers rather than two: `shutdown` is stdio-only (it is the verb of
the process that owns the pipe), and `drain` is additionally absent from the
`gateway` answer — it ends the runtime for every other attached client, which a
paired device does not get to decide even at `console` tier. A device learns
what it may ask by MEMBERSHIP; the manifest and the dispatcher cannot disagree,
because both read one tuple (`OPS_EVERY_TRANSPORT` minus `OPS_GATEWAY_DENIED`).

**`hello_ok` also carries `reached_at: {host, port}` — the one address on this
lane that is measured rather than inferred** (D12, ruled 2026-09-05). It is the
accepting socket's own `getsockname()`, read once at accept
(`serve_socket/wire.py::_reached_at`, parked on `SocketConnection.reached_at`), so on
a wildcard bind it names the single interface *this* connection arrived on — the
address that demonstrably carried a packet, as against the routing-table read
(R-D8) and datagram probe (R-D2) every published candidate comes from. The same
value rides each `connections` row (`SocketConnection.payload`), which is how
the accepting install's own launcher reads it, and the `gateway peers join` ack,
copied off the frame and never re-derived. Absent — never fabricated — when the
socket cannot answer, when the sockaddr is not an IP one, or when the host is a
wildcard: R-D1's "never hand out a bind address" held at a new door. On the
loopback lane it honestly reads `127.0.0.1`; a consumer promoting it to a
published endpoint reads `transport` first.

**The `rpc` roster is THIRTEEN methods, and each is named by its handler** —
every one registered by a `@method("…")` decorator in `serve_rpc.py`, which is
the only registration site, so this list is
`grep -rn '@method(' agent_runtime/serve_rpc/` and nothing else:

| Method | Handler | Domain |
|---|---|---|
| `runtime.office.get` | `_runtime_office_get` | read the level |
| `runtime.office.subscribe` | `_runtime_office_subscribe` | office push lane on |
| `runtime.office.unsubscribe` | `_runtime_office_unsubscribe` | office push lane off |
| `runtime.office.upsert` | `_runtime_office_upsert` | place / move |
| `runtime.office.remove` | `_runtime_office_remove` | delete |
| `runtime.office.surface.update` | `_runtime_office_surface_update` | folder taxonomy |
| `runtime.office.resolve_conflict` | `_runtime_office_resolve_conflict` | realm-sync resolve |
| `runtime.agent.create` | `_runtime_agent_create` | roster row + chat root + actor |
| `runtime.agent.retire` | `_runtime_agent_retire` | the inverse of the above |
| `runtime.persona.prewarm` | `_runtime_persona_prewarm` | warm a persona |
| `runtime.chat.message` | `_runtime_chat_message` | send one mission-chat turn |
| `runtime.chat.steer` | `_runtime_chat_steer` | steer the running turn |
| `runtime.media.index` | `_runtime_media_index` | what media this install can hand over |
| `runtime.media.get` | `_runtime_media_get` | one artifact's bytes, by content handle |
| `peer.ping` | `_peer_ping` | is the install⇄install edge alive |
| `peer.agent_chat.execute` | `_peer_agent_chat_execute` | run one chat turn for a paired install |
| `peer.agent_chat.cancel` | `_peer_agent_chat_cancel` | stop the turn a paired install's execute started |

**Row count corrected 2026-08-27 (gateway Stage 6).** This table said TEN and
listed ten while the runtime had twelve: Stage 3's `runtime.chat.*` pair landed
in the manifest and in four literal pins but not here. The two rows above are
that correction, made while adding the thirteenth rather than filed for later.
**Fourteen since gateway Stage 7** added `peer.agent_chat.execute` (§1.3), and
**SIXTEEN since gateway Stage 8** added the two `runtime.media.*` verbs
(§2.1).

**`peer.agent_chat.cancel` (D1.07).** Cancel is owned by the process that
supervises the work; for a cross-install dispatch that is the install running
the turn. The sender (`tools/agent_chat_dispatch/remote.request_remote_cancel`,
reached from `running_work.cancel_work("dispatch:…")` in any process) writes the
row's durable `cancel_requested`, dials ONCE at the dial timeout and sends
`{dispatch_id, reason}`. The owner (`agent_runtime/peer_chat_cancel.cancel_peer_turn`)
re-derives the execute's `turn_request_id` (`chat_turn.dispatch_turn_request_id`,
`agent-dispatch-<id>` — a wire literal between builds), refuses to see a receipt
whose replay scope names another install, and answers `stopping` (the receipt's
`stop_requested` made durable for a queued turn, then the serve's
`interrupt_operator` seam), `already_finished` (with `exit_code`) or
`not_running`. A stopped turn keeps the partial output it wrote (owner ruling
2026-10-10). The sender's own supervisor reads the mark before every attempt and
after an accept, so it never re-sends the execute after a Stop, and forwards the
cancel on its own edge when the Stop raced the accept. An install that cannot be
reached answers `peer_unreachable`; one without the verb, `peer_refused`.

`peer.ping` is the first name outside the `runtime.*` family, and the prefix is
a declaration: `runtime.*` verbs act on this install's level — read it, mutate
it, or run an agent on it — while `peer.*` verbs are about the EDGE between two
installs and touch no level at all. A client can tell them apart without
consulting a table, which matters most for the one surface an operator on
another machine is asked to trust.

**Each method also declares a TIER, and the map rides `rpc` beside `methods`**
(`"tiers": {"runtime.office.get": "read", …}`, hermes `8d69f8858b`). The
classification rule is one line: a level MUTATION is `console`, everything else
is `read` — so the four office writes and both agent verbs are `console`, and
`get` / `subscribe` / `unsubscribe` / `prewarm` are `read`. `prewarm` sits with
the reads because its own contract is that it writes no store state, emits no
event and mints no id; spending CPU is a rate-limiting question, and rate
limiting is not a tier.

The tier is REQUIRED at the registration — `@method(name, tier=…)` has no
default, so a tierless method is unrepresentable rather than merely untested,
and an unknown tier raises at import. Adding the block moved no contract
integer: it is a key beside `methods`, not a shape change to any existing
method's request or result, which is exactly what the set-plus-integer rule
below permits. The launcher reads it (`MissionRuntimeRpcManifest.tiers`) and
branches on nothing — a manifest says what a call WANTS, never what a connection
HOLDS. The enforcement is `serve_rpc.handle_request`'s gate; see
[06 §authorization](06-office-and-board.md).

**A third map rides beside them: `params`, which says which KEYS a method
honours** (`"params": {"runtime.chat.message": [...], "runtime.chat.steer":
[...]}`, R-C8). The method lane ignores an unknown param rather than refusing it
— a client cannot be refused for a key a runtime has never heard of — and that
kindness is exactly what made a client unable to trust the lane: on 2026-09-06 a
console send from Windows to a Mac never left the launcher, because the
launcher's lowering could see that `runtime.chat.message` EXISTS and not that it
silently dropped `workspace_name`, so it fell back to argv and argv to a remote
install is a designed wall. Publishing what is heard is what makes ignoring the
rest safe. The block covers the two chat verbs and only those — they are the
ones whose surface an operator types into, and a block claiming to be exhaustive
over twenty-six methods would be a promise `manifest()` cannot keep. The lists
are derived from `chat_turn`'s own `CHAT_MESSAGE_PARAMS` / `CHAT_STEER_PARAMS`
tuples, which the normalisers read, and a test drives each normaliser through a
recording mapping to assert the advertisement equals the keys actually asked
for. Additive under the same rule as `tiers`: no existing request or result
shape moved, so the integer holds, and a manifest with NO `params` block reads
as "a runtime that predates R-C8" — the launcher falls back to the eleven keys
it knew — rather than as "no params".

**`images` on `runtime.chat.message` (RT-OPERATOR-CHAT-SEND-PERSONA, 2026-10-18).**
`[{media_type: image/png|image/jpeg, data_b64}]`, at most 4, each at most 5 MiB
decoded, magic bytes matching the declared type; refusals `image_invalid` /
`image_too_large` at the door. The bytes are stored content-addressed under
`<store root>/operator_images/` and the argv names each as `--image
sha256:<hex>.png|.jpg` (never a path, never bytes), so the accept fingerprint
covers them. The turn refuses `vision_unsupported` (admission family) when
upstream's `agent.image_routing.decide_image_input_mode` answers `text` for the
model it runs on; otherwise the provider gets upstream's
`build_native_content_parts` and the transcript row carries one `MEDIA:<path>`
line per image (the bubble, and `runtime.media.get`'s derived scope). Module:
`agent_runtime/operator_images.py`.

**`files` on `runtime.chat.message` (RT-MISSION-CHAT-MESSAGE-TAKES, 2026-10-19).**
`[{name ≤200, media_type, data (base64)}]` — the native lane's `prompt.files` item shape —
bounded by `rpc.limits.files` (8 files, 256 KiB each, 512 KiB together, `text/*`, json,
xml, yaml, csv, pdf). Refusals at the door are the native spellings, `file_unsupported` /
`file_oversize` / `file_invalid` (`ChatTurnInvalid.reason`). The bytes are stored
content-addressed under `<store root>/operator_files/<sha256>.<ext>` with a
`<sha256>.name.json` sidecar, and the argv names each as `--file sha256:<hex>.<ext>`. A
file is STAGED, never inlined (owner ruling 2026-10-19): the turn's request text and its
user row gain one guidance sentence and one `FILE:<path>` line per file, before any
`MEDIA:` lines, and the agent reads what it needs with `read_file`. A `FILE:` line joins
`runtime.media.get`'s derived scope only when its path sits directly in that store
(`media_handles._DECLARATION_ADMITS`). `RPC_CONTRACT_VERSION` does not move. Module:
`agent_runtime/operator_files.py`.

**The tier is now a refusal, and what it refuses is a paired device** (Stage A5,
landed with the gateway's Stage 1). `authorize_call` compares the tier a
device's record HOLDS — read off `gateway/devices.json` by the transport, fixed
at a pairing ceremony only an operator at this install's own machine can run —
against the tier the verb DECLARES, and answers a `read`-tier device asking for
a `console` verb with the typed `data.reason: "scope_denied"` the launcher's
decoders already branch on. Nothing local moved: `local_console` and
`stdio_owner` are grandfathered exactly as A3 left them, because a device's
authority was added BESIDE that set rather than folded into it — two callers
whose authority comes from different kinds of fact should not share one
membership test. Reads stay open to `unknown`, deliberately and not by
omission: nothing on the read side mutates a level.

**A PEER is refused by an allowlist rather than by a tier** (Stage 6, §1.2).
`PEER_METHOD_ALLOWLIST` was `{peer.ping, peer.agent_chat.execute}` (Stage 7
widened it by one, §1.3, with the reason in a comment beside the set; the
same-account pairing lane and P4 took it to six — §1.2 names them — and D1.07's
`peer.agent_chat.cancel` to seven) and the
arm runs before the read-tier
arm — which is open to every caller, so a peer evaluated after it would hold
this runtime's entire read surface including verbs nobody has written yet. The
choice of an allowlist over a third tier word is about what happens as the
registry GROWS: a tier comparison admits every future verb declaring that word,
where a membership test admits nothing it was not edited to admit. So canon 06's
exclusion holds by construction, and the test that pins it iterates
`method_names()` rather than naming `runtime.agent.create` and
`runtime.agent.retire` — a rule pinned by two literals stops being pinned the
moment a third verb arrives.

`peer.ping` itself declares `read`, and that is not a lie to device or console
readers. The map answers what a call WANTS, never what a connection HOLDS, so a
verb that reads no store, writes nothing and mints no id belongs with
`runtime.office.get`; a read-tier device may indeed call it. The allowlist
NARROWS the peer lane and does not widen this row. A third tier word only one
caller kind could hold would put a value in the map every existing reader must
be taught to ignore.

`peer.agent_chat.execute` declares `console` by the same rule read the other
way: a chat turn runs an agent with tools, so anything softer would be a door
around `console` — the same answer `runtime.chat.message` gives. The tier is
still not what admits a peer, and the verb refuses a non-peer caller with its
own `peer_identity_required` rather than `scope_denied`: the chokepoint DID
admit a console caller, and it is the VERB that has no provenance to run under.

**Both `runtime.media.*` verbs declare `console`, and this is the row where the
one-line rule does NOT decide it** (gateway Stage 8). Neither mutates anything,
so the rule as stated would put them with the reads. They are `console` for two
reasons the rule does not cover. Handing a caller the raw BYTES of a file on
this machine is an EGRESS, not a read of the level. And the read tier is
deliberately open to `unknown` — a caller the transport authenticated and could
not place — which is exactly the caller who must not be able to pull files off
the disk; A5 kept that arm open on purpose, so a `read` declaration here would
have been a hole shaped like a classification. It also settles what a
`read`-tier device gets: a viewer is a viewer of the LEVEL, not a subscriber to
every proof screenshot on the machine.

This table used to be a list of ten LINE NUMBERS. Two of them (`2055`, `2115`)
had already rotted by 2026-08-27 — a slice landing above them moved both — while
the sentence around them still read as verified. A method name is what a client
sends and a handler name is what `@method` binds it to; neither moves when
somebody edits the function above.

Both follow one discipline: **a set plus an integer.** The set grows when a verb
is added — a client only ever sends a verb it FOUND — and the integer moves only
when an existing verb's shape changes incompatibly. `ops` is answered **per
transport** because the answer genuinely differs: `shutdown` is the stdio
owner's verb and is refused on the socket, so `OPS_STDIO_ONLY` (`:289`) is
unioned in only for stdio, and the block names the transport it describes so a
cached copy cannot be mis-applied.

**The push gate is `subscribe_lanes`, not `ops`.** `"subscribe" in ops` says the
op is dispatched; `"stream" in subscribe_lanes` says THIS lane is carried
(`SUBSCRIBE_LANES = ("stream",)`, `:295`). A runtime predating the advertisement
carries no `ops` key — read that as "undiscoverable, keep the existing lane",
not as a failure. The advertisement exists because a probe cannot distinguish
"too old" from "refused THIS subscribe": `unsupported_lane`, `draining` and
`already_subscribed` are all real answers a live lane gives (`:2595-2651`).

**A third block rides the same three frames, and it is not a manifest.**
`"install"` — `{install_id, display_name, state}`, resolved once per boot from
`agent_runtime/gateway_identity.py` and echoed on `ready`, `hello_ok` and every
`version` re-ask — answers *which runtime you reached*, where `rpc`/`ops` answer
*what it can do*. It rides the greeting for the same reason they do: a client
that must ask a second question has a window in which it does not know, and from
the remote gateway's Stage 2 a client on another machine has no `runtime_root`
path it can interpret. It is a pair of strings, not a set plus an integer, so
nothing negotiates on it and its arrival moved no contract integer
(`SERVE_SCHEMA_VERSION`, `RPC_CONTRACT_VERSION` and `OPS_CONTRACT_VERSION` are
all unchanged by it). Three rules hold it:

- **It names; it never authorises.** The per-root `serve_auth` token proves a
  caller may talk to this runtime, and the device/peer tiers will do so remotely.
  An id that did both is how "I know your install id" becomes "I am you".
  Nothing secret is reachable from the block.
- **It states its own outcome.** `state` is `loaded` | `minted` |
  `error:<reason>`, so a runtime that could not write its identity is
  distinguishable from one that predates the lane — which absence alone cannot
  say. Same rule as `auth.token_file` and `socket.outcome`.
- **It is resolved at boot, not per frame.** A `version` re-ask echoes the block
  the greeting carried, so an operator rename mid-session cannot make a later
  frame disagree with the handshake a client correlates against.

The record is `<store_root>/gateway/install.json`, per store root and
mint-iff-absent — deliberately NOT `monitoring.install_id` (home-scoped and
rotatable by design) nor the telemetry `install_id` (an anonymity primitive).
The argument is in the module's own docstring; the staged plan is
`archive/remote-gateway.md`.

### 2.1 The `fetch` family — media by content handle (gateway Stage 8)

`runtime.media.index` answers `{contract, cap_bytes, truncated, artifacts:
[{handle, reference, media_type, size_bytes, fetchable}], scanned: {logs,
declarations}}` and takes no argument but `correlation_id`.
`runtime.media.get` takes `{handle}` and answers `{contract, handle,
media_type, size_bytes, encoding: "base64", data}`.

**Why two verbs.** A chat image reaches a client as a `MEDIA:<absolute path>`
line inside the message TEXT — there is no media field on any chat record and no
blob store under the store root — so the client's only pointer is a PATH, and it
cannot compute a content handle from one. `index` is the bridge: each row
carries the `reference` the client already rendered AND the `handle` it may
spend.

**A reference travels OUT and never IN, and that asymmetry is the security
story.** What comes back is a string the caller already read out of a message it
was allowed to read. What goes in is `sha256:<64 hex>`, refused by a regex
before the process constructs a `Path`, so there is no traversal surface — there
is no step that turns caller input into a path. A handle resolves only by
LOOKUP in a set the server enumerated itself.

**The scope is DERIVED, never registered** (`agent_runtime/media_handles.py`).
It is rebuilt per call from the chat live-log mirror
(`<head-home>/chat_live_logs/*.jsonl`), through that module's own
`capture_chat_live_log_root` rather than a second resolution ladder. There is no
handle registry to drift, and the per-file digest memo is keyed on
`(path, size, mtime_ns)` so a rewritten file mints a new handle instead of
serving the old one's bytes.

**Two bounds beyond reachability.** Only files whose extension is in the image
set ever become handles — `MEDIA:` is a line the MODEL writes, so reachability
alone would put `MEDIA:~/.ssh/id_rsa` in the namespace; the allowlist makes a
credential unrepresentable rather than rejected. And `MAX_FETCH_BYTES` is 5 MiB,
which is `gateway/platforms/api_server.py`'s `_MEDIA_DATA_URL_MAX_BYTES` reused
rather than re-decided: the same question about the same protocol. Consequence,
stated rather than hidden: video and PDF have no handle at all.

Refusals branch on `data.reason`: `handle_invalid` (where a path-shaped argument
lands), `unknown_handle`, `artifact_too_large` (carrying `cap_bytes` and
`size_bytes`), `artifact_unreadable`. No ranging exists, because no artifact
measured on this machine exceeds the cap.

**`PEER_METHOD_ALLOWLIST` was not widened**, so a paired install is refused both
verbs by construction — the property the iterated registry test asserts about
the rule rather than about names. Cross-install media is an open row.

**The proxy arm's dial is off the reader loop (2026-09-02).** Stage P4 shipped
it inline and filed the cost: a handle that resolves to a `RemoteMediaArtifact`
made this loop wait on another machine's power state — up to
`media_proxy.PEER_DIAL_TIMEOUT_SECONDS` to give up dialling, up to
`PEER_READ_TIMEOUT_SECONDS` more if the far install accepted and then went
quiet — with every other request from that client queued behind it. The fetch
now goes to the SAME worker pool the chat lane uses, through
`RpcContext.spawn_reply`, and the finished frame is emitted from the worker on
this request's own `id`.

The seam is `spawn_chat_turn`'s argument made general: a chat turn hands the
pool a whole request and acks, this hands it the TAIL of one — a callable
returning the frame the handler would have returned. A handler that takes it
returns `serve_rpc.DEFERRED`, and the dispatcher's one job is not to write that
sentinel (`serve_rpc.is_deferred`). Three things deliberately did not move: the
frame (byte for byte, refusals included), the bound (`media_proxy`'s two
timeouts stay the only clock — a watchdog on the reader would be a second one,
and the long-run lane's rule is that work is bounded at its source), and the
LOCAL arm, which never dialled. What moved is arrival ORDER, which JSON-RPC
2.0 §6 already requires a client to tolerate and which this lane's own clients
already do (`media_proxy._ask` correlates on `id` and skips the rest). The seam
declines while DRAINING — a drain is waiting for that pool to empty — and a
handler that finds it absent (a test-built context, a transport with no pool)
answers on its own thread.

**The ten `runtime.realm.*` verbs ride the same seam (2026-10-06, lane h-newchat-t1).**
`status` fetches the realm remote and walks every store for drift; inline, the launcher's
periodic poll held the reader loop from 01:25:01 to 01:25:04 local and the operator's first
chat send of a new chat was accepted only after it (`send_to_admit_ms=2564`, turn
`5377d205`). `agent_runtime/serve_rpc/realm.py` now offers each verb to `spawn_reply` and
runs them one at a time among themselves (`_REALM_VERB_LOCK`), which is the serialization the
inline lane used to give them for free.

**`runtime.realm.revoked` records backend `realm.revoked` (2026-10-18, lane w2-realm).** Hermes
holds no realtime subscription and no credential between calls, so the launcher, which receives
the durable `personal:` event, forwards `{realm_id, reason}` (the backend's `RealmRevokedReason`).
`agent_runtime/realm_sync/revocation.py` writes `realm_sync_state/<realm>.revoked.json`: the realm
and its local data stay, the snapshot's realm `sync.revoked` carries `{reason, revoked_at,
host_state}` (`host_state` true for `git_host_unbound`), and every credentialed sync verb refuses
`realm_revoked` (not retryable) before any network call — `status` degrades to its local half. A
re-adopt lifts the mark. Method lane only; it rides `_REALM_VERB_LOCK` with the ten. The credential
mint's permanent `409 realms.git_host_unbound` / `409 realms.git_host_binding_lost` are forwarded
through the same verb (`reason` may be either `error.code`, `BACKEND_REFUSAL_REASONS`) and become
host-state marks — never `sync_remote_unreachable`, the retryable 503's word. No `realm.granted`
follows a reconnect, so a host-state mark is lifted by the next call carrying an admitted credential
(the mint re-verified the binding); a membership mark is lifted only by a re-adopt.

## 3. The mission-control stream

`agent_runtime/stream/session.py::stream_frames` (the whole function at `:1221`) is the single producer body.
It yields exactly one `hydrate`, then tails the event log from that frame's
`watermark.event_offset` (`_resume_offset`, `:305`) emitting `patch`, full-core
`delta`, and `heartbeat` frames. **An unknown resume position is not byte 0**:
`_resume_offset` returns `None` rather than folding a missing watermark key and
an explicitly-unknown one into `0`, because tailing from `0` replayed the entire
event log as fresh activity at the root of every Mission Control surface
(`:883-889`).

**Freshness backstop.** Every store mutation is supposed to append an event; a
write that slips the rule would freeze watermark-gated consumers forever, since
they drop same-offset re-hydrates. At heartbeat cadence the loop fingerprints
the scope/catalog state no evented store guards, and a fingerprint change with
no offset advance appends a synthetic `state.reconciled` that flows out as an
ordinary full-core delta (`_scope_fingerprint`, `:1194`;
`_append_state_reconciled`, `:1346`). SLO: staleness ≤ 2× heartbeat interval.
Every `state.reconciled` names a producer bug to fix at source.

| Frame | Builder | `schema_version` | Carries a core? |
|---|---|---|---|
| `hydrate` | `hydrate_frame` (`:223`) | 1 | yes — the full snapshot under `core` |
| `delta` | `delta_frame` (`:376`) / `delta_batch_frame` (`:393`) | 1 | yes — ONE core per batch |
| `patch` | `patch_batch_frame` (`:456`) | 2 | **no** |
| `heartbeat` | `heartbeat_frame` (`:328`) | 1 | no |
| `running_work` | `running_work_frame` / `running_work_section_frame` (`stream/frames.py`) | 1 | **no** — the `running_work` section alone (un-sequenced overlay, or sequenced for a `running_work_section` room) |
| `persona_chat_turn` | `persona_chat_turn_frames` (`stream/frames.py`) | 2 | **no** — one chat root's turn sections |

The chat lane's per-request protocol-v2 frames (`turn.start`, `segment.*`, `tool.*`,
`reasoning.summary`, `turn.end`, then `chat.final`) are not stream frames and have no row here;
their one additive turn-end pair — `reasoning_tokens` / `reasoning_ms` on `turn.end` and
`chat.final`, and on each history-replay `thinking_summary` message carried in the core's
operator-channel conversation — is doc 05 §2b. Every `segment.delta` carries `t_ms`: an int,
milliseconds since that turn's emitter started (`_ChatProtocolV2Emitter._started_at`, monotonic),
stamped at emit, so a consumer can tell which hop bunches streamed text (launcher `MC-STREAM-CHOPPY`).

`persona_chat_turn` (plan h-turn1 §2 C1/C2) replaces the demote core of a batch
made ONLY of chat-turn events (`batch_turn_roots`: the three `persona_chat.*`
publishes and the chat-trace `run.*`; anything else in the batch, including
`gateway.peer.updated`, keeps today's core) for a subscriber that declared the
`persona_chat_turn` capability token (`patch_coverage.PERSONA_CHAT_TURN_CAPABILITY`).
One frame per root, chained: `base_offset` / `watermark` exactly as `patch`
carries them, so the client consumes the batch with it behind its gap gate. It
carries the root's `persona_chat_history` row (`null` with `omitted: true` when
the core's 50-row bound leaves the root out — `only_session_ids` narrows AFTER
that bound; the bound ranks by activity with every instance's bound chat pinned,
and emits the kept rows in creation order, `HistorySummary.activity_key`), its `operator_channel`, its `persona_instance` row
and `running_work`, each built by the core's own section builders over the full
instance list, so each equals the row a full core would carry. Not
`prompt_observability`, not `events`: they wait for the next core. A mixed room
gets the overlay and the demote core in one `fold_variants` envelope; the two
subscribers of one launcher share one read through `turn_section_reuse`
(position-keyed, as `demote_core_reuse`). A read that fails demotes the batch
as before. Receipt: `turn_section reason=<start|end|trace> root=… source=<built|reused> … executor=<worker|in_process|-> worker_pid=…`.

With the resident snapshot worker bound, the sections are read IN the worker
(`snapshot.turn_section`, `turn_section_read.read_turn_sections`) on their own
thread beside any build; the serve keeps `running_work` and sends its chat-runtime
registry as an export (`runtime_registry.export_runtime_observations`), so a
worker-built history row (overlay or core) carries the serve's `runtime_state`.
A lost worker reads in process under `snapshot_turn_yield`, as before.

A new chat's open (the instance's `state.patched` upsert, never `created`, plus
`persona_instance.chat_opened`, beside the new root's turn) rides the overlay
only for a subscriber that ALSO declared `persona_chat_open`
(`patch_coverage.PERSONA_CHAT_OPEN_CAPABILITY`); every frame may carry
`evicted_roots` (absent when empty) — the top-ranked roots the history bound now
omits, one per root the batch names — which that client removes.

`hydrate` carries `core`, `identity_map`, `watermark`, and the parity envelope's
`completeness` / `drops` / `parity_warnings`. With the patch lane on it also
carries `delta_patches: true` — the signal to RETAIN this frame's raw core as
the patch base — and the ACCEPTED `fold_entities`, sorted (`:291-293`). Both are
absent when the flag is off, so a flag-off hydrate stays byte-identical.

`delta_batch_frame` carries the SAME core exactly once per drained batch — the
old loop shipped one `build_snapshot()` per event, a ~9MB rebuild per append.
Its shape is strictly ADDITIVE over the single-delta shape: `watermark`/`seq` at
the FINAL offset so a `>`-only sequence gate applies the batch once,
`entity`/`op` still the LAST event for pre-batch consumers, `events` +
`coalesced_count` the additions (`:396-412`). Cap `_DELTA_BATCH_CAP = 256`.

`patch_batch_frame` carries op-based wire patches and **no core**. `base_offset`
is the watermark the batch applies FROM — the client folds only when its held
watermark equals it, and a mismatch is a sequence gap → checkpoint resync;
`watermark.event_offset` is the post-batch offset the fold advances to
(`:456-510`). **A frame that advances a watermark must carry the state that
justifies it**, which `batch_carries_patch_rows` (`:424`) guards: coverability is
decided per event, so a covered domain event whose paired `state.patched` never
arrived is coverable ON ITS OWN, and the frame that used to ship was
`{"type":"patch","patches":[],…}` — the client advanced its watermark having
folded nothing, with no downstream gate able to see it. Five producer paths
reach that case, so the guard sits at the drain, and `patch_batch_frame` refuses
to BUILD it too (`:493`).

`heartbeat` is liveness only. `offset=None` is the honest heartbeat of a stream
that could not read the log's tail and must not be stamped `0`, which every
watermark-gated reader would take as a real cursor at the head of the log
(`:337-341`). A heartbeat whose offset is AHEAD of the consumer's last applied
state-bearing frame proves a frame was missed: keep the applied watermark and
rehydrate.

`running_work` (2026-10-01) is shipped by `StreamSession.flush` BEFORE the
batch's own frames whenever the batch carries a `persona_chat.turn_ended` —
one per batch, never per event, and not counted toward `max_frames`. Its
fields: `as_of_offset` (the drained offset the section was read after; `null`
is "unknown", never 0) and `running_work` (the same shape as the core's
`running_work` section). It carries NO `watermark` on purpose: it is an
overlay of one section on the held core, applied only when `as_of_offset` is
past the held core's offset and replaced by the next core, and it must never
move a consumer's sequence. Why: a turn-end batch can never promote (the event
is uncovered), so the finished turn left `running_work` only with the next
full core — 16.6 s after `turn_ended` measured live, a 10.2 s build queued
behind another. The office sink skips it (`_NON_OFFICE_STATE_FRAME_TYPES`).

Since 2026-10-19 (row `RT-EMIT-RUNNING-WORK-CHAT`, plan `archive/p10-turn-2026-10-19.md` §2) the
overlay also ships for a batch carrying a terminal process's `running_work.process_started` /
`running_work.process_ended` (`stream/frames.py::batch_changes_running_work_presence`; the old
`batch_changes_chat_turn_presence` name is an alias for one release). The pair is appended by
`agent_runtime/running_work/process_presence.py` from the additive upstream seam
`tools/process_registry.py::ProcessRegistry.add_lifecycle_listener` (spawn and FIRST finish, after the
checkpoint write; a held PR row in `planned/upstream-footprint-ledger.md`), installed by the plugin's
`register(ctx)` in every hermes process. A batch made ONLY of those events (and watchdog reconciles
whose `families == ["running_work"]`, `stream/frames.py::batch_is_running_work_only`) is expressed
whole by the section, so a room where EVERY subscriber declared the sixth token
`running_work_section` (`patch_coverage.RUNNING_WORK_SECTION_CAPABILITY`) is handed ONE
`running_work` frame carrying `base_offset` / `watermark` exactly as `patch` does (and
`coalesced_count`, no `as_of_offset`) instead of the demote core
(`stream/build.py::_turn_batch_frames`); the client folds the section whole and advances its sequence
on it. Some or none declared, or the read failed → today's demote core; there is no split. The
un-sequenced overlay still ships first from `StreamSession.flush` either way. Announced builds stay on
the full-core lane (RULED 2026-10-16: their writer is not hermes).

`_delta_op` (`:1375`) is a four-arm table — `run.tool.*` / `run.progress` →
`chat.trace.appended`, `incident.*` → the source type verbatim,
`persona_assignment.*` → `instance.upserted`, everything else →
`event.appended`. `_redaction_safe_json` (`:1426`) makes payloads JSON-safe:
lists truncated to 200 items, secrets rewritten via the single-homed
`redaction.ENV_SECRET_ASSIGNMENT_RE`.

## 4. Patch frames and the fold negotiation

The producer half is the `agent_runtime/state_patches/` package. With
`read_model.delta_patches` on, a store chokepoint mutating a keyed entity
appends a `state.patched` event carrying a **wire-level op** — `upsert` (with
`changed`), `remove`, or `refresh` (`:96-98`). The projection is hermes': at
emit time the changed entity goes through the exact per-entity projection
`snapshot.py` uses, so the launcher folds projected fields verbatim and never
re-derives. One authority, no per-field allowlist (`:1-32`).

The lane ships ON — `SHIPPED_DELTA_PATCHES = True`
(`agent_runtime/runtime_config.py::SHIPPED_DELTA_PATCHES`). A config FAULT lands on
`FALLBACK_DELTA_PATCHES = False` (same module), off AND loud, because "emit a new
class of event from every store chokepoint" is not what a runtime should infer
from silence it could not read. Sizing is capped by
`EVENT_PAYLOAD_LIMIT_BYTES = 4096`: an oversized `changed` value becomes an
accounted `{"oversize": true, "bytes": N}` marker, and if the payload still
overflows the patch degrades to `op: "refresh"` — accounted, never a partial
merge the client cannot vouch for (`PATCH_VALUE_BUDGET_BYTES`, `:115-116`).

**Capability negotiation.** A consumer's fold is only as wide as its own entity →
core-section table, and a `patch` for an entity it cannot fold is strictly WORSE
than the `delta` it replaced — the consumer pays the patch and then a whole core
anyway. So it declares: `hermes harness stream --fold-entities a,b`
(`hermes_cli/harness_parts/parser/machine.py::add_stream`, parsed by
`agent_runtime/patch_coverage.py::parse_fold_entities_option`)
or `{"op":"subscribe","lane":"stream","fold_entities":[…]}` (`:2623-2631`).
Rules, all in `agent_runtime/patch_coverage.py`:

- **Omitting the declaration means `HISTORICAL_FOLD_ENTITIES = {persona_instance,
  incident}`, not the empty set** (`:355`) — absence is what every fielded client
  sends and that set is exactly today's wire, so defaulting to empty would have
  demoted every connected client to full cores forever. An EXPLICIT empty
  declaration is honoured as empty (`normalize_fold_entities`, `:363`).
- **The shared producer accepts the INTERSECTION**, never the union
  (`accepted_fold_entities`, `:380`): one producer fans every frame to every
  subscriber, so a promotion must be safe for everyone in the room.
- **The accepted set is echoed, not assumed** — on the `subscribed` ack
  (`serve.py`) and again on the hydrate (`agent_runtime/stream/build_policy.py::log_stream_attach`). A client can be
  honoured for strictly less than it asked for.
- **A malformed declaration is REFUSED**, not read as absent (`subscribe_denied`
  / `invalid_fold_entities`, `serve.py`) — a client that meant to
  narrow and was silently widened back would get patches it cannot fold.
- A batch naming any undeclared entity is demoted IN FULL to a core-bearing
  frame; there is no partial patch frame (`_batch_frames_with_liveness`,
  `agent_runtime/stream/session.py::stream_frames`). The demotion bills `snapshot_build reason=demote`
  (`BATCH_REASON_DEMOTE`, `:64`), which makes a foldable update that paid for a
  whole snapshot greppable.

Negotiation makes a new entity POSSIBLE; it does not enable one. The producer
still emits `state.patched` only for entities its chokepoints cover.

**Frame-gating tokens** ride the same declaration channel and are intersected the same way, but gate
a FRAME rather than a patch row: `persona_chat_turn` (the fourth), `persona_chat_open` (the fifth,
a widening of the fourth) and `running_work_section` (the sixth, 2026-10-19, §3 above: a
running-work-only batch rides a sequenced `running_work` section frame). Every mixed pair degrades to
today's wire: an old client never declares a token and keeps its core; an old runtime ignores the
string.

**The `scope` entity, and the demote a pointer flip no longer buys
(2026-09-01, instant-workspace-switching WS1/WS4 — hermes `ffd540bf73`).**
`workspace.activated` / `realm.activated` are now covered:
`WorkspaceStore.set_active` / `RealmStore.set_active` append a paired
`state.patched` for entity `scope`, op `upsert`, whose payload is BOTH
pointers (`{active_workspace_id, active_realm_id}` — always both, because a
realm activate can move the workspace and two half-patches are two chances to
disagree). Before this, the cheapest possible state change demoted every batch
it rode in to a full O(world) core — measured launcher-side at p50 **8.76 s**
before the `active` flags flipped (doc 08 carries the figure). The coverage is
honest by a pinned audit: `snapshot.py` reads `active_id()` in exactly seven
places, all derivable from the two pointers, and
`test_scope_patch_coverage.py` enumerates them by normalized source text so an
eighth reader fails with instructions rather than making the patch a lie. Skew
needs no flag: an undeclaring subscriber takes `span_not_foldable` → the
demoted core, per-subscriber. There is no `replace` op —
`FOLDABLE_PATCH_OPS = {upsert, remove}`, and a complete-row `upsert` IS the
replace. The same lane's WS4 gave the switch its accept verbs:
`runtime.workspace.use` / `runtime.realm.use` on the method lane, gated by
`call_authorization.LOCAL_CONSOLE_METHODS` — evaluated before every other
arm, so a paired device of ANY tier (including `console`) is refused; that
membership set, not the tier equality, is what enforces "a remote viewer
never parks the harness pointer" (the launcher plan's R-B). Both verbs share
one implementation with the argv CLI (`agent_runtime/scope_activation.py`);
neither joins `PEER_METHOD_ALLOWLIST`.

## 5. Attachment receipts

`log_stream_attach` (`agent_runtime/stream/build_policy.py::log_stream_denied`) writes ONE line per attachment to the
shared producer, at subscribe time, into the serve child's own `agent.log`.
Three call sites attach a reader to the same producer, and until this line
existed the log named none of them:

| Caller | `op` / `purpose` | Site |
|---|---|---|
| socket/stdio op lane | `subscribe` / `stream_lane` | `serve.py` |
| RPC office lane | `runtime.office.subscribe` / `office_patch` | `serve_office_subscriptions.py:902` |
| argv CLI | `harness_stream` / `cli_stream` | `runtime_commands.py:669-670` |

`op` is the call as the client made it, `purpose` is what the attachment is FOR
— neither implies the other. `pid` rides LAST here and on both build families
(`snapshot_build`, `snapshot_build_core`), so an attachment and the builds it
paid for join on one key instead of on wall clocks (`agent_runtime/stream/build.py::_is_one_shot`). It
never raises — an instrument must not be why a subscribe fails.

**Who paints the boot's one stale core is a property of the ROOM**, so
`stream_frames(wants_stale_first=…)` is stated by the caller —
`serve.py::_room_wants_stale_first`  reads the hub's two subscriber
tables at producer-build time, `_cmd_stream` (`runtime_commands.py:690`) states
`True`, default `False`. It cannot be re-derived inside the producer: the
subscriber attaching FIRST at boot is the RPC office lane, whose sink discards
every non-`office_actor` row, and measured 2026-08-18 two boots in three handed
the stale paint to that sink (`agent_runtime/stream/build.py::_build_with_liveness`).

## 6. The office push lane is a re-envelope, not a second derivation

`agent_runtime/serve_office_subscriptions.py` registers with the SAME
`StreamHub` every stream client uses, under a sink re-wrapping the frames it
cares about as JSON-RPC notifications. It adds no derivation, and three
consequences followed: one producer, so a patch cannot exist on one lane and not
the other; an RPC subscriber COUNTS as a subscriber, so the hub does not stop
producing under it; backpressure and drop accounting inherited whole (`:1-24`).
What crosses is decided by `state_patches.office_patch_scope`, the ONE authority
for "is this row in this workspace" — single-homed because it was not, and the
fork cost a silent drop when `office_surface` became promotable with a BARE
workspace id that failed the private "id under `<workspace_id>/`" restatement
(`:26-45`). A `hydrate` or `delta` means the batch was not patch-coverable, so it
becomes a resync notification; an UNKNOWN frame type takes the same branch
deliberately. Drops are typed, never silent: a subscriber outrunning its bounded
buffer gets `subscription_dropped` naming which of the two bounds tripped —
frame count or bytes — then is unsubscribed (`serve.py`).

## 7. The PUSH-vs-RPC boundary, and the fork boundary

**The 2026-08-13 ruling stands: this fork owns the better PUSH lane; upstream
owns the better CALL lane.** The push half is live-on-by-default —
`SHIPPED_DELTA_PATCHES = True`, the hub lane advertised on every greeting, the
launcher gating on `subscribe_lanes`. The call half deliberately mirrors
`tui_gateway`'s JSON-RPC 2.0 shape and error codes rather than minting a third
convention, and sits BESIDE the argv lane: a frame is claimed by the method lane
only when it names `jsonrpc` or `method`, neither of which an argv request has
ever carried (`serve.py`).

**A CLI verb reaches the live serve through ONE route** (cli-serve-route plan,
2026-10-16): `agent_runtime/serve_socket/cli_route.py::relay_argv` dials the
root's socket target, says hello with the root token, sends `{id, argv}` and
reads that request to its end, returning a typed `RelayOutcome` (`served`,
`no_serve`, `unreached`, `refused`). Whether a failure may run the verb in the
asking process is decided once, by `RelayOutcome.runs_locally(FallbackPolicy)`:
`READ` (`harness query`) falls back on anything; `WRITE` (`harness serve
settles rearm`) runs locally only with no live serve, and a live serve that is
unreachable or fails the request is a non-zero exit, never a second write;
`TURN_HANDOFF` (`mission-chat message`) runs locally only while nothing was
sent. Inside the serve the request id is bound (`current_serve_request_id`),
so the relayed argv runs store-direct there with no extra flag.

**The fork boundary is the reverse of the natural assumption: `agent_runtime/`
is not in upstream at all.** The check that proves it is a path filter, not a
judgement call — `git diff --name-only <baseline>..HEAD` minus
`^(agent/|agent_runtime/|hermes_cli/harness)` and minus
`^tools/(agent_chat_tool|mission_goal_tool)\.py$` — and anything it surfaces
needs a ledger row. Archived doc 17 carries the rows; doc 18 carries the merge
rehearsal that priced them — 59 conflicted files in its first table, 63 on the
same-day re-rehearsal (`:151-153`), and only one named by doc 17 either way, so
the next sync is not a two-file merge. One transport-relevant row:
`scripts/generate_agent_runtime_stream_fixtures.py` is fork-created and
fork-only by construction, and sat in upstream-owned `scripts/` with no row
until it was filed.

## 8. The launcher-side consumer contract

`tests/fixtures/stream_frames/` holds fourteen manifest-pinned files. The
EterniaLauncher repo commits **byte-identical copies** under
`test/fixtures/harness_stream/` and parses them through its real decode +
read-model pipeline (`mission_stream_contract_fixture_test.dart`). Verified
2026-08-22: the two `MANIFEST.sha256` files are identical. Seven are generated
by `scripts/generate_agent_runtime_stream_fixtures.py` from a **seeded isolated
runtime root** through the current production builders, never from a live store;
the rest are hand-maintained and validated by shape + live-classifier agreement
(`tests/agent_runtime/test_stream_patch.py`) because they demonstrate fold
semantics over entities the seeded root does not contain. `patch_remove.json` is
un-emittable today — the `incident.closed` remove fold, de-registered with its
last writer, kept classifying by
`patch_coverage.HISTORICAL_COVERED_DOMAIN_EVENT_TYPES` (`:204`).

**Update rule: these fixtures change only in a cross-stack change that lands
hermes AND the launcher together** — regenerate, copy bytes, update both
manifests in the same change. Membership AND ORDER are compared before bytes by
the launcher's `tool/test_quality/check_producer_contracts.py` (that checker
lives in the LAUNCHER repo, invoked with `--hermes-root`), so a new row goes in
at the same position on both sides.

**The additive-only wire rule — why `sections_ms`-style keys must never ride the
parity envelope.** `sections_ms` rides the parity envelope, which rides the
hydrate frame, which is byte-pinned by these goldens AND by the launcher's
mirror. Two keys there for an observability nicety would be a cross-stack
fixture landing, and a hermes-only half of one is exactly the failure this repo
already paid for: hermes green, the launcher's byte-compare red on every push.
So the readiness-split attribution went to a LOG RECEIPT (`sections_top` on
`snapshot_build_core`) and `agents_readiness` kept its exact span, meaning and
key (`agent_runtime/snapshot/sections.py:140-153`). The same discipline keeps
`correlation_id` an UNREGISTERED optional payload key — the contract hash
derives from the registry rows alone, so registering it would shift
`decision_contract_hash` inside every generated core.

## 9. Delivery directives — a name that no longer describes a transport

`agent_runtime/delivery_directive.py` is 222 lines with no wire surface. Its
transport-shaped half — a directive DECLARED on a goal-create request, stored on
the `Task`, executed at terminal settle by `ArchiveStore.archive_tasks` — went
with the mission lane; S24 swept the executors, the declaration path, and the
delivery-time patch capture that had no producer left. What remains is
`reap_orphan_worktrees` (`:38`), a capture-then-reap janitor driven by
`hermes harness worktree reap` and `harness doctor --fix`. Nothing is deleted
with an uncaptured diff: dirty candidates go to `<store_root>/wt_reaped_patches/`
under collision-proof exclusive-create names (`:162`). One registered event,
`worktree.orphans_reaped`.

## 10. MCP transport

MCP tool registration (`tools.mcp_tool.discover_mcp_tools`) is wired to the CLI
entry points that host a model turn against the operator's full MCP surface —
bare `hermes` / `chat` / `acp` / `rl`, plus `cron run|tick`, `gateway run`,
`mcp serve`. **`hermes harness …` is deliberately excluded and must stay
excluded**: the harness lane is a fast, deterministic control plane and cannot
pay an MCP connect budget on every command (`agent_runtime/mcp_lane.py:1-20`).
Admission is therefore per-RUN and per-PERSONA via
`register_mcp_servers({name: cfg})` over an explicitly resolved subset, and two
transport facts follow. Registration is **single-flight**, because
`tools.registry` and `tools/mcp_tool._servers` are process-global while a serve
process is multi-persona (`ThreadPoolExecutor(4)`) — interleaved admissions are
refused as `mcp_admission_lane_busy` rather than raced. And **the registry scope
lives with the transport session and the admission content, while the call budget
belongs to the run** (D1.01, owner ruling 2026-10-10, superseding R2's per-run
teardown): `agent_runtime/mcp_admission/resident.py` keeps an admitted server's
tools registered between runs while its session, its listed tools and its admitted
config are unchanged; `release_mcp_admission` unbinds the run's budget at every
admitted run's end and `drop_resident_scopes` is the explicit removal. Isolation
between personas is `resolve.py::scope_toolsets_to_admission`
(`agent_runtime/mcp_admission/resolve.py::resolve_mcp_admission`). Admission POLICY belongs to the
chat-lane doc. Relay hops are gated by `agent_runtime/relay_policy.py` — one
authority, so in-process tool relay, CLI and serve transport get the same depth
/ cycle / budget answer from explicit envelope data rather than inference.

## 11. Wire value contracts — what a value MEANS (owner rulings 2026-10-15)

The launcher decodes one wire fact in several files; where those readers disagreed the
disagreement was a per-file policy with no hermes contract behind it. These rules are that
contract. Producer halves are pinned in `tests/agent_runtime/test_wire_value_contracts.py`.

**11.1 Integers are strict (RT-WIRE-FACT-DECODES-DIFFERENT).** Every integer hermes puts
on the wire is a JSON integer: never a numeric string, never a float, never a bool. A
reader may refuse anything else and must not round or truncate a number into one. A value
hermes does not know is ABSENT (or `null`), never a sentinel it invents; a value a tool
reported is passed through as reported, so a tool's `exit_code` of `-1` (upstream's
terminal and code-kernel spelling of "no process exit") is `-1` on every lane, not absent
on one and `-1` on another. Gate: every integer-named key in a built hydrate frame and in
every committed stream golden is a JSON integer.

**11.2 An empty realm-adopt reply is a failure (RT-TWO-RESOLVERS-ANSWER-HARNESS).**
`harness realm adopt` succeeds with exit 0 and a non-empty `kind: list` envelope, even
when nothing was adopted (`count: 0`); it fails with a non-zero exit and an error
envelope. A reply with exit 0 and no payload, or a null payload, is therefore never
success, and every reader of the verb treats it as a failure. Gate: a successful adopt
of nothing still answers the list envelope.

**11.3 An absent status word is `unknown` (RT-MISSIONAGENTLOGSTATUS).** Hermes writes
a `state` on every persona-instance row (a `WorkerSessionState` value, `idle` by
default) and does not emit agent-log rows at all (the launcher derives them). So no
hermes row ever omits its status word, and a reader that finds none has no evidence of
anything: it reads `unknown` on every door, never `idle`.

## Invariants

1. **Parse per line, branch on `type`, ignore unknown fields.** Hub-vs-argv
   parity is a property of the DECODED frame, not the line — `harness stream`
   writes compact separators, `_FrameWriter` json's defaults
   (`test_serve_stream_lane_parity.py`).
2. **Every wire addition is additive**; byte-pinned frames move cross-stack.
3. **Observability never adds a key to a BYTE-PINNED surface** — an operator's
   number belongs on an `agent.log` line, not on the parity envelope the stream
   goldens and the launcher's mirror compare byte-for-byte. Additive keys on
   surfaces that are NOT byte-pinned are the deliberate exception: `phases` on
   the create RPC's result and on the turn record are both client-visible and
   both allowed (`agent_create_phases.py:14-21`).
4. **Absence and emptiness are different statements** — for `fold_entities`, for
   `watermark.event_offset`, for a heartbeat with no position. Collapsing either
   pair has cost a live incident each time.
5. **A frame that advances a watermark carries the state that justifies it.** No
   empty `patches` list, ever.
6. **A shared producer promotes on the INTERSECTION of its room's declarations**
   and echoes what it accepted; widening it may only name entities every
   fielded client already folds.
7. **The harness lane never registers MCP globally.** Admission is per-run and
   single-flight; the admitted scope stays resident between runs, scoped out of
   every run that did not admit it.
8. **`agent_runtime/` is fork-only.** Any edit outside
   `agent/ | agent_runtime/ | hermes_cli/harness*` needs a boundary-ledger row.
9. **A listener beyond loopback is opt-in per install, forever**; it is TLS-only
   (a certificate that cannot be minted means the lane does not open — never
   that it opens in the clear); and it accepts only per-device credentials. The
   loopback lane's host is not a knob and does not become one: widening exposure
   is a different listener with a different credential story, not a different
   value in `SOCKET_HOST`.
10. **A credential appears in exactly one frame, once** — the `hello_ok` that
    redeemed the pairing code that minted it. It is absent from
    `SocketConnection.payload()`, from every log line, and from `DeviceRecord`,
    which has no field for it by construction.

### Provider sign-in deadline projection

`provider_signin._Session.view` adds nullable `provider_started_at` and
`provider_expires_at`, both UNIX seconds, to `runtime.provider.signin.*` results.
`provider_browser_login.run_browser_login` forwards the same fields in an optional
NDJSON `expiry` event. The original registry `started_at` stays session creation;
its 15-minute cap is not advertised as the provider's code lifetime.

Optional `on_expiry` callbacks on the existing Nous/xAI/MiniMax/Codex helpers
report their provider response expiry. Codex browser login reports its actual
loopback callback timeout. Missing device expiry and Anthropic paste-code expiry
stay null. `tests/hermes_cli/test_provider_signin_expiry_downstream.py` proves the
deadline through each machine driver and the registry, plus unknown/invalid values.

### Provider account display projection

`provider_account._usage_view` and `usage.serialize._serialize_usage_lane` emit
the same additive `account` block: `email`, `organisation`, and `plan` are each
string or null. Unknown stays null; account IDs and provider labels are never
substituted for account identity. Legacy `plan` remains available.

`provider_account_metadata.nous_usage_snapshot` reuses the existing portal report's
email/organisation and usage plan. `usage_snapshot` reads existing Codex credentials
without refresh and uses `_upstream_doors.codex_account_claims` only when their
principal matches the usage snapshot identity. Codex email comes from that JWT's
profile claim; organisation stays null when not reported. The current Anthropic
OAuth usage reader provides no identity or plan; these remain null until a trusted
report supplies them. No new account endpoint or auth flow is introduced.

`provider_account_view.account_view` is pure; credential reads remain in fetch
code. `tests/agent_runtime/test_provider_account_metadata.py` proves transport
parity, nulls, secret exclusion, existing Nous projection and Codex account matching.

### Provider usage/reset contract

Two doors carry account usage, and both read upstream's own fetchers. Every
window is `{label, used_percent, reset_at|resets_at, scope}`: `scope: account`
means exhausting it exhausts the login, `model` caps one model family only
(upstream `AccountUsageWindow.scope`). Usage is a percent; no upstream fetcher
reports an absolute used/limit pair, so none is invented.

- `runtime.provider.usage` (`provider_account._usage_view`): one provider's
  provider-wide snapshot, fetched on call.
- The model facts (`session_model_catalog.facts`, so both
  `runtime.operator.conversation.models` and the native conversation reads) carry
  `provider_usage: {provider_id: usage}` — upstream `hermes_cli.inventory`'s
  `usage` block verbatim, cache-only with a queued refresh: `{windows}` for a
  single-account provider, `{accounts: [{id, label, windows, state, resets_at}]}`
  for a multi-entry credential pool (`state` ready/limited/unknown/unavailable;
  `resets_at` the latest exhausted account window or live cooldown). A provider
  with no fresh snapshot is absent. `test_session_model_catalog_usage` pins it.

Session token totals (`usage` beside it) are a different meaning: cumulative
counters of the session lineage, not quota and not per turn.

## Open rows

- **Single-transport collapse is half-done** — the hub lane is primary and
  gated; the argv backstop's deletion waits on an observation window
  ([archive/single-transport-collapse.md](archive/single-transport-collapse.md)).
- **Correlation-id coverage is partial** — the office lane and
  `runtime.agent.create` carry the token, the remaining argv capability lanes do
  not, and the one-grep acceptance was never scripted
  ([planned/correlation-id-coverage.md](planned/correlation-id-coverage.md)).
- **The remote gateway SHIPPED (stages 0–8, 2026-08-27/28), and the live gaps
  this row carried are CLOSED (re-read 2026-09-06).** The socket lane became
  the gateway lane: `gateway.listen`, install identity, TLS-only bind beyond
  loopback, device pairing, the peer ceremony, cross-install
  `agent_chat_send`, and the two-verb media family. The row said until
  2026-09-06 that no physical second machine had exercised the LAN bind and
  that cross-install media was unbuilt; both were stale — the Mac paired both
  ways on 2026-09-04, the cockpit switched to it with a live stream on
  2026-09-05, console chat to a Mac agent rode the method lane on
  2026-09-06, and cross-install media landed as P4 (`ed3c6a11aa`). What is
  genuinely open is enumerated in
  [09 — Multi-device runtime](09-multi-device-runtime.md) § Open rows (R12/R13
  unruled, the broker appendix unstaged, the A→B→A cycle, the `unknown_device`
  read, D12's launcher half). The staged history stays where it is:
  `EterniaLauncher/docs/archive/mission_control/universal-remote-gateway.md` and
  [archive/remote-gateway.md](archive/remote-gateway.md), the hermes-half
  pointer.
- **`serve.py` says the RPC registry holds "currently eight" methods; ten
  are registered.** That same docstring warns "a docstring that copies a
  register starts lying the first time the register moves" — it has.
- **Two module docstrings cite doc paths that moved into `archive/`** —
  `delivery_directive.py:8` → `delivery-directive.md`, `serve.py` →
  `harness-serve-design.md`. Both pointers are dangling.
- **`tests/fixtures/stream_frames/README.md` describes thirteen of its fourteen
  pinned files** — `patch_office_actor.json` has no row in the origin table.

## Unverified carry-forward

- **The persona-chat event lane's two 2026-08-09 properties** — that the
  auto-title now runs AFTER the chat-root lease releases (so
  `persona_chat.projected` and `persona_chat.metadata_updated` for one turn are
  separated by a whole auxiliary-LLM round trip, and the root accepts a send in
  between), and that `persona_chat.send_refused` omits the message text because
  the sanitising chokepoints sit inside the lease the refusal never took. All
  three types are registered (`decision_contract_registry.py:184-196`) and
  emitted from `hermes_cli/harness_parts/persona/chat_events.py` (`_publish_persona_chat_projection_event`,
  `_publish_persona_chat_metadata_event`, `_publish_persona_chat_send_refused_event`), but the
  ORDERING claim and the omission RATIONALE were not re-verified against the
  lease code. Source: `…/mission-control-stream.md:361-383`.
- **The measured patch-lane saving** — 486 bytes against an 822,671-byte core,
  the ~99.96% reduction the S6/S7 acceptance names. Cited at
  `patch_coverage.py:347` and `agent_runtime/stream/frames.py::heartbeat_frame` as 2026-07/08 measurements;
  not re-measured here, so a historical figure, not a benchmark.

## Supersedes

`planned/agent-placement-verb.md` — **deleted 2026-08-27 by the S10 fold-in
commit** (sha `1295212f2e`, in the history folded before the 2026-09-15 `main`, so not
reachable from `main` or any remote ref). Its wire half is above and in 06: `runtime.agent.create` gained an
optional `position`, a `skills` param and four ack keys, and
`runtime.agent.retire` joined the `rpc` roster — all of it additive, with
`RPC_CONTRACT_VERSION` never moving, which is the set-plus-integer discipline
§2 states and the reason a set of ten could become a set of ten with one name
swapped in without a contract bump. Its D12 rollout gate — the launcher reading
`runtime.agent.retire`'s PRESENCE as "this serve accepts an absent `position`" —
is the only place in this canon where a method name is used as a capability
proxy for a PARAMETER; it is recorded as a named risk, not as a pattern to copy.

All others under `archive/2026-08-22-pre-consolidation/`:

| Archived doc | Where it went |
|---|---|
| [`mission-control-stream.md`](archive/2026-08-22-pre-consolidation/mission-control-stream.md) | primary source for §3–§5 |
| [`harness-serve-design.md`](archive/2026-08-22-pre-consolidation/harness-serve-design.md) | the 2026-07-08 settled design behind §1 |
| [`delivery-directive.md`](archive/2026-08-22-pre-consolidation/delivery-directive.md) | removed contract; §9 is the live half |
| [`17-upstream-boundary-ledger.md`](archive/2026-08-22-pre-consolidation/17-upstream-boundary-ledger.md) · [`18-upstream-merge-rehearsal-20260730.md`](archive/2026-08-22-pre-consolidation/18-upstream-merge-rehearsal-20260730.md) | summarised in §7; still the authority for their own detail |
| [`SINGLE_TRANSPORT_COLLAPSE_PLAN_2026-08-16.md`](archive/2026-08-22-pre-consolidation/SINGLE_TRANSPORT_COLLAPSE_PLAN_2026-08-16.md) | landed stages → §2/§5; open half → `archive/single-transport-collapse.md` |
| [`CORRELATION_ID_PLAN_2026-08-16.md`](archive/2026-08-22-pre-consolidation/CORRELATION_ID_PLAN_2026-08-16.md) | landed stages → §8; open half → `planned/correlation-id-coverage.md` |

## Console history: reviewed Redo

Console Redo extends the existing authenticated history operation, not the
native Work task system. Its endpoint and recovery contract is recorded in
[Reviewed Console Redo](../downstream/console-redo-2026-10-13.md); Undo status,
recovery and pending discovery serve both directions.

## Native Work methods

`agent_runtime/work/` serves Work on the workspace todo boards (plan
[work-on-markdown-2026-10-18.md](archive/work-on-markdown-2026-10-18.md) §2, §5, §6.2). An owner is a
WORKSPACE; its board is the `type: queue` notes of every repo slot it binds (plus the auto-created
default brain when none carries a brain); a row in the ADR 0011 grammar IS a task, keyed `(slot, ID)`.
The default brain is a MACHINE-LOCAL binding
(`<store_root>/work/<ws>/default_brain.json`), never a declared slot, so it needs no realm publish right
(owner ruling 2026-10-18); once a repo slot with a brain is bound, its rows move into that brain's
`work-queue.md` in one commit and the default board drops from `boards[]`. There is no task database: reads come from hermes's own worktree of each slot after a fetch, and every
write is ONE row operation committed and pushed fast-forward by `agent_runtime/work_store/writer.py`.
Upstream's kanban is not read or written. All methods are console-tier and deferred through
`spawn_reply`; replies carry `version: 2`, `install_id` and (owner calls) `owner`; a refusal is error 4090
`{"reason", "detail"}` with `reason` a `agent_runtime/work_store/reasons.py::Reason` word. Phone bundles
omit the module and never advertise the methods.

| Method | Input beyond scope | Result | Typed refusals |
|---|---|---|---|
| `runtime.work.capabilities` | `observe?` (true: words only, no create/promote/move — then `missing` / `move_pending` say what a full call would do) | `owners[] {owner, workspace_id, kind, label, operations}` (one `kind: workspace` owner per workspace, then the `kind: personal` board — the operator's machine-local brain, never promoted; `workspace_id: personal`), `board_kinds[]` (`workspace`, `personal`, `agent`), `personal_board {state: present \| created \| missing (observe) \| unavailable (+ `reason`)}`, `default_brain {ws: {state: present \| created \| moved (+ `into`) \| absent \| unavailable (+ `reason`) \| remote (+ `clone_url`) \| remote_pending_declare (+ `clone_url`, `slot`) \| remote_refused (+ `reason`, `retry_after`)}}` (`present`/`created` carry `reason: needs_git_account` while no GitHub credential answers), `limitations[]`, `chat_scopes`, `execution_identity_guard`, `observe[]` (the operations taking `observe: true`) | `scope_denied`, `work_unavailable` |
| `runtime.work.context` | `client_scope`, `conversation` | `scopes`, `agent_profile`, `assignee`, `can_start` | `invalid_request`, `work_owner_changed` |
| `runtime.work.list` | `kind?` (`workspace` / `personal` must match the owner; `agent` needs no `owner` and answers the AGENT VIEW: `assignee` (or the operator conversation's instance) → `{kind: agent, assignee, assignees[], owners[] {owner, workspace_id, kind, label, boards[] …, stale} or {…, boards: [], refused}, read_at, stale}` — the rows assigned to the instance or its persona across its workspace's boards and the personal board; every workspace for a runtime-global instance or a bare persona id), `slot?`, `status?` (`READY` / `BLOCKED` / `DEFERRED` / `NEEDS PLAN` / `TAKEN`), `assignee?` (`persona:<token>`), `view?` (`all` / `conversation`), `stale_ok?`, `observe?` (true: read the existing worktrees as they are — no normalization, sync, fetch or write; a board with no worktree has `readable: false` and no queues; `stale` unless every worktree is at its local tip) | `boards[] {slot, label, brain_dir, bound_here, local, is_default, default_branch, committed_at, readable, queues[] {note, program, title, rows[]}}` — grouped per brain, then per domain (one queue note each; `program` from its frontmatter; every row carries `slot` and `program`), `cursor: null`, `read_at`, `stale` | `work_owner_changed`, `fetch_failed` (unless `stale_ok`) |
| `runtime.work.inspect` | `kind?` (must match the owner), `slot`, `task_id`, `observe?` (as `list`; an unread board refuses `no_brain`) | `task` or null; `ending {commit, at, subject, body}` (the deleting commit) when null | `work_owner_changed`, `slot_unbound` |
| `runtime.work.start` | `request_id`, `title` (≤160), `body?` (≤50,000), `slot?`, `note?`, `assignee?`, `conversation?` | `task`, `disposition: accepted`, `receipt` — a minted `WORK-<6>` row; a non-empty body is its brief note | `invalid_request`, `no_brain`, `slot_unbound`, `assignee_unknown`, `push_contended`, the git reasons |
| `runtime.work.assign` | `request_id`, `slot`, `task_id`, `assignee` (or null to clear) | `task`, `receipt` | `row_gone`, `assignee_unknown`, git reasons |
| `runtime.work.claim` | `request_id`, `slot`, `task_id`, `who?` (`persona:<instance_id>`, default the context's assignee) | `task`, `receipt` | `row_gone`, `already_taken`, `assignee_unknown`, git reasons |
| `runtime.work.release` | `request_id`, `slot`, `task_id`, `status?` | `task`, `receipt` | `row_gone`, `not_claimant`, git reasons |
| `runtime.work.set_status` | `request_id`, `slot`, `task_id`, `status` (a full status segment) | `task`, `receipt` | `row_gone`, `grammar_invalid`, `not_claimant`, git reasons |
| `runtime.work.done` | `request_id`, `slot`, `task_id`, `result` (≤4,000, one paragraph) | `ending`, `receipt` — the row is deleted; the commit body carries the result | `row_gone`, `not_claimant`, git reasons |
| `runtime.work.create_brain` | `request_id`, `slot?` (omitted: the default brain), `promote?` (`true`: promote the default brain to a private GitHub remote now, ignoring the automatic path's back-off — doc 06 § The todo board) | `board`, `receipt`, `promotion?` (`{outcome: promoted \| already, url, declaration}`) | `slot_unbound`, git reasons; with `promote`: `needs_git_account`, `remote_exists`, `git_host_unsupported`, `token_scope`, `host_unreachable`, `remote_diverged`, `url_mismatch` |
| `runtime.work.lend_skills` | `request_id`, `slot`, `task_id`, `skills` (non-empty list of slugs), `mode?` (`lend` default: the union with the row's set; `revoke`: the difference) | `task`, `receipt` — the row's `skills:` segment rewritten (removed when empty); a write verb (RULED 2026-10-18) | `invalid_request`, `skills_not_loadable` (+ `rejected_skills {slug: reason}`; nothing written), `row_gone`, `not_claimant`, git reasons |

Scope is `install_id` plus the opaque `owner` = `fingerprint([install, workspace_id])`; every call
re-derives the owner set and a missing or changed owner refuses. The idempotency key is `request_id`
(the commit body's `request_id: <rid>` line at the tip): a repeat returns the recorded receipt
(`replayed: true`). The operator's console writes as `who: operator` and may release or re-status a row
another claimant holds; a paired device writes as `device:<id>` and may not borrow the operator's name.
The git reasons are `slot_unbound`, `git_unavailable`, `machine_identity_unavailable`, `worktree_failed`,
`remote_missing`, `fetch_failed`, `branch_missing`, `worktree_dirty`, `note_missing`, `grammar_invalid`,
`commit_failed`, `push_refused`, `push_contended` — one per failure branch of the plan's §5 step table.
Every write logs one receipt line `work.row_<op>` (`agent_runtime/work_store/receipts.py`); the serve log
is the receipt log.

A session that races the writer on the same queue note re-applies its op by ID with
`scripts/work_row.py` in its own checkout (never a text merge).

A row's `skills: `<slug>`[, `<slug>`]` segment (ADR 0011 amendment 2026-10-19) lends skills to whoever
works it: every projected task carries `skills: [..]`; the engine's and the batch planner's `Assignment.skills`
are DERIVED from it (a batch lane takes its rows' union, `Lane.skills` on the wire), and the persona-turn
executor queues them for the run's turn through `queue_skills_for_next_turn` before it queues the turn (an
unloadable skill refuses the run `skills_not_loadable`); an `UNTIL_DONE` continuation re-queues them.

### Chat goal methods and `UNTIL_DONE` Work runs

`runtime.chat.goal.set | status | pause | resume | clear` (`agent_runtime/serve_rpc/chat_goal.py` over
`agent_runtime/chat_goal.py::OPS`) drive upstream's goal engine, `hermes_cli/goals.py::GoalManager`, on a
chat root named by `session_id` (dispatcher plan
[dispatcher-and-libraries-2026-10-18.md](archive/dispatcher-and-libraries-2026-10-18.md) §5). `set` takes
`goal`, `max_turns?`, `contract?` (`outcome`, `verification`, `constraints`, `boundaries`, `stop_when`) and
`gates?` (shell commands); every verb answers `{"goal": {status, goal, turns_used, max_turns, contract,
gates[], paused_reason, last_verdict, last_reason, status_line, run}}` (`status: none` when the root holds
none; `run` the Work request that owns it). Console tier, deferred through `spawn_reply`. Refusals:
`invalid_request` (-32602), `no_goal` (4001).

A Work assignment with `goal_mode: until_done` (`work_store/goal_turns.py`) sets the root's goal from the
brief (objective; acceptance as the contract's outcome; one gate per `Brief.tests` command, on by default)
and binds the root to the run (`<store_root>/chat_goal_bindings/<root>.json`). Every terminal QUEUED turn
on a bound root reaches the after-turn hook (the queued-send runner's `on_settle`): gates then judge run
in the persona's workdir; a continuation is forged as the run's next queued send, never a direct turn; an
operator send already waiting wins the slot (the run holds and is judged again after it). A `work_report`
of `blocked`/`stopped`, a failed turn, or a judge decision other than continue ends the run; the goal is
paused and the root unbound. Receipts: `work.goal_arm | goal_continue | goal_hold | goal_end`. A judge `wait` parks the goal on upstream's barrier; the Work engine's tick
(`goal_turns.wake_parked`) continues it when the barrier lifts — a bound run from its binding, a chat goal
no run owns from the settled turn's arguments its `wait` recorded (`<store_root>/chat_goal_parks/<root>.json`).

### Batch methods

`runtime.batch.plan | start | status | stop | land | approve` (`agent_runtime/batch/rpc.py` over
`agent_runtime/batch/dispatcher.py::BatchDispatcher`; dispatcher plan
[dispatcher-and-libraries-2026-10-18.md](archive/dispatcher-and-libraries-2026-10-18.md) §3) plan the
workspace's READY rows into thick lanes (one per `Domain(slot, note, heading)`, sized by the files the rows
name — 65 rows only a ceiling — a lane sharing a file with an earlier one sequenced after it, one landing
lane), claim them `persona:<instance_id>` (the rows' assignee, else the roster instance whose role is the
slot's `context.role`, else the operator names it: `start` `personas {lane: instance}`), run each lane as
ONE executor assignment, and write every row's ending back by ID. Scope, tier, deferral and the 4090
refusal shape are Work's; replies carry `version: 1`, `install_id`, `owner`.

| Method | Input beyond scope | Result | Typed refusals |
|---|---|---|---|
| `runtime.batch.plan` | none | `plan {id: BATCH-<6>, lanes[], landing, budget, asks[]}` — writes nothing | `plan_refused` (`nothing_ready`, `mixed_assignees`) |
| `runtime.batch.start` | `batch_id` (the plan's id), `personas?` | `batch` | `idempotency_conflict` (the board moved), `persona_unresolved`, `not_owner_machine`, git reasons |
| `runtime.batch.status` | `batch_id?` | `batches[] {…, lanes[], landing, marks {slot/ID: who \| status \| gone}}`, `automation`, `machine` | `batch_missing` |
| `runtime.batch.stop` | `batch_id`, `lane?` (omitted: abort the batch) | `batch` | `state_transition_invalid`, `batch_missing` |
| `runtime.batch.land` | `batch_id`, `persona?` | `batch` | `state_transition_invalid`, `landing_in_progress`, `not_owner_machine` |
| `runtime.batch.approve` | `batch_id` | `batch` (`LANDED`, `landing_sha`) | `state_transition_invalid`, `not_owner_machine`, `landing_in_progress`, `gate_not_green` (no green code-run gate receipt for the landing HEAD), `push_contended` (the tip moved since the merge: land again), `worktree_dirty`, `push_refused` |

A batch is its manifest note, `<default brain>/50 — Agent Handoffs/batches/<BATCH-id>.md` (frontmatter
`type: batch`, `owner_machine`; one appended line per lane per state), its lane briefs beside it, and its
rows' claim marks — no other store; every call folds it afresh. The default brain is the board
`ensure_default_brain` returns (the first bound repo brain, else the machine-local one). `stop` on a
running lane WAITS for the turn (`STOP_REQUESTED`; the settle ends it `STOPPED`, rows released
`DEFERRED`); `approve` is the only edge to `LANDED`. `batch_automation` (`off | plan | start`, default
`off`) is the frontmatter of `batches/settings.md`; it gates only a scheduler fire, and `land`/`approve`
are never automated. The W3 engine skips a row a live batch lane holds. Receipts: `batch.planned |
started | lane_refused | waiting_box | lane_settled | stop_requested | ready_to_land | landing |
awaiting_approval | landing_red | landed | aborted`. Phone bundles omit the module.

Lanes run in worktrees (B5, `agent_runtime/batch/lane_executor.py::BatchLaneExecutor` over the persona-turn
executor, `lane_git.py` for the git). A work lane of slot `S` works in `<clone's parent>/.worktrees/<clone
name>-<batch>-<lane>` on `q/<batch>/<lane>`, cut from the fetched tip (or from the branch of the same-slot
lane it is sequenced after); its brief (the playbook's skeleton, ≤ 40 lines with the `work_report` ask) is
written to the `-scratch` directory beside it and sent as the persona's turn, which runs there
(`run_workdir`, on top of the workdir ladder; a `run_workdir` this machine cannot use refuses the turn —
`invalid_request`, `reason: run_workdir_unavailable` — never falls back to the ladder). The settle reads the lane's commits from git (`base..branch`).
`land` cuts `land/<batch>` per slot the batch touched and merges each `REPORTED` lane `--no-ff` in order (a
conflict is aborted and named in the landing brief). When the landing turn settles, the executor runs the
landing gate itself, off the settle's thread, in each slot's landing worktree (`gate.py::GateRunner`) and
records one code-run receipt per slot — `{slot, command, exit_code, summary, sha, seconds}`, `sha` the HEAD it ran on —
in the manifest's batch line (`gate_receipts`; `Batch.gate_receipts`). Those receipts alone decide
`AWAITING_APPROVAL`; the persona's `work_report` verdict is advisory (`advisory`; row RT-BATCH-GATE-RECEIPT,
owner ruling 2026-10-18). `approve` refuses `gate_not_green` without a green receipt per slot, and
`lander.py::GitLander` checks every slot (clean, the fetched tip an ancestor, a green receipt naming that
HEAD) before it pushes each landing HEAD fast-forward. `land` and `approve` hold
`locks.batch_landing_lock` (one landing per machine). Receipts: `batch.lane_site`, `batch.gate_started`,
`batch.gate`.

Which command runs per slot (row RT-BATCH-GATE-PER-SLOT-COMMAND, owner ruling 2026-10-19): the plan's
`landing` lane carries `gates {slot: [command…] | null}`, one entry per slot its lanes touch, read at plan
time by `gate.py::slot_gate` in this order — (1) the slot declaration's `context.gate` (a list of non-empty
command strings set through `workspace.slots.declare`, refused `invalid_declaration` when one carries a
credential; `[]` is "declared none", a red receipt); (2) `GATES_BY_TOOLCHAIN_KIND[toolchain.kind]`
(`python`/`hermes` → `bash scripts/run_tests_bundled.sh tests`, `flutter` → `dart tool/heavy_run/run.dart --
dart tool/run_tier.dart`, `django`/`backend` → `bash scripts/test.sh`, `brain` → `:`); (3) the default brain:
`:`, a green receipt `no code to test: brain-only slot` without a subprocess; (4) `null`: a RED receipt
`no gate declared for slot <name>; set context.gate`, never a skip, so `approve` refuses `gate_not_green`. A
manifest written before `gates` existed folds to `{}` — every slot red; that batch is stopped and planned
again.

### Schedule methods — the serve's scheduler

`runtime.schedule.arm | disarm | list` (`agent_runtime/serve_rpc/schedule.py` over
`work_store/schedule_ops.py::OPS`) drive `work_store/serve_scheduler.py::ServeTickScheduler`, the desktop
runtime's scheduler (dispatcher plan §2.3, §4; upstream cron is not run, `Trigger.from_cron_job` is the
one door from an upstream job record). `arm` takes `key`, `trigger` (`{kind: manual|at|every|cron|when_idle,
at, minutes, expr, tz, root, settle_ticks}`) or `cron_job` (+ `tz`), and `action` (`{type: persona_prompt,
persona_instance_id, prompt}` | `{type: run_assignment, assignment}` | `{type: start_batch, workspace_id,
plan_id}`), joins an existing key, and answers `{"schedule": <record>}`; `list` answers `{"schedules":
[<record>]}`; `disarm` `{key, disarmed}`. A record is `store/schedules/<key>.json` (`{key, trigger, action,
next_fire, last_fire, enabled, owner_machine, armed_at, armed_by, idle_ticks, held_since}`) — the files are
the whole state. Console tier, deferred through `spawn_reply`. Refusals: `invalid_request` /
`schedule_invalid` (-32602), `automation_off` (a `start_batch` while the workspace's `batch_automation` is
not `start`) and `machine_identity_unavailable` (4090).

The serve ticks it every 60 s beside the Work engine (`queued_turns.start_serve_scheduler`); nothing fires
during a drain, and only the owning machine fires a record. A fire is a QUEUED send on the instance's
chat root (`PersonaTurnExecutor.queue_prompt` / `start_from`), its origin naming `schedule: <key>`; at most
`agent_runtime.scheduler.max_parallel` (root config, read each tick; default 4, `0` unlimited) scheduled turns are in flight (an over-cap fire stays due and logs `schedule.queued`, its fire carries
`waited_s`); `when_idle` fires after `settle_ticks` consecutive idle ticks or gives up after 15 minutes.
A `run_assignment` fire is the Work engine's (`WorkEngine.adopt`): its one row is claimed
`persona:<instance_id>`, recorded and started, so its settle is written back like any engine run; a fire
on a row another claimant holds is refused `already_taken`, a multi-row assignment `schedule_invalid`.
The persona tool is `schedule_manage`, in the opt-in `schedule` toolset (never `harness_core`). Receipts:
`schedule.arm | disarm | fire | queued | abandoned`.

### Messaging methods — the headless persona gateway (p10-messaging)

`runtime.messaging.*` (`agent_runtime/messaging/rpc.py::OPS`, one row per op, registered lazily by
`serve_rpc/registry.py::_ensure_messaging_methods` only where `agent_runtime.messaging` ships — both bundle
manifests switch it off). `status` (read) answers `{enabled, default_persona, platforms: {telegram:
{credential: present|absent, bindings, operators, lane: {state: running|off|draining, reason}}}}`; the token
itself is never on a reply, a receipt or a log. Console: `binding.set|clear|list` (a platform chat POINTS AT a
persona instance; the session is always the instance's current chat root), `operator.allow|revoke|list`
(unknown platform users are dropped fail-closed), `refused.recent` (`{platform?}` → `{refused: {<platform>:
[{user_id, display, chat_id, at}]}}` — the last ≤10 strangers the bridge dropped as `unknown_operator`,
newest first, one row per user, a user allowed since left out; `messaging/refused.py`), `credential.set|clear` (also `LOCAL_CONSOLE_METHODS`: a
paired device never writes the bot token), and `platform.enable|disable` (`{platform?}` → `{platform,
enabled, lane}`), which write `plugins.entries.eternia-harness.settings.messaging_enabled` through
`hermes_cli.config.save_config` and wake the running serve's lane, which converges within one tick — read
`status` for the result. Refusals: `invalid_request` / `unknown_platform` / `token_invalid` (-32602),
`unknown_instance` (4001), else `messaging_unavailable` (-32000), each with `data.reason`.

The bridge is a serve lane (`agent_runtime/messaging/serve_lane.py::start_messaging_bridge`, started by
`queued_turns.start_serve_work_engine` after the scheduler, on the same executor): a platform runs while the
setting is true, its token is present and no drain has begun, else it is `off` with a typed `LaneReason`
(`disabled`, `credential_absent`, `start_failed`, `not_serving`) — a missing token is reported, never raised.
An inbound message is a QUEUED send (`PersonaTurnExecutor.queue_inbound`, cmid `msg-<platform>-<update_id>`,
origin kind `messaging`), so it shows as a `running_work` row of kind `messaging_turn` and its settle carries
the reply; an exec approval on any bound root becomes a platform card answered through
`respond_operator_approval`, the launcher's own resolve. Receipts: `messaging.inbound | queued | replied |
refused | bound | lane | approval_card | approval_answered`. Plan and remaining stages:
[p10-messaging](planned/p10-messaging-2026-10-19.md).

### Lens ingress — the push door

`runtime.lens.ingress.*` (`agent_runtime/serve_rpc/lens.py`, tier console) owns the Lens L3 push door, an
in-serve stdlib listener (`agent_runtime/lens/ingress.py::IngressListener`) bound loopback by default, a
private address only through `ingress.bind`, and only while a route exists. `POST /lens/<route_id>`; a
refusal is a bodiless 4xx (`REFUSAL_STATUS`) plus, for a route that exists, an `ingress_refused` gap row.

A route records its **auth mode** (`ingress_routes.IngressAuth`), chosen at `ingress.register {monitor_id,
kind, mapping?, auth?}`:

- `hmac` (default): `X-Lens-Signature` HMAC-SHA256 over `"<ts>:" + body` with `X-Lens-Timestamp`, or Svix.
  A 5-minute timestamp window and a ring of the last 1024 nonces guard replay.
- `bearer` (owner ruling 2026-10-19, `RT-LENS-ALERTMANAGER-UNSIGNED`; Alertmanager's `webhook_config`
  cannot sign a body): `Authorization: Bearer <the route's same secret>`, compared with
  `hmac.compare_digest` (`ingress.py::verify_bearer`). A bearer route takes bearer only, and an HMAC route
  ignores a bearer header (`AUTH_VERIFIERS`, keyed by the route's mode). With no timestamp, replay is guarded
  by a timestamp-free ring of body digests (`BEARER_REPLAY_WINDOW`, 5 minutes, at most `NONCE_RING`
  entries): the same body to the same route within the window answers 409 `replay`. The ring is listener
  memory and **survives nothing**: a restart or a rebind forgets it, so a body replayed across a restart is
  accepted once more. Only `kind: alertmanager` may take bearer (`BEARER_KINDS`; `bearer_not_for_kind`),
  and only while the bind is loopback or private (`is_local_bind`): register refuses
  `bearer_needs_local_bind`, `ingress.bind` refuses every public or unspecified host for every route
  (`bind_host_not_local`), a hand-edited `lens/ingress.json` naming a host that is not local (or a port
  outside `1024..65535`) is read back as loopback on the default port with the log receipt
  `lens ingress bind refused` (`ingress_routes.ingress_address`), and a listener constructed on a bind that
  is not local answers a bearer route 403 `bearer_public_bind`.

Every route on the wire (`register`, `list`, `revoke`) carries `auth` and `weaker` (`true` for bearer: the
secret travels on every request); the Console labels a weaker route. The secret is in `register`'s answer
once and never on a list, a receipt or a log line; the refusal log receipt is `lens ingress refused:
route=… auth=… reason=…`. Stores written before `auth` existed gain the column on open
(`store.py::_add_route_auth`) and read their routes as `hmac`.

### Conversation-scoped Work

`agent_runtime/work/context.py` resolves optional `conversation` references through existing
conversation authorities. A native reference is `{kind: native, profile, profile_home, session_id}`
(browse only; it names no assignee). An operator reference is `{kind: operator, workspace_id, persona_id,
persona_instance_id, session_id}`; it passes `validate_operator_conversation`, and its persona instance
IS the assignee: `context.assignee = persona:<persona_instance_id>`, the default `who` of a claim, the
default `assignee` of a `start` (a row started there for that instance is written `TAKEN` by it), and the
`conversation` view lists the rows that instance holds (`in_conversation`).

**Lending skills to a worker (p10-work S2).** The gateway worker's `eternia.skills.{list,detail,history}`
(`conversations/worker_skills.py`) take the `eternia.subagents.*` child address — `owner_scope`,
`worker_generation`, `child_ref`, all three or none (a partial address is 4090 `invalid_request`). With it,
the read is the CHILD's (`subagents/native.py::child_record`: its agent's cwd, its own `valid_tool_names` for
`can_load`, its own `session_id` for history) and `list` adds `lent: [..]`; a stale generation or a replaced
worker is the subagent refusal (4602 `subagent_reference_stale`), never a parent read.
`eternia.skills.lend` `{session_id, owner_scope, worker_generation, child_ref, skills, mode: lend | revoke,
request_id}` is the worker half of lending (a write verb, RULED 2026-10-18; a task's half is
`runtime.work.lend_skills`, and `lend` without a child says so): every lent skill is resolved first
(`skills_not_loadable` + `rejected_skills`, nothing written), then the record
`<store_root>/skill_lends/child_<subagent_id>.json` `{target, owner_session, skills, lent_at, lent_by, pid}`
(`agent_runtime/skill_lends.py`), then the child's `_chat_lane_compact_skill_categories` = the parent's
compact set ∩ compact(lent) (an unscoped parent stays unscoped; nothing lent restores the unscoped child),
then a steer (`Skills lent: …` / `Skills no longer lent: …`). Reply `{target, skills_lent, effective:
"next_turn", steered}` — a body already loaded is not unloaded mid-turn. The `eternia.subagents.list` roster
row carries `skills_lent`. The record lives as long as its child: the dispatch drain's orphan cadence
(`dispatch_delivery/drain.py::sweep_skill_lends`) and every lend drop a record whose child this process no
longer registers, and another process's record once that process is dead.

## Optional Console follow-up suggestions

`agent_runtime/serve_rpc/console_suggestions.py` advertises contract 1 through the
existing authenticated Console method lane. `runtime.console_suggestions.settings`
owns `get`, `set`, `subscribe`, `unsubscribe`; `runtime.operator.conversation.suggestions`
owns `read`, `subscribe`, `unsubscribe`, `dismiss`. Each family pushes `.changed`
notifications through the existing connection. The Launcher uses the same notification
dispatcher on local serve and paired LAN routes; an older manifest has no capability.

Settings require `install_id`; writes use `expected_revision` and only changed fields:
`enabled`, `max_context_messages`, `cooldown_seconds`, `auxiliary_override` (null resets
provider/model/base_url while preserving the host's other task policy). The sole writer
is `hermes_cli.plugins_state.update_plugin_configuration`, with managed-key enforcement
and atomic config locking. Defaults are false / 4 / 3. Missing, malformed or invalid
configuration never enables generation; invalid optional tuning remains repairable.

Chat methods use the existing exact operator subject: install, workspace (nullable),
persona, instance, session and client_scope. Native membership and account ownership
are checked before context/inference. Disabled read/subscribe returns without history,
cache initialization or worker startup. Settings metadata subscriptions survive disable.
Invalid arguments use -32602; stale identity/revision uses 4090 with a sanitized reason.

Responses carry `contract`, exact subject, `policy_epoch` and state. A ready entry has
`entry_id`, `entry_revision`, `source_turn_id`, `source_revision`, and free-form `text`.
A durable generation failure uses `unavailable`, the same identity, and a sanitized
auth/rate_limit/timeout/storage/provider reason without draft text. Usage includes the
actual resolved provider/model and token/cost facts from the host facade, separately
from the primary turn. Dismiss compares entry id/revision, and is idempotent.

Subscription replies establish sequence zero; client buffers pre-ack pushes and applies
the newest complete snapshot. Coalesced notifications intentionally permit sequence gaps:
each is a complete state, not a delta. Reconnect creates a fresh authorized subscription.
Use always performs a fresh exact-source read before the existing draft owner inserts.
