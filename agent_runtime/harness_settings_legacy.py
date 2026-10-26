"""Retire the legacy top-level ``remote_gateway.*`` / ``charsheet.*`` blocks — move, delete and report.

RT-RETIRE-LEGACY-TOP-LEVEL (ruled go 2026-10-25: the installed Launcher writes
``plugins.entries.eternia-harness.settings.*`` since 290449df44). The one reader,
``agent_runtime.harness_settings``, no longer falls back to the old blocks; this is
the one chokepoint that makes the disk agree. For each config file (root and every
profile) and each retired ``(block, key)``:

* the new path absent -> the old value is MOVED there (an operator's LAN listener is
  never switched off by the retirement);
* then the old key is DELETED, and its block too once it is empty;
* every move and delete is logged at WARNING and returned in the report.

Round-trip YAML (``utils.atomic_roundtrip_yaml_update``), so comments, order and the
file's other keys survive. Idempotent — a file without the blocks is only read —
and fail-open per file, like ``persona_toolsets_migration``.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from .harness_settings import SETTINGS_PATH

__layer__ = "stores"
__all__ = ["RETIRED_KEYS", "retire_legacy_harness_blocks"]

logger = logging.getLogger(__name__)

#: setting name -> the retired top-level ``(block, key)`` it used to be read from.
RETIRED_KEYS: dict[str, tuple[str, str]] = {
    "remote_gateway_listen": ("remote_gateway", "listen"),
    "remote_gateway_port": ("remote_gateway", "port"),
    "charsheet_provider_timeout_seconds": ("charsheet", "provider_timeout_seconds"),
}

_BLOCKS = frozenset(block for block, _key in RETIRED_KEYS.values())


def _settings(loaded: Any) -> Any:
    node = loaded
    for segment in SETTINGS_PATH:
        node = node.get(segment) if isinstance(node, dict) else None
    return node


def _retire_in(path: Path) -> list[dict[str, Any]]:
    from utils import atomic_roundtrip_yaml_update

    from . import yaml_io

    text = path.read_text(encoding="utf-8")
    if not any(block in text for block in _BLOCKS):  # the common case: one read, no parse
        return []
    loaded = yaml_io.load(text)
    if not isinstance(loaded, dict):
        return []
    settings = _settings(loaded)
    done: list[dict[str, Any]] = []
    for name, (block, key) in RETIRED_KEYS.items():
        body = loaded.get(block)
        if not isinstance(body, dict) or key not in body:
            continue
        value = body[key]
        moved = value is not None and not (isinstance(settings, dict) and name in settings)
        if moved:
            atomic_roundtrip_yaml_update(path, ".".join((*SETTINGS_PATH, name)), value)
        atomic_roundtrip_yaml_update(path, f"{block}.{key}", None)
        done.append({"path": str(path), "key": f"{block}.{key}", "moved_to": name if moved else None})
        logger.warning("harness_legacy_key_retired path=%s key=%s.%s moved_to=%s",
                       path, block, key, name if moved else None)
    for block in _BLOCKS:
        reloaded = yaml_io.load(path.read_text(encoding="utf-8"))
        if isinstance(reloaded, dict) and reloaded.get(block) in ({}, None) and block in reloaded:
            atomic_roundtrip_yaml_update(path, block, None)
    return done


def retire_legacy_harness_blocks(hermes_root: Path | None = None) -> dict[str, Any]:
    """Move-then-delete the retired blocks in the root and every profile ``config.yaml``."""

    from hermes_constants import get_default_hermes_root

    from .persona_toolsets_migration import hermes_config_files

    root = Path(hermes_root) if hermes_root is not None else get_default_hermes_root()
    retired: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    for path in hermes_config_files(root):
        try:
            retired.extend(_retire_in(path))
        except Exception as exc:
            errors.append({"path": str(path), "error": type(exc).__name__})
            logger.warning("harness_legacy_key_retire_failed path=%s error=%s", path, type(exc).__name__)
    return {"retired": retired, "errors": errors}
