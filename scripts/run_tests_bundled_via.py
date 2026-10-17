"""What a pytest process, or a file's outcome, ran as: the typed via.

A via used to be a bare string ("known-red", "shard 1/4", "whole-check", ...)
spelled in five modules, and the run ledger counted processes by a string's
first word. :class:`Via` is still a ``str`` -- its printed spelling, so the
progress lines, the Summary and ``runs.jsonl`` read exactly as before -- but it
carries its :class:`ViaKind`, and every decision (count, cache, cap) reads the
kind, never the spelling. :func:`kind_of` is the one reader for a bare string
that predates the type; an unknown spelling raises instead of miscounting.

Loaded first by ``run_tests_bundled._load_sibling`` (``scripts/`` is not a
package), so the siblings' plain ``import run_tests_bundled_via`` resolves to
the same module. Standard library only.
"""

from __future__ import annotations

import re
from enum import Enum


class ViaKind(Enum):
    """Every via the runner spells."""

    BUNDLE = "bundle"
    SOLO = "solo"
    KNOWN_RED = "known-red"  # a known red's one capped run (fast-gate §2)
    KNOWN_RED_SKIPPED = "known-red, skipped"  # reported without a process
    SHARD = "shard"  # one shard i/k of a slow file (fast-gate §3)
    SHARDS = "shards"  # the joined outcome of a file's k green shards
    WHOLE_CHECK = "whole-check"  # the one whole run after a red shard
    RERUN = "rerun"  # a bundle member re-run alone
    RETRY = "retry"  # a straggler retry
    CACHED = "cached"  # skipped as cached green
    AUDIT_FLAKY = "audit-flaky"  # a cache-audit hit red, then green alone


class Via(str):
    """A via's spelling (``str``) with its :attr:`kind`."""

    kind: ViaKind

    def __new__(cls, kind: ViaKind, spelling: str | None = None) -> Via:
        obj = super().__new__(cls, kind.value if spelling is None else spelling)
        obj.kind = kind
        return obj

    def __reduce__(self):
        return (Via, (self.kind, str(self)))

    @classmethod
    def shard(cls, index: int, count: int) -> Via:
        return cls(ViaKind.SHARD, f"shard {index}/{count}")

    @classmethod
    def shards(cls, count: int) -> Via:
        return cls(ViaKind.SHARDS, f"{count} shards")

    @classmethod
    def cached(cls, detail: str) -> Via:
        return cls(ViaKind.CACHED, f"cached; {detail}")


BUNDLE = Via(ViaKind.BUNDLE)
SOLO = Via(ViaKind.SOLO)
KNOWN_RED = Via(ViaKind.KNOWN_RED)
KNOWN_RED_SKIPPED = Via(ViaKind.KNOWN_RED_SKIPPED)
WHOLE_CHECK = Via(ViaKind.WHOLE_CHECK)
RERUN = Via(ViaKind.RERUN)
RETRY = Via(ViaKind.RETRY)
AUDIT_FLAKY = Via(ViaKind.AUDIT_FLAKY)

_SHARD = re.compile(r"shard \d+/\d+")
_SHARDS = re.compile(r"\d+ shards")


def kind_of(via: object) -> ViaKind:
    """The kind of ``via``: a :class:`Via`'s own, else a bare spelling parsed here, once."""

    if isinstance(via, Via):
        return via.kind
    text = str(via)
    try:
        return ViaKind(text)
    except ValueError:
        pass
    if _SHARD.fullmatch(text):
        return ViaKind.SHARD
    if _SHARDS.fullmatch(text):
        return ViaKind.SHARDS
    if text.startswith("cached;"):
        return ViaKind.CACHED
    raise ValueError(f"unknown via {text!r}")


__all__ = [
    "AUDIT_FLAKY", "BUNDLE", "KNOWN_RED", "KNOWN_RED_SKIPPED", "RERUN", "RETRY", "SOLO", "WHOLE_CHECK",
    "Via", "ViaKind", "kind_of",
]
