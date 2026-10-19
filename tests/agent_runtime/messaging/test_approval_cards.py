"""p10-messaging M4: an exec approval on a bound root becomes a platform card, answered through the ONE resolve path.

Upstream's real approval queue (``tools.approval``) under the fork's ``session_approval_scope``; the real
``TelegramTransport`` over the recorded fake Bot API (never the network); the real binding/operator stores
on this test's isolated home. The exact-owner identity is a fake and ``respond_operator_approval`` is wrapped
by a recorder that resolves through upstream's queue, so the test sees which door a press went through.
"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import httpx
import pytest

from agent_runtime import operator_session_controls, paths, session_controls
from agent_runtime.messaging.approvals import ApprovalCards, card_choices
from agent_runtime.messaging.bindings import Binding, BindingStore
from agent_runtime.messaging.bridge import MessagingBridge
from agent_runtime.messaging.models import Platform
from agent_runtime.messaging.operators import Operator, OperatorStore
from agent_runtime.messaging.telegram_api import TelegramTransport
from agent_runtime.operator_conversation import OperatorConversationRefused
from agent_runtime.session_controls import APPROVAL_CHOICES, approval_notifiers, session_approval_scope
from agent_runtime.work_store.persona_turn import PersonaTurnExecutor
from tests.agent_runtime.messaging.fake_bot_api import API_BASE, FakeBotApi
from tests.waiting import wait_until

TOKEN = "123456789:AAFakeTokenForTestsOnly_abcdefghijk"
TG = Platform.TELEGRAM
ROOTS = {"inst-alice": "persona_chat_root_alice", "inst-bob": "persona_chat_root_bob"}
ROOT = ROOTS["inst-alice"]


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    def refuse(*_args, **_kwargs):
        raise AssertionError("a messaging test reached the network")
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", refuse)


@pytest.fixture(autouse=True)
def _manual_approvals():
    from hermes_constants import get_hermes_home

    home = get_hermes_home()
    home.mkdir(parents=True, exist_ok=True)
    (home / "config.yaml").write_text(json.dumps({"approvals": {"mode": "manual", "timeout": 30}}), encoding="utf-8")
    yield
    for root in list(approval_notifiers):
        session_controls.unregister_approval_notifier(root)


class _Instances:
    def get(self, instance_id):
        return SimpleNamespace(id=instance_id, persona_id="alice", runtime_root=str(paths.store_root()))


@pytest.fixture
def rig(monkeypatch):
    api = FakeBotApi(TOKEN)
    transport = TelegramTransport(TOKEN, client=api.client(), api_base=API_BASE, wait=lambda _s: False)
    turns = PersonaTurnExecutor(instances=_Instances(), root_of=lambda store, persona_instance_id, **_:
                                ROOTS.get(persona_instance_id), wake=lambda: None)
    cards = ApprovalCards(transport, turns, identity=lambda root, iid: {"session_id": root, "persona_instance_id": iid})
    bridge = MessagingBridge(transport, turns, roster=list, approvals=cards)
    OperatorStore().allow(Operator(TG, "42", "Max", "rpc:stdio_owner", "2026-10-19T00:00:00+00:00"))
    BindingStore().set(Binding(TG, "-1001", None, "inst-alice", "rpc:stdio_owner", "2026-10-19T00:00:00+00:00"))
    resolved: list[dict] = []

    def respond(params):
        from tools.approval import resolve_gateway_approval

        resolved.append(params)
        if resolve_gateway_approval(params["session_id"], params["choice"], request_id=params["approval_id"]) != 1:
            raise OperatorConversationRefused("approval_expired")
        return {"accepted": True}

    monkeypatch.setattr(operator_session_controls, "respond_operator_approval", respond)
    return SimpleNamespace(api=api, transport=transport, turns=turns, cards=cards, bridge=bridge, resolved=resolved)


def _guarded(root=ROOT):
    from tools.approval import check_all_command_guards

    with session_approval_scope(root):
        return check_all_command_guards("git reset --hard", "local")


def _card(api) -> dict:
    return wait_until(lambda: next((m for m in api.sent if "reply_markup" in m), None), what="the approval card")


def _press(rig, data, user_id=42, message_id=7):
    rig.api.push_press(data, user_id=user_id, message_id=message_id)
    rig.transport.poll_once(rig.bridge.inbound)


def _buttons(card) -> list[tuple[str, str]]:
    return [(b["text"], b["callback_data"]) for row in card["reply_markup"]["inline_keyboard"] for b in row]


def test_one_resolve_path(rig):
    """Killing mutation: ``on_callback`` resolves through ``tools.approval.resolve_gateway_approval`` itself
    instead of ``operator_session_controls.respond_operator_approval`` → the recorder never hears it → red."""
    assert rig.cards.refresh() == {ROOT}
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(_guarded)
        try:
            card = _card(rig.api)
            _label, data = _buttons(card)[0]
            assert data.endswith(":once")
            _press(rig, data)
            result = future.result(timeout=10)
        finally:
            from tools.approval import resolve_gateway_approval

            resolve_gateway_approval(ROOT, "deny", resolve_all=True)
    assert result["approved"] is True
    [params] = rig.resolved
    assert params["session_id"] == ROOT and params["persona_instance_id"] == "inst-alice" and params["choice"] == "once"
    edits = [payload for method, payload in rig.api.calls if method == "editMessageText"]
    assert [e["text"] for e in edits] == [f"Approved ({dict(card_choices())['once']}) by Max."]
    assert ("answerCallbackQuery", {"callback_query_id": rig.api.calls[-1][1]["callback_query_id"], "text": "Done."}) \
        in rig.api.calls


def test_non_operator_press_is_refused(rig):
    """Killing mutation: drop the ``operators.is_allowed`` check in ``on_callback`` → the stranger's press
    resolves the approval → red."""
    from tools.approval import list_gateway_approvals, resolve_gateway_approval

    rig.cards.refresh()
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(_guarded)
        try:
            card = _card(rig.api)
            _press(rig, _buttons(card)[0][1], user_id=99)
            assert rig.resolved == [] and len(list_gateway_approvals(ROOT)) == 1
            assert any(m == "answerCallbackQuery" and p.get("text") == "Not allowed." for m, p in rig.api.calls)
        finally:
            resolve_gateway_approval(ROOT, "deny", resolve_all=True)
        assert future.result(timeout=10)["approved"] is False


def test_choices_are_upstreams(rig):
    """Killing mutation: the card spells its own buttons (e.g. adds ``always``, or labels ``Allow``) instead of
    ``ea_action_labels`` filtered by ``APPROVAL_CHOICES`` → red."""
    from gateway.platforms.base_exec_approval import ea_action_labels, ea_header_text

    rig.cards.refresh()
    rig.cards.on_pending(ROOT, {"request_id": "r1", "command": "rm -rf build", "description": ""})
    [card] = rig.api.sent
    labels = ea_action_labels()
    assert _buttons(card) == [(labels[c], f"ap:r1:{c}") for c in labels if c in APPROVAL_CHOICES]
    assert {c for _l, d in _buttons(card) for c in [d.rsplit(":", 1)[1]]} == set(APPROVAL_CHOICES)
    assert card["text"].startswith(ea_header_text()) and "rm -rf build" in card["text"]


def test_a_notifier_is_registered_only_for_bound_roots(rig):
    """Killing mutation: ``refresh`` never unregisters a root no binding reaches (drop the ``gone`` loop) → the
    cleared chat's root keeps getting cards → red."""
    assert rig.cards.refresh() == {ROOT}
    assert set(approval_notifiers) == {ROOT} and ROOTS["inst-bob"] not in approval_notifiers
    BindingStore().clear(TG, "-1001")
    assert rig.cards.refresh() == set() and approval_notifiers == {}
    rig.cards.on_pending(ROOT, {"request_id": "r2", "command": "x"})
    assert rig.api.sent == []


def test_a_timeout_edits_the_card_to_upstreams_notice(rig):
    from gateway.platforms.base_exec_approval import format_approval_timed_out_notice
    from hermes_constants import get_hermes_home

    (get_hermes_home() / "config.yaml").write_text(json.dumps({"approvals": {"mode": "manual", "timeout": 0}}),
                                                   encoding="utf-8")
    rig.cards.refresh()
    result = _guarded()
    assert result["approved"] is False and result["outcome"] == "timeout"
    edits = [payload["text"] for method, payload in rig.api.calls if method == "editMessageText"]
    assert edits == [format_approval_timed_out_notice(0)]


def test_a_raising_notifier_never_denies_for_the_launcher():
    """Killing mutation: ``_notify_root`` lets the notifier's exception through → upstream answers
    ``notify_failed`` and denies before the launcher can answer → red."""
    from tools.approval import list_gateway_approvals, resolve_gateway_approval

    session_controls.register_approval_notifier(ROOT, lambda data: 1 / 0)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(_guarded)
        try:
            [pending] = wait_until(lambda: list_gateway_approvals(ROOT), what="the pending approval")
            assert resolve_gateway_approval(ROOT, "once", request_id=pending["request_id"]) == 1
        finally:
            resolve_gateway_approval(ROOT, "deny", resolve_all=True)
        assert future.result(timeout=10)["approved"] is True
