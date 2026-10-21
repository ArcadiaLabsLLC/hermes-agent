"""A reply split at a platform's message limit (p10-messaging §2.3: 4,096 for Telegram).

Prefers a paragraph break, then a line break, then a space inside the window; a run with none of them is
cut hard. ``size`` measures a piece the way the platform does (Telegram counts UTF-16 code units, so an
emoji is two). Nothing is dropped or reordered: ``"".join(chunk(t, n))`` differs from ``t`` only by the
whitespace each cut consumed at a break.
"""

from __future__ import annotations

from collections.abc import Callable

__layer__ = "models"
__all__ = ["chunk", "utf16_size"]

_BREAKS = ("\n\n", "\n", " ")


def utf16_size(text: str) -> int:
    return len(text.encode("utf-16-le")) // 2


def _fits(text: str, limit: int, size: Callable[[str], int]) -> int:
    """The longest prefix length of ``text`` whose size is within ``limit`` (at least one character)."""
    if size(text) <= limit:
        return len(text)
    lo, hi = 1, len(text)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if size(text[:mid]) <= limit:
            lo = mid
        else:
            hi = mid - 1
    return lo


def chunk(text: str, limit: int, *, size: Callable[[str], int] = len) -> list[str]:
    """``text`` as pieces no larger than ``limit``; an empty or blank text is no pieces."""
    if limit < 1:
        raise ValueError("limit must be positive")
    rest, pieces = text.strip(), []
    while rest:
        cut = _fits(rest, limit, size)
        if cut < len(rest):
            window = rest[:cut]
            # The first break kind found in the window's back half wins; a break nearer the front
            # would make a tiny piece, so it is only taken when nothing better exists.
            found = [window.rfind(mark) for mark in _BREAKS]
            at = next((i for i in found if i >= cut // 2), max(found))
            if at > 0:
                cut = at
        piece, rest = rest[:cut].rstrip(), rest[cut:].lstrip()
        if piece:
            pieces.append(piece)
    return pieces
