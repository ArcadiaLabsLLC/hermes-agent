"""Fork-owned Hermes home authorities: head home, shared auth home, shared roots.

Moved out of the upstream file ``hermes_constants.py`` by Stage 4 of
``docs/agent-runtime-harness/planned/harness-plugin-and-upstream-seams.md``
(inventory: ``docs/agent-runtime-harness/planned/seam-s4-s5-s6-inventory-2026-09-23.md``
§2.1, bucket "ours"). Upstream has no equivalent of any name here: the head
home is the Mission Control operator home across persona relay hops, the auth
home is the harness's one shared operator auth, and the shared skills /
characters roots are the realm's install-wide libraries.

Stdlib + ``hermes_constants`` + ``agent_runtime.chat_session_scope`` (itself
stdlib-only at import) only, so it stays importable from anywhere
``hermes_constants`` is. Upstream helpers are read through the module
(``_hc.get_hermes_home()``) at call time, so a test that patches them on
``hermes_constants`` still reaches these functions.
"""

from __future__ import annotations

import os
from contextvars import ContextVar, Token
from dataclasses import dataclass
from pathlib import Path
from typing import Any, List, Optional

import hermes_constants as _hc
# The ENV_HEAD_HOME rung is read by the resolution authority, never here
# (tests/agent_runtime/test_hermes_home_env_gate.py). Stdlib-only at import.
from agent_runtime.chat_session_scope import configured_head_home

_UNSET = object()

CANONICAL_SHARED_SKILL_IDS = frozenset(
    {
        "harness-dev-delivery",
        "harness-qa-verdict",
        "harness-runtime-model",
        "harness-charsheet-authoring",
    }
)

_HERMES_HEAD_HOME: ContextVar[str | object] = ContextVar(
    "_HERMES_HEAD_HOME", default=_UNSET
)

_HERMES_AUTH_HOME_OVERRIDE: ContextVar[str | object] = ContextVar(
    "_HERMES_AUTH_HOME_OVERRIDE", default=_UNSET
)


def set_hermes_auth_home_override(path: str | Path | None) -> Token:
    """Set a context-local shared-auth home override and return its reset token."""
    value: str | object = _UNSET if path is None else str(path)
    return _HERMES_AUTH_HOME_OVERRIDE.set(value)


def reset_hermes_auth_home_override(token: Token) -> None:
    """Restore the previous context-local shared-auth home override."""
    _HERMES_AUTH_HOME_OVERRIDE.reset(token)


def get_hermes_auth_home() -> str:
    """The explicit shared-auth home: context-local override first, env second.

    Returns ``""`` when neither authority answers, which is the caller's signal
    to fall back to the historical global root. This is the ONE reader of the
    ``HERMES_AUTH_HOME`` authority that every in-process consumer should use;
    reading the env var raw sees only half of it.
    """
    override = _HERMES_AUTH_HOME_OVERRIDE.get()
    if override is not _UNSET and override:
        return str(override).strip()
    return os.environ.get("HERMES_AUTH_HOME", "").strip()


def record_hermes_head_home_if_unset(path: str | Path | None) -> Token | None:
    """Record the OUTERMOST (operator/head) Hermes home for this context, once.

    Returns a reset token when THIS call recorded the head (the caller owns the
    reset), or ``None`` when an enclosing scope already recorded it — a nested
    relay hop must NOT overwrite the outermost home. ``None``/empty is ignored.
    """
    if path is None or not str(path):
        return None
    current = _HERMES_HEAD_HOME.get()
    if current is not _UNSET and current:
        return None
    return _HERMES_HEAD_HOME.set(str(path))


def reset_hermes_head_home(token: Token | None) -> None:
    """Restore the previous head-home recording (no-op when token is ``None``)."""
    if token is not None:
        _HERMES_HEAD_HOME.reset(token)


def get_hermes_head_home() -> Path:
    """Return the operator/head Hermes home — the home the Mission Control
    projection reads — IGNORING any active persona profile-home override.

    The launcher may provide ``HERMES_HEAD_HOME`` to keep the Mission Control
    transcript store stable while ``HERMES_HOME`` selects a different runtime
    profile. A context-local relay head still wins so nested persona execution
    cannot escape the operator that started it. With neither authority present,
    behavior falls back to the ordinary resolved home.
    """
    head = _HERMES_HEAD_HOME.get()
    if head is not _UNSET and head:
        return Path(head)
    configured = configured_head_home()
    if configured:
        return Path(configured).expanduser()
    return _hc.get_hermes_home()


def hermes_head_home_is_authoritative() -> bool:
    """True when :func:`get_hermes_head_home` answers from an explicit head
    authority — the context-recorded outermost home (relay nesting) or the
    operator-supplied ``HERMES_HEAD_HOME`` environment value.

    False means the head has degenerated to the ambient :func:`get_hermes_home`
    resolution, so under an active profile-home override the "head" IS the
    override and the real operator home is unknown. Operator-visible stores
    must fail closed in that state instead of writing a transcript into a
    profile-local DB the Mission Control projection never reads. When the head
    is authoritative, it may legitimately EQUAL the active override (a persona
    bound to the operator's own head profile, e.g. the seeded base agent) —
    that is the same database, not a divergence.
    """
    head = _HERMES_HEAD_HOME.get()
    if head is not _UNSET and head:
        return True
    return bool(configured_head_home())


def get_hermes_background_work_home() -> Path:
    """The home the OPERATOR-VISIBLE background-work stores live under.

    ``processes.json`` (the terminal checkpoint) and ``state.db``'s
    ``async_delegations`` table are written by one process and READ by another:
    an agent spawns a build inside a serve-hosted persona turn, and the
    operator's Activity HUD reads it from a snapshot built on a different lane.
    Writer and reader therefore have to agree on the directory, and until this
    function existed they did not — the writers resolved ambient
    ``get_hermes_home()`` while the projection resolved the head-home scope. On
    the launcher's own layout (``HERMES_HOME=profiles/<profile>`` with
    ``HERMES_HEAD_HOME=profiles/base``) those are DIFFERENT directories, so the
    writers wrote to the profile home while the reader watched base and reported
    "nothing running" through an entire build.

    The precedence is deliberately the one :func:`get_hermes_head_home` already
    implements, and this function is a NAME for that decision rather than a
    second resolver:

    * An explicit head — the ``HERMES_HEAD_HOME`` env value, or the outermost
      home recorded in the contextvar by ``persona_profile_context`` — wins.
      That is what makes a turn running under a profile-home override still
      register its background work where the operator can see it.
    * With neither present the answer is the ambient home, byte-identical to
      the historical behaviour. The gateway, the TUI and plain CLI runs set
      neither, so nothing on those lanes moves.
    """

    return get_hermes_head_home()


def get_shared_skills_dir(default: Path | None = None) -> Path:
    """Return the canonical shared skills root every persona references.

    This is the single physical skills directory that all persona-profiles
    read/write and that realm sync publishes. It lives under the Hermes
    *root* (beside ``profiles/``), not inside any one profile — so it is
    shared across every persona AND addressed relative to the root, which
    makes it portable across machines/OSes (no hard-coded ``~/.claude`` or
    per-machine home path).

    The default resolves the same way for every profile: because
    ``get_default_hermes_root()`` maps ``<root>/profiles/<name>`` back to
    ``<root>``, ``alice``, ``neko``, ``base``, … all compute the *same*
    ``<root>/shared/skills`` from their own ``HERMES_HOME`` with no env
    injection or per-profile config. Cross-machine, each host resolves its
    own root and realm sync git-carries the contents between them.

    Resolution order:
        1. ``HERMES_SHARED_SKILLS`` env var (explicit override / MC-injected)
        2. Caller-supplied ``default``
        3. ``<hermes_root>/shared/skills``  (default — the canon path)
    """
    override = os.getenv("HERMES_SHARED_SKILLS", "").strip()
    if override:
        return Path(override).expanduser()
    if default is not None:
        return default
    return _hc.get_default_hermes_root() / "shared" / "skills"


def get_shared_characters_dir(default: Path | None = None) -> Path:
    """Return the ONE install-wide character library every persona authors into.

    The sibling of :func:`get_shared_skills_dir`, and it exists for the same
    reason: the library lives under the Hermes *root* (beside ``profiles/``),
    not inside any one profile, so ``alice``, ``base``, ``neko``, … all compute
    the SAME directory from their own home with no env injection and no
    per-profile config. That convergence is the whole point — a character draft
    is addressed install-wide by its id, and a turn that resolved a home nobody
    selected still reads and writes the library the operator meant.

    **Why this does NOT reuse** :func:`get_default_hermes_root` **, despite
    computing the same mapping.** That function reads bare
    ``os.environ["HERMES_HOME"]`` and never consults the context-local override
    (:func:`get_hermes_home_override`). A resolver built on it answers the
    PROCESS home while an in-process persona binding is scoped to another one —
    which is precisely the cross-persona bleed the serve lane retired, re-imported
    one directory later. So the derivation rides :func:`get_hermes_home` (the
    override → env → platform-default ladder) and maps the profile shell off it
    here.

    Resolution order:
        1. ``HERMES_SHARED_CHARACTERS`` env var (explicit operator/test
           override). A bare env read is sound for THIS authority and not for
           the derivation below it: an install-wide library named explicitly is
           named for the whole install, so there is no persona-scoped answer a
           ContextVar could carry.
        2. Caller-supplied ``default``
        3. ``<hermes_root>/shared/characters`` — where ``<hermes_root>`` is the
           resolved home's grandparent when the home is ``<root>/profiles/<name>``,
           and the home itself otherwise (a bare or Docker-style home IS the root).
    """
    override = os.getenv("HERMES_SHARED_CHARACTERS", "").strip()
    if override:
        return Path(override).expanduser()
    if default is not None:
        return default
    home = _hc.get_hermes_home()
    root = home.parent.parent if home.parent.name == "profiles" else home
    return root / "shared" / "characters"


@dataclass
class ProfileTemplateInfo:
    """Lightweight profile summary for read-only library surfaces."""

    name: str
    path: Path
    model: Optional[str] = None
    provider: Optional[str] = None
    description: str = ""


def available_profile_template_summaries() -> List[ProfileTemplateInfo]:
    """Return live, servable profile metadata without parsing runtime config.

    Mission Control's available-persona roster uses only the profile name,
    path, and description. Reading every large ``config.yaml`` merely to
    discard model/provider adds substantial latency to a cold snapshot. The
    roster of names alone is upstream's :func:`list_profile_names`.
    """

    from hermes_cli.profiles import read_profile_meta

    from ._upstream_doors import iter_named_profile_dirs, profile_id_pattern

    profiles: list[ProfileTemplateInfo] = []
    try:
        # A raw directory walk admits tombstones, ghost shells and crashed
        # empty-.env profiles as placeable Launcher personas.
        entries = iter_named_profile_dirs()
    except Exception:
        return []

    for entry in entries:
        try:
            if not _hc.named_profile_has_servable_identity(entry):
                continue
            name = entry.name
            if name == "default" or not profile_id_pattern().match(name):
                continue
            meta = read_profile_meta(entry)
            profiles.append(
                ProfileTemplateInfo(
                    name=name,
                    path=entry,
                    description=meta.get("description", ""),
                )
            )
        except Exception:
            continue

    return profiles


def profile_is_tombstoned(profile_name: Any) -> bool:
    """Whether upstream's delete tombstone marks this named profile as deleted.

    Owner ruling 2026-09-24 (3): profile delete adopts upstream's tombstone
    (``hermes_constants.mark_named_profile_deleted``, written by ``delete_profile``). The
    harness DERIVES "this persona's profile is gone" from that one fact at read time —
    it no longer writes a second one (``mark_profile_personas_orphaned``, called from
    ``delete_profile``, deleted by lane DOORS-A). ``default`` / empty is never tombstoned;
    an unreadable check answers False (absence of proof keeps the persona backed).
    Caveat the owner accepted: re-creating the profile clears the tombstone, and
    same-name personas are backed again.
    """

    name = str(profile_name or "").strip()
    if not name or name == "default":
        return False
    try:
        from hermes_cli.profiles import get_profile_dir
        from hermes_constants import named_profile_is_deleted

        return bool(named_profile_is_deleted(get_profile_dir(name)))
    except Exception:
        return False
