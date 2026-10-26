"""``RT-SERVE-LOG-SESSION-TAG-LEAK`` — a pooled serve worker's log ``[session]`` tag is its own request's.

Real serve, one worker: the first request leaves a stale tag behind (as an agent turn does), the
next chat turn logs an admission line BEFORE setting anything, and that line must carry the next
turn's own ``--session-id``; a non-turn request after it logs untagged.

Killing mutation (recorded in the landing commit): drop ``_tag_worker_session(request)`` from
``ArgvLanes._run`` -> the admission line carries the previous turn's tag.
"""

from __future__ import annotations

import logging

from tests.agent_runtime.test_serve_socket_lane import _read_until, client, running_serve

_LOG = logging.getLogger("test.serve_worker_session_tag")


class _Tags(logging.Handler):
    def __init__(self):
        super().__init__(logging.INFO)
        self.tags: dict[str, str] = {}

    def emit(self, record):
        self.tags[record.getMessage()] = getattr(record, "session_tag", "")


def _dispatch(argv):
    from hermes_logging import set_session_context

    _LOG.info("admission %s", argv[-1])
    if argv[-1] == "first":
        set_session_context("persona_chat_dev_previous")  # what an agent turn leaves on the thread
    return 0


def test_each_request_logs_under_its_own_session_tag():
    from hermes_logging import _install_session_record_factory

    _install_session_record_factory()
    handler = _Tags()
    _LOG.addHandler(handler)
    _LOG.setLevel(logging.INFO)
    turn = ["harness", "mission-chat", "message", "--client-message-id"]
    try:
        with running_serve(dispatch=_dispatch, pool_size=1) as handle:
            with client(handle, name="launcher") as (connection, _hello):
                for rid, argv in (
                    ("r1", [*turn, "c1", "--session-id", "persona_chat_dev_previous", "first"]),
                    ("r2", [*turn, "c2", "--session-id", "persona_chat_neko_next", "second"]),
                    ("r3", ["harness", "status", "third"]),
                ):
                    connection.send({"id": rid, "argv": argv})
                    assert _read_until(connection, "exit")["code"] == 0
    finally:
        _LOG.removeHandler(handler)
    assert handler.tags["admission second"] == " [persona_chat_neko_next]"
    assert handler.tags["admission third"] == ""
