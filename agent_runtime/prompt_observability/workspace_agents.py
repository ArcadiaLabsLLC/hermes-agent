"""The workspace ``AGENTS.md`` read: bounded, typed, with the reason a read did not happen.

Separate because the chat lane's turn context reads it directly, without the
rest of the observability build.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from .context_files import WorkspaceAgentsContext, _token_estimate_from_bytes
from .safe_views import _safe_preview

__layer__ = "stores"
__all__ = [
    "MAX_WORKSPACE_AGENTS_BYTES",
    "load_workspace_agents_context",
]


MAX_WORKSPACE_AGENTS_BYTES = 128 * 1024


def load_workspace_agents_context(value: str | None) -> WorkspaceAgentsContext | None:
    """Load a Launcher-selected ``AGENTS.md`` without changing process CWD.

    Invalid, missing, unreadable, and oversized files produce an honest receipt
    and no injected content. Mission chat remains available in every case.
    """

    raw_value = str(value or "").strip()
    if not raw_value:
        return None
    requested = Path(raw_value).expanduser()
    receipt: dict[str, Any] = {
        "path": str(requested),
        "name": requested.name or "AGENTS.md",
        "kind": "workspace_context",
        "source": "workspace",
        "included": False,
        "status": "invalid_path",
    }
    if not requested.is_absolute():
        return WorkspaceAgentsContext(content=None, receipt=receipt)
    if requested.name.lower() != "agents.md":
        receipt["status"] = "invalid_name"
        return WorkspaceAgentsContext(content=None, receipt=receipt)
    try:
        resolved = requested.resolve(strict=True)
    except (OSError, RuntimeError):
        receipt["status"] = "missing"
        return WorkspaceAgentsContext(content=None, receipt=receipt)
    receipt["path"] = str(resolved)
    if not resolved.is_file():
        receipt["status"] = "not_a_file"
        return WorkspaceAgentsContext(content=None, receipt=receipt)
    try:
        size = resolved.stat().st_size
    except OSError as exc:
        receipt.update(status="unreadable", error=type(exc).__name__)
        return WorkspaceAgentsContext(content=None, receipt=receipt)
    receipt["bytes"] = size
    if size > MAX_WORKSPACE_AGENTS_BYTES:
        receipt.update(status="too_large", max_bytes=MAX_WORKSPACE_AGENTS_BYTES)
        return WorkspaceAgentsContext(content=None, receipt=receipt)
    try:
        raw = resolved.read_bytes()
    except OSError as exc:
        receipt.update(status="unreadable", error=type(exc).__name__)
        return WorkspaceAgentsContext(content=None, receipt=receipt)
    content = raw.decode("utf-8", errors="replace")
    receipt.update(
        included=True,
        status="loaded",
        sha256=hashlib.sha256(raw).hexdigest().upper(),
        bytes=len(raw),
        preview=_safe_preview(content),
    )
    estimate = _token_estimate_from_bytes(len(raw))
    if estimate is not None:
        receipt["token_estimate"] = estimate
    return WorkspaceAgentsContext(content=content, receipt=receipt)
