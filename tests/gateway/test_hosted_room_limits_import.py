"""``gateway.hosted_room_limits`` imports on its own, in either order, with one identity."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_CHECK = """
import importlib
for name in {order!r}:
    importlib.import_module(name)
import gateway.hosted_room_discussion as d, gateway.hosted_room_limits as l
assert d.DEFAULT_LIMITS is l.DEFAULT_LIMITS and d.DiscussionLimits is l.DiscussionLimits
assert (l.DEFAULT_LIMITS.max_members, l.DEFAULT_LIMITS.max_rounds, l.DEFAULT_LIMITS.max_messages) == (
    d.MAX_DISCUSSION_MEMBERS, d.MAX_DISCUSSION_ROUNDS, d.MAX_DISCUSSION_MESSAGES)
"""


@pytest.mark.parametrize("order", [
    ("gateway.hosted_room_limits",),
    ("gateway.hosted_room_discussion",),
])
def test_fresh_interpreter_import_order(order):
    result = subprocess.run([sys.executable, "-c", _CHECK.format(order=order)], cwd=_REPO,
                            capture_output=True, text=True, timeout=120, check=False)
    assert result.returncode == 0, result.stderr[-2000:]
