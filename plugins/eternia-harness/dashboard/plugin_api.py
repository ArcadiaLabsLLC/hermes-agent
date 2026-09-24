"""Dashboard API routes of the eternia-harness plugin, mounted by upstream's
``hermes_cli.web_server_dashboard._mount_plugin_api_routes`` under
``/api/plugins/eternia-harness/``.

``POST /api/plugins/eternia-harness/profiles/{name}/promote`` was the fork-only
``POST /api/profiles/{name}/promote`` inside upstream's
``hermes_cli/web_routers/profiles.py`` until lane CARRY3 (2026-09-24).
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

_log = logging.getLogger(__name__)

router = APIRouter()


class ProfilePromoteRequest(BaseModel):
    """Body for ``POST /api/plugins/eternia-harness/profiles/{name}/promote``."""

    slot_role: str = "builder"


@router.post("/profiles/{name}/promote")
async def promote_profile_endpoint(name: str, body: ProfilePromoteRequest):
    """Mint (and persist) an agent-runtime persona backed by a raw profile.

    Promotion resolves through the permanent
    :mod:`agent_runtime.blueprints.resolve` shim, which re-exports
    ``promote_profile_to_persona`` from :mod:`agent_runtime.personas`: an
    explicit matching persona template is cloned; otherwise a profile-backed
    persona is minted from the agent-runtime defaults while the supplied
    ``slot_role`` is retained as data.
    """
    from hermes_cli import profiles as profiles_mod

    try:
        profile_name = profiles_mod.normalize_profile_name(name)
        if not profiles_mod.profile_exists(profile_name):
            raise HTTPException(status_code=404, detail=f"Profile '{profile_name}' does not exist")
        from agent_runtime.blueprints.resolve import promote_profile_to_persona

        persona = promote_profile_to_persona(profile_name, slot_role=body.slot_role)
        return {
            "ok": True,
            "profile": profile_name,
            "persona_id": persona.id,
            "persona": {
                "id": persona.id,
                "display_name": persona.display_name,
                "role": persona.role,
                "hermes_profile": persona.hermes_profile,
            },
        }
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        _log.exception("POST /api/plugins/eternia-harness/profiles/%s/promote failed", name)
        raise HTTPException(status_code=500, detail=str(exc))
