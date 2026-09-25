"""Load ``agent_runtime`` config (profile-aware or ROOT), resolve the model authority, and report provenance.

Map: ``agent_runtime/config/__init__.py``.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from hermes_constants import get_config_path
from ..personas import persona_id_aliases
from ..redaction_mode import normalize_redaction_mode
from ..serde import optional_str, positive_int
from .schema import ROOT_ONLY_CONFIG_KEYS, AgentRuntimeConfig
from .sections import SECTION_PARSERS

__layer__ = "policy"

#: ``_override_state``'s words: how an ``agent_runtime.default_*`` override
#: stands against the top-level ``model.*`` authority. They ride the doctor's
#: JSON and the launcher's Model Authority panel as strings, so they are named
#: constants beside their producer (no Enum); the readers compare by name.
OVERRIDE_STATE_ABSENT = "absent"
OVERRIDE_STATE_OVERRIDE_ONLY = "override_only"
OVERRIDE_STATE_REDUNDANT = "redundant"
OVERRIDE_STATE_SHADOWING = "shadowing"


def _top_level_model_authority(top: dict[str, Any]) -> tuple[str | None, str | None]:
    """Read the top-level ``model:`` block — the authority the user sets via
    ``hermes model`` and reads back via ``hermes status``.

    Tolerates ``model:`` as a mapping (``default``/``name`` + ``provider``) or as
    a bare string model id, mirroring ``hermes_cli/status.py``'s tolerance.
    """
    model_block = top.get("model")
    if isinstance(model_block, dict):
        model = optional_str(model_block.get("default")) or optional_str(model_block.get("name"))
        return (model, optional_str(model_block.get("provider")))
    if isinstance(model_block, str):
        return (optional_str(model_block), None)
    return (None, None)


def _resolve_default_authority(
    override_value: Any,
    top_value: str | None,
    override_source: str,
    top_source: str,
) -> tuple[str | None, str]:
    """Resolve a runtime default: an explicit ``agent_runtime.*`` override wins;
    otherwise the top-level ``model.*`` authority; otherwise unset."""
    override = optional_str(override_value)
    if override is not None:
        return (override, override_source)
    if top_value is not None:
        return (top_value, top_source)
    return (None, "unset")


def load_agent_runtime_config(config_path: Path | None = None) -> AgentRuntimeConfig:
    from ..parse_cache import cached_yaml_file

    config_path = config_path or get_config_path()
    # mtime-cached parse: this is called many times per snapshot build (and across
    # the runtime) and was re-parsing the full config.yaml each time.
    loaded = cached_yaml_file(config_path, default=None)
    top = loaded if isinstance(loaded, dict) else {}
    raw = top.get("agent_runtime", {}) or {}
    # Single runtime-default authority: the harness follows the top-level
    # ``model.default`` the user sets, unless ``agent_runtime.default_*`` is
    # explicitly pinned as a harness-wide override.
    top_model, top_provider = _top_level_model_authority(top)
    resolved_model, default_model_source = _resolve_default_authority(
        raw.get("default_model"), top_model, "agent_runtime.default_model", "model.default"
    )
    resolved_provider, default_provider_source = _resolve_default_authority(
        raw.get("default_provider"), top_provider, "agent_runtime.default_provider", "model.provider"
    )
    sections = {name: parse(raw.get(name) or {}) for name, parse in SECTION_PARSERS.items()}
    cfg = AgentRuntimeConfig(
        schema_version=int(raw.get("schema_version", 1)),
        store_root=raw.get("store_root"),
        head_agent_profile=raw.get("head_agent_profile") or raw.get("head_profile"),
        default_provider=resolved_provider,
        default_model=resolved_model,
        default_api_mode=raw.get("default_api_mode", "codex_responses"),
        redaction_mode=normalize_redaction_mode(raw.get("redaction_mode") or os.environ.get("HERMES_REDACTION_MODE", "strict")),
        # S57 removed 29 load lines here — the whole ``daemon_*`` family, the four
        # ``live_run_*`` budgets, the four ``liveness_*`` knobs, the three
        # ``artifact_storage_*`` watermarks, the two mission ceilings, the two
        # neko caps, ``heartbeat_ttl_seconds``, ``max_actions_per_tick``,
        # ``root_node_mode``, ``preferred_goal_execution_mode``,
        # ``scope_wait_deadline_seconds``, ``run_lease_seconds``,
        # ``tool_wait_timeout_seconds``, ``child_progress_min_interval_seconds``
        # and ``deploy_timeout_seconds``. None had a production reader (S56's gate
        # measured it; S57 re-verified each by hand, AST + string form). A yaml
        # that still sets any of them now loads and is IGNORED — ``raw`` is read
        # by ``.get`` per key, so an unknown key is simply never consulted.
        lock_acquire_timeout_seconds=positive_int(raw.get("lock_acquire_timeout_seconds"), default=15),
        **sections,
        personas=raw.get("personas", {}) or {},
        default_model_source=default_model_source,
        default_provider_source=default_provider_source,
    )
    return cfg


def _override_state(override: str | None, top_value: str | None) -> str:
    """Classify an ``agent_runtime.default_*`` value against the top-level authority.

    - ``absent``: no override (the healthy state — the runtime follows the user default).
    - ``override_only``: override set but no top-level authority to compare against.
    - ``redundant``: override equals the top-level default (an unmaintained duplicate;
      recommend removal so the single authority stays single).
    - ``shadowing``: override diverges from the top-level default (the stale-pin bug —
      agents silently run something other than what the user set).
    """
    if override is None:
        return OVERRIDE_STATE_ABSENT
    if top_value is None:
        return OVERRIDE_STATE_OVERRIDE_ONLY
    return OVERRIDE_STATE_REDUNDANT if override == top_value else OVERRIDE_STATE_SHADOWING


def describe_runtime_default_authority(config_path: Path | None = None) -> dict[str, Any]:
    """Pure, redaction-safe provenance report comparing the top-level ``model:``
    authority against any ``agent_runtime.*`` override and per-persona pins.

    Single source of truth for the migrations warning and the harness-doctor
    ``model_authority`` block, so the "shadowing vs redundant vs stale pin"
    classification is never re-derived divergently.

    ``persona_pins[].persona_id`` is the key AS PERSISTED. Where that key has a
    historical spelling, ``persona_id_alias`` carries it (``None`` otherwise).
    """
    from ..parse_cache import cached_yaml_file

    config_path = config_path or get_config_path()
    loaded = cached_yaml_file(config_path, default=None)
    top = loaded if isinstance(loaded, dict) else {}
    raw = top.get("agent_runtime", {}) or {}
    top_model, top_provider = _top_level_model_authority(top)
    override_model = optional_str(raw.get("default_model"))
    override_provider = optional_str(raw.get("default_provider"))
    resolved_model, model_source = _resolve_default_authority(
        raw.get("default_model"), top_model, "agent_runtime.default_model", "model.default"
    )
    resolved_provider, provider_source = _resolve_default_authority(
        raw.get("default_provider"), top_provider, "agent_runtime.default_provider", "model.provider"
    )

    persona_pins: list[dict[str, Any]] = []
    personas = raw.get("personas", {}) or {}
    if isinstance(personas, dict):
        for pid, overrides in personas.items():
            if not isinstance(overrides, dict):
                continue
            pin_model = optional_str(overrides.get("model"))
            pin_provider = optional_str(overrides.get("provider"))
            if pin_model is None and pin_provider is None:
                continue
            # S66: report what is ACTUALLY IN THE CONFIG. This used to rewrite a
            # pin persisted under ``alice_supervisor`` to ``neko_supervisor``,
            # so an operator reading a PROVENANCE report was told a key their
            # file does not contain — and could not find it by searching for the
            # name the report gave them. The alias is still surfaced, but as a
            # separate, clearly-labelled field rather than by falsifying the
            # first one.
            # The historical spelling (personas.persona_id_aliases) is reported
            # ALONGSIDE the persisted key, never substituted for it.
            alias = next(iter(persona_id_aliases(pid)), None)
            persona_pins.append({
                "persona_id": pid,
                "persona_id_alias": alias,
                "model": pin_model,
                "provider": pin_provider,
                # None when the pin sets no model (provider-only pin); otherwise
                # whether the pin duplicates the resolved runtime default (redundant).
                "matches_runtime_default": (pin_model == resolved_model) if pin_model is not None else None,
                "provider_pinned_without_model": pin_provider is not None and pin_model is None,
            })

    return {
        "resolved": {
            "model": resolved_model,
            "provider": resolved_provider,
            "model_source": model_source,
            "provider_source": provider_source,
        },
        "top_level": {"model": top_model, "provider": top_provider},
        "harness_override": {
            "model": override_model,
            "provider": override_provider,
            "model_state": _override_state(override_model, top_model),
            "provider_state": _override_state(override_provider, top_provider),
        },
        "persona_pins": persona_pins,
    }


def harness_root_config_path() -> Path:
    """The harness-global ``config.yaml`` under the Hermes ROOT home.

    Harness-wide operator policy must resolve against the ROOT config no
    matter which profile is sticky-active. The CLI bootstrap redirects a bare
    invocation into the active profile's home
    (``hermes_cli.main._apply_profile_override``), so ``get_config_path()`` —
    and therefore ``load_agent_runtime_config()`` with no argument — silently
    reads THAT profile's ``config.yaml``. Live proof 2026-07-23: with
    ``alice`` sticky-active, the mission-chat lane resolved
    ``chat_lane_restore_toolsets`` against ``profiles/alice/config.yaml``,
    so the operator's root-config ruling (Neko ``file`` restore, 2026-07-18)
    was dead on arrival. Policy readers that must be immune to that redirect
    load through this path instead of ``get_config_path()``.
    """

    from hermes_constants import get_default_hermes_root

    return get_default_hermes_root() / "config.yaml"


def load_root_runtime_config() -> AgentRuntimeConfig:
    """Load the harness-global runtime config from the ROOT ``config.yaml``.

    Convenience for harness-wide policy readers that must be immune to the CLI
    profile redirect. A bare invocation runs
    ``hermes_cli.main._apply_profile_override`` at import time, which reads
    ``<root>/active_profile`` and points ``HERMES_HOME`` at
    ``<root>/profiles/<name>``. From that point ``get_config_path()`` — and so
    ``load_agent_runtime_config()`` with no argument — silently resolves against
    THAT profile's ``config.yaml``, letting whichever profile is sticky-active
    shadow harness-global operator policy (live proof 2026-07-23: with ``alice``
    active, the mission-chat lane resolved ``chat_lane_restore_toolsets`` off
    ``profiles/alice/config.yaml``, so the root-config ruling was dead on
    arrival — see :func:`harness_root_config_path`).

    Policy that is a property of the harness as a whole — not of any one
    profile — loads through this instead of the bare
    ``load_agent_runtime_config()``. Per-profile facts (``personas``, the
    ``default_model`` / ``default_provider`` / ``default_api_mode`` resolution,
    skills) must NOT use this; they stay on ``load_agent_runtime_config()`` so
    the active profile's own overrides apply.
    """

    return load_agent_runtime_config(harness_root_config_path())


def _profile_config_paths() -> list[Path]:
    """Every ``profiles/<name>/config.yaml`` under the Hermes root.

    Returns ``[]`` when the profiles directory cannot be listed — the caller
    must treat that as "could not examine", never as "none found".
    """

    from hermes_constants import get_default_hermes_root

    try:
        profiles = get_default_hermes_root() / "profiles"
        return sorted(
            entry / "config.yaml"
            for entry in profiles.iterdir()
            if entry.is_dir() and (entry / "config.yaml").is_file()
        )
    except OSError:
        return []


def _key_present(raw: dict[str, Any], path: tuple[str, ...]) -> list[tuple[str, ...]]:
    """Concrete key paths PRESENT in ``raw`` matching ``path`` (``*`` = any key).

    Presence, not truthiness: a profile that omits ``delta_patches`` parses
    identically to one that sets it ``false``, so a value check could not tell
    an operator's inert instruction from an absent one.
    """

    if not path:
        return [()]
    head, rest = path[0], path[1:]
    if not isinstance(raw, dict):
        return []
    if head == "*":
        found: list[tuple[str, ...]] = []
        for key, value in raw.items():
            for tail in _key_present(value, rest):
                found.append((str(key),) + tail)
        return found
    if head not in raw:
        return []
    return [(head,) + tail for tail in _key_present(raw[head], rest)]


def scan_misplaced_root_only_keys() -> dict[str, Any]:
    """Root-only keys that an operator has set in a PROFILE config, where they
    are inert.

    Returns ``{"rows": [...], "scope": {...}}``. Each row names the profile, the
    full dotted key, and the reader that will never see it — enough to fix
    without re-deriving the analysis. An empty ``rows`` means "examined and none
    found"; the caller distinguishes "could not examine" by catching the
    exception this may raise. ``scope`` is the denominator those rows have to be
    read against — see the comment on the return statement.

    ``set_in_root`` separates the two cases, which are NOT the same defect and
    must not be reported at one severity:

    * ``False`` — the key is set ONLY in a profile, so the operator's value is
      being IGNORED. This is the 2026-08-13 shape and it is actionable.
    * ``True`` — the root also carries it, so the live value is correct and the
      profile copy is a redundant leftover. Reporting this at defect severity
      would leave ``harness doctor`` permanently red for a cosmetic duplicate,
      which is the "a gate that is always red is not a gate" failure.
    """

    from ..parse_cache import cached_yaml_file

    root_path = harness_root_config_path()
    root_loaded = cached_yaml_file(root_path, default=None)
    root_raw = (
        (root_loaded or {}).get("agent_runtime") or {} if isinstance(root_loaded, dict) else {}
    )

    rows: list[dict[str, Any]] = []
    profiles_examined = 0
    for config_path in _profile_config_paths():
        loaded = cached_yaml_file(config_path, default=None)
        raw = (loaded or {}).get("agent_runtime") or {} if isinstance(loaded, dict) else {}
        if not isinstance(raw, dict):
            profiles_examined += 1
            continue
        for key_path, reader in ROOT_ONLY_CONFIG_KEYS:
            for concrete in _key_present(raw, key_path):
                # Presence of the SAME concrete path in the root, not merely of
                # the pattern: a root that pins ``personas.neko.workdir`` does
                # not make a profile's ``personas.qa.workdir`` effective.
                rows.append(
                    {
                        "profile": config_path.parent.name,
                        "config_path": str(config_path),
                        "key": "agent_runtime." + ".".join(concrete),
                        "read_only_by": reader,
                        "root_config_path": str(root_path),
                        "set_in_root": bool(_key_present(root_raw, concrete)),
                    }
                )
        profiles_examined += 1
    return {
        "rows": rows,
        # The DENOMINATOR, from this same walk (w12/m5). A row is
        # (profile x concrete key) and two of the four patterns are per-persona,
        # so the count scales with how many profiles and personas a machine HAS.
        # The census that raised this read 9 on one store against 2 on another
        # and called it a 4.5x asymmetry; without the scope beside it, a raw
        # count comparison across two machines compares their inventories. Read
        # from the same iteration as the rows on purpose: a scope derived from a
        # second walk is a second authority that can disagree with the numerator
        # it exists to explain.
        "scope": {
            "profiles_examined": profiles_examined,
            "root_only_key_patterns": len(ROOT_ONLY_CONFIG_KEYS),
        },
    }
