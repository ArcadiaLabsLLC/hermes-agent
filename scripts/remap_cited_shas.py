#!/usr/bin/env python3
"""Rewrite cited wave-branch SHAs to the commits that landed them, before a closing queue commit.

A lane cites its own branch commits (``6fa63514ea2``) in queue rows, VERDICT lines and
closures; the landing rebases the branch, and the cited SHA then names a commit no
``main`` contains — one branch delete or GC from gone. This maps each cited SHA that is
NOT on ``--onto`` to the commit on ``--onto`` with the same author, author date and
subject (the landed equivalent: a rebase or cherry-pick keeps all three, and comparing them
reads no tree, which matters in the shared clone's treeless partial clone) and rewrites it in place, keeping the cited length. A cited commit with no
landed equivalent is HELD work: it is reported with the remote branches that hold it, so
the landing pins it (``git tag held/<lane>/<sha> <sha>`` and pushes the tag) and names
the branch beside it.

    python scripts/remap_cited_shas.py --onto origin/main "Harness_Brain/20 — Active Initiatives/fork-hygiene-queue.md"
    python scripts/remap_cited_shas.py --onto origin/main --check <files>   # report only, exit 1 on anything stale

Rule: fork-hygiene-queue row "CLASS — closures and VERDICT lines cite pre-rebase
wave-branch SHAs" (2026-10-15); ``Harness_Brain/50 — Agent Handoffs/Dispatching a lane.md``.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

#: a backticked or bare hex token a queue cites as a commit (10–40 hex digits)
_SHA = re.compile(r"(?<![0-9a-f])[0-9a-f]{10,40}(?![0-9a-f])")
#: how far back on ``--onto`` a landed equivalent is searched
DEFAULT_DEPTH = 400


def _git(repo: Path, *args: str, stdin: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo), *args], input=stdin, capture_output=True,
                          text=True, encoding="utf-8", check=False, timeout=120)


def _commits(repo: Path, tokens: list[str]) -> dict[str, str]:
    """token -> full commit SHA, for every token that names a commit (one ``cat-file`` call)."""

    out = _git(repo, "cat-file", "--batch-check=%(objectname) %(objecttype)", stdin="\n".join(tokens) + "\n").stdout
    found = {}
    for token, line in zip(tokens, out.splitlines()):
        name, _, kind = line.partition(" ")
        if kind == "commit":
            found[token] = name
    return found


def _reachable(repo: Path, *revs: str) -> set[str]:
    return set(_git(repo, "rev-list", *revs).stdout.split())


_SEP = "\x1f"
_KEY_FORMAT = "%H%x1f%ae%x1f%ad%x1f%s"


def _keys(repo: Path, *revs: str, walk: bool = False) -> dict[str, str]:
    """commit -> its identity key (author email, author date, subject), one ``git log`` call;
    ``walk`` walks history from ``revs``, otherwise exactly the named commits."""

    mode = "--no-merges" if walk else "--no-walk=unsorted"
    out = _git(repo, "log", mode, "--date=raw", f"--format={_KEY_FORMAT}", *revs).stdout
    keys = {}
    for line in out.splitlines():
        sha, _, rest = line.partition(_SEP)
        keys[sha] = rest
    return keys


@dataclass
class Mapping:
    remapped: dict[str, str]  # cited token -> landed token (same length)
    held: dict[str, list[str]]  # cited token -> remote branches holding it


def landed_index(repo: Path, onto: str, depth: int) -> dict[str, str]:
    """identity key -> commit, over the last ``depth`` non-merge commits on ``onto``."""

    index: dict[str, str] = {}
    for sha, key in _keys(repo, f"--max-count={depth}", onto, walk=True).items():
        index.setdefault(key, sha)
    return index


def plan(repo: Path, onto: str, texts: list[str], depth: int = DEFAULT_DEPTH) -> Mapping:
    tokens = sorted({t for text in texts for t in _SHA.findall(text)})
    commits = _commits(repo, tokens)
    on_main = _reachable(repo, onto)
    off_main = {token: full for token, full in commits.items() if full not in on_main}
    result = Mapping({}, {})
    if not off_main:
        return result
    upstream = _reachable(repo, "--remotes=upstream")  # cited as upstream's: never the fork's to land
    index = landed_index(repo, onto, depth)
    cited = _keys(repo, *off_main.values())
    for token, full in off_main.items():
        landed = index.get(cited.get(full, ""))
        if landed:
            result.remapped[token] = landed[: len(token)]
        elif full not in upstream:
            result.held[token] = _git(repo, "branch", "-r", "--format=%(refname:short)", "--contains", full).stdout.split()
    return result


def rewrite(text: str, remapped: dict[str, str]) -> str:
    return _SHA.sub(lambda m: remapped.get(m.group(0), m.group(0)), text)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("files", nargs="+", type=Path)
    parser.add_argument("--onto", default="origin/main")
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--depth", type=int, default=DEFAULT_DEPTH)
    parser.add_argument("--check", action="store_true", help="report only; exit 1 when a cited SHA is off --onto")
    args = parser.parse_args(argv)
    texts = [path.read_text(encoding="utf-8-sig") for path in args.files]
    mapping = plan(args.repo, args.onto, texts, args.depth)
    for token, landed in sorted(mapping.remapped.items()):
        print(f"REMAP {token} -> {landed} (same author, date and subject on {args.onto})")
    for token, branches in sorted(mapping.held.items()):
        print(f"HELD {token}: no landed equivalent; only on {', '.join(branches) or 'no remote branch'} — pin it with a tag")
    if args.check:
        return 1 if mapping.remapped or mapping.held else 0
    for path, text in zip(args.files, texts):
        new = rewrite(text, mapping.remapped)
        if new != text:
            path.write_text(new, encoding="utf-8", newline="\n")
            print(f"rewrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
