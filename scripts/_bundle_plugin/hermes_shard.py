"""pytest plugin: run ONE shard of the collected tests (``--hermes-shard=i/k``).

Loaded by ``scripts/run_tests_bundled.py`` (``-p hermes_shard``) when it splits
a slow file across ``k`` processes (fast-gate plan §3). A test belongs to shard
``crc32(nodeid) % k``: a stable hash of the NODE ID, never a precomputed list,
so a new test lands in exactly one shard, parametrised ids split across
shards, and module/class fixtures run once per shard (the cost that bounds k).
The other shards' items are deselected through ``pytest_deselected``; a shard
left with nothing exits 5, which the per-file runner reads as a pass.

Generic on purpose (no fork paths), like ``hermes_bundle_report``.
"""

from __future__ import annotations

import zlib

import pytest

_OPTION = "--hermes-shard"


def pytest_addoption(parser):
    parser.addoption(
        _OPTION,
        dest="hermes_shard",
        default=None,
        metavar="I/K",
        help="Run only the tests whose crc32(node id) % K == I.",
    )


def parse_shard(value: str) -> tuple[int, int]:
    """``"i/k"`` → ``(i, k)``; ``ValueError`` unless ``0 <= i < k``."""

    index, _, count = value.partition("/")
    i, k = int(index), int(count)
    if not 0 <= i < k:
        raise ValueError(f"shard {value!r} is not i/k with 0 <= i < k")
    return i, k


def shard_of(nodeid: str, k: int) -> int:
    return zlib.crc32(nodeid.encode("utf-8")) % k


def pytest_configure(config):
    value = config.getoption("hermes_shard")
    try:
        config._hermes_shard = parse_shard(value) if value else None  # type: ignore[attr-defined]
    except ValueError as exc:
        raise pytest.UsageError(f"{_OPTION}: {exc}") from None


@pytest.hookimpl(trylast=True)
def pytest_collection_modifyitems(session, config, items):
    shard = getattr(config, "_hermes_shard", None)
    if shard is None:
        return
    i, k = shard
    keep = [item for item in items if shard_of(item.nodeid, k) == i]
    drop = [item for item in items if shard_of(item.nodeid, k) != i]
    if drop:
        config.hook.pytest_deselected(items=drop)
        items[:] = keep
