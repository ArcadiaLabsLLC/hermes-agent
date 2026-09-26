"""The runtime config's vocabulary: ``AgentRuntimeConfig``, the bounds, the root-only key table.

Map: ``agent_runtime/config/__init__.py``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..runtime_config import RuntimeConfig

__layer__ = "models"


#: Bounds for ``agent_runtime.mission_chat.default_max_seconds``. Below the
#: floor the graceful checkpoint reserve (``turn_budget``: ``max(60s, 15%)``,
#: capped so 30 s of work survives) consumes the whole window and the turn can
#: run no tool at all; above the ceiling one conversational turn outlives a day.
#: (The ceiling was originally derived from ``mission_wall_clock_deadline_seconds``,
#: itself 86400; S57 removed that field as reader-less, so 86400 is now this
#: constant's own value rather than a reference to another knob.)
MISSION_CHAT_MIN_MAX_SECONDS = 30.0
MISSION_CHAT_MAX_MAX_SECONDS = 86_400.0

#: Bounds for ``agent_runtime.mission_chat.compaction_threshold_tokens`` when it
#: is enabled. The floor exists because a cap under ~16 k would compact a chat
#: root before its own turn-1 prefix fits (measured: 22.7 k for a qa turn on
#: 2026-08-09, of which ~9.3 k is tool schema that no compaction can remove), so
#: the lane would summarize on every turn and never converge. The ceiling is the
#: largest window this lane has seen; a cap above it can only be a no-op anyway,
#: because ``_apply_threshold_tokens_cap`` already clamps the cap to the model's
#: context length. Zero is NOT clamped into this window — it is the documented
#: "no lane cap" spelling and is honoured verbatim.
MISSION_CHAT_MIN_COMPACTION_TOKENS = 16_000
MISSION_CHAT_MAX_COMPACTION_TOKENS = 2_000_000

#: Hard ceiling for ``agent_runtime.mcp_admission.max_tool_calls_per_run``.
#: A per-run MCP call budget only bounds a looping agent while it is actually
#: reachable, so "effectively unlimited" must not be spellable in config — a
#: mistyped ``1000000`` clamps here instead of silently retiring the bound. The
#: value is far above any honest QA drill (the 6-row Stage C acceptance matrix
#: costs ~60 admitted calls) and far below a loop worth paying for.
MCP_ADMISSION_MAX_TOOL_CALLS_CEILING = 1_000


@dataclass(slots=True)
class AgentRuntimeConfig(RuntimeConfig):
    store_root: str | None = None
    head_agent_profile: str | None = None
    personas: dict[str, dict[str, Any]] = field(default_factory=dict)
    # Provenance of the resolved runtime default: which YAML key actually
    # supplied ``default_model`` / ``default_provider``. The top-level ``model:``
    # block is the surface ``hermes model`` / ``hermes status`` own and the user
    # treats as truth; ``agent_runtime.default_*`` is an explicit harness-wide
    # override (and, when absent, silence — the runtime follows the top-level
    # default). These labels let the launcher and ``hermes harness config show``
    # report which authority won without re-deriving it.
    default_model_source: str = "unset"
    default_provider_source: str = "unset"


#: Keys under ``agent_runtime`` that are ONLY ever read through the ROOT config,
#: paired with the reader that consumes each. ``"*"`` matches any persona id.
#:
#: Setting one of these in a PROFILE ``config.yaml`` is silently inert: the
#: reader resolves :func:`harness_root_config_path` and never looks at the
#: profile, so the operator's value is accepted by YAML, reported back by any
#: profile-aware surface, and ignored by the only code that acts on it.
#:
#: This is a REPEATED defect class, twice in three weeks, in both directions:
#:
#: * 2026-07-23 — the ruling lived in the ROOT and the reader used the profile,
#:   so ``chat_lane_restore_toolsets`` resolved off ``profiles/alice`` and the
#:   operator's root-config ruling was dead on arrival. Fixed by moving the
#:   READER to the root (that is why :func:`harness_root_config_path` exists).
#: * 2026-08-13 — the mirror image. ``read_model.delta_patches: true`` was
#:   written into ``profiles/base`` and ``profiles/alice`` while the reader
#:   correctly used the root, which carried no ``read_model`` block at all. The
#:   S7-A patch producer therefore stayed dark for its whole life: measured
#:   live, ONE field change on ONE persona instance shipped an 822,671-byte
#:   delta carrying an 864,241-byte full snapshot core, where the patch frame
#:   the lane was built for is 486 bytes. ``harness status`` reported
#:   ``delta_patches: true`` throughout, because status reads profile-aware.
#:
#:   2026-08-14 follow-up: a doctor row only helps an operator who RUNS the
#:   doctor, and the misplaced value had a WRITER — the Launcher installer's
#:   ``kMissionControlBaseSeedConfigYaml`` seeds ``delta_patches: true`` into the
#:   fresh ``base`` PROFILE — so every fresh install reproduced it. The lane's
#:   durability therefore does not depend on any file at all any more:
#:   ``read_model.delta_patches`` SHIPS on
#:   (``runtime_config.SHIPPED_DELTA_PATCHES``) and silence resolves to LIVE. A
#:   profile copy is still reported here, because it is still inert and still
#:   worth deleting — it just no longer decides whether the lane runs.
#:
#: Note ``read_model`` WAS split across both loaders and only the leaf was
#: root-only: ``read_model.enabled`` was read profile-aware (``snapshot.py``
#: consulted the passed cfg), while ``read_model.delta_patches`` is root-only.
#: So this list keys on LEAVES, never blocks — a block-level rule would have
#: raised a false positive on every profile that legitimately set ``enabled``.
#:
#: STAGE 6 (2026-08-22) removed the profile-aware half: ``read_model.enabled``
#: has no reader at all now, because the lane it gated is retired. The
#: leaf-keyed shape STAYS — not because ``read_model`` still needs it, but
#: because it is the correct shape for any block whose leaves resolve at
#: different scopes, and re-deriving that after the next such block appears is
#: how the original defect got in. ``delta_patches`` remains the one live leaf
#: and the one root-only row.
ROOT_ONLY_CONFIG_KEYS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("read_model", "delta_patches"), "agent_runtime.state_patches.delta_patches_enabled"),
    (("mcp_admission",), "agent_runtime.mcp_admission.admission_config"),
    (("personas", "*", "chat_lane_restore_toolsets"), "agent_runtime.config.chat_lane_restore_toolsets"),
    (("personas", "*", "workdir"), "agent_runtime.config.mission_chat_workdir"),
)


#: Typed issue code for a ``tool_permissions.default_mode`` the runtime cannot
#: honor. Same ``{code, subject, summary, fix_hint}`` row shape the envelope
#: grant issues and the MCP admission denials already emit.
TOOL_PERMISSION_DEFAULT_MODE_UNKNOWN = "tool_permission_default_mode_unknown"
