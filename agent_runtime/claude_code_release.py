"""The current Claude Code release, for a device that has no ``claude`` command to ask.

A Claude subscription (OAuth) request carries a Claude Code identity, whose version upstream reads
from ``claude --version`` and otherwise takes from ``agent/anthropic_adapter.py``'s
``_CLAUDE_CODE_VERSION_FALLBACK`` (``2.1.74``, set 2026-03-17). Anthropic refuses an identity too far
behind the current release — on the owner's phone every Claude Opus 5.5 turn was refused
``HTTP 400: Claude Code 2.1.74 does not support this model; version 2.1.280 or newer is required``
(RT-FU-A-CLAUDE-SUBSCRIPTION-TURN-ON-A-PHONE-REPORTS-A-CURRENT-CLAUDE-CODE-VERSION). A phone never has
the command, so the phone's stand-in for that probe (``agent_runtime/spawn_stand_ins.py``) asks here.

The answer, in order:

1. a release read within :data:`MAX_AGE` and kept on disk (``<hermes home>/cache/claude_code_release.json``);
2. else the published release, read now from the npm registry's ``latest`` tag of
   ``@anthropic-ai/claude-code`` (Claude Code's own distribution channel) with a short timeout, and kept;
3. else the last release kept, however old (offline, or the registry did not answer);
4. else the caller's fallback.

Called once per process (upstream caches the version for the process), on the first subscription
request; never raises. No user data leaves the device: the request is a public, anonymous read.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
import urllib.request
from pathlib import Path
from typing import Any, Callable

__layer__ = "stores"
__all__ = ["MAX_AGE", "RELEASE_URL", "current_claude_code_version"]

#: Claude Code's published release (the npm registry's ``latest`` dist-tag; ``{"version": "2.1.280", …}``).
RELEASE_URL = "https://registry.npmjs.org/@anthropic-ai/claude-code/latest"
#: How long a release read stays current before it is read again.
MAX_AGE = 24 * 60 * 60
_TIMEOUT = 4.0
_VERSION = re.compile(r"^\d+\.\d+\.\d+$")
_log = logging.getLogger(__name__)

#: The test seam: ``urllib.request.urlopen``'s shape.
urlopen = urllib.request.urlopen


def _store() -> Path:
    from hermes_constants import get_process_hermes_home

    return Path(get_process_hermes_home()) / "cache" / "claude_code_release.json"


def _valid(version: Any) -> str | None:
    text = version.strip() if isinstance(version, str) else ""
    return text if _VERSION.match(text) else None


def _kept_release(path: Path) -> tuple[str, float] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        version, at = _valid(data.get("version")), float(data.get("read_at"))
    except Exception:  # health: allow BLE001 -- a missing or damaged record is no record
        return None
    return (version, at) if version else None


def _keep_release(path: Path, version: str, at: float) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps({"version": version, "read_at": at}), encoding="utf-8")
        os.replace(tmp, path)
    except OSError as exc:  # the answer stands; it is read again next process
        _log.debug("claude code release not kept: %s", type(exc).__name__)


def _published() -> str | None:
    try:
        request = urllib.request.Request(RELEASE_URL, headers={"Accept": "application/json"})
        with urlopen(request, timeout=_TIMEOUT) as response:
            return _valid(json.loads(response.read().decode("utf-8")).get("version"))
    except Exception as exc:  # health: allow BLE001 -- offline or refused: the kept release answers
        _log.info("claude code release not read: %s", type(exc).__name__)
        return None


def current_claude_code_version(fallback: str, *, now: Callable[[], float] = time.time,
                                store: Path | None = None) -> str:
    """The Claude Code version a subscription request names where no ``claude`` command exists."""

    path = store or _store()
    kept = _kept_release(path)
    if kept is not None and 0 <= now() - kept[1] < MAX_AGE:
        return kept[0]
    published = _published()
    if published is not None:
        _keep_release(path, published, now())
        return published
    return kept[0] if kept is not None else fallback
