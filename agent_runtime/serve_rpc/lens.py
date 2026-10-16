"""``runtime.lens.*`` — Eternia Lens on the method lane (plan ``eternia-lens-in-hermes.md`` §3).

The one-import seam the plan names: Lens's verbs register here, in fork-owned
``serve_rpc/``, so no upstream file is edited. Tier ``console``: a monitor names
the operator's own systems.

Stage L0 lands ``runtime.lens.list`` only. Until the store lands (L1) there are no
monitors to list; the result says which feed kinds this build can poll, so a
caller can tell "nothing configured" from "this build cannot poll that".
"""

from __future__ import annotations

from typing import Any

from agent_runtime.call_authorization import TIER_CONSOLE
from agent_runtime.serve_rpc.protocol import RpcContext, ok
from agent_runtime.serve_rpc.registry import method

__layer__ = "lanes"

__all__ = ["_runtime_lens_list"]


def _feed_kinds() -> dict[str, str]:
    from agent_runtime.lens.feed import AVAILABLE_FEED_KINDS, FeedKind

    return {kind.value: ("available" if kind in AVAILABLE_FEED_KINDS else "unavailable") for kind in FeedKind}


@method("runtime.lens.list", tier=TIER_CONSOLE)
def _runtime_lens_list(rid: Any, params: dict, context: RpcContext | None = None) -> dict:
    """Params: none. Result: ``{monitors: [], feed_kinds: {kind: available|unavailable}}``."""

    return ok(rid, {"monitors": [], "feed_kinds": _feed_kinds()})
