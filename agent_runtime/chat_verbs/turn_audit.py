"""``mission-chat audit`` / ``runtime.chat.turn_audit`` — what a persona's turns did, read from the turn journal.

RT-TURN-AUDIT-ENTRY (owner 2026-10-25: "this should be auditable especially since i have external
harness use on"). A finished turn's tool calls, worktrees and commits were found only by opening
``agent-runtime/mission_chat_turns/<chat>_<id>.json`` by hand, in a store the reader first had to
locate. This is the one read: given a persona instance or a chat, the turns newest first and, per
turn, every tool call (command, exit, duration, timed out), the files it wrote, the worktrees and
branches it created or removed, its commits, and its model and tokens.

``namespace`` names the store that answered by KIND and id — the account namespace (``acct-…``), an
account sandbox, a profile namespace, or ``base`` — plus the store root and this machine's install
id, so "which namespace" never means two things. Strictly read-only: nothing is minted, swept or
repaired (the machine id is READ, ``gateway_identity.read_install_identity``).

Worktrees and branches are derived from the stored terminal commands (a regex over-approximation,
like ``turn_outcome.classify_command``): each row carries the call's exit code, so a failed
``worktree add`` reads as failed rather than as created. Cost is priced at read time from the stored
tokens (``agent.usage_pricing.estimate_usage_cost``); ``status: unknown`` when it cannot be.
"""

from __future__ import annotations

import re
import shlex
from collections.abc import Callable
from typing import Any

__layer__ = "lanes"
__all__ = ["TURN_AUDIT_LIMIT_MAX", "audit_namespace", "turn_audit"]

TURN_AUDIT_LIMIT_DEFAULT = 20
TURN_AUDIT_LIMIT_MAX = 200

_SEGMENT_SPLIT = re.compile(r"&&|\|\||[;|\n]")
_GIT_GLOBAL = {"-C", "-c", "--git-dir", "--work-tree"}
_WORKTREE_VALUE_OPTS = {"--reason", "-b", "-B", "--orphan"}


def _audit_git_argv(segment: str) -> list[str] | None:
    """``segment``'s git argv after the global options, or None when it is not a git call."""

    try:
        argv = shlex.split(segment, posix=True)
    except ValueError:
        argv = segment.split()
    while argv and "=" in argv[0] and not argv[0].startswith("-"):
        argv = argv[1:]  # VAR=value prefixes
    if not argv or argv[0] not in {"git", "git.exe"}:
        return None
    rest, index = argv[1:], 0
    while index < len(rest) and rest[index].startswith("-"):
        index += 2 if rest[index] in _GIT_GLOBAL else 1
    return rest[index:]


def _worktree_change(args: list[str], exit_code: int | None) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """``git worktree add|remove …``: the worktree row and the branch ``-b`` created, if any."""

    positional, branch, index = [], None, 1
    while index < len(args):
        token = args[index]
        if token in _WORKTREE_VALUE_OPTS and index + 1 < len(args):
            branch = args[index + 1] if token in {"-b", "-B", "--orphan"} else branch
            index += 2
            continue
        if not token.startswith("-"):
            positional.append(token)
        index += 1
    worktrees = [{"op": args[0], "path": positional[0], "exit_code": exit_code}] if positional else []
    branches = [{"op": "create", "name": branch, "exit_code": exit_code}] if branch else []
    return worktrees, branches


def _branch_changes(verb: str, args: list[str], exit_code: int | None) -> list[dict[str, Any]]:
    """``checkout -b`` / ``switch -c`` create a branch; ``branch -d|-D`` deletes them."""

    if verb in {"checkout", "switch"}:
        flags = {"-b", "-B"} if verb == "checkout" else {"-c", "-C"}
        return [{"op": "create", "name": args[index + 1], "exit_code": exit_code}
                for index, token in enumerate(args[:-1]) if token in flags]
    if verb == "branch" and args and args[0] in {"-d", "-D", "--delete"}:
        return [{"op": "delete", "name": name, "exit_code": exit_code} for name in args[1:] if not name.startswith("-")]
    return []


def _git_changes(command: str, exit_code: int | None) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """The ``(worktrees, branches)`` one terminal command created or removed."""

    worktrees: list[dict[str, Any]] = []
    branches: list[dict[str, Any]] = []
    for segment in _SEGMENT_SPLIT.split(command or ""):
        argv = _audit_git_argv(segment.strip())
        if not argv:
            continue
        verb, args = argv[0], argv[1:]
        if verb == "worktree" and args and args[0] in {"add", "remove"}:
            made, named = _worktree_change(args, exit_code)
            worktrees.extend(made)
            branches.extend(named)
        else:
            branches.extend(_branch_changes(verb, args, exit_code))
    return worktrees, branches


def _audit_tool_row(element: dict[str, Any]) -> dict[str, Any]:
    outcome = element.get("outcome") or element.get("status")
    return {
        "seq": element.get("seq"),
        "name": element.get("name"),
        "command": element.get("command") or None,
        "args": element.get("args") or None,
        "exit_code": element.get("exit_code"),
        "duration_ms": element.get("duration_ms"),
        "outcome": outcome,
        "timed_out": outcome == "timed_out",
    }


def _turn_wall_seconds(record: dict[str, Any]) -> float | None:
    for budget in (record.get("run_budget") or {}).get("budgets") or ():
        if isinstance(budget, dict) and budget.get("kind") == "wall":
            return budget.get("consumed")
    return None


def _price_usage(usage: dict[str, Any]) -> dict[str, Any] | None:
    if not usage.get("model"):
        return None
    try:
        from agent.usage_pricing import CanonicalUsage, estimate_usage_cost

        result = estimate_usage_cost(
            str(usage["model"]),
            CanonicalUsage(
                input_tokens=int(usage.get("input_tokens") or 0),
                output_tokens=int(usage.get("output_tokens") or 0),
                cache_read_tokens=int(usage.get("cache_read_tokens") or 0),
                cache_write_tokens=int(usage.get("cache_write_tokens") or 0),
                reasoning_tokens=int(usage.get("reasoning_tokens") or 0),
                request_count=int(usage.get("api_calls") or 1),
            ),
            provider=usage.get("provider"),
        )
    except Exception as exc:  # a price is a lookup; its failure is a stated unknown, never a refusal
        return {"usd": None, "status": "unknown", "label": f"pricing failed: {type(exc).__name__}"}
    amount = result.amount_usd
    return {"usd": None if amount is None else str(amount), "status": result.status, "label": result.label}


def _audit_turn_row(record: dict[str, Any], price: Callable[[dict[str, Any]], dict[str, Any] | None]) -> dict[str, Any]:
    from agent_runtime.turn_outcome import TURN_OUTCOME_KEY
    from agent_runtime.turn_usage import TURN_USAGE_KEY

    tools = [element for element in record.get("elements") or () if element.get("kind") == "tool"]
    worktrees: list[dict[str, Any]] = []
    branches: list[dict[str, Any]] = []
    for element in tools:
        if element.get("name") == "terminal":
            made, named = _git_changes(element.get("command") or "", element.get("exit_code"))
            worktrees.extend(made)
            branches.extend(named)
    outcome = record.get(TURN_OUTCOME_KEY) or {}
    usage = record.get(TURN_USAGE_KEY)
    return {
        "turn_id": record.get("turn_id"),
        "client_message_id": record.get("client_message_id"),
        "state": record.get("state"),
        "started_at": record.get("started_at"),
        "updated_at": record.get("updated_at"),
        "persona_instance_id": record.get("persona_instance_id"),
        "root_chat_session_id": record.get("root_chat_session_id"),
        "active_session_id": record.get("active_session_id"),
        "wall_seconds": _turn_wall_seconds(record),
        "tool_calls": [_audit_tool_row(element) for element in tools],
        "tool_ms": sum(int(element.get("duration_ms") or 0) for element in tools),
        "files_written": list(outcome.get("files") or ()),
        "tests": list(outcome.get("tests") or ()),
        "commits": list(outcome.get("commits") or ()),
        "worktrees": worktrees,
        "branches": branches,
        "usage": usage,
        "cost": price(usage) if isinstance(usage, dict) else None,
    }


def audit_namespace() -> dict[str, Any]:
    """The store that answers: namespace kind and id, store root, and this machine's install id."""

    from agent_runtime import paths
    from agent_runtime.gateway_identity import read_install_identity
    from agent_runtime.namespace import namespace_kind, namespace_stamp

    ns_id = namespace_stamp()
    store_root = paths.store_root()
    identity = read_install_identity(store_root)
    return {
        "kind": namespace_kind(ns_id) if ns_id else "base",
        "id": ns_id or "base",
        "store_root": str(store_root),
        "machine": {"install_id": identity.install_id, "display_name": identity.display_name,
                    "state": identity.state},
    }


def turn_audit(
    *,
    persona_instance_id: str | None = None,
    session_id: str | None = None,
    turn_id: str | None = None,
    limit: Any = TURN_AUDIT_LIMIT_DEFAULT,
    price: Callable[[dict[str, Any]], dict[str, Any] | None] = _price_usage,
) -> dict[str, Any]:
    """The audit row: ``ok``, ``namespace``, ``turns`` (newest first), ``count``, ``truncated``.

    One of ``persona_instance_id`` / ``session_id`` / ``turn_id`` is required; a session matches a
    record's root or active chat session id.
    """

    from agent_runtime.mission_chat_turns import all_mission_chat_turn_records

    wanted = {key: str(value).strip() for key, value in (
        ("persona_instance_id", persona_instance_id), ("session_id", session_id), ("turn_id", turn_id),
    ) if isinstance(value, str) and value.strip()}
    if not wanted:
        return {"ok": False, "error_kind": "invalid_request",
                "error": "name a persona_instance_id, a session_id or a turn_id"}
    try:
        cap = max(1, min(TURN_AUDIT_LIMIT_MAX, int(limit or TURN_AUDIT_LIMIT_DEFAULT)))
    except (TypeError, ValueError):
        cap = TURN_AUDIT_LIMIT_DEFAULT

    def matches(record: dict[str, Any]) -> bool:
        if "persona_instance_id" in wanted and record.get("persona_instance_id") != wanted["persona_instance_id"]:
            return False
        if "session_id" in wanted and wanted["session_id"] not in {
            record.get("root_chat_session_id"), record.get("active_session_id")
        }:
            return False
        return "turn_id" not in wanted or wanted["turn_id"] in {record.get("turn_id"), record.get("client_message_id")}

    records = sorted(
        (record for record in all_mission_chat_turn_records() if matches(record)),
        key=lambda item: str(item.get("started_at") or item.get("updated_at") or ""),
        reverse=True,
    )
    return {
        "ok": True,
        "capability_id": "mission.chat.turn_audit",
        "namespace": audit_namespace(),
        "filter": wanted,
        "count": min(len(records), cap),
        "total": len(records),
        "truncated": len(records) > cap,
        "turns": [_audit_turn_row(record, price) for record in records[:cap]],
    }
