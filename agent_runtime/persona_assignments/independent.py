"""Provision the private identity of an explicitly authored agent."""

from __future__ import annotations

import hashlib
import os
import uuid
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, Any

from hermes_cli.profiles import get_profile_dir
from hermes_constants import get_hermes_home

from .. import paths, yaml_io
from ..agent_profile_create import OWNER_FILE, create_agent_profile
from ..config.roster import ensure_persisted_personas
from ..errors import NotFound
from ..locks import agent_create_lock, agent_record_write_lock
from ..models import AgentPersona, PersonaInstance, apply_instance_model_overrides
from ..persona_chat_durability import PersonaChatPersistenceError
from ..prompt_sources import resolve_persona_system_prompt_path
from ..redaction import is_secret_field_name
from ..store import AgentStore, WorkspaceStore
from ..sync_admission import content_refusal, payload_refusal
from .errors import RetiredPersonaInstanceError
from .identity import persona_chat_session_id_for, persona_instance_id_for_placement

if TYPE_CHECKING:
    from .store import PersonaInstanceStore

__layer__ = "stores"

_OWNER_FILE = OWNER_FILE
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


#: The source's ``model:`` keys a copy carries: which model, through which provider
#: and endpoint, spoken how. Never ``api_key`` (nor ``api``, which the runtime also
#: reads as a key): the copy's turns borrow the head's sign-in, as the source's do.
_CARRIED_MODEL_KEYS = ("default", "provider", "base_url", "api_mode")
#: The fields of a named custom endpoint (``providers.<key>`` or a legacy
#: ``custom_providers`` item) a copy carries. An allowlist: ``api_key``,
#: ``key_env``, ``key_cmd``, ``extra_headers`` and ``extra_body`` can hold or fetch
#: a credential and stay with the source.
_CARRIED_ENDPOINT_KEYS = (
    "name", "api", "url", "base_url", "api_mode", "transport",
    "model", "default_model", "models", "context_length",
)


def _without_credential_names(value: Any) -> Any:
    """``value`` without any nested field (inside ``models``, say) the one key rule
    (``redaction.is_secret_field_name``) names a secret; a secret VALUE under another name is
    :func:`_credential_free`'s second step."""

    if isinstance(value, dict):
        return {
            key: _without_credential_names(item) for key, item in value.items() if not is_secret_field_name(key)
        }
    if isinstance(value, list):
        return [_without_credential_names(item) for item in value]
    return value


def _credential_free(fields: dict[str, Any]) -> dict[str, Any]:
    """Drop credential-named nested fields, then each field whose value still
    carries a secret-shaped assignment.

    Realm portability is not this test: a copy stays on this machine, and a raw
    profile ``config.yaml`` never publishes (``realm_sync.persona_artifacts``).
    """

    fields = {key: _without_credential_names(value) for key, value in fields.items()}
    return {key: value for key, value in fields.items() if payload_refusal({key: value}, check_portability=False) is None}


def _named_endpoint(config: dict[str, Any], provider: str) -> dict[str, Any]:
    """The source's own ``custom:<name>`` endpoint entry, credential fields left out."""

    from hermes_cli.providers import custom_provider_aliases

    wanted = provider.strip().lower()
    providers = config.get("providers")
    for key, entry in (providers.items() if isinstance(providers, dict) else ()):
        if isinstance(entry, dict) and wanted in custom_provider_aliases(str(entry.get("name") or key), str(key)):
            carried = _credential_free({k: entry[k] for k in _CARRIED_ENDPOINT_KEYS if k in entry})
            return {"providers": {key: carried}} if carried else {}
    legacy = config.get("custom_providers")
    for entry in legacy if isinstance(legacy, list) else ():
        if isinstance(entry, dict) and wanted in custom_provider_aliases(
            str(entry.get("name") or ""), str(entry.get("provider_key") or ""),
        ):
            carried = _credential_free({k: entry[k] for k in _CARRIED_ENDPOINT_KEYS if k in entry})
            return {"custom_providers": [carried]} if carried else {}
    return {}


def _carried_model_config(home: Path) -> dict[str, Any]:
    """The ``config.yaml`` a copy of the agent at ``home`` starts from.

    It answers through the same model and endpoint as its source (row
    ``RT-AGENT-COPY-DROPS-ITS-SOURCES-MODEL-ENDPOINT``), and carries no
    credential value and no other setting the copy owns.
    """

    path = home / "config.yaml"
    if path.is_symlink() or not path.is_file():
        return {}
    config = yaml_io.load(path.read_text(encoding="utf-8"))
    if not isinstance(config, dict):
        return {}
    model = config.get("model")
    if isinstance(model, str):
        model = {"default": model}
    if not isinstance(model, dict):
        return {}
    carried = _credential_free({
        key: value for key in _CARRIED_MODEL_KEYS if isinstance((value := model.get(key)), str)
    })
    if not carried:
        return {}
    provider = carried.get("provider", "")
    endpoint = _named_endpoint(config, provider) if provider.strip().lower().startswith("custom:") else {}
    return {"model": carried, **endpoint}


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

    def populate(made: Path) -> None:
        (made / "personas").mkdir(parents=True, exist_ok=True)
        if prompt is not None:
            (made / _PROFILE_PROMPT).write_text(prompt, encoding="utf-8")
        if overlay is not None:
            (made / _PROFILE_SOUL).write_text(overlay, encoding="utf-8")

    # The one profile creator (``agent_profile_create``), never a hand staging.
    create_agent_profile(home.name, owner=owner, config=_carried_model_config(source_home), soul=soul, populate=populate)
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
        retired_persona = persona_file.exists()
        if retired_persona:
            os.replace(persona_file, archive / "persona.json")
        os.replace(home, archive / "profile")
    if retired_persona:
        from ..events import EventLog
        from ..state_patches.persona import emit_persona_updated

        # The failed create's record is gone: a client that folded its create
        # patch re-reads the catalog from the full core this refresh demotes to.
        emit_persona_updated(EventLog(), persona_id=persona_id, display_name=None)


def archive_failed_placement_identity(
    store: PersonaInstanceStore, instance: PersonaInstance, placement_id: str,
) -> None:
    digest = hashlib.sha256(f"placement:{placement_id}".encode()).hexdigest()[:24]
    persona_id, profile = f"agent_{digest}", f"agent-{digest}"
    if (instance.persona_id, instance.profile_id) == (persona_id, profile):
        with agent_create_lock(f"identity-{digest}"):
            _archive_unbound_identity(store, persona_id, profile)


def _create_digest(placement_id: str | None, workspace_id: str | None, creation_key: str | None) -> str:
    anchor = f"placement:{placement_id}" if placement_id else f"create:{workspace_id}:{creation_key or uuid.uuid4().hex}"
    return hashlib.sha256(anchor.encode()).hexdigest()[:24]


def _source_instance(store: PersonaInstanceStore, source_persona_id: str, source_instance_id: str | None):
    try:
        source_instance = store.get(source_instance_id) if source_instance_id else None
    except (NotFound, FileNotFoundError) as exc:
        raise ValueError("The source agent no longer exists.") from exc
    if source_instance and source_instance.persona_id != source_persona_id:
        raise ValueError("The source agent does not belong to the requested persona.")
    return source_instance


def create_agent_template(
    store: PersonaInstanceStore,
    *,
    source_persona_id: str,
    display_name: str,
    creation_key: str,
    source_instance_id: str | None = None,
    refuse_taken_name: bool = False,
) -> AgentPersona:
    """A NEW agent made with no workspace: its persona and profile only, a template.

    No instance and no chat: an instance stands in a workspace, and this create
    names none (rows ``RT-FU-A-NEW-AGENT-MADE-WITH-NO-WORKSPACE-HAS-NO-INSTANCE-UNTIL-IT-IS-PLACED``,
    ``RT-FU-CREATE-INDEPENDENT-COPY-LEAVES-AN-INSTANCE-PLACED-NOWHERE``; owner
    2026-11-21: every live agent is a placed instance). Its first New chat places
    one, as for any template (``agent_create.staff.reuse_or_place``).

    One identity per ``creation_key``: a retry of the same key returns the agent
    it already made before the name is asked, so it never meets its own name.
    """

    digest = _create_digest(None, None, creation_key)
    persona_id, profile = f"agent_{digest}", f"agent-{digest}"
    source_instance = _source_instance(store, source_persona_id, source_instance_id)
    with agent_create_lock(f"identity-{digest}"):
        try:
            made = AgentStore().get(persona_id)
        except NotFound:
            made = None
        # MUTATION: ask the name before this lookup and
        # test_a_retry_after_a_crash_before_the_receipt_answers_its_own_agent reddens
        # (the retry meets its own agent's name).
        if made is None and refuse_taken_name:
            from ..agent_create.outcome import AgentCreateNameTaken
            from ..agent_duplicate import name_is_taken

            if name_is_taken(display_name):
                raise AgentCreateNameTaken(display_name)
        _provision(source_persona_id, persona_id, profile, display_name, source_instance)
        return AgentStore().get(persona_id)


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
    refuse_taken_name: bool = False,
) -> PersonaInstance:
    """One identity per placement or explicit create intent, including retries.

    ``refuse_taken_name`` raises :class:`AgentCreateNameTaken` before anything is
    written when a FRESH mint would take a name an agent already has; a retry of
    the same key returns its own agent first and never meets its own name. The
    caller holds ``AGENT_NAME_LOCK`` around the call, as ``runtime.agent.create``
    does (row ``RT-INDEPENDENT-AGENT-COPY-HAS-ONE-ACTION``, seen 2026-11-19: two
    copies of Base both named "Base Agent copy")."""

    if not workspace_id:
        # An instance stands in a workspace; with none, the agent is its template only
        # (:func:`create_agent_template`). MUTATION: drop this refusal and
        # test_an_independent_agent_instance_is_never_made_in_no_workspace reddens.
        raise ValueError("An agent's instance needs a workspace; with none, make its template only.")
    if placement_id is None:
        try:
            workspace = WorkspaceStore().get(workspace_id)
        except NotFound as exc:
            raise ValueError("The destination workspace does not exist.") from exc
        if realm_id is not None and realm_id != workspace.realm_id:
            raise ValueError("The destination workspace belongs to a different realm.")
        realm_id = workspace.realm_id
    digest = _create_digest(placement_id, workspace_id, creation_key)
    persona_id = f"agent_{digest}"
    profile = f"agent-{digest}"
    placement = placement_id or f"independent_{digest[:16]}_agent_{digest[16:]}"
    source_instance = _source_instance(store, source_persona_id, source_instance_id)
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
        if refuse_taken_name:
            from ..agent_create.outcome import AgentCreateNameTaken
            from ..agent_duplicate import name_is_taken

            if name_is_taken(display_name):
                raise AgentCreateNameTaken(display_name)
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
