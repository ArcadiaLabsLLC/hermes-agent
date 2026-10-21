"""Work store tests: a fresh workspace on the session chain's isolated home.

The chain (``tests/conftest.py``) gives every test its own Hermes home, so the store root, the
machine roots and the gateway install id are this test's own; nothing is patched. The shared
builders live in ``work_store_support.py``.
"""

from __future__ import annotations

import pytest

from agent_runtime.machine_roots import machine_roots_cache_clear
from agent_runtime.store import WorkspaceStore


@pytest.fixture
def workspace() -> str:
    machine_roots_cache_clear()
    return WorkspaceStore().create(name="Work").id
