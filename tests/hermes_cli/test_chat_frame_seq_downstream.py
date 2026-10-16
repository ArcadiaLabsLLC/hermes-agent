"""Every streamed console frame carries a per-turn ``frame_seq`` (w1015b-con-x).

``seq`` is the ELEMENT ordinal: a segment's start, every delta and its end share one,
so a consumer cannot tell a replayed delta from the next one by ``seq``
(launcher row "stream seq not per-frame", 2320bea5bd). ``frame_seq`` is 1, 2, 3 … in
write order, so ``(turn_id, frame_seq)`` names exactly one frame.
"""

from __future__ import annotations

import json

from hermes_cli.harness_parts.persona import chat_events


def test_every_frame_has_the_next_frame_seq_while_deltas_share_one_element_seq(capsys):
    emitter = chat_events._ChatProtocolV2Emitter(turn_id="turn_1", client_message_id="client_1")
    emitter.delta("Hel")
    emitter.delta("lo")
    emitter.end_segment()
    frames = [json.loads(line) for line in capsys.readouterr().out.splitlines() if line.strip()]

    assert [frame["frame_seq"] for frame in frames] == list(range(1, len(frames) + 1))
    deltas = [frame for frame in frames if frame["type"] == "segment.delta"]
    assert len(deltas) == 2
    assert deltas[0]["seq"] == deltas[1]["seq"], "the element seq is shared: the reason frame_seq exists"
    assert deltas[0]["frame_seq"] != deltas[1]["frame_seq"]
