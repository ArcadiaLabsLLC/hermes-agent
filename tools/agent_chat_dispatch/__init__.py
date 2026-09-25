"""Detached execution for ``agent_chat_send(wait=false)`` — one child process per dispatch.

The synchronous relay runs the target's turn INSIDE the sender's turn: the
sender blocks for the whole thing, which caps agent-to-agent work at whatever
fits in a conversational window and makes "go run the suite and tell me when
it's done" impossible to express. This module is the other half — the target's
turn moves into its own process, the sender's tool call returns a handle
immediately, and :mod:`agent_runtime.dispatch_delivery` forges the answer back
into the sender's thread later, when the sender is idle.

WHY A SUBPROCESS AND NOT A THREAD — the correction that defines this file
------------------------------------------------------------------------
The first implementation ran detached turns in-process on a daemon executor.
That is unshippable, and not for a subtle reason: every persona turn in this
runtime executes under ``profile_runner._WORKDIR_LOCK``, a PROCESS-WIDE
``RLock`` held for the ENTIRE model turn (``_execute_agent_run``). Serve handles
requests concurrently, but persona turns serialize on that lock. A single
30-minute detached dispatch would therefore have:

* frozen every foreground operator turn — and frozen it AFTER the journal's
  ``executing`` transition, so the console shows a running turn with no typed
  refusal, no timeout, and nothing to expire it (the wall budget only starts
  ticking INSIDE the lock);
* frozen the SENDER's own next turn, exactly inverting the feature;
* made ``dispatch_max_concurrent`` a fiction — three dispatches would be three
  30-minute waits in series, not in parallel;
* left queued waiters holding the TARGET's chat-root lease while blocked, so an
  operator messaging that agent gets ``chat_busy`` for hours;
* frozen the delivery drain itself, whose forge takes the same lock;
* deadlocked outright on a nested dispatch, where a parent waiting on a child
  holds the lock the child needs.

A child process has its own ``_WORKDIR_LOCK``, its own ``HERMES_HOME`` override,
and its own cwd. The executor thread here spawns and WAITS — holding NO lock
while it waits, which is the entire point — so the parent stays free to run
operator turns and deliveries throughout. ``dispatch_max_concurrent`` now means
three genuinely concurrent turns.

The nested-dispatch deadlock is gone too, but NOT because a child spawns a
grandchild — an earlier version of this note claimed that and it was wrong. The
child is a cold one-shot CLI, so its delivery capability is False and a nested
``wait: false`` is REFUSED (``async_delivery_unavailable``) before anything
runs. That is the honest outcome rather than a limitation: the child's process
ends with its turn, so a grandchild would outlive the only thing that could
record what happened to it. A dispatched agent that needs a teammate uses
``wait: true`` and gets the reply inline.

The cost is a cold start per dispatch. That is the right trade for work whose
budget is measured in minutes, and it buys a second property worth as much: a
dispatch that wedges or explodes cannot take the serve process with it.

WHAT THE PARENT STILL OWNS
--------------------------
The child is an ordinary ``hermes harness mission-chat message`` turn and knows
nothing about dispatches. Bookkeeping stays here: this thread stamps the child's
PID identity onto the row when it spawns, enforces the wall budget with a
kill-after-grace, and writes the terminal completion the delivery drain reads.
Because the row carries the CHILD's pid + start time, the orphan sweep can tell
"still working" from "its process is gone" without needing this thread alive.

THE PACKAGE MAP (rule 16)
-------------------------
==========  ======  ===========================================================
module      layer   owns
==========  ======  ===========================================================
child       policy  ONE child process: the argv and environment it is built
                    from, the bounded tails that read it, the pumps that drain
                    it and are forced loose, its identity, its kill, the payload
                    parser, the lane-specific error rewrite
remote      lanes   the cross-install leg (Gateway Stage 7): the peer params,
                    the frame reader, ``_run_remote_dispatch``
local       lanes   the supervisor pool (the supervised-id set, the executor,
                    ``dispatch_detached_turn``), the local leg
                    (``_run_dispatch`` -> ``_run_dispatch_guarded``) and
                    ``summarize_for_caller``
==========  ======  ===========================================================

Entry points: ``agent_chat_send(wait=false)`` (``tools/agent_chat_tool``) ->
``local.dispatch_detached_turn`` -> ``local._run_dispatch_guarded`` -> ``child``;
a cross-install dispatch -> ``local`` (the fork on ``remote_install_id``) ->
``remote`` -> ``child.parse_child_payload``; the orphan sweep's question
(``agent_runtime.dispatch_store``) -> ``dispatch_store.supervision``, which
``local``'s supervisors mark and forget;
``agent_chat_dispatches`` -> ``local.summarize_for_caller``. W0-G6 does not walk
``tools/`` (a fork-only tree in an upstream directory), so the layers below are
declared for the day it does.
"""

from __future__ import annotations

__all__ = [
    "KILL_GRACE_SECONDS",
    "PEER_DIAL_TIMEOUT_SECONDS",
    "PEER_RETRY_BACKOFF_SECONDS",
    "build_dispatch_argv",
    "build_peer_execute_params",
    "child_environment",
    "dispatch_detached_turn",
    "supervised_dispatch_ids",
    "parse_child_payload",
    "summarize_for_caller",
]

from tools.agent_chat_dispatch.child import (  # noqa: F401 — __all__ + the test-pinned privates
    _MAX_STREAM_CHARS,
    KILL_GRACE_SECONDS,
    SERVE_STDOUT_EVENT,
    _BoundedTail,
    _child_identity,
    _detached_error_text,
    _kill_child,
    build_dispatch_argv,
    child_environment,
    parse_child_payload,
)
from tools.agent_chat_dispatch.remote import (  # noqa: F401
    RemoteDispatch,
    PEER_DIAL_TIMEOUT_SECONDS,
    PEER_RETRY_BACKOFF_SECONDS,
    _remote_reply_payload,
    _run_remote_dispatch,
    build_peer_execute_params,
)
from tools.agent_chat_dispatch.local import (  # noqa: F401
    _forget_supervised,
    _get_executor,
    _mark_supervised,
    _run_dispatch,
    _run_dispatch_guarded,
    dispatch_detached_turn,
    summarize_for_caller,
    supervised_dispatch_ids,
)

__layer__ = "lanes"
