"""The serve socket's line reader waits through a read that would block (fork-owned).

Row RT-FU-FOUR-AGENT-RUNTIME-TESTS-RED-ON-MAIN-ON-WINDOWS: on Windows a TLS socket in timeout mode
answered a read that found nothing with ``BlockingIOError`` (WSAEWOULDBLOCK), and the serve's read loop
closed the reverse lane ``read_error:BlockingIOError`` mid-conversation
(``tests/agent_runtime/test_reverse_lane.py``, about one run in three). The reader now waits for the socket
as its timeout says and reads again.

Killing mutation: drop the ``BlockingIOError`` arm in ``agent_runtime/serve_socket/wire.py::_LineReader.read_line``
and the first test reddens on the BlockingIOError.
"""

from __future__ import annotations

import socket

import pytest

from agent_runtime.serve_socket.wire import _LineReader


class _WouldBlockOnce:
    """A real socket whose first ``recv`` answers WSAEWOULDBLOCK, as the TLS socket did."""

    def __init__(self, sock: socket.socket) -> None:
        self._sock = sock
        self.would_block = 1

    def recv(self, size: int) -> bytes:
        if self.would_block:
            self.would_block -= 1
            raise BlockingIOError(10035, "A non-blocking socket operation could not be completed immediately")
        return self._sock.recv(size)

    def gettimeout(self) -> float | None:
        return self._sock.gettimeout()

    def fileno(self) -> int:
        return self._sock.fileno()


@pytest.fixture
def pair():
    left, right = socket.socketpair()
    left.settimeout(2.0)
    yield left, right
    left.close()
    right.close()


def test_a_read_that_would_block_waits_and_reads_again(pair):
    left, right = pair
    flaky = _WouldBlockOnce(left)
    right.sendall(b"hello\n")
    assert _LineReader(flaky).read_line(deadline_seconds=None) == "hello"
    assert flaky.would_block == 0  # positive control: the would-block was met, not skipped


def test_a_wait_with_nothing_to_read_is_the_socket_timeout_or_the_deadline(pair):
    left, _right = pair
    left.settimeout(0.2)
    with pytest.raises(socket.timeout):
        _LineReader(_WouldBlockOnce(left)).read_line(deadline_seconds=None)
    assert _LineReader(_WouldBlockOnce(left)).read_line(deadline_seconds=0.3) is None
