#!/usr/bin/env python3
"""LIVE check (RT-MESSAGING-TELEGRAM-ON-UPSTREAM-ADAPTER-OPT-IN): the upstream Telegram adapter, behind the
fork's shim, against REAL Telegram.

The owner runs this with a THROWAWAY test bot (create one with @BotFather; do not use a bot the Harness
is already polling — Telegram allows one poller per token). The bot itself walks the owner through the
steps in the chat; this console prints what the adapter saw and a summary at the end.

    set the token yourself, in your own terminal (it is never printed and never written to disk):
        PowerShell:  $env:TELEGRAM_LIVE_TEST_TOKEN = '<token from @BotFather>'
        bash:        export TELEGRAM_LIVE_TEST_TOKEN='<token from @BotFather>'
    then, from the repository root:
        python scripts/live_telegram_check.py

Nothing of the owner's Harness is touched: the adapter's files go to a temporary home, no persona runs, no
turn is queued. What is under test is the one thing the audit could not show — the adapter and the shim
talking to Telegram's real servers: connect, receive, reply (buzz, threading), formatting, a long reply,
an approval card's buttons, a photo, and a stranger being refused.
"""

from __future__ import annotations

import logging
import os
import secrets
import sys
import tempfile
import threading
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

TOKEN_ENV = "TELEGRAM_LIVE_TEST_TOKEN"
BASE_URL_ENV = "TELEGRAM_LIVE_TEST_BASE_URL"  # dry runs against the local stand-in only
PRESS_PREFIX = "ap"
TIMEOUT_S = float(os.environ.get("TELEGRAM_LIVE_TEST_TIMEOUT", "600"))

FORMATTED = (
    "*Step 2 of 6 — formatting.*\n\n"
    "This reply has **bold**, _italic_, `inline code`, a list and awkward characters:\n\n"
    "- price: $4.50 (50% off!)\n- path: C:\\Users\\name\\file_v2.txt\n- maths: 2 * 3 = 6, a_b_c, [x](y)\n\n"
    "```python\nprint('hello | world')  # a code block\n```\n\n"
    "If you can read all of that, formatting works. Reply *ok* to continue."
)


def main() -> int:
    token = os.environ.get(TOKEN_ENV, "").strip()
    if not token:
        print(f"Set {TOKEN_ENV} in your own terminal first (see the top of this file). Nothing was run.")
        return 2
    os.environ["HERMES_HOME"] = tempfile.mkdtemp(prefix="live-telegram-check-")
    for name in ("TELEGRAM_ALLOWED_USERS", "TELEGRAM_GROUP_ALLOWED_USERS", "GATEWAY_ALLOW_ALL_USERS",
                 "TELEGRAM_WEBHOOK_URL", "TELEGRAM_BOT_TOKEN"):
        os.environ.pop(name, None)
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")

    from agent_runtime.messaging.transport import Button, CallbackPress, InboundMessage
    from agent_runtime.messaging.upstream_adapter_transport import TelegramUpstreamAdapterTransport
    from gateway.config import PlatformConfig
    from plugins.platforms.telegram.adapter import TelegramAdapter

    extra = {}
    if os.environ.get(BASE_URL_ENV):
        extra["base_url"] = os.environ[BASE_URL_ENV]
        os.environ["HERMES_TELEGRAM_DISABLE_FALLBACK_IPS"] = "1"
    adapter = TelegramAdapter(PlatformConfig(enabled=True, token=token, typing_indicator=False, extra=extra))

    code = f"{secrets.randbelow(900000) + 100000}"
    state = {"owner": None, "chat": None, "step": 0, "card": None, "refused": []}
    results: list[tuple[str, str]] = []
    done = threading.Event()
    lock = threading.Lock()

    def note(name: str, outcome: str) -> None:
        results.append((name, outcome))
        print(f"  [{outcome}] {name}", flush=True)

    def is_allowed(user_id: str) -> bool:
        return state["owner"] is None or user_id == state["owner"]

    def on_refused(user_id: str, chat_id: str) -> None:
        state["refused"].append(user_id)
        print(f"  [seen] a stranger (user {user_id}) was refused by the adapter before reaching the handler",
              flush=True)

    transport = TelegramUpstreamAdapterTransport(adapter, press_prefix=PRESS_PREFIX, connect=True,
                                                 is_allowed=is_allowed, on_refused=on_refused)

    def say(text: str, reply_to: str | None = None) -> bool:
        sent = transport.send(state["chat"], text, None, reply_to)
        return bool(sent.refs)

    def on_update(update) -> None:
        with lock:
            try:
                handle(update)
            except Exception as exc:  # keep the poller alive; the failure is a result
                note(f"step {state['step']} raised {type(exc).__name__}: {exc}", "FAIL")

    def handle(update) -> None:
        if isinstance(update, CallbackPress):
            if state["step"] == 4 and state["card"] is not None:
                choice = update.data.rsplit(":", 1)[-1]
                transport.answer_callback(update.callback_id, f"You pressed: {choice}")
                transport.edit(state["card"], f"Step 4 of 6 — you pressed “{choice}”. The buttons are gone "
                                              "and this text replaced the card.", None)
                note("approval card: a press arrived, was answered and the card was edited", "ok")
                state["step"] = 5
                say("*Step 5 of 6 — a photo.* Send me any photo (a caption is optional).")
            return
        if not isinstance(update, InboundMessage):
            return
        text = update.text.strip()
        if state["owner"] is None:
            if code not in text:  # the adapter merges messages sent in quick succession into one
                return  # not claimed yet: only the code printed in the console is accepted
            state["owner"], state["chat"] = update.user_id, update.chat_id
            note(f"connect and receive: your message arrived (you are user {update.user_id})", "ok")
            ok = say("*Step 1 of 6 — a reply.* This message should have made your phone buzz, and it should "
                     "be shown as a reply to the code you sent. Reply *ok* to continue.", update.message_id)
            note("reply sent as a threaded, notifying message", "ok" if ok else "FAIL")
            state["step"] = 1
            return
        if state["step"] == 1:
            ok = say(FORMATTED)
            note("formatted reply accepted by Telegram", "ok" if ok else "FAIL")
            state["step"] = 2
        elif state["step"] == 2:
            body = "\n".join(f"{n}. This is line {n} of a long reply, to cross Telegram's message limit."
                             for n in range(1, 131))
            sent = transport.send(state["chat"], "*Step 3 of 6 — a long reply.*\n\n" + body
                                  + "\n\nIt should have arrived as several messages ending at line 130. "
                                    "Reply *ok* to continue.", None, None)
            note(f"long reply delivered in {len(sent.refs)} message(s)", "ok" if len(sent.refs) > 1 else "FAIL")
            state["step"] = 3
        elif state["step"] == 3:
            state["card"] = transport.send_card(
                state["chat"], "Step 4 of 6 — an approval card. Press either button.",
                [Button("Allow once", f"{PRESS_PREFIX}:live:once"), Button("Deny", f"{PRESS_PREFIX}:live:deny")],
                None)
            note("approval card sent", "ok")
            state["step"] = 4
        elif state["step"] == 5:
            note("photo: the adapter received it and handed it on without error", "ok")
            state["step"] = 6
            say("*Step 6 of 6 — a stranger.* Optional: from a DIFFERENT Telegram account, send this bot any "
                "message or photo. It must get no answer. Then, from this account, reply *done* "
                "(or reply *done* now to skip).")
        elif state["step"] == 6 and text.lower() == "done":
            say("All steps finished. Thank you — the summary is in the console.")
            done.set()

    print("Connecting to Telegram…", flush=True)
    started = time.monotonic()
    try:
        transport.start(on_update)
    except Exception as exc:
        print(f"Could not connect: {type(exc).__name__}: {str(exc).replace(token, '<token>')[:300]}")
        return 1
    if not adapter.is_connected:
        print("The adapter did not connect (wrong token, or another program is polling this bot).")
        transport.stop()
        return 1
    bot = getattr(adapter, "_bot", None)
    username = getattr(bot, "username", None) or "your bot"
    note(f"connected to Telegram as @{username} in {time.monotonic() - started:.1f}s", "ok")
    print(f"\n  Open Telegram, find @{username}, and send it this code:  {code}\n"
          f"  The bot will then walk you through six steps. (Waiting up to {int(TIMEOUT_S / 60)} minutes.)\n",
          flush=True)

    finished = done.wait(TIMEOUT_S)
    transport.stop()
    print("\n── Summary ──")
    for name, outcome in results:
        print(f"  [{outcome}] {name}")
    if state["refused"]:
        print(f"  [ok] {len(state['refused'])} message(s) from a stranger were refused before the handler")
    else:
        print("  [not tried] no stranger messaged the bot")
    if not finished:
        print(f"  [incomplete] stopped at step {state['step']} of 6 (timed out or interrupted)")
    failed = [name for name, outcome in results if outcome == "FAIL"]
    print("\nWhat only you can confirm, by looking at the phone: the buzz on step 1, the reply threading on "
          "step 1, the formatting on step 2, the last line (130) on step 3, and the card changing on step 4.")
    return 1 if failed or not finished else 0


if __name__ == "__main__":
    raise SystemExit(main())
