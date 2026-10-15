"""The delivery forge runs its turn through the mission-chat door (ruling Q10).

``dispatch_delivery.forge_delivery_turn`` used to import the CLI's private
handler; it now calls ``agent_runtime.mission_chat_door.run_mission_chat_turn``
(lane B1's door, bound at plugin registration and serve boot — and for every
test by the ``_mission_chat_door_bound`` autouse fixture). These pin the forge's
side of it: the handler the door holds is the one that runs, the forge reads the
LAST payload it emitted, and an unbound door is a loud forge failure, not a
silent delivery.
"""

from __future__ import annotations

import pytest

from agent_runtime import dispatch_delivery, mission_chat_door
from agent_runtime.mission_chat_door import MissionChatDoorUnbound


def _forge():
    return dispatch_delivery.forge_delivery_turn(
        root_session_id="persona_chat_personainst_neko_aaaaaaaaaaaa",
        persona_id="neko_supervisor",
        persona_instance_id="personainst_neko",
        message="done",
        client_message_id="dispatch-delivery-d1",
        dispatch_id="d1",
        max_seconds=5.0,
    )


def test_the_forge_runs_the_bound_handler_and_reads_its_last_payload(monkeypatch):
    seen = []

    def handler(args):
        seen.append((args.session_id, args.client_message_id, args.new_session))
        args.payload_sink({"ok": False, "stage": "admitted"})
        args.payload_sink({"ok": True, "reply": "thanks"})
        return 0

    monkeypatch.setattr(mission_chat_door, "_turn", handler)

    assert _forge() == (True, {"ok": True, "reply": "thanks"})
    assert seen == [("persona_chat_personainst_neko_aaaaaaaaaaaa", "dispatch-delivery-d1", False)]


def test_an_unbound_door_is_a_forge_failure_not_a_silent_delivery(monkeypatch):
    monkeypatch.setattr(mission_chat_door, "_turn", None)

    with pytest.raises(MissionChatDoorUnbound):
        _forge()
