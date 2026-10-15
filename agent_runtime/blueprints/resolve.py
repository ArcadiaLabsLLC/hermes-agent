"""Permanent compatibility import for the upstream profile endpoint."""

from __future__ import annotations

from agent_runtime.persona_profiles import promote_profile_to_persona

__layer__ = "stores"

# ``promote_profile_to_persona`` now lives in ``agent_runtime.persona_profiles`` — it is
# persona lifecycle, not stage routing, and it
# has a live caller outside this package (mission-lane removal, S1).
#
# This re-export is NOT cosmetic. The promotion endpoint
# (``POST /api/plugins/eternia-harness/profiles/{name}/promote``) does
# ``from agent_runtime.blueprints.resolve import promote_profile_to_persona``.
# Since 2026-09-24 (lane CARRY3) the route lives in the eternia-harness
# dashboard plugin (``plugins/eternia-harness/dashboard/plugin_api.py``), no
# longer in upstream's ``hermes_cli/web_routers/profiles.py``; the import path
# must keep resolving for as long as that endpoint exists. See the S1 report and doc 18's executed-merge record.
__all__ = ["promote_profile_to_persona"]
