"""Detached execution for ``agent_chat_send(wait=false)`` — the target's turn runs natively in this Hermes.

The synchronous relay runs the target's turn INSIDE the sender's turn: the
sender blocks for the whole thing, which caps agent-to-agent work at whatever
fits in a conversational window and makes "go run the suite and tell me when
it's done" impossible to express. This package is the other half — the
target's turn runs on its own thread, the sender's tool call returns a handle
immediately, and :mod:`agent_runtime.dispatch_delivery` forges the answer back
into the sender's thread later, when the sender is idle.

ONE HERMES, ONE PATH (owner ruling 2026-11-21, row
``RT-AGENT-DISPATCH-RUNS-AS-A-NATIVE-TURN-IN-THE-SAME-HERMES``): "it should be a
native first class function within the same hermes, for starters duplicating
the memory for a new hermes is silly". Until then each dispatch spawned a child
Hermes (``hermes harness mission-chat message --in-process``) and read its
answer off stdout; the child carried its own approval queue (relayed back
through files), its own model reads, its own background-job registry (ended with
its process group) and the code on disk rather than the code the serve runs.
The turn now enters the mission-chat door on a thread of the serve, as the
inline relay and the delivery forge do, so it shares all four with every other
turn. The reasons the child was kept (the module history: the whole-run
``_WORKDIR_LOCK``, retired by run-serialization S5; the POSIX ``HOME`` gate,
which now waits only between profiles with different ``home/`` directories, as
any two turns do; the child's pid as the thing a sweep or kill could act on)
are answered in ``native.py``: a native turn is stopped through its agent's own
interrupt, and a turn that ignores it is left to its thread while its request
settles. A nested ``wait: false`` from a dispatched turn is admitted like any
serve-hosted turn's.

WHAT THE SUPERVISOR OWNS
------------------------
The turn is an ordinary mission-chat turn and knows nothing about dispatches.
Bookkeeping stays here: the supervisor stamps this process as the row's owner
when the turn starts, carries a Stop to the turn, enforces the wall budget with
an interrupt after grace, and writes the terminal completion the delivery drain
reads.

THE PACKAGE MAP (rule 16)
-------------------------
==========  ======  ===========================================================
module      layer   owns
==========  ======  ===========================================================
outcome     policy  what a turn's payload becomes on its row: the one mapping
                    (``payload_completion``), the lane-specific error rewrite,
                    the peer frame payload reader
native      lanes   ONE native turn: the door's arguments, its thread, its
                    interrupt, the supervise-and-abandon loop
remote      lanes   the cross-install leg (Gateway Stage 7): the peer params,
                    the frame reader, ``_run_remote_dispatch``
local       lanes   the supervisor pool (the supervised-id set, the executor,
                    ``dispatch_detached_turn``), the local leg
                    (``_run_dispatch`` -> ``_run_dispatch_guarded`` ->
                    ``native.run_turn``) and ``summarize_for_caller``
cancel_    lanes   the supervising process's cancel watch: a durable
watch               ``cancel_requested`` another process left becomes this
                    process's ``request_cancel`` (D1.07, owner ruling a)
==========  ======  ===========================================================

Entry points: ``agent_chat_send(wait=false)`` (``tools/agent_chat_tool``) ->
``local.dispatch_detached_turn`` -> ``local._run_dispatch_guarded`` ->
``native.run_turn``; a cross-install dispatch -> ``local`` (the fork on
``remote_install_id``) -> ``remote`` -> ``outcome.parse_reply_payload``; the
orphan sweep's question (``agent_runtime.dispatch_store``) ->
``dispatch_store.supervision``, which ``local``'s supervisors mark and forget;
``agent_chat_dispatches`` -> ``local.summarize_for_caller``. W0-G6 does not walk
``tools/`` (a fork-only tree in an upstream directory), so the layers below are
declared for the day it does.
"""

from __future__ import annotations

__all__ = [
    "KILL_GRACE_SECONDS",
    "PEER_DIAL_TIMEOUT_SECONDS",
    "PEER_RETRY_BACKOFF_SECONDS",
    "build_peer_execute_params",
    "dispatch_detached_turn",
    "parse_reply_payload",
    "request_cancel",
    "request_remote_cancel",
    "summarize_for_caller",
    "supervised_dispatch_ids",
]

from tools.agent_chat_dispatch.outcome import (  # __all__ + the test-pinned privates
    KILL_GRACE_SECONDS,
    SERVE_STDOUT_EVENT,
    _detached_error_text,
    parse_reply_payload,
    payload_completion,
)
from tools.agent_chat_dispatch.remote import (
    RemoteDispatch,
    PEER_DIAL_TIMEOUT_SECONDS,
    PEER_RETRY_BACKOFF_SECONDS,
    _remote_reply_payload,
    _run_remote_dispatch,
    build_peer_execute_params,
    request_remote_cancel,
)
from tools.agent_chat_dispatch.local import (
    _forget_supervised,
    _get_executor,
    _mark_supervised,
    _run_dispatch,
    _run_dispatch_guarded,
    dispatch_detached_turn,
    request_cancel,
    summarize_for_caller,
    supervised_dispatch_ids,
)

__layer__ = "lanes"
