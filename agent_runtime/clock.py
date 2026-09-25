"""Monotonic-clock helpers the fork shares: one owner each (program rule 15).

A stdlib-only leaf, like :mod:`agent_runtime.serde`, so any module may import it
without risking a cycle. ``now_iso`` joins here when lane R3 folds the four
``_now_iso`` copies (god-file program §4).
"""

from __future__ import annotations

import time

__layer__ = "models"
__all__ = ["elapsed_ms"]


def elapsed_ms(started: object) -> int | None:
    """Milliseconds since a ``time.monotonic()`` reading, floored at 0.

    ``None`` when ``started`` is not a number — an unstamped segment has no
    duration, and reporting 0 would claim it had one.
    """

    try:
        began = float(started)  # type: ignore[arg-type]
    except Exception:  # noqa: BLE001 — an unreadable stamp has no duration
        return None
    return max(0, int((time.monotonic() - began) * 1000))
