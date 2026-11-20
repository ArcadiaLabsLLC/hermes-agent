"""The Telegram live check, run end to end against the local Bot API stand-in, so a break shows before the owner's sitting.

Row ``RT-MESSAGING-LIVE-CHECK-STAND-IN-RUN-NEEDS-A-HAND-WRITTEN-DRIVER`` (review w1118a.48 D8): nothing in the
suite ran ``scripts/live_telegram_check.py``; its dry run (``TELEGRAM_LIVE_TEST_BASE_URL``) still waited for
a human to send the code and each reply. This test plays that human against ``FakeTelegram``: the code the
console prints, an ``ok`` per step, a press on the approval card, a photo, a stranger, then ``done`` — and
asserts what each step put on the wire, exit 0, and that the token is in neither the log nor the console.
A fake token only; nothing leaves 127.0.0.1.
"""

from __future__ import annotations

import importlib.util
import logging
import re
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.agent_runtime.messaging._telegram_extra import require_telegram_extra
from tests.agent_runtime.messaging.fake_bot_api_server import FakeTelegram
from tests.agent_runtime.messaging.test_upstream_telegram_end_to_end import GATE_ENV, TOKEN, _wait

require_telegram_extra()

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "live_telegram_check.py"
OWNER, STRANGER = 42, 99
#: The adapter's own photo batch window (``_media_batch_delay_seconds``, default 0.8 s), named here so the
#: photo step's wait is a known bound, not a guessed sleep: the script only answers once the batch flushed.
MEDIA_BATCH_DELAY_S = 0.8
STEP_WAIT_S = 20.0


def _load_script():
    spec = importlib.util.spec_from_file_location("live_telegram_check_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def run(monkeypatch, tmp_path, caplog):
    check = _load_script()
    server = FakeTelegram(TOKEN)
    console: list[str] = []
    for name in GATE_ENV:
        monkeypatch.delenv(name, raising=False)
    # ``main`` writes these into ``os.environ`` itself; setting them here first lets monkeypatch restore them.
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "before"))
    monkeypatch.setenv("HERMES_TELEGRAM_DISABLE_FALLBACK_IPS", "1")
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    monkeypatch.setenv("HERMES_TELEGRAM_MEDIA_BATCH_DELAY_SECONDS", str(MEDIA_BATCH_DELAY_S))
    monkeypatch.setenv(check.TOKEN_ENV, TOKEN)
    monkeypatch.setenv(check.BASE_URL_ENV, server.base_url)
    monkeypatch.setattr(check, "TIMEOUT_S", 45.0)
    monkeypatch.setattr(check, "tempfile", SimpleNamespace(
        mkdtemp=lambda prefix: str(tmp_path / "check-home")))
    monkeypatch.setattr(check, "print", lambda *args, **_: console.append(" ".join(map(str, args))),
                        raising=False)
    caplog.set_level(logging.DEBUG)
    outcome: dict = {}
    thread = threading.Thread(target=lambda: outcome.setdefault("exit", check.main()),
                              name="live-telegram-check", daemon=True)
    thread.start()
    rig = SimpleNamespace(server=server, console=console, outcome=outcome, thread=thread,
                          text=lambda: "\n".join(console))
    yield rig
    thread.join(check.TIMEOUT_S + 5)
    server.close()


def _sent_since(server: FakeTelegram, mark: int) -> list[dict]:
    return list(server.sent[mark:])


def _methods_since(server: FakeTelegram, mark: int) -> list[str]:
    return [method for method, _ in server.calls[mark:]]


def test_the_live_check_passes_its_six_steps_and_the_stranger_against_the_stand_in(run, caplog):
    server = run.server
    # Step 0: connect. Mutation: ``if True:`` for ``if not adapter.is_connected:`` (the not-connected
    # exit always taken) -> red: the code never prints.
    printed = _wait(lambda: re.search(r"send it this code:\s+(\d{6})", run.text()), STEP_WAIT_S, "the code")
    assert printed, run.text()
    assert {"getMe", "getUpdates"} <= set(server.methods())

    # Step 1: the owner sends the code; the answer is a threaded, notifying reply to it.
    # Mutation: ``say(..., None)`` for step 1 (no reply_to) -> red: the reply is not threaded.
    mark = len(server.sent)
    sent_code = server.push_message(f"my code is {printed.group(1)}", user_id=OWNER)
    assert _wait(lambda: _sent_since(server, mark), STEP_WAIT_S, "step 1's reply")
    reply = server.sent[mark]
    reply_to = reply.get("reply_to_message_id") or (reply.get("reply_parameters") or {}).get("message_id")
    assert str(reply_to) == str(sent_code["message"]["message_id"])
    assert not reply.get("disable_notification")

    # Step 2: a formatted reply. Mutation: ``say("hi")`` for ``say(FORMATTED)`` -> red.
    mark = len(server.sent)
    server.push_message("ok", user_id=OWNER)
    assert _wait(lambda: _sent_since(server, mark), STEP_WAIT_S, "step 2's reply")
    formatted = server.sent[mark]
    assert formatted.get("parse_mode") in {"MarkdownV2", "HTML", "Markdown"}
    assert "hello" in str(formatted.get("text"))

    # Step 3: a long reply, split under Telegram's limit, ending at line 130.
    # Mutation: ``range(1, 11)`` in step 2's branch -> red: one message, the note says FAIL.
    mark = len(server.sent)
    server.push_message("ok", user_id=OWNER)
    assert _wait(lambda: any("130" in str(m.get("text")) for m in _sent_since(server, mark)),
                 STEP_WAIT_S, "step 3's last line")
    parts = _sent_since(server, mark)
    assert len(parts) > 1 and all(len(str(part.get("text"))) <= 4096 for part in parts)

    # Step 4: an approval card; a press is answered and the card edited.
    # Mutation: drop ``transport.edit`` in the press branch -> red: no editMessageText.
    mark = len(server.sent)
    server.push_message("ok", user_id=OWNER)
    assert _wait(lambda: any(m.get("reply_markup") for m in _sent_since(server, mark)), STEP_WAIT_S, "the card")
    calls = len(server.calls)
    server.push_press("ap:live:once", message_id=999, user_id=OWNER)
    assert _wait(lambda: {"answerCallbackQuery", "editMessageText"} <= set(_methods_since(server, calls)),
                 STEP_WAIT_S, "the press answered and the card edited")

    # Step 5: a photo; the script asks for step 6 only once the adapter's photo batch flushed.
    # Mutation: the step-5 branch keyed on ``state["step"] == 50`` -> red: step 6 is never asked.
    mark = len(server.sent)
    server.push_photo("a caption", user_id=OWNER)
    assert _wait(lambda: any("Step 6" in str(m.get("text")) for m in _sent_since(server, mark)),
                 STEP_WAIT_S + MEDIA_BATCH_DELAY_S, "step 6's prompt after the photo batch")

    # Step 6: a stranger is refused at intake: no media fetched, no answer.
    # Mutation: ``is_allowed`` returns True -> red: no refusal is printed.
    mark, calls = len(server.sent), len(server.calls)
    server.push_photo("hi from a stranger", user_id=STRANGER, first_name="Stranger")
    server.push_message("hello?", user_id=STRANGER, first_name="Stranger")
    assert _wait(lambda: run.text().count(f"a stranger (user {STRANGER}) was refused") >= 2,
                 STEP_WAIT_S, "both of the stranger's messages refused")
    assert not {"getFile", "<download>"} & set(_methods_since(server, calls))
    assert not [m for m in _sent_since(server, mark) if str(m.get("chat_id")) == str(STRANGER)]

    # ``done`` ends the run with exit 0. Mutation: ``done.set()`` dropped -> red: the run times out, exit 1.
    server.push_message("done", user_id=OWNER)
    run.thread.join(STEP_WAIT_S)
    assert run.outcome.get("exit") == 0, run.text()
    assert "[incomplete]" not in run.text() and "[FAIL]" not in run.text()

    # Neither the token nor its secret half reaches the log (at DEBUG) or the console.
    secret = TOKEN.split(":", 1)[1]
    for where, text in (("log", caplog.text), ("console", run.text())):
        assert TOKEN not in text and secret not in text, where
    assert caplog.records, "the log was captured at DEBUG"
