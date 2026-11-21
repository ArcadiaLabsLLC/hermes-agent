"""pytest plugin: run ONE shard of the collected tests (``--hermes-shard=i/k``).

Loaded by ``scripts/run_tests_bundled.py`` (``-p hermes_shard``) when it splits
a slow file across ``k`` processes (fast-gate plan §3). The collected node ids
are ranked by a stable hash (``crc32(nodeid)``, the id breaking a tie) and the
test at rank ``r`` belongs to shard ``r % k``: every shard process collects the
same ids, so each test lands in exactly one shard, never by a precomputed list;
parametrised ids split across shards, and module/class fixtures run once per
shard (the cost that bounds k). The shards differ by at most one test: with
``crc32(nodeid) % k`` alone, a two-test file split in two put both tests in one
shard half the time (``tests/agent_runtime/test_native_large_recovery.py`` ran
62.6 s in shard 1/2 while 0/2 held nothing,
FH-PREPUSH-TOUCHED-NATIVE-LARGE-RECOVERY-OVER-BUDGET).
The other shards' items are deselected through ``pytest_deselected``.

A shard left EMPTY (fewer tests than shards) keeps ONE other shard's item, marked skip, instead of
exiting 5. Exit 5 alone is a per-file pass, but a run that is just that shard
(``scripts/prepush.sh`` starts each shard as its own runner) collected nothing,
and the runner's nothing-ran guard reds it: "NO TESTS RAN — 0 collected" over a
green file (FH-PREPUSH-NAMED-FILE-NO-TESTS-RAN). The skip is reported with its
reason and never sets up a fixture.

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
        help="Run only shard I of K: the collected ids ranked by crc32(node id), dealt round K shards.",
    )


def parse_shard(value: str) -> tuple[int, int]:
    """``"i/k"`` → ``(i, k)``; ``ValueError`` unless ``0 <= i < k``."""

    index, _, count = value.partition("/")
    i, k = int(index), int(count)
    if not 0 <= i < k:
        raise ValueError(f"shard {value!r} is not i/k with 0 <= i < k")
    return i, k


def shard_of(nodeid: str, k: int) -> int:
    """The hash a test is ranked by (kept for callers that spread their own work the same way)."""

    return zlib.crc32(nodeid.encode("utf-8")) % k


def shards_of(nodeids, k: int) -> dict[str, int]:
    """Each id's shard: ranked by ``crc32``, then dealt round the ``k`` shards, so sizes differ by ≤ 1."""

    ranked = sorted(set(nodeids), key=lambda nodeid: (zlib.crc32(nodeid.encode("utf-8")), nodeid))
    return {nodeid: rank % k for rank, nodeid in enumerate(ranked)}


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
    # MUTATION: rank nothing (``home = {n: shard_of(n, k) ...}``) and
    # test_a_two_test_file_split_in_two_runs_one_test_per_shard reddens.
    home = shards_of([item.nodeid for item in items], k)
    keep = [item for item in items if home[item.nodeid] == i]
    drop = [item for item in items if home[item.nodeid] != i]
    if not keep and drop:
        placeholder = drop.pop(0)
        placeholder.add_marker(pytest.mark.skip(
            reason=f"{_OPTION}={i}/{k} holds none of these {len(items)} tests; "
                   f"this one runs in shard {home[placeholder.nodeid]}/{k}"
        ))
        keep = [placeholder]
    if drop:
        config.hook.pytest_deselected(items=drop)
        items[:] = keep
