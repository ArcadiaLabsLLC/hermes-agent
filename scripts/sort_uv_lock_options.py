"""Sort uv.lock's ``[options.exclude-newer-package]`` table by key.

uv 0.12.3 on Windows writes that table in an unordered sequence, so every
``uv lock`` during an upstream merge rewrites ~100 header lines against
upstream's copy (v0.21.6: +82 deleted lines in the footprint, fixed by hand in
``5be84f0770``). ``uv lock --locked`` accepts the sorted table unchanged.

Usage (``Merging upstream.md`` Step 3, right after ``uv lock``)::

    python scripts/sort_uv_lock_options.py            # rewrite uv.lock in place
    python scripts/sort_uv_lock_options.py --check    # exit 1 when unsorted
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

TABLE = "[options.exclude-newer-package]"
LOCK = Path(__file__).resolve().parent.parent / "uv.lock"


def sort_table(text: str) -> str:
    """``text`` with the table's ``key = value`` lines sorted by key; everything else untouched."""
    lines = text.split("\n")
    try:
        start = lines.index(TABLE) + 1
    except ValueError:
        return text
    end = start
    while end < len(lines) and lines[end] and not lines[end].startswith("["):
        end += 1
    lines[start:end] = sorted(lines[start:end], key=lambda line: line.partition(" = ")[0])
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true", help="exit 1 when the table is unsorted; write nothing")
    parser.add_argument("lock", nargs="?", type=Path, default=LOCK)
    args = parser.parse_args(argv)
    text = args.lock.read_text(encoding="utf-8")
    fixed = sort_table(text)
    if fixed == text:
        return 0
    if args.check:
        print(f"{args.lock}: {TABLE} is unsorted; run python scripts/sort_uv_lock_options.py", file=sys.stderr)
        return 1
    args.lock.write_bytes(fixed.encode("utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
