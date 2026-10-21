from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
import logging
import os
import re
from pathlib import Path
from typing import Any, Iterator

from hermes_constants import (
    get_hermes_home,
    reset_hermes_home_override,
    set_hermes_home_override,
)
from agent_runtime import paths
from agent_runtime.run_context import run_runtime_root_scope
from agent_runtime.profile_home import (
    PersonaProfileBinding,
    get_hermes_auth_home,
    get_hermes_head_home,
    record_hermes_head_home_if_unset,
    reset_hermes_auth_home_override,
    reset_hermes_head_home,
    set_hermes_auth_home_override,
)
from hermes_cli.profiles import (
    get_active_profile,
    get_profile_dir,
    normalize_profile_name,
    profile_exists,
)

__layer__ = "stores"

logger = logging.getLogger(__name__)

RUNTIME_ROOT_ENV = "HERMES_AGENT_RUNTIME_ROOT"

#: Where the exported runtime root came from, recorded on the typed row so an
#: operator reading it never has to guess.
RUNTIME_ROOT_SOURCE_ARGUMENT = "argument"
RUNTIME_ROOT_SOURCE_RESOLVER = "resolver"
RUNTIME_ROOT_SOURCE_UNRESOLVED = "unresolved"

#: A persona bound no Hermes profile, so this context exported the runtime root
#: but performed NO profile-home redirection. Typed so the degradation is
#: accounted for rather than inferred from an absent variable (audit Q1).
PROFILE_CONTEXT_NO_PROFILE_BINDING = "persona_profile_context_no_profile_binding"
#: The canonical resolver could not answer (probe isolation refused, or the
#: module is unimportable), so no runtime root was exported at all. The ONE
#: remaining path to an unset variable, and it is now named.
PROFILE_CONTEXT_RUNTIME_ROOT_UNRESOLVED = "persona_profile_context_runtime_root_unresolved"

# S54 took ``MCP_SERVER_PERSONA_OWNERS`` with ``mcp_owner_profile_name``, its
# only reader.

@dataclass(frozen=True, slots=True)
class ProfileContextRow:
    """A typed account of what this run's environment context actually did.

    Emitted for the cases that used to be silent. ``row()`` is the same
    ``{code, subject, entry_point_lane, summary, fix_hint}`` shape
    ``mcp_lane`` / ``mcp_admission`` / ``terminal_envelope`` already emit, so
    operator surfaces need no new case.
    """

    code: str
    persona_id: str
    summary: str
    fix_hint: str = ""
    runtime_root: str = ""
    runtime_root_source: str = RUNTIME_ROOT_SOURCE_UNRESOLVED

    def row(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "subject": self.persona_id,
            "entry_point_lane": "",
            "summary": self.summary,
            "fix_hint": self.fix_hint,
            "runtime_root": self.runtime_root,
            "runtime_root_source": self.runtime_root_source,
        }


_PROFILE_CONTEXT_ROWS: ContextVar[tuple[ProfileContextRow, ...]] = ContextVar(
    "hermes_profile_context_rows", default=()
)


# S54 removed ``current_profile_context_rows`` and ``mcp_owner_profile_name``.
# The typed rows are still BUILT and exported on the resolution path; these two
# were read-back accessors with no production consumer.

def _resolved_runtime_root() -> Path | None:
    """The configured runtime root, via the ONE canonical ladder. Never raises.

    ``paths.store_root()`` is ``resolution.resolve_runtime`` (env →
    ``agent_runtime.store_root`` in the root config → platform default) plus
    ``assert_probe_isolation``. It answers for EVERY persona, profile-bound or
    not — which is exactly why the runtime-root export does not need a profile
    binding and never should have been gated on one.

    ``None`` means the resolver genuinely refused (probe isolation, or an
    unimportable module). That is a typed outcome
    (:data:`PROFILE_CONTEXT_RUNTIME_ROOT_UNRESOLVED`), not a silent skip.
    """

    try:
        from . import paths

        root = paths.store_root()
    except Exception:
        logger.debug("Runtime root unresolvable for persona profile context", exc_info=True)
        return None
    text = str(root or "").strip()
    return Path(text) if text else None

def active_profile_name() -> str:
    """Return the current Hermes profile name without assuming Alice is head.

    Mission Control can be driven from any Hermes profile. Prefer the explicit
    profile environment set by the CLI/gateway, then derive the name from the
    active HERMES_HOME path, then fall back to the legacy active_profile marker
    or default profile.
    """
    raw = os.environ.get("HERMES_PROFILE", "").strip()
    if raw:
        return normalize_profile_name(raw)
    from hermes_constants import get_hermes_home

    home = get_hermes_home()
    if home.parent.name == "profiles" and home.name:
        return normalize_profile_name(home.name)
    # The sticky-marker fallback reads through the CANONICAL resolver
    # (hermes_cli.profiles → hermes_constants.get_default_hermes_root), never a
    # hand-spelled ``Path.home() / ".hermes"``: that spelling is the wrong
    # location on native Windows (the platform default is %LOCALAPPDATA%\
    # hermes), so this fallback read a marker file no other code wrote and
    # ``agents --json``'s source_profile column lied under ambient environment
    # (2026-08-12 root-observability wave).
    return normalize_profile_name(get_active_profile() or "default")


def cli_sticky_profile_name() -> str:
    """The CLI's sticky ``active_profile`` — the profile a bare ``hermes`` in a terminal edits.

    Deliberately NOT :func:`active_profile_name`: that is the profile THIS
    process serves (``HERMES_PROFILE`` / ``HERMES_HOME`` first), and a serve
    started on ``base`` keeps serving ``base`` after the operator runs
    ``hermes profile use gpt-launcher`` in a shell. ``hermes model`` from that
    shell then writes gpt-launcher's ``model.default`` while the agents keep
    resolving base's — the split the snapshot envelope reports so the launcher
    can say so.
    """

    return normalize_profile_name(get_active_profile() or "default")


def resolve_persona_profile(persona) -> PersonaProfileBinding:
    if not persona.hermes_profile:
        return PersonaProfileBinding(
            persona_id=persona.id,
            hermes_profile=None,
            profile_home=None,
            readiness="ready",
            summary="inherits active Harness profile",
        )
    name = normalize_profile_name(persona.hermes_profile)
    if not profile_exists(name):
        return PersonaProfileBinding(
            persona_id=persona.id,
            hermes_profile=name,
            profile_home=None,
            readiness="missing_profile",
            summary=f"Hermes profile '{name}' does not exist",
        )
    home = get_profile_dir(name)
    return PersonaProfileBinding(
        persona_id=persona.id,
        hermes_profile=name,
        profile_home=home,
        readiness="ready",
        summary="profile exists",
    )


@contextmanager
def persona_profile_context(
    binding: PersonaProfileBinding,
    *,
    runtime_root: Path | None = None,
) -> Iterator[None]:
    """Bind this run's profile CONTEXT-LOCALLY. Audit Q1: the runtime root is UNCONDITIONAL.

    Writes no process-global environment. Everything it installs is a
    ContextVar: the home override (``set_hermes_home_override``), the head-home
    recording, the shared-auth home (``set_hermes_auth_home_override``), the
    run's runtime root (``run_runtime_root_scope``) and the typed rows. They are
    per-task and per-thread, so two concurrent entries cannot lose each other's
    update and no OTHER thread's ``get_hermes_home()`` can observe this binding
    — which is why it needs no lock.

    The ``os.environ`` mirror (``HERMES_HOME`` / ``HOME`` / ``HERMES_AUTH_HOME``
    / ``HERMES_AGENT_RUNTIME_ROOT``, saved, mutated and restored, sound only
    while every run held ``_WORKDIR_LOCK``) is gone: run-serialization S5
    (``7c3bb31a12b``) left it no production caller. A spawn takes its env from
    ``run_context``'s child-env builder, which reads these ContextVars; a
    ContextVar never crosses a spawn on its own. ``HOME`` is not redirected
    here — POSIX ``os.path.expanduser`` / ``Path.home()`` have no context-scoped
    hook (the profile runner owns that under its process-home lock); on native
    Windows it is unobservable, ``ntpath.expanduser`` reads ``USERPROFILE``.

    This block used to conflate two responsibilities and gate both on one field.
    Profile-home redirection (``HERMES_HOME`` / ``HOME`` / ``HERMES_AUTH_HOME``)
    genuinely requires a bound Hermes profile. Exporting the runtime root does
    NOT — ``paths.store_root()`` answers for every persona — yet the
    ``profile_home is None`` early-``yield`` skipped it too.

    That was path 1 of the ambient-environment split: a persona with no
    ``hermes_profile`` ran with ``HERMES_AGENT_RUNTIME_ROOT`` unset, which made
    the legacy terminal envelope INERT and let ``git push origin main`` execute
    ungated and unrecorded, while the same lane with a profile-bound persona
    hard-blocked it. Same lane, same role, opposite outcomes, decided by a
    config field most personas never set.

    Now: the runtime root is bound for every persona (``run_runtime_root_scope``),
    the profile-home redirection stays gated on the binding, and
    both degradations — "no profile bound" and "resolver could not answer" —
    emit a typed :class:`ProfileContextRow` instead of being inferable only from
    an absent variable.

    This must land WITH the Q2 scope binding, never before it: on its own it
    arms the legacy env-keyed envelope on every lane that previously ran with
    the variable unset. With Q2, those lanes bind a scope and are decided by
    policy, so the export changes no verdict — it only makes receipts land.
    """

    resolved_root = runtime_root if runtime_root is not None else _resolved_runtime_root()
    root_source = (
        RUNTIME_ROOT_SOURCE_ARGUMENT
        if runtime_root is not None
        else (
            RUNTIME_ROOT_SOURCE_RESOLVER
            if resolved_root is not None
            else RUNTIME_ROOT_SOURCE_UNRESOLVED
        )
    )
    rows: list[ProfileContextRow] = []
    if resolved_root is None:
        rows.append(
            ProfileContextRow(
                code=PROFILE_CONTEXT_RUNTIME_ROOT_UNRESOLVED,
                persona_id=binding.persona_id,
                summary=(
                    f"No runtime root could be resolved for persona '{binding.persona_id}', so "
                    f"{RUNTIME_ROOT_ENV} is not exported for this run."
                ),
                fix_hint=(
                    "Set agent_runtime.store_root in the root config.yaml, or export "
                    f"{RUNTIME_ROOT_ENV}. Under HERMES_REQUIRE_ISOLATED_ROOT this is expected: "
                    "the resolver refuses rather than let a probe write into the live store."
                ),
                runtime_root_source=RUNTIME_ROOT_SOURCE_UNRESOLVED,
            )
        )

    if binding.profile_home is None:
        rows.append(
            ProfileContextRow(
                code=PROFILE_CONTEXT_NO_PROFILE_BINDING,
                persona_id=binding.persona_id,
                summary=(
                    f"Persona '{binding.persona_id}' binds no Hermes profile, so this run "
                    "inherits the active profile home; only the runtime root is exported."
                ),
                fix_hint=(
                    "Set the persona's hermes_profile if it needs its own HERMES_HOME / HOME / "
                    "HERMES_AUTH_HOME. Running without one is supported and is not an error."
                ),
                runtime_root=str(resolved_root or ""),
                runtime_root_source=root_source,
            )
        )
        rows_token = _PROFILE_CONTEXT_ROWS.set(tuple(rows))
        try:
            with run_runtime_root_scope(resolved_root):
                yield
        finally:
            _PROFILE_CONTEXT_ROWS.reset(rows_token)
        return

    # Record the operator/head home BEFORE this override diverts ``get_hermes_home()``. Set-once
    # (nested relay hops keep the outermost) so a relay-target turn under a persona override still
    # persists its persona-chat SessionDB transcript where Mission Control reads it (2026-07-18).
    head_home_token = record_hermes_head_home_if_unset(get_hermes_head_home())
    token = set_hermes_home_override(binding.profile_home)
    # The shared-auth home this binding pins: the head's, so a persona keeps its
    # own profile home for memory/sessions/config while borrowing the head
    # credential pool. Resolved through ``get_hermes_auth_home()`` (ContextVar
    # first, env second) so a nested binding reads the outer one's answer.
    head_auth_home = get_hermes_auth_home() or (os.environ.get("HERMES_HOME") or "")
    auth_token = set_hermes_auth_home_override(head_auth_home or None)
    rows_token = _PROFILE_CONTEXT_ROWS.set(tuple(rows))
    try:
        with run_runtime_root_scope(resolved_root):
            yield
    finally:
        _PROFILE_CONTEXT_ROWS.reset(rows_token)
        reset_hermes_auth_home_override(auth_token)
        reset_hermes_home_override(token)
        reset_hermes_head_home(head_home_token)


@contextmanager
def process_home_scope(home: Path | str | None, *, head_home: Path | str | None = None) -> Iterator[None]:
    """Bind *home* as THIS task's Hermes home, context-locally. The other half.

    Everything above is written from the producing side — a lane that needs a
    persona's home and takes it. This is the CONSUMING side: a lane that has a
    home of its own and must not lose it to somebody else's mirror.

    **The defect it retires** (measured 2026-08-27, operator's screen). The
    launcher's serve child was booted onto ``profiles\\alice`` and ran its boot
    actor prewarm (``persona_chat_actor_prewarm``) over every placed persona at
    20:56:06-20:56:14: four instances bound to the profile ``launcher-qa``, the
    first bind held for 11.25 s. Each of those binds then ran
    :func:`persona_profile_context` with its ``os.environ`` mirror on (the
    mirror is gone since run-serialization S5; this scope still guards any
    ambient ``HERMES_HOME`` a lane did not bind). A concurrent ``harness characters status --draft
    ...`` on the serve's argv lane, on a pool worker with no binding of its own,
    fell through ``get_hermes_home()``'s ladder to the mirrored
    ``os.environ["HERMES_HOME"]`` and resolved
    ``...\\profiles\\launcher-qa\\characters\\.drafts``. It then reported a
    base-authored draft as nonexistent. Nothing was wrong with the draft; the
    request was asked to read the wrong disk.

    **Why a ContextVar is the right instrument and env is not.** The override
    installed here is per-task and per-thread, so it out-ranks the env var for
    this lane and is invisible to every other one. That asymmetry is the fix:
    the lane that reads in-process stops being a passenger on a global channel. Writing a second env
    var would only add another global to lose the same race.

    **The home must be CAPTURED, not re-read.** The caller hands over a home it
    resolved at a boot instant that provably precedes any persona scope in the
    process — for ``harness serve`` that is the same instant
    ``core_cache.capture_fingerprint_home`` is taken at, and for the same reason
    (that module's HC-1 note argues it at length: resolving lazily pins whatever
    scope happened to be live at first use). Re-reading ``os.environ`` at
    request entry would simply inherit a flip that was already live, which is
    half the field cases.

    **What it does NOT cover, named rather than discovered later.** Only
    ``HERMES_HOME``. ``HOME`` has no context-scoped hook at all (POSIX
    ``expanduser``; unobservable on native Windows, where ``ntpath`` consults
    ``USERPROFILE``), and ``HERMES_AUTH_HOME``'s mirror is written with the HEAD
    auth home rather than the persona's, so it is not a cross-persona bleed to
    begin with. A subprocess spawned from inside this scope still inherits the
    ambient ``os.environ`` — a ContextVar never crosses a spawn — so a lane that
    spawns and must not be redirected needs more than this.

    ``None`` binds nothing and yields. A plain CLI process never captured a boot
    home and must behave exactly as it does today; pinning an empty override
    would out-rank a legitimate persona binding, which is a worse fault than the
    one being fixed.

    ``head_home`` is the serve's head FALLBACK (``ServeSession.serve_head_home``): recorded as
    this task's head, set-once, when the serve booted with nothing naming one -- no
    ``HERMES_HEAD_HOME``, no shared pointer, no config declaration. Without it every persona
    turn of such a serve failed ``chat_session_db_unavailable``: this override is active and
    the head had degenerated to it (``default_persona_session_db`` fails closed on exactly
    that). It is a context-local record, never a machine-wide declaration.
    """

    if home is None or not str(home):
        yield
        return
    head_token = record_hermes_head_home_if_unset(head_home) if head_home else None
    token = set_hermes_home_override(str(home))
    try:
        yield
    finally:
        reset_hermes_home_override(token)
        reset_hermes_head_home(head_token)


def _profile_home_for_token(token: str) -> Path | None:
    """Profile-aware pull destination (W-H4, plan §5.1).

    Before 2026-07-17 this mapping collapsed EVERY ``profiles/<name>/…``
    artifact into the active profile home (a degenerate ternary — both
    branches returned ``get_hermes_home()``), so a multi-profile realm pull
    last-write-wins'd every profile's config.yaml/MEMORY.md onto one home.
    Now: the active profile keeps the active home; any other published profile
    resolves to ITS OWN home via ``get_profile_dir`` (materialized by the pull
    write-loop's mkdir and reported as a typed ``profile_sync`` row). Untrusted
    remote component: refuse traversal/absolute/drive-letter shapes.
    """

    if token in ("", ".", "..") or ":" in token or token.startswith(("/", "\\")):
        return None
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,120}", token):
        return None
    if token == paths.safe_path_token(active_profile_name()):
        return get_hermes_home()
    try:
        from hermes_cli.profiles import get_profile_dir, normalize_profile_name

        return get_profile_dir(normalize_profile_name(token))
    except Exception:
        return None
