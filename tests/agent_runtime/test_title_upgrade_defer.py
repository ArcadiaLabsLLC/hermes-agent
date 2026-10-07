"""h-title-defer: which title upgrades wait for ``request_sent``, and which one it starts."""

from __future__ import annotations

import threading
from types import SimpleNamespace

from agent_runtime.title_upgrade_defer import hold_title_upgrade, start_held_title_upgrade


def _upgrade(ran: list) -> threading.Thread:
    return threading.Thread(target=lambda: ran.append(1), name="auto-title", daemon=True)


def test_only_the_traced_responses_path_is_held():
    assert hold_title_upgrade(_upgrade([]), {"api_mode": "codex_responses"}) is True
    assert hold_title_upgrade(_upgrade([]), {"api_mode": "chat_completions"}) is False
    assert hold_title_upgrade(_upgrade([]), None) is False


def test_request_sent_starts_the_held_upgrade_once():
    ran: list = []
    upgrade = _upgrade(ran)
    assert hold_title_upgrade(upgrade, {"api_mode": "codex_responses"})
    agent = SimpleNamespace(_deferred_title_upgrade=upgrade, session_id="s")
    assert start_held_title_upgrade(agent) is True
    upgrade.join(5)
    assert ran == [1] and agent._deferred_title_upgrade is None
    assert start_held_title_upgrade(agent) is False


def test_upstreams_self_hosted_hold_is_left_for_finalize_turn():
    upgrade = _upgrade([])  # held by title_upgrade_must_wait_for_turn: untagged
    agent = SimpleNamespace(_deferred_title_upgrade=upgrade, session_id="s")
    assert start_held_title_upgrade(agent) is False
    assert upgrade.ident is None and agent._deferred_title_upgrade is upgrade
