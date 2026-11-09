"""Fork carry of upstream's ``test_origin_creates_session_in_own_profile_and_replies_to_origin`` with a settle
that waits for the reply (FH-FLAKE-PLUGIN-ORIGIN-PROFILE-PATH, first landed in the upstream file as 9f1b9a5e26).

Upstream's ``_settle`` polls 200 x 10 ms rounds and returns SILENTLY when they run out, so under load the next
injection overtook the previous profile's turn and the turn order flipped (2/18 red at 2 cores + 3 burners).
The upstream file stays at upstream bytes (no footprint without an owner ruling) and its node is skip-listed
in ``tests/fixtures/upstream_skip_list.txt``; this copy runs instead, everything else imported from it.
"""

from unittest.mock import patch

import pytest

import gateway.run as gateway_run
from gateway.platforms.base import MessageEvent, MessageType
from tests.gateway.test_plugin_origin_injection import _context, _origin, _publish, gateway  # noqa: F401 (fixture)
from tests.waiting import async_wait_until

# The session's 30 s default covers a cold state.db schema init plus four turns on a quiet box only;
# at 2 cores under load the cold run took 27-31 s (w1109a stress, FH-FLAKE-PLUGIN-ORIGIN-PROFILE-PATH).
pytestmark = pytest.mark.timeout(120)


#: A deadline, not a delay: only a hang waits this long. Under a 2-core load one injected turn took
#: up to 12 s to reach its reply (w1109a, FH-FLAKE-PLUGIN-ORIGIN-PROFILE-PATH).
_SETTLE_DEADLINE_S = 60.0


async def _settle(runner, adapter, *, sent: int):
    """Wait until ``adapter`` has sent ``sent`` replies and nothing is in flight. The reply is the
    last thing a turn does, so the next injection can never overtake this one; a hang raises."""
    await async_wait_until(
        lambda: (len(adapter.sent) >= sent and not runner._background_tasks
                 and not adapter._session_tasks and not adapter._active_sessions),
        timeout=_SETTLE_DEADLINE_S, what=f"{adapter.label} to send {sent} repl(ies) and go idle")


@pytest.mark.asyncio
async def test_origin_creates_session_in_own_profile_and_replies_to_origin(gateway):
    """No session at the origin: the plugin's profile gets a fresh session, the turn runs under that
    profile's home and secrets, the reply goes back to the origin chat, and a human follow-up in the
    same chat continues the SAME session (A -> B -> A: beta in between, alpha's scope comes back)."""
    runner, alpha, beta = gateway.runner, gateway.adapters["alpha"], gateway.adapters["beta"]
    ctx_alpha, mgr_alpha = _context(gateway.homes["alpha"])
    ctx_beta, mgr_beta = _context(gateway.homes["beta"])
    with patch("hermes_cli.plugins._known_plugin_managers", return_value=[mgr_alpha, mgr_beta]):
        await _publish(runner)
        assert ctx_alpha.inject_message("Kick off the review", origin=_origin("100")) is True
        await _settle(runner, alpha, sent=1)
        assert ctx_beta.inject_message("Beta's own post", origin=_origin("200")) is True
        await _settle(runner, beta, sent=1)
        assert ctx_alpha.inject_message("Second post", origin=_origin("101")) is True
        await _settle(runner, alpha, sent=2)

    first, middle, last = gateway.turns
    assert (first.home, first.marker) == (gateway.homes["alpha"], "alpha")
    assert (middle.home, middle.marker) == (gateway.homes["beta"], "beta")
    assert (last.home, last.marker) == (gateway.homes["alpha"], "alpha")
    assert first.message.endswith("Kick off the review") and first.history == []
    assert alpha.sent == [("100", "reply-1"), ("101", "reply-3")]
    assert beta.sent == [("200", "reply-2")]
    # The reply is sent after the handler returns: it must still run in the plugin's profile scope.
    assert alpha.send_scopes == [(gateway.homes["alpha"], "alpha")] * 2
    assert beta.send_scopes == [(gateway.homes["beta"], "beta")]
    assert gateway.adapters["default"].sent == []

    entry = runner.session_store._entries["agent:alpha:telegram:group:100:7"]
    assert entry.session_id == first.session_id
    assert not any(key.startswith(("agent:main:", "agent:beta:")) and ":100:" in key
                   for key in runner.session_store._entries)

    # A human reply in the same chat keys into the plugin-created session. A secondary adapter's
    # intake task runs inside its profile scope (it is spawned from connect() under that scope).
    reply = alpha.build_source(chat_id="100", chat_type="group", thread_id="7", user_id="u1")
    async with gateway_run._async_profile_runtime_scope(gateway.homes["alpha"]):
        await alpha.handle_message(MessageEvent(text="thanks", message_type=MessageType.TEXT, source=reply))
    await _settle(runner, alpha, sent=3)
    assert gateway.turns[-1].session_id == first.session_id
    assert alpha.sent[-1] == ("100", "reply-4")
