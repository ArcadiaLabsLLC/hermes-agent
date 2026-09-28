"""Refuse a profile's switched-off upstream routes, caller-side — upstream's router is never edited.

The bundled desktop profile does not serve upstream's local-model download
surface (``hermes_cli/web_routers/local_models.py``): the Launcher's download
manager owns every model download. :func:`install_route_gate` adds one ASGI
middleware to the dashboard app that answers each refused path with a 404 and
a typed body naming the profile and the switched-off feature, before the route
runs.

Install time is checked against the app itself: every refused path must name
a route that is actually mounted, so a path upstream renames turns into a loud
:class:`RouteGateError` rather than a gate that silently refuses nothing.
"""

from __future__ import annotations

import json
from typing import Any, Awaitable, Callable

from agent_runtime.bundle_profiles.manifest import ProfileManifest

__layer__ = "policy"

REFUSAL_STATUS = 404
REFUSAL_CODE = "disabled_by_profile"

_Scope = dict
_Receive = Callable[[], Awaitable[dict]]
_Send = Callable[[dict], Awaitable[None]]


class RouteGateError(RuntimeError):
    """A refused path names no mounted route."""


def mounted_paths(app: Any) -> set[str]:
    """Every route path the app serves, asked of the app's public OpenAPI surface.

    FastAPI >= 0.140 keeps an included router as one lazy ``_IncludedRouter``
    entry with no ``path``, so ``app.router.routes`` no longer enumerates the
    included paths; ``app.openapi()`` does on every version. Plain routes are
    unioned in for anything mounted with ``include_in_schema=False``.
    """
    paths = {getattr(route, "path", None) for route in app.router.routes} - {None}
    return paths | set((app.openapi() or {}).get("paths", {}))


def refusal_body(manifest: ProfileManifest) -> dict:
    return {
        "detail": f"{manifest.refused_routes.feature} is switched off in the {manifest.profile} profile",
        "code": REFUSAL_CODE,
        "profile": manifest.profile,
        "feature": manifest.refused_routes.feature,
    }


class ProfileRouteGate:
    """ASGI middleware: refuse ``paths`` for HTTP and websocket scopes; pass everything else."""

    def __init__(self, app: Any, *, paths: frozenset[str], body: dict) -> None:
        self.app = app
        self.paths = paths
        self._payload = json.dumps(body).encode("utf-8")

    def refuses(self, path: str) -> bool:
        return path.rstrip("/") in self.paths if path != "/" else "/" in self.paths

    async def __call__(self, scope: _Scope, receive: _Receive, send: _Send) -> None:
        if scope.get("type") in ("http", "websocket") and self.refuses(scope.get("path", "")):
            if scope["type"] == "websocket":
                await send({"type": "websocket.close", "code": 1008})
                return
            await send({
                "type": "http.response.start",
                "status": REFUSAL_STATUS,
                "headers": [(b"content-type", b"application/json"),
                            (b"content-length", str(len(self._payload)).encode())],
            })
            await send({"type": "http.response.body", "body": self._payload})
            return
        await self.app(scope, receive, send)


def install_route_gate(app: Any, manifest: ProfileManifest) -> frozenset[str]:
    """Add the gate to ``app`` (before it starts serving); return the refused paths."""
    paths = frozenset(manifest.refused_routes.paths)
    if not paths:
        return paths
    missing = sorted(paths - mounted_paths(app))
    if missing:
        raise RouteGateError(f"refused paths name no mounted route: {missing}")
    app.add_middleware(ProfileRouteGate, paths=paths, body=refusal_body(manifest))
    return paths
