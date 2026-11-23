"""RT-FU-A-COLD-HARNESS-SERVE-REGISTERS-SECONDS-SOONER: the serve's snapshot build context is made on first use.

Importing the snapshot package cost ~0.3 s of a cold boot before the serve registered, and no
cached read can arrive before ``ready``. The context is made by the first read and then shared.
"""

from __future__ import annotations

import threading
from types import SimpleNamespace

from agent_runtime.snapshot.context import SnapshotBuildContext
from hermes_cli.harness_parts.serve.session import ServeSession


def _session_state() -> SimpleNamespace:
    return SimpleNamespace(_read_build_context=None, _read_build_context_lock=threading.Lock())


def test_the_first_read_makes_the_context_and_later_reads_share_it():
    state = _session_state()
    read = ServeSession.read_build_context.fget

    first = read(state)

    assert isinstance(first, SnapshotBuildContext)
    assert read(state) is first


def test_request_state_setup_leaves_the_context_unmade_until_a_read_asks():
    session = ServeSession.__new__(ServeSession)
    session.frames = object()
    session.read_cache_max_age = 1.0

    session._init_request_state()

    assert session._read_build_context is None
    assert isinstance(session.read_build_context, SnapshotBuildContext)
