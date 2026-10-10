"""The harness's process-env defaults, applied where the fork composes a process.

They used to be written by the eternia-harness plugin's ``register()``, so every plugin
discovery — at boot or lazily inside an upstream path such as ``profiles.describe`` —
leaked them into whatever process it ran in (v0216 plan §2). Plugin code writes no
process env; the serve and the conversation-worker composer apply this table instead,
and children inherit it. The operator's own value always wins (``setdefault``).
"""

from __future__ import annotations

import os
from collections.abc import Mapping, MutableMapping

__layer__ = "policy"

#: The harness's kanban claim lifetime. Long supervisor-style cards can spend more than
#: upstream's 15 minutes inside one external call before they can ``kanban_heartbeat``.
KANBAN_CLAIM_TTL_SECONDS = 45 * 60

HARNESS_PROCESS_ENV_DEFAULTS: Mapping[str, str] = {
    # Upstream reads it for every claim AND the heartbeat extension.
    "HERMES_KANBAN_CLAIM_TTL_SECONDS": str(KANBAN_CLAIM_TTL_SECONDS),
    # Upstream's ``hermes_cli.venv_sync`` skips its sync-and-relaunch under it, so a
    # harness process never mutates or restarts the running venv on its own; ``0`` is the
    # opt-out (owner 2026-09-29: the env stays).
    "HERMES_DISABLE_LAZY_INSTALLS": "1",
}


def apply_harness_process_env_defaults(
    environ: MutableMapping[str, str] | None = None,
) -> tuple[str, ...]:
    """``setdefault`` each default into *environ* (``os.environ`` when omitted).

    Returns the keys it wrote; a key the caller already set is left alone.
    """
    target = os.environ if environ is None else environ
    written = []
    for key, value in HARNESS_PROCESS_ENV_DEFAULTS.items():
        if key not in target:
            target[key] = value
            written.append(key)
    return tuple(written)
