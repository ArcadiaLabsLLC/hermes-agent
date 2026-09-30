"""The Launcher is the one model downloader: ``local_models.downloads`` and its caller-side wrappers.

Embedded-hermes plan D1 item 1, D2 and D3 item 1 (launcher
``docs/embedded_hermes/planned/IMPLEMENTATION_2026-09-28.md``): a bundled profile never downloads a
model itself. The switch is one profile-config key, ``local_models.downloads`` (default on — full
Hermes unchanged; off in both bundled profiles), read here and only here. Upstream's downloaders are
never edited; the fork refuses them where it CALLS INTO upstream:

* :func:`gate_model_download_routes` — the dashboard's local-model catalog / download / search /
  quickstart routes (upstream's ``hermes_cli/web_routers/local_models.py``) answer a typed 404
  before the route runs. Installed by the harness plugin's dashboard API module, which upstream's
  ``_mount_plugin_api_routes`` imports while the app is assembled.
* :func:`apply_model_download_switch` — the speech loaders' download-if-missing fallbacks
  (Piper's voice download in ``tools/tts_tool_local.py``, faster-whisper's ``local_files_only=False``
  retry in ``tools/transcription_local.py``, onnx-asr / KittenTTS / NeuTTS) all fetch through
  ``huggingface_hub``, which honours ``HF_HUB_OFFLINE``: the serve loop sets it before any loader
  is imported, so a missing model is an error, never a download.
"""

from __future__ import annotations

import os
from typing import Any, MutableMapping

__layer__ = "policy"

KEY = ("local_models", "downloads")

#: Upstream's local-model DOWNLOAD surface. The engine install and server control stay.
MODEL_DOWNLOAD_ROUTES = frozenset({
    "/api/local-models/catalog",
    "/api/local-models/download",
    "/api/local-models/download/pause",
    "/api/local-models/download/resume",
    "/api/local-models/quickstart",
    "/api/local-models/search",
    "/api/local-models/search/files",
    "/api/local-models/download-browsed",
})

FEATURE = "model_downloads"
OFFLINE_ENV = "HF_HUB_OFFLINE"


def model_downloads_enabled() -> bool:
    """``local_models.downloads`` from the merged config; absent or unreadable = on (today)."""
    from hermes_cli.config import config_switch

    return config_switch(*KEY, default=True)


def refusal_body() -> dict:
    return {
        "detail": "model downloads are switched off (local_models.downloads: false); the Launcher downloads models",
        "code": "disabled_by_profile",
        "feature": FEATURE,
        "key": ".".join(KEY),
    }


def gate_model_download_routes(app: Any) -> frozenset[str]:
    """Refuse :data:`MODEL_DOWNLOAD_ROUTES` on ``app`` when downloads are off; return what is refused.

    Every refused path must be a route upstream's router still mounts — a renamed path is a loud
    :class:`~agent_runtime.bundle_profiles.route_gate.RouteGateError`, never a gate that refuses
    nothing. Asked of the router, not ``app.openapi()``: this runs while the app is still being
    assembled, and the OpenAPI schema would be cached without the routes mounted after it.
    """
    if model_downloads_enabled():
        return frozenset()
    from agent_runtime.bundle_profiles.route_gate import ProfileRouteGate, RouteGateError
    from hermes_cli.web_routers.local_models import router

    state = getattr(app, "state", None)
    if getattr(state, "eternia_model_download_gate", False):
        return MODEL_DOWNLOAD_ROUTES
    missing = sorted(MODEL_DOWNLOAD_ROUTES - {getattr(route, "path", None) for route in router.routes})
    if missing:
        raise RouteGateError(f"refused paths name no mounted route: {missing}")
    app.add_middleware(ProfileRouteGate, paths=MODEL_DOWNLOAD_ROUTES, body=refusal_body())
    if state is not None:
        state.eternia_model_download_gate = True
    return MODEL_DOWNLOAD_ROUTES


def apply_model_download_switch(environ: MutableMapping[str, str] = os.environ) -> bool:
    """With downloads off, set ``HF_HUB_OFFLINE`` (unless the host already chose a value). Returns
    whether downloads are off. Must run before ``huggingface_hub`` is imported: it reads the
    variable once, at import."""
    if model_downloads_enabled():
        return False
    environ.setdefault(OFFLINE_ENV, "1")
    return True
