# Upstream platform adapters as plain transports — audit, 2026-11-14

Rows: `RT-MESSAGING-UPSTREAM-ADAPTER-TRIAL` (its step 1, then both halves of
step 2) and the owner's decision `RT-MESSAGING-NEXT-APPS-REUSE-UPSTREAM-CONNECTORS`.
Related: `FORK-PARALLEL-MESSAGING-GATEWAY`. Run on Windows at fork `eb1fa62052`,
Python 3.13.15, by lane msg-adapter-audit at the owner's ask in chat.

## Result in one paragraph

An upstream adapter can be used as a pipe. Four real adapter classes (Telegram, Discord,
Slack, Signal) were built with no `GatewayRunner`, given one handler, and handed an inbound
message through the real `handle_message`. In every case the handler got the message, the
reply went out through the adapter's `send`, no `SessionStore` was built and `gateway.run`
was never imported. Then the fork side was built as a throwaway trial: one shim class behind
`agent_runtime/messaging/transport.py::Transport`, with the real
`agent_runtime/messaging/bridge.py::MessagingBridge` on top. A message through each of the
four upstream adapters became a queued turn on the persona's one chat root, and the settle's
reply went back out through the adapter — 24 tests passed. No adapter was connected to its
real platform; that is the main thing still not shown.

## What was run

`adapter_probe.py` and `adapter_probe_queued.py` in this folder, from the repository root
with `PYTHONPATH` set to it and the fork's test interpreter. Each builds the upstream class
from a `PlatformConfig`, replaces only the network calls (`send`, `send_typing`,
`stop_typing`) with a recorder, sets `HERMES_HOME` to a fresh temp directory, and counts
`gateway/session.py::SessionStore` constructions.

| | Telegram | Discord | Slack | Signal |
|---|---|---|---|---|
| Built with `gateway_runner` None | yes | yes | yes | yes |
| Handler called once with the text | yes | yes | yes | yes |
| Reply returned by the handler sent to the same chat, as a reply | yes | yes | yes | yes |
| `SessionStore` objects built | 0 | 0 | 0 | 0 |
| `gateway.run` imported | no | no | no | no |

Two ways to answer were probed:

1. **The handler returns the reply text** (`adapter_probe.py`). The base class sends it.
   It also writes a durable record first: `state.db` under `HERMES_HOME`, table
   `delivery_obligations`, one row per reply holding the full reply text, the chat id and
   upstream's session key (`agent:main:telegram:dm:4242`). That table was the only one in
   the file — no sessions, no messages. The switch is `gateway.delivery_ledger: false`
   (`gateway/delivery_ledger.py::ledger_enabled`, default on). The fork's own receipts never
   carry message text, so this mode needs that switch off or it adds a second place reply
   text is stored.
2. **The handler returns None and the reply is sent later** (`adapter_probe_queued.py`),
   which is how the fork already works: the turn is queued and the settle carries the
   reply. Nothing was written under `HERMES_HOME`, the adapter's busy guard was empty as
   soon as the handler returned, and a later direct `adapter.send(...)` delivered. This
   mode needs no "wait for the reply" bridge and skips the base class's delivery ledger,
   media extraction and voice-reply steps, because they only run on a returned reply.

Mode 2 is the one that fits the fork.

## The plan's two reasons, re-read at both commits

`docs/agent-runtime-harness/planned/p10-messaging-2026-10-19.md` §2.2 read upstream
`e0b51e400f`. The boundary there and at today's tree is the same in the ways that matter:

| | at `e0b51e400f` | at `eb1fa62052` |
|---|---|---|
| `gateway/platforms/base.py` class default `gateway_runner = None` | present | present |
| `set_message_handler` takes one callable | yes | yes |
| Uses of `self.gateway_runner.` reachable with no runner set | 0 (2 lines, each reached only when a runner is set) | 0 (the same 2 lines) |
| Telegram / Discord / Slack uses of the runner or `_session_store` not behind getattr | 0 / 0 / 0 | 0 / 0 / 0 |

So upstream did not change this since the plan was written: the plan overstated it. Reason
(a), "wrapping the adapter is wrapping upstream's session machinery", and reason (b), "a
fork handler would have to impersonate the runner's private surface", do not hold. The
adapters themselves say why: under upstream's multi-profile mode the handler is a plain
closure with no runner behind it, and the Telegram and Slack adapters carry comments and
fallbacks for exactly that case. Reason (c), most of an adapter is upstream product
behaviour the fork does not ship, holds.

## Costs, measured

- **Libraries** (installed size in the fork's environment, package folder only, their own
  dependencies not counted): `telegram` 7.7 MB, `discord` 7.9 MB plus `nacl` 1.0 MB,
  `slack_bolt` 2.3 MB plus `slack_sdk` 3.1 MB. Whether each can enter the bundled-desktop
  and bundled-phone closures was not checked.
- **Upstream tests on ADR 0015's skip list** (`tests/fixtures/upstream_skip_list.txt`):
  194 file rows are marked `unused: messaging platform adapters (ADR 0015)`. By name:
  Telegram 60, Discord 49, Slack 25, WhatsApp 18, Matrix 18, Signal 2. Adopting one
  adapter makes that adapter's rows a choice: run them again, or keep them skipped and
  cover the pipe with fork tests. Their gate seconds were not measured (the plan says
  610 s for all of them).
- **Adapter size the fork would depend on but not own**: Telegram 6,759 lines, Discord
  7,312, Slack 6,958, Signal 984 (`adapter.py` alone), on a 4,837-line base class.

## Base-class behaviour that overlaps the fork's send queue

| Behaviour | Where | In mode 2 |
|---|---|---|
| Busy-chat guard and interrupt-or-queue of a second message | `handle_message`, `_handle_message_while_active` | Inactive: the guard clears when the handler returns |
| Delivery ledger with reply text | `_record_delivery_obligation` | Not reached |
| Media extraction and voice replies from reply text | `_extract_response_content`, `_synthesize_auto_tts` | Not reached |
| Typing refresh while the handler runs | `_start_typing_refresh` | Runs only for the instant the handler takes; the fork sends its own |
| Text batching of split messages | `_enqueue_text_event` | Still runs where an adapter uses it (0.3 s default); not probed |
| Upstream slash commands (`/new`, `/model` and so on) | the runner's handler | Absent with the runner; only the fork's `/persona` exists |

## The fork half: the shim trial (added later the same day)

Built on branch `trial/upstream-adapter-shim` (pushed to origin, commit `6b2ae23ffa`; not on
`main`, nothing constructs it in the serve): one class, `UpstreamAdapterTransport`, that
implements the fork's `Transport` over any upstream adapter, and one test file that runs the
real `MessagingBridge` on top of it — the real operator, binding and refused-sender stores,
the real send queue and `PersonaTurnExecutor`, the rig of
`tests/agent_runtime/messaging/test_bridge_inbound.py`. Only the adapter's network calls are
recorders; a message arrives through the adapter's real `handle_message`.

**24 passed: 6 tests, each against the Telegram, Discord, Slack and Signal adapters.**

| What the test shows | All four adapters |
|---|---|
| A message through the upstream adapter is a QUEUED turn on the persona's one chat root, bound instance and origin recorded | yes |
| No upstream `SessionStore` is built, and the adapter holds no busy state afterwards | yes |
| The settle's reply goes out through the adapter to the origin chat and thread, as a reply to the message | yes |
| A stranger reaches the bridge, is refused there and is listed for the console's Allow list | yes |
| The same message delivered twice is one queued entry | yes |
| A busy root holds the message and says so once | yes |
| An unbound chat gets the roster and `/persona` binds it (upstream's slash commands are absent with the runner) | yes |

Each of the shim's three load-bearing lines was broken once and the tests watched go red:
the handler not calling the bridge (24 failed), `send` returning before `adapter.send`
(12 failed), the message id mixing in a clock (20 failed); restored, 24 passed.

**The shim's cost:** 154 lines, 119 without blanks and comments. It is the same class for
all four adapters — no per-adapter branch. For comparison the fork's own Telegram transport,
`agent_runtime/messaging/telegram_api.py`, is 279 lines for one platform.

**One thing the trial found and fixed:** with the adapter's defaults the typing indicator
was sent twice per message, once by the base class's own typing refresh and once by the
bridge. `PlatformConfig(typing_indicator=False)` turns the base class's off; the shim's
adapters must be built that way.

## What is still not shown

- No adapter connected to its platform. `connect()` needs real credentials and a network;
  the inbound message was built with `build_source` and handed to `handle_message`, so each
  adapter's own parsing of a platform update, and its sender gate ahead of `handle_message`,
  were not exercised. The shim tells the adapter's gate yes through
  `set_authorization_check` and lets the fork's operator list decide; whether every adapter
  honours that callback before its own environment allowlist needs one live message per app.
- Approval cards: `send_card`, `edit` and `answer_callback` raise in the shim. Upstream has
  `send_exec_approval` per adapter; mapping the fork's cards onto it is not tried.
- The bridge was labelled `telegram` in every run: `agent_runtime/messaging/models.py::Platform`
  has one member, and a new member, its token shape and its page in Eternia are per-app work.
- Token storage: the adapters read `PlatformConfig.token`; feeding it from
  `agent_runtime/messaging/credentials.py::bot_token` was not tried.
- Whether each adapter library can enter the bundled-desktop and bundled-phone closures.
- Long replies: each adapter splits at its own limit inside `send`, which the recorder
  replaced, so chunking through an upstream adapter was not observed.

## Reading

Worth it for the apps after Telegram. The reason the fork hand-built Telegram — keeping the
persona system and one conversation — does not require hand-building the next app: the
persona system sits above the pipe in both designs, and one 154-line class carried four
different upstream adapters through the bridge's behaviour unchanged. The fork's own
Telegram transport has no reason to be replaced. What a real second app still needs is the
list above, and the first item — one live message on the real platform — is the one that
could still change this reading.
