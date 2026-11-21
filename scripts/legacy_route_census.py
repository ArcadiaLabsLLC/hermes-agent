#!/usr/bin/env python3
"""Read-only census of the retired profile conversations' saved routes on this computer.

RT-FU-A-SAVED-PROFILE-CONVERSATION-OUTSIDE-A-GROUP-IS-KEPT-BUT-NEVER-BECOMES-AN-AGENTS-CHAT asks
whether any box still holds a route of the retired profile-scoped conversation path
(``native_conversation_routes.db``) that has turns and was never imported into an agent's chat.
Every ``native_conversation_routes.db`` under the given roots (default: the user's home) is opened
read-only (``mode=ro``) and counted; nothing is written, moved or deleted.

    python scripts/legacy_route_census.py [ROOT ...]

Prints one line per database that holds a route, then a total. ``pending`` is a route with turns
and no migration mark: what that row would import. Exit 0 always (a census, never a gate).
"""
from __future__ import annotations

import sqlite3
import sys
from contextlib import closing
from pathlib import Path

ROUTES_FILE = "native_conversation_routes.db"


def count(path: Path) -> dict[str, int]:
    """``routes``, ``with_turns``, ``migrated`` and ``pending`` for one routes database, read-only."""
    with closing(sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)) as db:
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}

        def one(sql: str) -> int:
            return db.execute(sql).fetchone()[0]

        if "conversation_routes" not in tables:
            return {"routes": 0, "with_turns": 0, "migrated": 0, "pending": 0}
        turns = ("EXISTS (SELECT 1 FROM conversation_turns t WHERE t.conversation_id=r.id)"
                 if "conversation_turns" in tables else "0")
        marked = ("EXISTS (SELECT 1 FROM conversation_migrations m WHERE m.conversation_id=r.id)"
                  if "conversation_migrations" in tables else "0")
        return {"routes": one("SELECT COUNT(*) FROM conversation_routes r"),
                "with_turns": one(f"SELECT COUNT(*) FROM conversation_routes r WHERE {turns}"),
                "migrated": one(f"SELECT COUNT(*) FROM conversation_routes r WHERE {marked}"),
                "pending": one(f"SELECT COUNT(*) FROM conversation_routes r WHERE {turns} AND NOT {marked}")}


def census(roots) -> tuple[dict[str, int], list[tuple[Path, dict[str, int]]], list[tuple[Path, str]]]:
    total = {"files": 0, "routes": 0, "with_turns": 0, "migrated": 0, "pending": 0}
    held, unreadable = [], []
    for root in roots:
        for path in sorted(Path(root).rglob(ROUTES_FILE)):
            try:
                found = count(path)
            except sqlite3.Error as exc:
                unreadable.append((path, type(exc).__name__))
                continue
            total["files"] += 1
            for key, value in found.items():
                total[key] += value
            if found["routes"]:
                held.append((path, found))
    return total, held, unreadable


def main(argv: list[str]) -> int:
    roots = argv or [str(Path.home())]
    total, held, unreadable = census(roots)
    for path, found in held:
        print(path, " ".join(f"{key}={value}" for key, value in found.items()))
    for path, reason in unreadable:
        print(path, "unreadable", reason)
    print("total", " ".join(f"{key}={value}" for key, value in total.items()), "unreadable=" + str(len(unreadable)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
