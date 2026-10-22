"""Rows (win32 only): upstream's OWN Windows reds at release tag v0.22.4 -- retired by an upstream fix.

Every id here was red on both runs of the pure tag ``v0.22.4`` (``4d04303818``, a detached worktree,
no fork code; ``scripts/classify_reds_on_tag.py --tag v0.22.4``, 2026-10-22 release merge) AND red on
the merge candidate. A per-test strict xfail, so an upstream fix turns the row into an XPASS(strict)
red that retires it. Registered in ``hooks._merge`` and the map ``tests/_downstream/id_markers/__init__.py``.
"""

from __future__ import annotations

import pytest

from tests._downstream.id_markers.reasons import _up_red, _WIN

__layer__ = "models"

_REASON = "red on pure upstream tag v0.22.4 4d04303818 on Windows (2026-10-22 release merge)"

_NODES = (
        'tests/agent/lsp/test_client_e2e.py::test_reader_failure_retires_client_and_rejects_later_work[clean_eof]',
        'tests/test_live_system_guard_self_test.py::test_host_gateway_start_blocked_but_container_exec_allowed',
)

ROWS: dict[str, tuple[pytest.MarkDecorator, ...]] = (
    {node: (_up_red(_REASON),) for node in _NODES} if _WIN else {}
)
