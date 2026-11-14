"""Probe: can an upstream platform adapter run as a plain transport, with no GatewayRunner?

For each adapter: build the real upstream class from a PlatformConfig, install ONE handler
(message in -> reply text out), replace only the network send calls with a recorder, hand it one
inbound MessageEvent through the real ``handle_message``, and read what happened.
Nothing connects to a network; HERMES_HOME is a fresh temp dir so any file written is visible.
"""
import asyncio
import importlib
import json
import os
import sys
import tempfile
import time
from pathlib import Path

HOME = Path(tempfile.mkdtemp(prefix="adapter-probe-"))
os.environ["HERMES_HOME"] = str(HOME)
for key in ("TELEGRAM_BOT_TOKEN", "DISCORD_BOT_TOKEN", "SLACK_BOT_TOKEN", "SLACK_APP_TOKEN"):
    os.environ.pop(key, None)

from gateway.config import Platform, PlatformConfig  # noqa: E402
from gateway.platforms.event import MessageEvent  # noqa: E402
import gateway.session as gateway_session  # noqa: E402

STORES_BUILT = []
_orig_init = gateway_session.SessionStore.__init__


def _counting_init(self, *a, **k):
    STORES_BUILT.append(1)
    return _orig_init(self, *a, **k)


gateway_session.SessionStore.__init__ = _counting_init

CASES = [
    ("telegram", "plugins.platforms.telegram.adapter", "TelegramAdapter",
     PlatformConfig(enabled=True, token="1234567890:" + "A" * 35)),
    ("discord", "plugins.platforms.discord.adapter", "DiscordAdapter",
     PlatformConfig(enabled=True, token="x" * 59)),
    ("slack", "plugins.platforms.slack.adapter", "SlackAdapter",
     PlatformConfig(enabled=True, token="xoxb-" + "1" * 40, extra={"app_token": "xapp-" + "1" * 40})),
    ("signal", "plugins.platforms.signal.adapter", "SignalAdapter",
     PlatformConfig(enabled=True, extra={"http_url": "http://127.0.0.1:9", "account": "+10000000000"})),
]


def files_under(root: Path) -> list[str]:
    return sorted(str(p.relative_to(root)).replace("\\", "/") for p in root.rglob("*") if p.is_file())


async def probe(name, module, cls_name, config):
    out = {"adapter": name}
    try:
        cls = getattr(importlib.import_module(module), cls_name)
    except Exception as exc:  # the library or the class is not importable here
        out["import_error"] = f"{type(exc).__name__}: {exc}"[:200]
        return out
    try:
        adapter = cls(config)
    except Exception as exc:
        out["construct_error"] = f"{type(exc).__name__}: {exc}"[:200]
        return out
    out["gateway_runner_is_none"] = getattr(adapter, "gateway_runner", "missing") is None
    sent, seen = [], []

    async def fake_send(chat_id, content, reply_to=None, metadata=None, **kwargs):
        from gateway.platforms.base import SendResult
        sent.append({"chat_id": str(chat_id), "content": content, "reply_to": reply_to})
        return SendResult(success=True, message_id="m-out-1")

    async def quiet(*a, **k):
        return None

    adapter.send = fake_send
    for attr in ("send_typing", "stop_typing"):
        setattr(adapter, attr, quiet)

    async def handler(event):
        seen.append({"text": event.text, "chat_id": event.source.chat_id, "user_id": event.source.user_id})
        return f"persona reply to: {event.text}"

    adapter.set_message_handler(handler)
    before = files_under(HOME)
    source = adapter.build_source(chat_id="4242", chat_type="dm", user_id="777", user_name="owner")
    event = MessageEvent(text="hello from the probe", source=source, message_id="m-in-1")
    try:
        await adapter.handle_message(event)
        deadline = time.monotonic() + 15
        while not sent and time.monotonic() < deadline:
            await asyncio.sleep(0.05)
        await asyncio.sleep(0.3)
    except Exception as exc:
        out["handle_error"] = f"{type(exc).__name__}: {exc}"[:300]
    out["handler_calls"] = seen
    out["sent"] = sent
    out["files_written_under_home"] = [f for f in files_under(HOME) if f not in before]
    try:
        await adapter.cancel_background_tasks()
    except Exception:
        pass
    return out


async def main():
    results = [await probe(*case) for case in CASES]
    print(json.dumps({
        "results": results,
        "session_stores_built": len(STORES_BUILT),
        "gateway_run_imported": "gateway.run" in sys.modules,
        "gateway_modules_loaded": sorted(m for m in sys.modules if m.startswith("gateway.run")),
        "home": str(HOME),
    }, indent=1))


asyncio.run(main())
