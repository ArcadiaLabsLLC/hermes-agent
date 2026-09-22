"""Whose file is this? — the scope shared by the fork's structural gates.

WHY THIS FILE EXISTS
====================

The fork carries structural gates upstream does not have: bans written as AST
walks over a whole directory (``test_no_midtest_monkeypatch_undo.py`` over
``tests/``, ``test_flag_binding_boundary.py`` over ``hermes_cli/``). They were
written against fork-authored code and they encode fork rulings.

A walk over a directory does not know who wrote what. The 2026-09-21
``upstream/main`` merge is where that stopped being academic: the undo ban
flagged sites in upstream's own tests and the flag-binding ban flagged
``hermes_cli/send_cmd.py:210`` (``mentions or []``), all of them upstream code
the fork does not edit. Neither gate can act on them:

* the fork's standing rule is that a file present in ``upstream/main`` is edited
  ADDITIVELY or not at all, because a rewritten upstream line is a conflict owed
  at every future merge;
* and neither gate grows an allowlist — both say so in their own docstrings, and
  an allowlist is how a gate turns into a list of exceptions nobody re-reads.

So the answer is scope, not exemption: a file that is byte-identical to
``upstream/main`` is upstream's to police, and the fork's gates look at the
files the fork actually touched. This module answers that one question, once,
for every gate that needs it.

WHAT "FORK-TOUCHED" MEANS, AND WHY A SECOND, NARROWER ANSWER EXISTS
===================================================================

``is_fork_touched(path)`` is True when the working file is absent from
``upstream/main`` OR its content differs from the blob ``upstream/main`` lists
for it. It is a FILE-level answer, and for a file the fork wrote it is the only
answer needed.

It is NOT sufficient for the file the fork EXTENDED. The fence is "a file
present in ``upstream/main`` is edited additively or not at all", so in such a
file the fork owns the lines it added and nothing else —
``tests/hermes_cli/test_gateway.py`` is 116 fork-added lines (working lines
12-20, 311-416 and 517 on the 2026-09-21 merge) bolted onto upstream's module,
and the two ``.undo()`` sites the undo ban reports in it, at :37 and :1349, sit
in neither range. A file-level answer would hand the fork two findings it is
forbidden to fix: rewriting either line is a non-additive edit, owed again at
every future merge.

So :func:`is_fork_authored` answers the narrower question a FINDING actually
asks — "did the fork write this line?" — by diffing the working file against
the upstream blob and taking the inserted lines. The two questions are the same
question for a file absent from upstream (every line is the fork's), which is
the common case; the diff is paid only for a finding in a file upstream also
ships.

FAIL CLOSED
===========

When the ``upstream/main`` ref is not there — a clone without the remote, CI
that fetches one branch, a shallow checkout — or when any git invocation fails,
every file reads as fork-touched and the gates scan exactly what they scanned
before this module existed. A scope helper that failed OPEN would silently turn
a ban into a no-op on the one machine nobody was watching.

THE COST
========

One ``git ls-tree -r upstream/main`` per process, cached; one
``git hash-object``, and at most one ``git cat-file``, per path actually asked
about, cached. Callers ask about FINDINGS, not about every file they walk (see
each gate), so those two are paid a handful of times at most, and a green gate
pays them zero times.
"""

from __future__ import annotations

import difflib
import functools
import subprocess
from pathlib import Path

__all__ = [
    "UPSTREAM_REF",
    "fork_authored_lines",
    "is_fork_authored",
    "is_fork_touched",
    "read_upstream_blobs",
    "repo_root",
    "upstream_blobs",
    "working_blob",
]

#: The ref that answers "is this upstream's?". The fork integrates upstream by
#: a history-preserving merge, so this ref is what a fork-owned line is
#: measured against.
UPSTREAM_REF = "upstream/main"

_UNSET = object()


def repo_root() -> Path:
    """The checkout this module lives in (``tests/`` sits at the root)."""

    return Path(__file__).resolve().parents[1]


def _git(args: list[str], *, cwd: Path) -> bytes | None:
    """``git <args>`` stdout, or ``None`` for ANY failure.

    ``None`` is the fail-closed signal all the way up: no git, no repo, no ref,
    a non-zero exit, output this module cannot parse — the callers above turn
    every one of them into "fork-touched", never into "upstream's".
    """

    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=str(cwd),
            capture_output=True,
            check=False,
        )
    except (OSError, ValueError):  # git absent, cwd gone, bad argv
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout


def read_upstream_blobs(root: Path, ref: str = UPSTREAM_REF) -> dict[str, str] | None:
    """``{repo-relative posix path: blob sha}`` for ``ref``, or ``None``.

    ``root`` and ``ref`` are parameters rather than module constants so a test
    can drive the fail-closed path against a real empty repository instead of
    asserting it from the source.

    ``-z`` rather than plain ``-r``: ls-tree quotes and escapes paths outside
    ASCII by default, and a path this module re-spelled would compare unequal
    to the one the caller hands it.
    """

    out = _git(["ls-tree", "-r", "-z", ref], cwd=root)
    if out is None:
        return None

    blobs: dict[str, str] = {}
    for entry in out.split(b"\0"):
        if not entry:
            continue
        meta, _, path = entry.partition(b"\t")
        fields = meta.split()
        if not path or len(fields) != 3:
            return None  # an ls-tree this module cannot read is a git failure
        _mode, kind, sha = fields
        if kind != b"blob":
            continue  # a submodule/commit entry has no content to compare
        blobs[path.decode("utf-8", "surrogateescape")] = sha.decode("ascii")
    return blobs


@functools.lru_cache(maxsize=1)
def upstream_blobs() -> dict[str, str] | None:
    """:func:`read_upstream_blobs` for this checkout, once per process."""

    return read_upstream_blobs(repo_root())


@functools.lru_cache(maxsize=None)
def working_blob(relative: str) -> str | None:
    """The blob sha git would store for the WORKING file, or ``None``.

    ``git hash-object`` and not a hash computed here: the sha git stores is the
    content AFTER the checkout filters declared for that path (``text=auto``
    line-ending normalization above all), so a hash taken on raw bytes would
    report every CRLF file in the tree as fork-touched.
    """

    out = _git(["hash-object", "--", relative], cwd=repo_root())
    if out is None:
        return None
    return out.decode("ascii", "replace").strip() or None


def relative_path(path: str | Path) -> str | None:
    """``path`` as a repo-relative posix path, or ``None`` if it is outside.

    Relative input is taken as already repo-relative, which is how both gates
    spell their findings.
    """

    candidate = Path(path)
    if not candidate.is_absolute():
        return candidate.as_posix()
    try:
        return candidate.resolve().relative_to(repo_root()).as_posix()
    except ValueError:
        return None


def is_fork_touched(path: str | Path, *, blobs: object = _UNSET) -> bool:
    """Is ``path`` the fork's to police? See the module docstring.

    ``blobs`` is injectable so the fail-closed contract can be driven directly
    (``blobs=None``) without reaching into this module's caches.
    """

    index = upstream_blobs() if blobs is _UNSET else blobs
    if index is None:
        return True  # no upstream ref: everything is ours, as before this module

    relative = relative_path(path)
    if relative is None:
        return True  # outside the checkout; not upstream's by construction

    listed = index.get(relative)
    if listed is None:
        return True  # absent from upstream/main: fork-authored

    actual = working_blob(relative)
    if actual is None:
        return True  # git could not hash it; fail closed
    return actual != listed


def _upstream_text(relative: str) -> list[str] | None:
    """``upstream/main``'s copy of ``relative``, as lines, or ``None``."""

    out = _git(["cat-file", "blob", f"{UPSTREAM_REF}:{relative}"], cwd=repo_root())
    if out is None:
        return None
    return out.decode("utf-8", errors="replace").splitlines()


@functools.lru_cache(maxsize=None)
def fork_authored_lines(relative: str) -> frozenset[int] | None:
    """1-based WORKING line numbers the fork added, or ``None`` for "all of it".

    ``None`` is the whole-file answer and covers both the ordinary case (the
    file is absent from ``upstream/main``, so every line is the fork's) and
    every failure (no ref, unreadable blob, unreadable working file) — the same
    fail-closed direction as the rest of this module.

    ``difflib`` rather than ``git diff``: the inputs are already in hand (the
    blob and the working file), the comparison is line-for-line, and a text
    diff computed here cannot be bent by the caller's diff configuration
    (``diff.algorithm``, a driver declared in ``.gitattributes``).
    """

    index = upstream_blobs()
    if index is None or relative not in index:
        return None

    upstream = _upstream_text(relative)
    if upstream is None:
        return None
    try:
        working = (repo_root() / relative).read_text(
            encoding="utf-8", errors="replace"
        ).splitlines()
    except OSError:
        return None

    added: set[int] = set()
    matcher = difflib.SequenceMatcher(a=upstream, b=working, autojunk=False)
    for tag, _i1, _i2, j1, j2 in matcher.get_opcodes():
        if tag in ("insert", "replace"):
            added.update(range(j1 + 1, j2 + 1))  # working lines are 1-based
    return frozenset(added)


def is_fork_authored(path: str | Path, lineno: int) -> bool:
    """Did the FORK write ``path`` line ``lineno``? The finding-level filter.

    True for every line of a file the fork wrote, for a line the fork added to
    a file upstream also ships, and — fail-closed — for anything this module
    cannot resolve. False only when the line is demonstrably upstream's.
    """

    if not is_fork_touched(path):
        return False

    relative = relative_path(path)
    if relative is None:
        return True

    added = fork_authored_lines(relative)
    if added is None:
        return True
    return lineno in added
