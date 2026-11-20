"""One check answers whether a chat is busy (RT-ONE-CHECK-FOR-WHETHER-A-CHAT-IS-BUSY).

The send runner, the messaging bridge, the busy-target wait of agent_chat_dispatch
and the delivery drain all ask "does a turn hold this chat root right now". They
ask it through ``persona_chat_continuity.lease.chat_root_lease_holder`` (and its
bool face ``chat_root_is_busy``), never through a private zero-wait probe of
their own — four such copies existed, differing only in their owner label.

Killing mutation (recorded in the row's close): ``return dict(exc.owner)`` ->
``return None`` in ``chat_root_lease_holder`` reds the held-root tests here (a
busy root reads free). A private probe written back into any module reds the
source walk.
"""

from __future__ import annotations

import ast
from pathlib import Path

from agent_runtime.persona_chat_continuity import (
    chat_root_is_busy,
    chat_root_lease_holder,
    persona_chat_root_lease,
)
from agent_runtime.persona_chat_continuity.lease import _lease_paths

REPO = Path(__file__).resolve().parents[2]
ROOT = "persona_chat_busy_check_root"


def test_a_free_root_is_not_busy_and_the_check_leaves_it_free(isolate_agent_runtime_root):
    assert chat_root_lease_holder(ROOT, probe_owner="t") is None
    assert chat_root_is_busy(ROOT, probe_owner="t") is False
    # The check released what it took: a turn can take the root at once.
    with persona_chat_root_lease(ROOT, owner_id="the-turn", observer_kind="cli") as owner:
        assert owner["owner_id"] == "the-turn"


def test_a_held_root_is_busy_and_names_its_holder(isolate_agent_runtime_root):
    with persona_chat_root_lease(ROOT, owner_id="the-turn", observer_kind="cli"):
        holder = chat_root_lease_holder(ROOT, probe_owner="t")
        assert holder is not None and holder["owner_id"] == "the-turn"
        assert chat_root_is_busy(ROOT, probe_owner="t") is True
    assert chat_root_is_busy(ROOT, probe_owner="t") is False


def test_a_held_root_with_no_readable_owner_is_busy_not_free(isolate_agent_runtime_root):
    with persona_chat_root_lease(ROOT, owner_id="the-turn", observer_kind="cli"):
        _lease_paths(ROOT)[1].unlink()
        assert chat_root_lease_holder(ROOT, probe_owner="t") == {}
        assert chat_root_is_busy(ROOT, probe_owner="t") is True


def _is_busy_handler(handler: ast.ExceptHandler) -> bool:
    return "PersonaChatBusyError" in ast.unparse(handler.type) if handler.type is not None else False


def _is_probe_with(node: ast.With) -> bool:
    """A ``with persona_chat_root_lease(...)`` whose body only returns a constant or passes."""

    if not any("persona_chat_root_lease" in ast.unparse(item.context_expr) for item in node.items):
        return False
    return all(
        isinstance(stmt, ast.Pass) or (isinstance(stmt, ast.Return) and isinstance(stmt.value, ast.Constant | None))
        for stmt in node.body
    )


def private_busy_probes() -> list[str]:
    """Every zero-wait lease probe written outside the one check (``path:line``)."""

    found: list[str] = []
    for top in ("agent_runtime", "tools", "hermes_cli", "gateway"):
        for path in sorted((REPO / top).rglob("*.py")):
            rel = path.relative_to(REPO).as_posix()
            if rel == "agent_runtime/persona_chat_continuity/lease.py":
                continue
            text = path.read_text(encoding="utf-8")
            if "persona_chat_root_lease" not in text:
                continue
            for node in ast.walk(ast.parse(text)):
                if not isinstance(node, ast.Try) or not any(_is_busy_handler(h) for h in node.handlers):
                    continue
                if any(isinstance(stmt, ast.With) and _is_probe_with(stmt) for stmt in node.body):
                    found.append(f"{rel}:{node.lineno}")
    return found


def test_no_module_writes_its_own_busy_probe():
    assert private_busy_probes() == []
