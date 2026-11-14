# Switching Telegram to upstream's adapter — audit, 2026-11-14

Row: the owner's decision `RT-MESSAGING-NEXT-APPS-REUSE-UPSTREAM-CONNECTORS`. The owner asked
in chat for "a proper audit" before any switch. This note is that audit; the earlier trial is
`README.md` beside it. Run on Windows, Python 3.13.15, python-telegram-bot 22.8, by lane
msg-switch-audit. Code: branch `audit/upstream-telegram-switch` (pushed to origin, commit
`62920f2b68`; not on `main`, nothing constructs it in the serve).

## What changed since the trial: nothing is injected any more

The trial handed messages to `handle_message` and replaced the adapter's `send`. Here the
adapter is whole. A local HTTP server on 127.0.0.1
(`fake_bot_api_server.py`, in the branch's messaging tests) stands in for
Telegram's Bot API, and the upstream adapter is pointed at it with its own `base_url`
setting. `connect()` is the adapter's own; an update arrives through python-telegram-bot's
long poll and is parsed and gated by the adapter's own handlers; the reply leaves as a real
`sendMessage` HTTP request. No `GatewayRunner` exists in the process. The only thing not
real is Telegram itself.

## Results

| Check | Result | Evidence |
|---|---|---|
| The adapter connects with no runner | Pass, 0.5 s | `test_connect_is_the_adapters_own_and_needs_no_runner` |
| A real update becomes a queued turn on the persona's one chat root, keyed by Telegram's own update id | Pass | `test_a_real_update_becomes_a_queued_turn_and_the_reply_is_a_real_send` |
| The reply is a real `sendMessage` to the same chat, as a reply to the message | Pass | same |
| No upstream `SessionStore` is built; `gateway.run` is never imported | Pass | same; side-effect run below |
| A 10,000-character reply is split at Telegram's 4,096 limit with nothing lost | Pass | `test_a_long_reply_is_split_by_the_adapter_at_telegrams_limit` |
| `/persona` reaches the bridge through the adapter's command handler and binds the chat | Pass | `test_persona_command_reaches_the_bridge_and_binds_the_chat` |
| A forum-topic message keeps its thread in both directions | Pass | `test_a_forum_topic_message_keeps_its_thread_both_ways` |
| The fork's approval cards: sent, pressed, answered once, edited | Pass, with Telegram-specific code | `test_a_card_is_sent_pressed_answered_and_edited` |
| A button that is not the fork's stays the adapter's | Pass | `test_a_press_that_is_not_the_forks_stays_the_adapters` |
| The fork's own messaging tests still pass beside all of this | Pass | 65 passed in one run: the 5 audit and trial files plus `test_bridge_inbound.py`, `test_telegram_api.py`, `test_approval_cards.py` |

## Five defects the audit found, each fixed in the shim and pinned by a test

Every one of these would have shipped with a naive switch. Each fix was broken once on
purpose and its test watched go red.

1. **A stranger's media is fetched before anyone refuses them.** With no allowlist
   configured, `TelegramAdapter._is_user_authorized_from_message` passes every sender and
   leaves the decision to a runner the fork does not start; `_handle_media_message` then
   calls `getFile` and downloads the photo before the handler runs. Shown over HTTP
   (`test_with_the_open_gate_a_strangers_photo_is_downloaded_before_the_bridge_refuses`).
   Fix: the shim configures an (empty) `allow_from` so the adapter asks the fork's
   `OperatorStore` at intake. Hardened, nothing of a stranger's is fetched and the allowed
   operator still gets through. Cost of the fix: a stranger no longer reaches the bridge, so
   the console's Allow list must be fed from the shim's `on_refused`, which gets the user id
   and chat id but NOT the display name the fork's own transport records.
2. **Replies arrive silently.** The adapter sends with `disable_notification` unless a reply
   is marked `notify`; the base class marks that only on a reply the handler RETURNS, which
   the shim never does. The phone would not buzz. Fix: the shim sets `notify` on every send.
3. **Upstream's command menu is pushed onto the bot.** After connect the adapter calls
   `setMyCommands` with upstream's slash commands (`/new`, `/model` and so on), which live in
   the runner and would do nothing here. There is no config switch for it. Fix: an override
   of the adapter instance's `_register_command_menu` — a patch on a private method, which an
   upstream release can rename.
4. **The bot token is written to the log at INFO.** python-telegram-bot's HTTP client logs
   every request URL on the `httpx` logger, and the URL carries the token: 10 lines in one
   short session. Fix: the token is registered with the redactor the fork's own transport
   already uses.
5. **Message text is written to the log at DEBUG.** python-telegram-bot's own loggers print
   whole updates and sends. The fork's receipts never carry text. Fix: those loggers are held
   at INFO.

## Differences that are not defects but change what the owner sees

- **Formatting.** The adapter converts replies to Telegram MarkdownV2, so bold, code and
  lists render. The fork's transport sends plain text. An improvement, but it is a change.
- **Two extra files** appear in the Hermes home: `gateway_state.json` (a runtime-status
  writer whose thread, `gateway-runtime-status-writer`, was still alive after `stop()`) and
  `telegram_update_receipts_<bot id>.json` (the adapter's update de-duplication). Neither
  held the token or message text.
- **Approval cards need per-platform code.** Upstream's own approval buttons resolve against
  upstream's approval registry and cannot carry the fork's cards. The Telegram subclass goes
  down to the python-telegram-bot `Bot` and registers its own press handler ahead of the
  adapter's. That is about 60 lines that every other adapter would need its own version of,
  so "one shim, every app" holds for messages and not for approvals. The handler is added
  once after `connect()`; the adapter rebuilds its application on a transient-init retry,
  and a real build must register through upstream's plugin handler factory to survive that.
- **One poller per token.** Telegram allows one long poll per bot. The fork's transport and
  the upstream adapter must never run on the same token together; a staged switch is
  either-or per token, never both.

## Pairing codes

`gateway/pairing.py::PairingStore` was run on its own, no runner: an 8-character code,
stored salted and hashed; a second code for the same user is refused by its rate limit; a
wrong code is counted; `approve_code` returns the user id and name, which is what the fork
needs to write its own operator row. It also writes its own
`platforms/pairing/telegram-approved.json` — a second approved list. Nothing reads it if
the fork only consults `OperatorStore`, but it should be cleared or ignored on purpose, not
by accident. The step that replies to a stranger with a code is in the runner
(`gateway/run_inbound.py`), so the fork's bridge would send it.

## Builds

Not a new blocker. `agent_runtime.messaging` is itself in `switched_off_modules` in both
`bundled-desktop.yaml` and `bundled-phone.yaml`, beside `gateway.platforms` and
`plugins.platforms`: messaging already runs only on a full Harness, never in a bundled
build. There the adapter's library is the `messaging` extra of `pyproject.toml`
(`python-telegram-bot[webhooks]==22.8`), which must be installed where messaging is on.

## Streaming

Not available from the fork side today as far as was read: no partial-text hook was found in
`agent_runtime/work_store/persona_turn.py`, `agent_runtime/chat_root_send_queue.py` or
`agent_runtime/mission_chat_door.py`; the settle carries the whole reply. The adapter can
edit a sent message, so streaming is a fork-side feature to add, not something the switch
brings on its own. Read in code, not run.

## Upstream's own Telegram tests

The 60 Telegram test files on ADR 0015's skip list were run by name in the fork's environment: **558 passed, 2 failed, in 39 s**. Both failures are in `test_telegram_closewait_windows_live.py` (`test_drain_recovers_after_server_half_close_live`, `test_drain_bounded_and_functional_when_close_wedges_live`): Windows-only tests of the adapter recovering a long poll stuck on a half-closed socket. Why they fail on this box was not investigated. They matter for the switch: that recovery is what keeps the bot answering after a network drop on Windows, so it must be understood before upstream's adapter is the default there.

## What only the owner can check

Everything above ran against a stand-in for Telegram. Three things need a real bot, a real
phone and the owner:

1. That real Telegram accepts what the adapter sends the way the stand-in does: MarkdownV2
   formatting of a real agent reply is the likeliest surprise (a reply with unusual
   characters can be rejected and fall back to plain text).
2. That the phone buzzes, the reply threads under the question, and an approval card's
   buttons work in the real app.
3. A day of ordinary use, for the things a stand-in cannot produce: network drops, Telegram
   rate limits, the 409 conflict if two pollers ever meet.

## Reading

The switch is sound and the persona system is preserved, but it is not a drop-in: five
defects had to be fixed in the shim before the behaviour matched what the fork does today,
and one of them (a stranger's media fetched before refusal) is a safety matter. With those
fixes the upstream adapter did everything the fork's own Telegram transport does, against a
stand-in. The remaining risk is what only real Telegram can show. So: build it as a second
option that is off by default, on the code of this branch; the owner runs it with a real bot;
it becomes the default, and the fork's own transport is retired, only after that.

## After the audit: the live check and the opt-in build (added later the same day)

**Live, on real Telegram** (reported by the owner, not seen by the lane): the owner ran
`scripts/live_telegram_check.py` with a throwaway bot. The bot reached step 6 of 6, so
connect, a threaded reply, the formatted reply, the split long reply, an approval card's
press and edit, and a photo all went through Telegram's real servers; asked whether the phone
buzzed, the reply threaded, the formatting rendered, line 130 arrived and the card changed,
the owner answered yes. The console summary was not pasted, and the stranger step is not
confirmed.

**Built, on `main`, off by default** (`RT-MESSAGING-TELEGRAM-ON-UPSTREAM-ADAPTER-OPT-IN`):
the harness setting `messaging_telegram_transport` (`fork` by default, `upstream` to opt
in) picks the connector in `agent_runtime/messaging/serve_lane.py`; a changed setting stops
the running connector before the other starts. Beyond the audit branch, the build:

- asks the fork's operator list at the adapter's intake with the sender's NAME, so the
  console's Allow list shows a name as it does today (the audit's fix lost it);
- registers the approval-card press handler on every application the adapter builds, so a
  rebuilt application after a failed connect still has it;
- writes the same `messaging.refused` receipt the bridge writes for a stranger;
- treats an adapter that does not connect as a failed start (`start_failed`).

One more behaviour difference seen in the live script's dry run: the adapter merges messages
sent within a fraction of a second into one, where the fork's transport queues each.

Tests: `tests/agent_runtime/messaging/test_serve_lane_transport_choice.py` (the setting, the
restart order, the real factory through the lane against the local Bot API) beside the four
audit files. The whole messaging folder: 111 passed. The landing gate
(`scripts/run_tests_bundled.sh tests`) reported 92 failures in 79 files on this tree; one
was this change's (a test imported pyyaml) and is fixed; none of the others names a file of
this change, and five of them were read (a function-length floor in `chat_turn.py`, a
secret-word rule in `realm_sync`, two package patches in other tests, a source-grep
assertion, an id-marker set) — the rest were not read one by one.

Still unproven: a day of ordinary use on the owner's real bot, and the two upstream Windows
stuck-poll tests.
