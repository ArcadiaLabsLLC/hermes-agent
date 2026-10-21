"""Every test starts with an empty production bash memo (``agent_runtime/bash_resolution_memo.py``).

The memo lives for the process; a test that fakes ``pm.shell``'s probe or a candidate's file must
not be handed the bash an earlier test resolved. Within one test the memo stands, as in production.
"""

from __future__ import annotations

import sys

import pytest


@pytest.fixture(autouse=True)
def _bash_resolution_reset():
    memo = sys.modules.get("agent_runtime.bash_resolution_memo")
    if memo is not None:
        memo.clear()
