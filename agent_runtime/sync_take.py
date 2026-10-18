"""Which side wins a held sync conflict — the ``take`` every resolve verb reads.

One vocabulary, so a verb parses ``take`` through :class:`SyncTake` instead of re-spelling
``{"local", "remote"}`` (``tests/tooling/test_no_ladder_routing.py``).
"""

from __future__ import annotations

from enum import StrEnum

__layer__ = "models"
__all__ = ["SyncTake"]


class SyncTake(StrEnum):
    LOCAL = "local"
    REMOTE = "remote"
