"""Two members published at once: the remote side wins where both changed the same lines, as ``-X theirs`` does.

The binary half settles a diverged pull with ``git pull --no-rebase --no-edit -X theirs``. dulwich has no
strategy option, and its own merger needs the ``merge3`` package for any file both sides edited, which is
GPL-2.0-or-later only and never ships in Eternia. So the phone's merge is a stdlib ``difflib`` diff3 here:
each side's separate hunks are kept, and where the two sides' hunks overlap (or touch, as git counts it)
the favoured side's hunk is taken whole — ``THEIRS`` for a pull, ``OURS`` for the adopter's merge of an
unrelated history. A file one side deleted while the other edited it (modify/delete) is settled the same
way: the favoured side's tree wins — their delete removes our edited file, their edit restores a file we
deleted — and the merge names each such path in ``dropped`` (TASK-REALM-DELETE-MEETS-AN-EDIT, review
w1118a.36 D1: the owner's 2026-11-13 remote-wins rule, no new reconciliation layer). Every other tree-SHAPE
clash (file/directory, a mode change) stays a conflict, with its stages in the index, as git leaves it.

Pinned by ``tests/agent_runtime/test_realm_sync_merge_parity.py`` (git's tree on every content case) and
``tests/agent_runtime/test_realm_sync_dulwich_spawns_nothing.py`` (no ``merge3`` named here).
"""

from __future__ import annotations

import stat
from difflib import SequenceMatcher
from enum import Enum

from dulwich.merge import Merger
from dulwich.objects import Blob, Tree

__layer__ = "policy"
__all__ = ["Favour", "FavouringMerger", "merge_lines"]


class Favour(Enum):
    THEIRS = "theirs"
    OURS = "ours"


def _shared_lines(base: list[bytes], other: list[bytes]) -> dict[int, int]:
    """Base line index -> the other side's line index, for the lines the two share (monotonic)."""

    found: dict[int, int] = {}
    for block in SequenceMatcher(None, base, other, autojunk=False).get_matching_blocks():
        for offset in range(block.size):
            found[block.a + offset] = block.b + offset
    return found


def merge_lines(base: list[bytes], ours: list[bytes], theirs: list[bytes], favour: Favour) -> list[bytes]:
    """diff3 of three line lists; an overlapping hunk resolves to the ``favour`` side whole."""

    to_ours, to_theirs = _shared_lines(base, ours), _shared_lines(base, theirs)
    stable = [n for n in range(len(base)) if n in to_ours and n in to_theirs]
    out: list[bytes] = []
    i = j = k = 0
    for n in [*stable, len(base)]:
        o_end = to_ours[n] if n < len(base) else len(ours)
        t_end = to_theirs[n] if n < len(base) else len(theirs)
        if o_end < j or t_end < k:
            continue  # a stable line the walk already passed
        a, o, t = base[i:n], ours[j:o_end], theirs[k:t_end]
        if o == a:
            out.extend(t)
        elif t == a or o == t:
            out.extend(o)
        else:
            out.extend(t if favour is Favour.THEIRS else o)
        if n < len(base):
            out.append(base[n])
        i, j, k = n + 1, o_end + 1, t_end + 1
    return out


class FavouringMerger(Merger):
    """dulwich's tree merge, with every both-sides content edit settled by ``merge_lines`` (never ``merge3``)."""

    def __init__(self, object_store, favour: Favour) -> None:
        super().__init__(object_store)
        self.favour = favour
        #: The paths whose losing side's change a modify/delete settlement dropped, in walk order.
        self.dropped: list[bytes] = []

    def merge_blobs(self, base_blob: Blob | None, ours_blob: Blob | None, theirs_blob: Blob | None,
                    path: bytes | None = None) -> tuple[bytes, bool]:
        if ours_blob is None and theirs_blob is None:
            return b"", False
        if ours_blob is None or theirs_blob is None:
            kept = theirs_blob if ours_blob is None else ours_blob
            return kept.data, False
        base = base_blob.data if base_blob is not None else b""
        merged = merge_lines(base.splitlines(keepends=True), ours_blob.data.splitlines(keepends=True),
                             theirs_blob.data.splitlines(keepends=True), self.favour)
        return b"".join(merged), False

    def _merge_trees(self, base_tree: Tree | None, ours_tree: Tree, theirs_tree: Tree,
                     prefix: bytes) -> tuple[Tree, list[bytes]]:
        """dulwich's per-level merge, made to answer per FILE as git does.

        A directory one side deleted while the other changed something in it is a conflict on each changed
        FILE in git (``realms/r/a.txt``), and dulwich would name only the directory (``realms``): the deleted
        side is given an empty directory there, so the merge walks into it. A directory the merge emptied is
        dropped, as git never stores one."""

        if base_tree is not None:
            ours_tree, theirs_tree = self._walk_into_deleted_dirs(base_tree, ours_tree, theirs_tree)
        merged, conflicts = super()._merge_trees(base_tree, ours_tree, theirs_tree, prefix)
        merged, conflicts = self._settle_modify_delete(merged, conflicts, prefix)
        empty = Tree().id
        if not any(stat.S_ISDIR(entry.mode) and entry.sha == empty for entry in merged.items()):
            return merged, conflicts
        pruned = Tree()
        for entry in merged.items():
            if not (stat.S_ISDIR(entry.mode) and entry.sha == empty):
                pruned.add(entry.path, entry.mode, entry.sha)
        return pruned, conflicts

    def _settle_modify_delete(self, merged: Tree, conflicts: list[bytes], prefix: bytes) -> tuple[Tree, list[bytes]]:
        """A modify/delete conflict at THIS level resolves to the favoured side, as a line clash does.

        Only a FILE that one side deleted while the other changed it; a clash where the surviving side is a
        directory (or the base was one) stays a conflict. MUTATION: return ``merged, conflicts`` unchanged
        and the parity test's modify/delete and delete/modify scenarios red at ``sync_conflict``."""

        if not conflicts:
            return merged, conflicts
        entries = {entry.path: (entry.mode, entry.sha) for entry in merged.items()}
        kept: list[bytes] = []
        settled = False
        for path in conflicts:
            info = self.conflict_info.get(path)
            name = path[len(prefix) + 1:] if prefix else path
            if info is None or b"/" in name:  # a deeper level's conflict, already left as it is
                kept.append(path)
                continue
            base_mode, ours, theirs = info.ancestor[0], info.ours, info.theirs
            one_side_gone = (ours[1] is None) != (theirs[1] is None)
            survivor = ours if theirs[1] is None else theirs
            if not one_side_gone or base_mode is None or stat.S_ISDIR(base_mode) or stat.S_ISDIR(survivor[0] or 0):
                kept.append(path)
                continue
            winner = theirs if self.favour is Favour.THEIRS else ours
            if winner[1] is None:
                entries.pop(name, None)
            else:
                entries[name] = (winner[0], winner[1])
            del self.conflict_info[path]
            self.dropped.append(path)
            settled = True
        if not settled:
            return merged, conflicts
        rebuilt = Tree()
        for name, (mode, sha) in sorted(entries.items()):
            rebuilt.add(name, mode, sha)
        self.object_store.add_object(rebuilt)
        return rebuilt, kept

    def _walk_into_deleted_dirs(self, base_tree: Tree, ours_tree: Tree, theirs_tree: Tree) -> tuple[Tree, Tree]:
        empty = Tree()
        self.object_store.add_object(empty)
        sides = []
        for side, other in ((ours_tree, theirs_tree), (theirs_tree, ours_tree)):
            have = {entry.path for entry in side.items()}
            others = {entry.path: entry for entry in other.items()}
            gone = [entry.path for entry in base_tree.items()
                    if stat.S_ISDIR(entry.mode) and entry.path not in have and entry.path in others
                    and stat.S_ISDIR(others[entry.path].mode) and others[entry.path].sha != entry.sha]
            if gone:
                filled = Tree()
                for entry in side.items():
                    filled.add(entry.path, entry.mode, entry.sha)
                for name in gone:
                    filled.add(name, stat.S_IFDIR, empty.id)
                self.object_store.add_object(filled)
                side = filled
            sides.append(side)
        return sides[0], sides[1]
