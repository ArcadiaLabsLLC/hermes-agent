"""RT-DISPATCH-DELIVERY-DROPS-CLARIFY: a background dispatch whose teammate
turn ends in ``clarify`` delivers the question WITH its token.

Live 2026-10-25 22:29: Base called ``clarify`` on a dispatched turn and the
``BACKGROUND DISPATCH COMPLETE`` block handed Neko only the question as reply
text — no ``clarify_request``, no ``clarify_token``, no choices — so the
answer could never land on the token.

Drives the supervisor's real settle (``_settle_local``) over the child's
printed payload, then the delivery formatter over the stored row.

Named sabotage: drop ``clarify_request=`` from ``_settle_local``'s
``record_completion`` call → the block carries no token (red).
"""

from __future__ import annotations

import json

import pytest

from agent_runtime.dispatch_delivery import format_dispatch_delivery
from agent_runtime.dispatch_store import get_dispatch, mint_dispatch_id, record_dispatch
from tools.agent_chat_dispatch.local import _settle_local

TOKEN = "clarify_tok_0123456789abcdef"


@pytest.fixture
def store_home(tmp_path, monkeypatch):
    home = tmp_path / "bg-home"
    home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setenv("HERMES_HEAD_HOME", str(home))
    return home


def _dispatch() -> str:
    dispatch_id = mint_dispatch_id()
    record_dispatch(
        dispatch_id=dispatch_id,
        sender_session_id="persona_chat_personainst_neko_aaaaaaaaaaaa",
        target_persona="base",
        target_instance_id="",
        title="Badge colour",
        ask="Pick the throwaway badge colour; call clarify.",
        notify_operator=False,
    )
    return dispatch_id


def _settle(dispatch_id: str, clarify_request: dict | None) -> None:
    payload = {
        "ok": True,
        "capability_id": "mission_chat_message",
        "reply": "Which colour should the throwaway test badge be: blue or green?",
        "session_id": "persona_chat_personainst_base_bbbbbbbbbbbb",
        "clarify_request": clarify_request,
    }
    _settle_local(dispatch_id, 600.0, 0, "", "noise\n" + json.dumps(payload) + "\n", "")


def test_the_delivery_carries_the_teammates_clarify_token_and_choices(store_home):
    dispatch_id = _dispatch()
    _settle(
        dispatch_id,
        {"question": "Which colour?", "choices": ["blue", "green"], "clarify_token": TOKEN},
    )

    row = get_dispatch(dispatch_id)
    assert row["result"]["clarify_request"] == {
        "question": "Which colour?",
        "choices": ["blue", "green"],
        "clarify_token": TOKEN,
    }
    block = format_dispatch_delivery(row)
    assert "--- THEY ASKED YOU A QUESTION (clarify) ---" in block
    assert f"clarify_token: {TOKEN}" in block
    assert "  - blue" in block and "  - green" in block
    assert f"clarify_token={TOKEN}" in block


def test_a_reply_without_a_question_keeps_its_exact_block(store_home):
    """Positive control for absence: no clarify, no lines, no stored key."""

    dispatch_id = _dispatch()
    _settle(dispatch_id, None)
    row = get_dispatch(dispatch_id)
    assert "clarify_request" not in row["result"]
    assert "clarify" not in format_dispatch_delivery(row).split("--- THEIR REPLY ---")[1]


def test_the_stored_question_is_bounded(store_home):
    dispatch_id = _dispatch()
    _settle(
        dispatch_id,
        {
            "question": "q" * 5000,
            "choices": [f"c{i}" for i in range(40)],
            "clarify_token": "t" * 500,
            "questions": [{"question": "a"}, {"question": "b"}],
        },
    )
    stored = get_dispatch(dispatch_id)["result"]["clarify_request"]
    assert len(stored["question"]) <= 2000
    assert len(stored["choices"]) == 12
    assert len(stored["clarify_token"]) == 128
    assert stored["question_count"] == 2
