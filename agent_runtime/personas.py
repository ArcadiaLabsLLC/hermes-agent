from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from enum import StrEnum

from .models import AgentPersona

__layer__ = "models"


class AgentRole(StrEnum):
    """RETIRED RESIDUE, deliberately kept. Read this before adding a member.

    One member, and that member (``pm``) is mothballed — see
    ``persona_lifecycle.MOTHBALLED_ROLE_TOKENS``, the set that actually
    enforces it. So this is not a live taxonomy of roles: roles are DATA in
    this runtime, S61/S64 made profile/persona declarations the sole capability
    authority, and ``coerce_agent_role`` returns a plain ``str`` for every role
    a persona really carries today. It survives because ``docs/agent-runtime-
    harness/archive/2026-08-22-pre-consolidation/02-execution-engine.md`` still names it and because the legacy
    ``pm`` spelling has to keep resolving on persisted rows — not because a
    role belongs here.
    """

    PM = "pm"


class AutonomyLevel(StrEnum):
    PROPOSE_ONLY = "propose_only"
    APPLY_WITH_REVIEW = "apply_with_review"
    AUTONOMOUS = "autonomous"


# Retired roles/personas are single-sourced in ``persona_lifecycle`` as
# ``MOTHBALLED_ROLE_TOKENS`` / ``MOTHBALLED_PERSONA_IDS``, which
# ``is_runtime_persona`` actually reads. A ``MOTHBALLED_ROLES`` frozenset lived
# here too, saying it existed so nothing would hand-roll ``role == "pm"`` — with
# zero readers, while the module IMPORTED the two live sets and used neither.
# A third spelling of one fact does not prevent a fourth; the reader does.


# Synthetic operator-channel personas built from a raw Hermes profile carry the
# "profile" role sentinel (see ``hermes_cli.harness._persona_by_id``). They are not
# a typed mission slot, so it is not a real ``AgentRole`` — passing it straight into
# ``AgentRole(...)`` raises ``'profile' is not a valid AgentRole`` and kills the whole
# operator chat turn. Unknown roles remain data and ``validate_toolsets`` applies
# no role-specific ceiling.
PROFILE_ROLE_SENTINEL = "profile"

#: Historical persona-id spellings, BOTH directions: a key persisted under one
#: spelling is also consulted (never substituted) under the other. The one
#: owner of the ``alice_supervisor`` <-> ``neko_supervisor`` alias.
_PERSONA_ID_ALIASES: dict[str, tuple[str, ...]] = {
    "alice_supervisor": ("neko_supervisor",),
    "neko_supervisor": ("alice_supervisor",),
}


def persona_id_aliases(persona_id: str) -> tuple[str, ...]:
    """The OTHER spellings ``persona_id`` is also known by (``()`` for most ids)."""

    return _PERSONA_ID_ALIASES.get(str(persona_id or "").strip(), ())


def coerce_agent_role(role: AgentRole | str | None) -> AgentRole | str:
    """Resolve a persona role token to an ``AgentRole``.

    Known legacy values retain their enum spelling for compatibility. Unknown
    values remain data: they are never dropped or coerced into a hardcoded role.
    """

    if isinstance(role, AgentRole):
        return role
    text = str(role or "").strip()
    try:
        return AgentRole(text)
    except ValueError:
        return text

# Fork registry hygiene (T6c, 2026-07-18). Upstream toolsets the fork's effective
# registry must never resolve on ANY agent-runtime lane: the whole ``kanban``
# toolset (superseded by the fork board/mission system) and the
# ``feishu_doc`` + ``feishu_drive`` toolsets (an irrelevant Feishu/Lark
# integration). The upstream tool files stay untouched (fork-sync cleanliness);
# this fork-owned constant is the deregistration mechanism. It is enforced in TWO
# places so no lane escapes:
#   1. folded into ``PERSONA_BLOCKED_TOOLS`` below → the persona chat/run lanes and
#      the ``tool_visibility`` permission-preview surface, and
#   2. unioned at the ``profile_runner`` agent-construction chokepoint → every
#      lane, including the worker / root-node lanes that pass
#      ``blocked_tool_names=[]`` (node_tools.py / root_node_engine.py).
# ``delegate_task`` and ``memory`` are deliberately NOT here — operator ruling:
# keep them registered (both are parallel-authority surfaces; a future lane that
# enables either owns reconciling delegation-vs-harness-dispatch / upstream-memory-
# vs-profile-memory).
#
# The block is by TOOLSET MEMBERSHIP, read from the generated builtin manifest
# (``tools/toolset_manifest.json``, drift-gated by ``tests/tools/
# test_toolset_manifest.py``), not a hand-kept tool list: upstream grows these
# toolsets (+5 kanban verbs at the 2026-07-31 sync, ``kanban_schedule`` at
# v0.21.6), and an enumerated list let each new verb resolve on a declaring lane
# until someone noticed. Upstream kanban itself is KEPT (it is not the fork
# board); it just must not resolve on an agent-runtime lane.
REGISTRY_HYGIENE_BLOCKED_TOOLSETS = ("kanban", "feishu_doc", "feishu_drive")

_BOUNDED_LANE_BLOCKED_TOOLS = frozenset(
    {
        "delegate_task",
        "clarify",
        "memory",
        "send_message",
        "cronjob",
        "cronjob_manage",  # upstream action-tool name; preserve the bounded-lane block
    }
)


@lru_cache(maxsize=1)
def registry_hygiene_blocked_tools() -> frozenset[str]:
    """``REGISTRY_HYGIENE_BLOCKED_TOOLS``, resolved on first use: importing this module
    must not import ``tools`` (a bundle's forced tree mounts ``tools`` after
    ``agent_runtime`` loads)."""
    from tools.toolset_manifest import builtin_tool_names_for_toolsets

    return frozenset(builtin_tool_names_for_toolsets(REGISTRY_HYGIENE_BLOCKED_TOOLSETS))


@lru_cache(maxsize=1)
def persona_blocked_tools() -> frozenset[str]:
    """``PERSONA_BLOCKED_TOOLS``: the bounded-lane block plus registry hygiene."""
    return _BOUNDED_LANE_BLOCKED_TOOLS | registry_hygiene_blocked_tools()


_LAZY_CONSTANTS = {
    "REGISTRY_HYGIENE_BLOCKED_TOOLS": registry_hygiene_blocked_tools,
    "PERSONA_BLOCKED_TOOLS": persona_blocked_tools,
}


def __getattr__(name: str):
    try:
        return _LAZY_CONSTANTS[name]()
    except KeyError:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from None


def role_from_persona(persona: AgentPersona) -> AgentRole | str:
    return coerce_agent_role(persona.role)


def validate_toolsets(configured: list[str]) -> list[str]:
    """Normalize a declared toolset list: strip, drop empties, dedupe in order.

    S66 removed the ``role`` parameter. It had been unused since S61/S64 made
    profile/persona declarations the sole capability authority and deleted the
    per-role allow/deny tables (``ALLOWED_TOOLSETS_BY_ROLE`` /
    ``PER_ROLE_TOOL_DENIES``, both s11 tombstones). Accepting a role here read
    as a ceiling this function has not applied for two waves — see
    ``chat_lane_toolsets``, whose safety argument was mis-stated in exactly that
    way. There is NO role ceiling; this is a normalizer.
    """

    return list(dict.fromkeys(str(toolset).strip() for toolset in configured if str(toolset).strip()))


def blocked_tool_names() -> frozenset[str]:
    """The runtime-wide chat blocklist.

    S66 removed the ``persona`` parameter: the body has returned the module
    constant for every persona since the per-role deny tables went, so the
    argument made a constant look like a per-persona lookup. Callers that want
    the constant directly may read ``PERSONA_BLOCKED_TOOLS``; this accessor
    stays because it is the name the visibility/runtime lanes already call.
    """

    return persona_blocked_tools()


def _blocked_tool_names_with_registry_hygiene(requested: list[str] | None) -> list[str]:
    """Union the fork registry-hygiene block into a request's ``blocked_tool_names``.

    This is the single fork-owned chokepoint that makes the deregistered upstream
    toolsets (``kanban`` + ``feishu_doc`` / ``feishu_drive``) unresolvable on EVERY
    agent-runtime lane — the persona chat/run lanes already carry them via
    ``PERSONA_BLOCKED_TOOLS``, but the worker / root-node lanes construct their
    request with ``blocked_tool_names=[]`` and would otherwise resolve them. Applied
    here (agent construction) so no call site can opt out. Order-preserving; the
    downstream tool-def cache keys on the set, so duplicates/order are harmless."""

    names = list(requested or [])
    seen = set(names)
    for name in sorted(registry_hygiene_blocked_tools()):
        if name not in seen:
            names.append(name)
            seen.add(name)
    return names


# ── the harness lane's ONE capability declaration (S0a A1, 2026-09-03) ───────
#
# Read ``docs/agent-runtime-harness/archive/s0a-atlas-cleanup.md`` §0.2 before
# changing any of this. The short version: nothing on the harness lane used to
# read a profile's ``toolsets:`` key at all. The shipped permission posture is
# ``unbounded`` and that branch resolved ``all_registered_toolsets()`` — every
# toolset registered in the process — so Neko, both devs and QA had
# byte-identical 79-tool surfaces, 17 of them withheld as registry hygiene every
# single turn, while three copies of a per-persona ``toolsets`` list (profile
# config, store row, realm-sync body) were consulted by nobody.
#
# Now the profile's top-level ``toolsets:`` IS the declaration, and this module
# is the one reader. The persona-level ``AgentPersona.toolsets`` field that
# survived as legacy display (R-S0a-3) was deleted 2026-10-08 (tool-visibility
# split, slice 1): config refuses the key, a store migration strips it.

#: What the harness lane resolves for a profile that declares nothing of its own.
HARNESS_LANE_DEFAULT_TOOLSETS: tuple[str, ...] = ("harness_core",)

#: ``ToolsetDeclaration.source`` values.
TOOLSET_SOURCE_PROFILE_CONFIG = "profile_config"
TOOLSET_SOURCE_LANE_DEFAULT = "lane_default"
TOOLSET_SOURCE_PROFILE_UNRESOLVED = "profile_unresolved"
#: The bound profile's ``config.yaml`` exists but could not be read or parsed.
#: Narrow like the two defaults above, and NAMED so it is not one of them: before
#: this value a read fault answered ``lane_default`` with a DEBUG line, which an
#: operator could not tell from a profile that simply declares nothing.
TOOLSET_SOURCE_PROFILE_CONFIG_UNREADABLE = "profile_config_unreadable"

#: The upstream CLI default (``hermes_cli.config_defaults.DEFAULT_CONFIG``).
#: Read as the default it IS rather than as an operator's choice — see
#: R-S0a-2. Kept as a literal fallback for the (import-error) case where the
#: CLI package cannot be reached from this module.
_UPSTREAM_DEFAULT_TOOLSETS: tuple[str, ...] = ("hermes-cli",)


class DeclarationIssueKind(StrEnum):
    """What is wrong with a declaration that still resolved (narrow)."""

    #: ``config.yaml`` is there and would not read; ``detail`` is the exception CLASS.
    CONFIG_READ_FAILED = "config_read_failed"
    #: A declared (or composite-member) toolset name nothing knows: not in
    #: ``toolsets.TOOLSETS``, not in the builtin manifest, not registered by a plugin.
    #: It resolves zero tools; the rest of the declaration resolves (ruling R4).
    UNKNOWN_TOOLSET = "unknown_toolset"
    #: ``agent_runtime.personas.<id>.toolsets`` is set (ruling R2, 2026-10-08): the key
    #: is refused — its value is dropped and admits nothing — and the refusal is this
    #: row, never a raise out of the config read (a raise took the live snapshot
    #: producer down on every rebuild, 2026-10-09). ``detail`` is the dotted key.
    LEGACY_PERSONA_TOOLSETS_KEY = "persona_toolsets_key_refused"


@dataclass(frozen=True)
class DeclarationIssue:
    """One typed issue on a :class:`ToolsetDeclaration`, rendered as a
    ``requirement_failures`` row so ``tool-diff`` and the HUD print it like any
    other accounted gap."""

    kind: DeclarationIssueKind
    #: The toolset name for ``unknown_toolset``; the exception class for
    #: ``config_read_failed`` (never the message — it can carry a path or YAML text).
    detail: str
    config_path: str | None = None

    def row(self, *, entry_point_lane: str = "") -> dict[str, object]:
        where = self.config_path or "the bound profile's config.yaml"
        if self.kind is DeclarationIssueKind.CONFIG_READ_FAILED:
            summary = (
                f"{where} could not be read ({self.detail}); the harness lane resolved "
                f"the narrow default ({', '.join(HARNESS_LANE_DEFAULT_TOOLSETS)}) instead "
                "of whatever that file declares."
            )
            fix_hint = "Fix or re-save the file; `hermes harness persona tool-diff <id>` re-reads it."
        elif self.kind is DeclarationIssueKind.LEGACY_PERSONA_TOOLSETS_KEY:
            summary = (
                f"{self.detail} is no longer accepted and was ignored: the bound profile's "
                "top-level toolsets: is the one declaration the harness lane reads."
            )
            fix_hint = (
                f"Delete {self.detail} from {self.config_path or 'the config.yaml that carries it'} (the plugin's startup migration strips it "
                "from every profiles/*/config.yaml); declare toolsets in the bound profile's "
                "own config.yaml (top-level `toolsets:`)."
            )
        else:
            summary = (
                f"Declared toolset '{self.detail}' is not a known toolset (not built in, not "
                "registered by any loaded plugin); it contributes no tools. The rest of the "
                "declaration resolves."
            )
            fix_hint = (
                f"Correct the name in the toolsets: key of {where}, or load the plugin that "
                "registers it."
            )
        return {
            "code": self.kind.value,
            "subject": self.detail,
            "config_path": self.config_path,
            "entry_point_lane": str(entry_point_lane or "").strip() or "unknown",
            "summary": summary,
            "fix_hint": fix_hint,
        }


@dataclass(frozen=True)
class ToolsetDeclaration:
    """What ONE persona's bound profile declares for the harness lane.

    ``toolsets`` is the expanded, validated member list the lane admits by;
    ``declared`` is what the config literally said (or the lane default);
    ``source`` says which of the two it was and why.
    """

    toolsets: tuple[str, ...]
    declared: tuple[str, ...]
    source: str
    profile: str | None = None
    config_path: str | None = None
    #: Typed issues the resolution hit (a read fault, an unknown name). Empty on
    #: a clean read — the positive control the issue rows are tested against.
    issues: tuple[DeclarationIssue, ...] = ()
    #: The member names nothing knows (``toolset_names.unknown_toolset_names``).
    unknown: tuple[str, ...] = ()

    def row(self) -> dict[str, object]:
        return {
            "toolsets": list(self.toolsets),
            "declared": list(self.declared),
            "source": self.source,
            "profile": self.profile,
            "config_path": self.config_path,
            "issues": [issue.row() for issue in self.issues],
            "unknown": list(self.unknown),
        }


#: Why a profile-backed chat persona inherited nothing. Typed so the fail-CLOSED
#: outcome is ACCOUNTED rather than silent: an operator whose chat has no tools
#: can be told which of these happened instead of reading an empty list.
PROFILE_CHAT_TOOLSET_NO_MATCH = "no_persona_declares_this_profile"
PROFILE_CHAT_TOOLSET_AMBIGUOUS = "profile_shared_by_multiple_personas"
PROFILE_CHAT_TOOLSET_MATCHED_EXACT = "exact_persona_id"
PROFILE_CHAT_TOOLSET_MATCHED_UNIQUE_PROFILE = "unique_profile_owner"


def profile_persona_resolution(
    profile_id: str,
    personas: list[AgentPersona] | tuple[AgentPersona, ...] | None = None,
) -> tuple[AgentPersona | None, str, tuple[str, ...]]:
    """Resolve the one persona allowed to supply profile-backed defaults.

    Exact persona ids outrank profile ownership. A unique profile owner may
    supply defaults; an unowned or multiply-owned profile inherits nothing.
    This is the single precedence authority for toolsets and the CLI's model,
    provider, API mode, autonomy, core-context and readiness defaults.
    """

    profile = str(profile_id or "").strip()
    declared = list(personas or [])
    exact = next(
        (
            persona
            for persona in declared
            if str(getattr(persona, "id", "") or "").strip()
            in {profile, f"profile:{profile}"}
        ),
        None,
    )
    profile_matches = [
        persona
        for persona in declared
        if str(getattr(persona, "hermes_profile", "") or "").strip() == profile
    ]
    candidates = tuple(
        str(getattr(persona, "id", "") or "").strip() for persona in profile_matches
    )
    if exact is not None:
        return exact, PROFILE_CHAT_TOOLSET_MATCHED_EXACT, candidates
    if len(profile_matches) == 1:
        return profile_matches[0], PROFILE_CHAT_TOOLSET_MATCHED_UNIQUE_PROFILE, candidates
    if len(profile_matches) > 1:
        return None, PROFILE_CHAT_TOOLSET_AMBIGUOUS, candidates
    return None, PROFILE_CHAT_TOOLSET_NO_MATCH, candidates


def all_registered_toolsets() -> list[str]:
    """Every toolset NAME the registry holds. No availability verdict.

    Through ``get_registered_toolset_names`` and not ``get_available_toolsets``,
    which answers the SAME key set — both are ``{entry.toolset for entry in <one
    snapshot>}`` — plus an ``available`` boolean per toolset that this caller
    discards. That boolean is the whole cost: it runs every toolset's
    ``check_fn``, which probes binaries, reads env and builds external clients.
    Measured warm on this checkout, first call: **3.96 s**, and this function is
    on ``perform_agent_create``'s path — the permission preview
    ``persona_instance_summary`` projects onto the wire row it emits — so an
    agent create paid four seconds of machine-capability probing to learn a list
    of strings the registry already had.

    ``import model_tools`` first on purpose: importing it is what POPULATES
    the registry, and a reader that reached the singleton without it would read
    an EMPTY one and answer "there are no toolsets" — a silent wrong answer,
    exactly the trap ``tool_visibility._ensure_tool_registry_populated``
    documents. The names accessor itself is upstream's
    ``ToolRegistry.get_registered_toolset_names``.
    """

    import model_tools  # noqa: F401 — populates the registry
    from tools.registry import registry

    return [str(name) for name in registry.get_registered_toolset_names()]


_CANONICAL_ALIASED_ID = "alice_supervisor"


def canonical_persona_id(persona_id: str) -> str:
    """The canonical spelling of a ruled alias; any other id unchanged. One-way:
    the direction a permission table resolves in (the terminal envelope's grant
    table), so an alias added to :data:`_PERSONA_ID_ALIASES` widens who a grant
    applies to — do not add one without a ruling that names it (S66 removed an
    un-ruled third entry for exactly that reason)."""

    return _CANONICAL_ALIASED_ID if _CANONICAL_ALIASED_ID in (persona_id, *persona_id_aliases(persona_id)) else persona_id


def role_or_attr(persona: object) -> str:
    """The persona's role as the role vocabulary reads it, or its raw ``role``
    attribute when that read faults. Never raises (both callers decorate a
    turn; neither may block one)."""

    try:
        return str(role_from_persona(persona))  # type: ignore[arg-type]
    except Exception:
        return str(getattr(persona, "role", "") or "")
