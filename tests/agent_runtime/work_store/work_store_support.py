"""Builders the work-store tests share: slot declarations, checkouts with a queue note, binds."""

from __future__ import annotations

import subprocess
from pathlib import Path

from agent_runtime.machine_roots import load_machine_roots, write_machine_roots
from agent_runtime.workspace_slots import declare

ISSUED = "2026-10-18T12:00:00+00:00"
LATER = "2026-10-18T13:00:00+00:00"
CLONE_URL = "https://github.com/ArcadiaLabsLLC/hermes-agent.git"

QUEUE_HEAD = "---\ntype: queue\nprogram: test\n---\n\n## Open\n\n"


def slot_decl(name: str, **context: str) -> dict:
    return {"name": name, "repo": {"clone_url": CLONE_URL.replace("hermes-agent", name), "default_branch": "main"},
            "context": context or None}


def checkout(root: Path, brain: str | None = "Harness_Brain", rows: str = "") -> Path:
    """A git checkout at ``root``; with ``brain``, one queue note holding ``rows`` and one non-queue note."""

    root.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    if brain:
        queue = root / brain / "20 — Active Initiatives"
        queue.mkdir(parents=True)
        (queue / "q.md").write_text(QUEUE_HEAD + rows, encoding="utf-8")
        (queue / "notes.md").write_text("---\ntype: moc\n---\n- **`NOT-A-ROW` — moc** · READY 2026-10-18\n",
                                        encoding="utf-8")
    return root


def bind_here(**slots: Path) -> None:
    roots = dict(load_machine_roots(refresh=True).roots)
    roots.update({name: str(path) for name, path in slots.items()})
    write_machine_roots(roots, dry_run=False)


def declare_slots(workspace_id: str, *decls: dict, issued_at: str = ISSUED) -> None:
    declare(workspace_id, list(decls), issued_at=issued_at, machine="test-machine")
