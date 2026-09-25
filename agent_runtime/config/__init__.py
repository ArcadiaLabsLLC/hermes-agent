"""The harness runtime config — ``agent_runtime.*`` in ``config.yaml`` (the package map, rule 16).

Entry points (what calls in):

* ``load_root_runtime_config`` — every harness-wide policy reader → ``loader``
  → ``sections`` (+ ``schema``).
* ``load_agent_runtime_config`` — the profile-aware load (personas, the model
  authority) → ``loader``.
* A per-turn knob such as ``mission_chat_default_max_seconds``
  (``chat_request``, ``profile_runner``) → ``knobs`` → ``loader`` →
  ``sections``.
* ``ensure_persisted_personas`` (``agent create``, ``snapshot``, the CLI)
  → ``roster`` (the store read) → ``persona_records`` (the pure merge) →
  ``loader``.
* ``harness doctor``'s two config sections
  (``describe_runtime_default_authority``, ``scan_misplaced_root_only_keys``) →
  ``loader``.

Modules, lowest layer first (no module imports one above it — W0-G6):

===============  ======  ======================================================
module           layer   owns
===============  ======  ======================================================
schema           models  ``AgentRuntimeConfig``, the bounds constants,
                         ``ROOT_ONLY_CONFIG_KEYS``,
                         ``TOOL_PERMISSION_DEFAULT_MODE_UNKNOWN``
sections         policy  the ten section parsers and the coercers they share
loader           policy  the two loads, the model-authority resolution, the two
                         provenance reports over the same files
knobs            policy  the per-turn ROOT-config readers and the two
                         ``resolve_*`` precedence chokepoints
persona_records  policy  persona records from config, the ``${roots.…}``
                         expansion, the merge with a roster passed IN
roster           stores  ``ensure_persisted_personas`` /
                         ``persona_skill_sources``: the persona-store read
===============  ======  ======================================================

The package door sits at ``stores`` because it re-exports ``roster``. So a
``policy`` module takes its config from the submodule (``config.loader``,
``config.knobs``, ``config.persona_records``), never from the package, and a
``policy`` module that needs the persona roster takes it as an ARGUMENT from
its ``stores`` caller (``persona_assignments.summary``'s ``roster=``; the two
identity lookups that read it live in ``persona_assignments.lookups``). Lane
Q-RUNTIME 2026-09-25 retired the ``persona_records`` → ``.store`` reach this
way.
"""

from __future__ import annotations

from agent_runtime.config.schema import (  # noqa: F401 — the vocabulary
    MCP_ADMISSION_MAX_TOOL_CALLS_CEILING,
    MISSION_CHAT_MAX_COMPACTION_TOKENS,
    MISSION_CHAT_MAX_MAX_SECONDS,
    MISSION_CHAT_MIN_COMPACTION_TOKENS,
    MISSION_CHAT_MIN_MAX_SECONDS,
    ROOT_ONLY_CONFIG_KEYS,
    TOOL_PERMISSION_DEFAULT_MODE_UNKNOWN,
    AgentRuntimeConfig,
)
from agent_runtime.config.sections import (  # noqa: F401 — THE section table + the test-pinned parsers
    SECTION_PARSERS,
    _event_log_config,
    _mcp_admission_config,
    _mission_chat_config,
    _read_model_config,
)
from agent_runtime.config.loader import (  # noqa: F401
    OVERRIDE_STATE_ABSENT,
    OVERRIDE_STATE_OVERRIDE_ONLY,
    OVERRIDE_STATE_REDUNDANT,
    OVERRIDE_STATE_SHADOWING,
    describe_runtime_default_authority,
    harness_root_config_path,
    load_agent_runtime_config,
    load_root_runtime_config,
    scan_misplaced_root_only_keys,
)
from agent_runtime.config.persona_records import (  # noqa: F401
    _expand_machine_root_tokens,
    merge_persisted_personas,
    persona_records_from_config,
    skill_sources_for,
)
from agent_runtime.config.roster import (  # noqa: F401
    ensure_persisted_personas,
    persona_skill_sources,
)
from agent_runtime.config.knobs import (  # noqa: F401
    chat_lane_restore_toolsets,
    mission_chat_clarify_token_binding,
    mission_chat_compaction_threshold_tokens,
    mission_chat_default_max_seconds,
    mission_chat_dispatch_max_concurrent,
    mission_chat_dispatch_max_seconds,
    mission_chat_dispatch_session_policy,
    mission_chat_workdir,
    resolve_mission_chat_dispatch_max_seconds,
    resolve_mission_chat_max_seconds,
)

__layer__ = "stores"
