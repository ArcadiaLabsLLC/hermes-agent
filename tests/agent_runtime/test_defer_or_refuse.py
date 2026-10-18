"""``serve_rpc.protocol.defer_or_refuse`` — the one door for "run the reply on the worker lane, else refuse".

The three families that refuse rather than answer inline (``runtime.chat.goal.*``, ``runtime.work.*``,
``runtime.conversation.*``) go through it, and their refusal frame is pinned to the BYTES it had when each
family hand-wrote it (RT-RPC-DEFER-OR-STOPPING-HANDWRITTEN).
"""

from __future__ import annotations

import json

import pytest

from agent_runtime.call_authorization import STDIO_OWNER
from agent_runtime.serve_rpc import handle_request
from agent_runtime.serve_rpc.protocol import DEFERRED, RpcContext

_UNAVAILABLE = '{"code": 4090, "message": "The runtime is unavailable.", "data": {"reason": "runtime_stopping"}}'
_CANNOT_ACCEPT = ('{"code": 4090, "message": "The runtime cannot accept this request.", '
                  '"data": {"reason": "runtime_stopping"}}')

FAMILIES = [
    ("runtime.chat.goal.status", {"session_id": "s1"}, _UNAVAILABLE),
    ("runtime.work.list", {}, _UNAVAILABLE),
    ("runtime.conversation.read", {}, _CANNOT_ACCEPT),
]


def _request(name: str, params: dict) -> dict:
    return {"jsonrpc": "2.0", "id": "r1", "method": name, "params": params}


@pytest.mark.parametrize(("name", "params", "error"), FAMILIES)
@pytest.mark.parametrize("spawn_reply", [None, lambda build: False], ids=["no_lane", "lane_refused"])
def test_a_refused_deferral_answers_the_bytes_each_family_hand_wrote(name, params, error, spawn_reply):
    frame = handle_request(_request(name, params), RpcContext(caller=STDIO_OWNER, spawn_reply=spawn_reply))

    assert json.dumps(frame) == '{"jsonrpc": "2.0", "id": "r1", "error": ' + error + "}"


@pytest.mark.parametrize(("name", "params", "error"), FAMILIES)
def test_an_accepted_deferral_answers_deferred_and_hands_the_lane_a_build(name, params, error):
    builds = []
    context = RpcContext(caller=STDIO_OWNER, spawn_reply=lambda build: builds.append(build) or True)

    assert handle_request(_request(name, params), context) is DEFERRED
    assert len(builds) == 1 and callable(builds[0])
