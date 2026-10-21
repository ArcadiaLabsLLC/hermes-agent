"""Profile delegation defaults: the ``delegation`` section of one profile's config.yaml.

Profile state, served by the serve process for the route's own resolved home, never by a
child host. A read reports what the NEXT child gets (upstream's own knob getters, read
under that home); a write lands in the profile's config.yaml through upstream's
``save_config``. Wire: ``docs/agent-runtime-harness/planned/p10-agent-2026-10-19.md`` §1.2;
pinned by ``tests/agent_runtime/test_subagent_settings.py``.
"""
import hashlib
import hmac
import json
import math
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from agent_runtime import _upstream_doors as upstream
from .model import VERSION, Refusal, SubagentError, validate_request
from .references import references

__layer__ = "lanes"


@dataclass(frozen=True)
class Field:
    key: str
    kind: type  # str | float (any finite non-negative number) | bool
    default: object
    applies: str = "next_child"

    def accepts(self, value) -> bool:
        if self.kind is bool:
            return type(value) is bool
        if self.kind is str:
            return isinstance(value, str) and len(value) <= 200
        return (type(value) in (int, float) and math.isfinite(value) and value >= 0)

    def wire(self, value):
        """The codec never reads null for ``value``/``default``: an unset knob is its zero."""
        return value if value is not None and self.accepts(value) else None


# The launcher fixture's fourteen keys, in its order; defaults are upstream DEFAULT_CONFIG's.
DELEGATION_FIELDS = (
    Field("model", str, ""), Field("provider", str, ""), Field("reasoning_effort", str, ""),
    Field("max_iterations", float, 250), Field("max_concurrent_children", float, 10),
    Field("max_spawn_depth", float, 1), Field("orchestrator_enabled", bool, True),
    Field("child_timeout_seconds", float, 0), Field("worktree_isolation", bool, False),
    Field("independent_completions", bool, False, "new_session"),
    Field("oneshot_max_children", float, 2), Field("compression_threshold_tokens", float, 0),
    Field("surface_child_process_notifications", bool, False, "next_notification"),
    Field("inherit_mcp_toolsets", bool, True),
)
_BY_KEY = {field.key: field for field in DELEGATION_FIELDS}


@contextmanager
def _home_override(home: Path):
    """Read and write under ``home`` for this context only; never ``os.environ``."""
    from hermes_constants import reset_hermes_home_override, set_hermes_home_override

    token = set_hermes_home_override(home)
    try:
        yield
    finally:
        reset_hermes_home_override(token)


def _read_raw(reader, home: Path) -> dict:
    """An unreadable or unparseable profile config is refused, never read as empty."""
    try:
        return reader(home / "config.yaml")
    except Exception as exc:  # OSError, YAML errors: the file cannot be trusted
        raise SubagentError(Refusal.UNAVAILABLE) from exc


def _effective(home: Path) -> tuple[dict, dict]:
    """(configured, effective) under ``home``: the raw file and what the next child gets."""
    from hermes_cli.config import load_config_readonly, read_user_config_raw

    with _home_override(home):
        raw = _read_raw(read_user_config_raw, home).get("delegation")
        merged = load_config_readonly().get("delegation") or {}
        knobs = upstream.delegation_knobs()
        effective = {field.key: knobs[field.key]() if field.key in knobs else merged.get(field.key)
                     for field in DELEGATION_FIELDS}
    return (raw if isinstance(raw, dict) else {}), effective


def read_settings(home: Path) -> dict:
    from hermes_constants import profile_name_for_home

    home = Path(home)
    configured, effective = _effective(home)
    managed = upstream.delegation_managed_keys()
    fields = []
    for field in DELEGATION_FIELDS:
        mine = field.wire(configured.get(field.key))
        source = "managed" if field.key in managed else "profile" if mine is not None else "native_default"
        value = field.wire(effective[field.key])
        fields.append({"key": field.key, "value": field.default if value is None else value,
                       "configured": mine, "default": field.default, "writable": source != "managed",
                       "source": source, "applies": field.applies})
    revision = hashlib.sha256(json.dumps(fields, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return {"scope": "profile_defaults", "profile_label": profile_name_for_home(home) or home.name,
            "revision": revision, "advanced_route": False, "fields": fields}


def write_settings(home: Path, expected_revision: str, changes: dict) -> dict:
    from hermes_cli.config import is_managed, read_user_config_raw, save_config

    home = Path(home)
    if not changes or any(key not in _BY_KEY or (value is not None and not _BY_KEY[key].accepts(value))
                          for key, value in changes.items()):
        raise SubagentError(Refusal.INVALID)
    current = read_settings(home)
    if not hmac.compare_digest(current["revision"], expected_revision):
        raise SubagentError(Refusal.STALE)
    writable = {field["key"]: field["writable"] for field in current["fields"]}
    if is_managed() or not all(writable[key] for key in changes):
        raise SubagentError(Refusal.MANAGED)
    with _home_override(home):
        config = _read_raw(read_user_config_raw, home)
        section = config.get("delegation")
        section = dict(section) if isinstance(section, dict) else {}
        for key, value in changes.items():
            if value is None:
                section.pop(key, None)
            else:
                section[key] = value
        config["delegation"] = section
        # A value equal to its default is still the operator's explicit choice.
        save_config(config, preserve_keys={("delegation", key) for key in section})
    return read_settings(home)


def inspect_settings(operation: str, params: dict, *, owner: tuple, home: Path) -> dict:
    """``settings`` / ``settings.set`` for one already-authorized route and its home."""
    validate_request(operation, params)
    generation = references.require_generation(("settings", owner), params.get("expected_generation"))
    if operation == "settings.set":
        data = write_settings(home, params["expected_revision"], params["changes"])
    else:
        data = read_settings(home)
    return {"version": VERSION, "generation": generation, "observed_at": time.time(), **data}
