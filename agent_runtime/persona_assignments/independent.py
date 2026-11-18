"""Provision the private identity of an explicitly authored agent."""

from __future__ import annotations

import hashlib
import os
import tempfile
import uuid
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING

from hermes_cli.profiles import get_profile_dir
from hermes_cli.profiles_initialization import finish_profile_layout
from hermes_constants import get_hermes_home

from .. import paths, yaml_io
from ..config.roster import ensure_persisted_personas
from ..errors import NotFound
from ..locks import agent_create_lock, agent_record_write_lock
from ..models import AgentPersona, PersonaInstance, apply_instance_model_overrides
from ..persona_chat_durability import PersonaChatPersistenceError
from ..prompt_sources import resolve_persona_system_prompt_path
from ..store import AgentStore, WorkspaceStore
from ..sync_admission import content_refusal, payload_refusal
from .errors import RetiredPersonaInstanceError
from .identity import persona_chat_session_id_for, persona_instance_id_for_placement

if TYPE_CHECKING:
    from .store import PersonaInstanceStore

__layer__ = "stores"

_OWNER_FILE = ".eternia-agent-owner"
_PROFILE_PROMPT = "personas/system-prompt.md"
_PROFILE_SOUL = "personas/soul-overlay.md"


def _text_from(path: Path | None, roots: tuple[Path, ...]) -> str | None:
    if path is None:
        return None
    resolved = path.resolve()
    if resolved.suffix.lower() not in {".md", ".txt"}:
        return None
    if not any(resolved.is_relative_to(root.resolve()) for root in roots):
        return None
    if not resolved.is_file():
        return None
    data = resolved.read_bytes()
    if content_refusal(data) is not None:
        raise ValueError("A source prompt contains a credential-shaped assignment.")
    return data.decode("utf-8")


def _portable_model_defaults(home: Path) -> dict[str, str]:
    path = home / "config.yaml"
    if path.is_symlink() or not path.is_file():
        return {}
    config = yaml_io.load(path.read_text(encoding="utf-8"))
    model = config.get("model") if isinstance(config, dict) else None
    if isinstance(model, str):
        model = {"default": model}
    if not isinstance(model, dict):
        return {}
    return {
        key: value
        for key in ("default", "provider")
        if isinstance((value := model.get(key)), str)
        and payload_refusal({key: value}, check_portability=True) is None
    }


def _profile_source(source_id: str) -> tuple[AgentPersona | None, Path]:
    source = next((person for person in ensure_persisted_personas() if person.id == source_id), None)
    profile = source.hermes_profile if source else None
    if source is None and source_id.startswith("profile_"):
        profile = source_id.removeprefix("profile_")
    return source, get_profile_dir(profile) if profile else get_hermes_home()


def _stage_profile(home: Path, source_home: Path, source: AgentPersona | None, owner: str) -> tuple[str, str | None]:
    prompt = _text_from(
        resolve_persona_system_prompt_path(source) if source else None,
        (source_home, Path(__file__).resolve().parents[2]),
    )
    overlay = _text_from(
        source_home / source.soul_overlay_path if source and source.soul_overlay_path else None,
        (source_home,),
    )
    soul = _text_from(source_home / "SOUL.md", (source_home,))
    model = _portable_model_defaults(source_home)
    home.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=home.parent, prefix=f".{home.name}-") as temp:
        stage = Path(temp) / "profile"
        (stage / "personas").mkdir(parents=True)
        (stage / "config.yaml").write_text(yaml_io.dump({"model": model} if model else {}), encoding="utf-8")
        if prompt is not None:
            (stage / _PROFILE_PROMPT).write_text(prompt, encoding="utf-8")
        if overlay is not None:
            (stage / _PROFILE_SOUL).write_text(overlay, encoding="utf-8")
        finish_profile_layout(stage, no_skills=False, clone_all=False, description=None, soul=soul)
        (stage / _OWNER_FILE).write_text(owner, encoding="utf-8")
        os.rename(stage, home)
    return _PROFILE_PROMPT if prompt is not None else "", _PROFILE_SOUL if overlay is not None else None


def _provision(
    source_id: str, persona_id: str, profile: str, display_name: str,
    source_instance: PersonaInstance | None,
) -> None:
    home = get_profile_dir(profile)
    owner = source_id if source_instance is None else f"{source_id}\n{source_instance.id}"
    store = AgentStore()
    try:
        existing = store.get(persona_id)
    except NotFound:
        existing = None
    if existing is not None and existing.hermes_profile != profile:
        raise ValueError("The destination persona already has a different profile.")
    source, source_home = _profile_source(source_id)
    base = source or AgentPersona(source_id, display_name, "agent", None, None, None)
    base = apply_instance_model_overrides(base, source_instance)
    if existing is None:
        for key in ("model", "provider", "api_mode", "skills"):
            if payload_refusal({key: getattr(base, key)}) is not None:
                raise ValueError(f"The source agent's {key} setting is not portable.")
    if home.exists() or home.is_symlink():
        marker = home / _OWNER_FILE
        if home.is_symlink() or marker.is_symlink() or not marker.is_file() or marker.read_text(encoding="utf-8") != owner:
            raise ValueError("The destination agent profile already has a different owner.")
        prompt = _PROFILE_PROMPT if (home / _PROFILE_PROMPT).is_file() else ""
        overlay = _PROFILE_SOUL if (home / _PROFILE_SOUL).is_file() else None
    else:
        prompt, overlay = _stage_profile(home, source_home, source, owner)
    if existing is not None:
        return
    store.save(replace(
        base,
        id=persona_id,
        display_name=display_name,
        hermes_profile=profile,
        system_prompt_path=prompt,
        soul_overlay_path=overlay,
        skills=list(base.skills),
        required_mcp_servers=[],
        repo_scope=None,
        repo_scope_label=None,
        readiness={},
        model_override_issued_at=None,
        skills_override_issued_at=None,
        character_assignment=None,
    ))


def _archive_unbound_identity(store: PersonaInstanceStore, persona_id: str, profile: str) -> None:
    home = get_profile_dir(profile)
    marker = home / _OWNER_FILE
    if home.is_symlink() or marker.is_symlink() or not marker.is_file():
        return
    with agent_record_write_lock("persona", persona_id):
        scan = store.scan_all()
        if scan.unreadable or any(
            item.persona_id == persona_id or item.profile_id == profile
            for item in scan.instances
        ):
            raise ValueError("The agent identity may still be referenced.")
        personas = ensure_persisted_personas()
        if any(p.id != persona_id and p.hermes_profile == profile for p in personas):
            raise ValueError("The backing profile is referenced by another persona.")
        persona_file = paths.agent_path(persona_id)
        if persona_file.exists() and AgentStore().get(persona_id).hermes_profile != profile:
            raise ValueError("The agent persona has a different backing profile.")
        # Preserve evidence (and any files written between phases) outside the
        # active persona and profile inventories.
        archive = home.parent / ".retired-independent-agents" / uuid.uuid4().hex
        archive.mkdir(parents=True)
        if persona_file.exists():
            os.replace(persona_file, archive / "persona.json")
        os.replace(home, archive / "profile")


def archive_failed_placement_identity(
    store: PersonaInstanceStore, instance: PersonaInstance, placement_id: str,
) -> None:
    digest = hashlib.sha256(f"placement:{placement_id}".encode()).hexdigest()[:24]
    persona_id, profile = f"agent_{digest}", f"agent-{digest}"
    if (instance.persona_id, instance.profile_id) == (persona_id, profile):
        with agent_create_lock(f"identity-{digest}"):
            _archive_unbound_identity(store, persona_id, profile)


def create_independent_agent(
    store: PersonaInstanceStore,
    *,
    source_persona_id: str,
    display_name: str,
    placement_id: str | None = None,
    creation_key: str | None = None,
    source_instance_id: str | None = None,
    workspace_id: str | None = None,
    realm_id: str | None = None,
    client_scope: str | None = None,
    correlation_id: str | None = None,
) -> PersonaInstance:
    """One identity per placement or explicit create intent, including retries."""

    if placement_id is None and workspace_id is not None:
        try:
            workspace = WorkspaceStore().get(workspace_id)
        except NotFound as exc:
            raise ValueError("The destination workspace does not exist.") from exc
        if realm_id is not None and realm_id != workspace.realm_id:
            raise ValueError("The destination workspace belongs to a different realm.")
        realm_id = workspace.realm_id
    anchor = f"placement:{placement_id}" if placement_id else f"create:{workspace_id}:{creation_key or uuid.uuid4().hex}"
    digest = hashlib.sha256(anchor.encode()).hexdigest()[:24]
    persona_id = f"agent_{digest}"
    profile = f"agent-{digest}"
    placement = placement_id or f"independent_{digest[:16]}_agent_{digest[16:]}"
    try:
        source_instance = store.get(source_instance_id) if source_instance_id else None
    except (NotFound, FileNotFoundError) as exc:
        raise ValueError("The source agent no longer exists.") from exc
    if source_instance and source_instance.persona_id != source_persona_id:
        raise ValueError("The source agent does not belong to the requested persona.")
    with agent_create_lock(f"identity-{digest}"):
        try:
            existing = store.get(persona_instance_id_for_placement(placement))
        except (NotFound, FileNotFoundError):
            existing = None
        if existing is not None and existing.persona_id == source_persona_id:
            # A legacy placement retry keeps the identity it already owns.
            return existing
        if existing is not None and existing.persona_id != persona_id:
            raise ValueError("The placement already belongs to a different agent.")
        if existing is not None:
            _provision(source_persona_id, persona_id, profile, display_name, source_instance)
            return existing
        instance_id = persona_instance_id_for_placement(placement)
        store.assert_bindable(
            persona_id=persona_id,
            session_id=persona_chat_session_id_for(instance_id),
            persona_instance_id=instance_id,
        )
        _provision(source_persona_id, persona_id, profile, display_name, source_instance)
        try:
            return store.add_instance(
                persona_id=persona_id,
                placement_id=placement,
                display_name=display_name,
                workspace_id=workspace_id,
                realm_id=realm_id,
                client_scope=client_scope,
                correlation_id=correlation_id,
            )
        except (OSError, ValueError, PersonaChatPersistenceError, RetiredPersonaInstanceError):
            _archive_unbound_identity(store, persona_id, profile)
            raise
