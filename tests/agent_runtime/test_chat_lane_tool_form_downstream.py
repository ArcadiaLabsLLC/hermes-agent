"""One owner of a persona chat turn's tool form (plan tool-form-one-owner-2026-10-08).

The turns run the real pieces in upstream's order on the writer-ledger fixture of
``test_chat_lane_cache_hit_downstream``: actors built by the runner's default factory,
upstream's between-turns slot, the eternia-harness ``pre_llm_call`` hook (the owner), the
request from ``agent.tools``, the ``llm_request`` middleware.
"""

from __future__ import annotations

from tests.agent_runtime.test_chat_lane_cache_hit_downstream import (  # noqa: F401 — the fixtures
    VAULT,
    _bytes,
    _register_late,
    _reset,
    chat,
)
from tests.agent_runtime.test_chat_lane_defer import _names, lane  # noqa: F401 — the fixture


def _receipt(agent):
    from agent_runtime.chat_lane_tool_form import RECEIPT_ATTR

    return getattr(agent, RECEIPT_ATTR)


def _wire_names(tools) -> list[str]:
    return [t.get("name") or (t.get("function") or {}).get("name") for t in tools]


def test_a_catalog_move_breaks_once(chat):
    """A tool registered between turns 1 and 2 moves the form once: turn 2 differs from turn 1,
    turn 3 equals turn 2, and turn 3 neither reads nor assembles.

    *Killing mutation:* the memo key drops ``registry_content_revision()`` -- the late
    registration never rebuilds and turn 2 ships turn 1's bytes."""
    new_actor, turn, raw, _ledger = chat
    actor = new_actor("chat-a")
    first, _ = turn(actor)
    _register_late(raw)
    second, _ = turn(actor)
    assert _receipt(actor).source == "rebuilt"
    third, _ = turn(actor)
    assert _bytes(second) != _bytes(first), "the catalog moved and the form did not"
    assert _bytes(third) == _bytes(second)
    assert _receipt(actor).source != "rebuilt", "a turn with no catalog move re-derived the form"


def test_the_pin_is_what_the_turn_ships(chat):
    """The session pin holds the turn's form after the owner and the block prune: the pre-brief
    ``request["tools"]`` names, ``agent.tools``'s names, never a deferred name.

    *Killing mutation:* the owner pins before it publishes -- the pin holds the previous form."""
    new_actor, turn, raw, ledger = chat
    actor = new_actor("chat-a")
    _register_late(raw)
    pre_brief: dict = {}
    turn(actor, pre_brief=pre_brief)
    assert ledger["pins"], "the turn's form moved and nothing was pinned"
    pinned = [t["function"]["name"] for t in ledger["pins"][-1]["tools"]]
    assert pinned == _wire_names(pre_brief["tools"]) == [t["function"]["name"] for t in actor.tools]
    assert not set(pinned) & set(VAULT), sorted(set(pinned) & set(VAULT))


def test_an_unchanged_form_is_not_published_again(chat):
    """Two settles with nothing moved between them: the second publishes nothing, pins nothing.

    *Killing mutation:* the owner publishes unconditionally -- a publish and a pin on the
    second settle."""
    from agent_runtime.chat_lane_tool_form import settle_turn_tool_form

    new_actor, _turn, raw, ledger = chat
    actor = new_actor("chat-a")
    _register_late(raw)
    assert settle_turn_tool_form(actor).published
    _reset(ledger)
    receipt = settle_turn_tool_form(actor)
    assert (receipt.source, ledger["publishes"], len(ledger["pins"]), ledger["reads"]) == ("unchanged", 0, 0, 0)


def test_a_persona_without_a_defer_list_is_left_to_its_constructor_form(lane):
    """An actor the factory did not build (no defer attribute) is never settled."""
    from agent_runtime.chat_lane_tool_form import settle_turn_tool_form

    _raw, build_agent = lane
    agent = build_agent()
    before = list(agent.tools)
    assert settle_turn_tool_form(agent) is None
    assert agent.tools == before
