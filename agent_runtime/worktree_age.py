"""The worktree-age floor ``harness doctor`` sweeps with, as a leaf.

A leaf so the ``hermes harness`` parser can state the ``--worktree-min-age-seconds``
default without importing the doctor package (~430 modules); the doctor's model
re-exports it.
"""

from __future__ import annotations

__layer__ = "models"

#: A worktree younger than this is never reaped by ``harness doctor --fix``.
DEFAULT_WORKTREE_MIN_AGE_SECONDS = 3600
