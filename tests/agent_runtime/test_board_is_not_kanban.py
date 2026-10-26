"""RT-BOARD-NOT-KANBAN: our board is the Mission Board and never calls itself kanban (naming map ruling 8).

A negative guarantee, so a source walk is the right tool: upstream's ``kanban.db`` keeps its name, and
nothing of OURS that defines or describes the board may borrow it.
"""

from __future__ import annotations

import inspect
from pathlib import Path

from agent_runtime.models import Board

ROOT = Path(__file__).resolve().parents[2]


def _ours() -> list[Path]:
    runtime = ROOT / "agent_runtime"
    return sorted({*runtime.glob("board_*.py"), *(runtime / "board_store").rglob("*.py"),
                   runtime / "workspace_template.py"})


def test_the_board_modules_never_say_kanban():
    offenders = [p.relative_to(ROOT).as_posix() for p in _ours() if "kanban" in p.read_text(encoding="utf-8").lower()]
    assert len(_ours()) > 3  # the walk found the board tree
    assert offenders == []


def test_the_board_model_calls_itself_the_mission_board():
    doc = inspect.getdoc(Board) or ""
    assert "Mission Board" in doc
    assert "kanban board" not in doc.lower()
