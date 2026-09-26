from __future__ import annotations

from typing import Any

from .config.schema import ALLOWED, OBSERVE, STRICT, normalize_redaction_mode


def redaction_mode(config: Any | None = None) -> str:
    if config is None:
        try:
            from .config import load_root_runtime_config

            config = load_root_runtime_config()
        except Exception:
            return STRICT
    return normalize_redaction_mode(getattr(config, "redaction_mode", STRICT))


def redaction_observe_enabled(config: Any | None = None) -> bool:
    return redaction_mode(config) == OBSERVE
