"""Who archived each key of a resurrection-guard ledger: this machine, or the realm.

A store's archive ledger (the office surface's ``archived_actor_keys``, a board's
``archived_card_ids``) holds two kinds of key. One is a delete made HERE, the
resurrection guard's whole point: a pull never brings it back. The other is a
peer's tombstone this machine adopted with the peer's surface or board: it
follows the realm, so a teammate who restores the desk or card gets it back on
every member (RT-REALM-MEMBER-DESK-ARCHIVED-BY-A-PULL-BLOCKS-THE-AGENT-COMING-BACK,
RT-REALM-BOARD-CARD-ARCHIVED-BY-A-PULL-BLOCKS-IT-COMING-BACK).

The second kind is recorded in ONE small file beside the ledger's own file, and
this module is its only reader and writer, for every store that keeps such a
ledger: each store names the file's path and nothing else. The merge that
decides which keys are the realm's is ``sync_merge.merge_archived_ledgers_by_origin``;
the answer "did this machine archive it" is :func:`own_archived`. The file is never
published: it says what THIS machine did not do.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from utils import atomic_json_write

from agent_runtime.serde import read_json

__layer__ = "stores"

__all__ = ["forget", "own_archived", "read_realm_held", "write_realm_held"]

# The office's first record (ce3b47fc6a) named its list ``actor_keys``; read so a
# record written before this module still says the same thing.
_KEY_FIELDS = ("keys", "actor_keys")


def read_realm_held(path: Path) -> set[str]:
    """The ledger keys the REALM put here, as recorded at ``path``.

    A missing or unreadable record answers the empty set: every key then reads
    as this machine's own, which is the ledger's old meaning and the safe
    direction (a desk or card stays archived; nothing is resurrected on a
    misread).
    """

    if not path.exists():
        return set()
    try:
        data = read_json(path)
    except Exception:  # the safe direction, see above
        return set()
    if not isinstance(data, dict):
        return set()
    for field in _KEY_FIELDS:
        keys = data.get(field)
        if isinstance(keys, list):
            return {str(key) for key in keys}
    return set()


def write_realm_held(path: Path, keys: Iterable[str]) -> None:
    """Record ``keys`` as the realm's; an empty set removes the record."""

    held = sorted({str(key) for key in keys})
    if not held:
        path.unlink(missing_ok=True)
        return
    atomic_json_write(path, {"keys": held}, indent=2, sort_keys=True)


def own_archived(ledger: Iterable[str], path: Path) -> set[str]:
    """The keys of ``ledger`` this machine archived: the ledger less the realm's.

    The one answer to "did I archive this", which a pull's classifier reads as
    ``locally_archived``; a realm-held key is not.
    """

    return {str(key) for key in ledger} - read_realm_held(path)


def forget(path: Path, key: str) -> None:
    """A delete made HERE makes ``key`` this machine's own from now on, even
    where the realm had held it: it must outlive a realm that drops it."""

    held = read_realm_held(path)
    if key in held:
        write_realm_held(path, held - {key})
