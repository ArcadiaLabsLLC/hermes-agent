"""Carry an opening Launcher's tools and connection into background construction.

Registration is process-wide; availability and dispatch are request-scoped.
Refreshing a catalog alone is therefore insufficient to prepare an actor.
"""

from __future__ import annotations

import logging
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Iterator

from . import launcher_app_functions as app

__layer__ = "lanes"

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class LauncherLinkPreparation:
    link: app.LauncherLink
    refresh: threading.Thread

    @classmethod
    def start(cls, link: app.LauncherLink) -> LauncherLinkPreparation:
        """Ask at the open gesture, never block the serve's reader thread."""
        refresh = threading.Thread(
            target=_refresh, args=(link,), name="persona-chat-open-link", daemon=True
        )
        refresh.start()
        return cls(link, refresh)


def _refresh(link: app.LauncherLink) -> None:
    try:
        app.refresh_app_function_tools(link)
    except Exception:
        logger.debug("chat-actor prewarm could not refresh launcher app functions", exc_info=True)


@contextmanager
def launcher_link_prewarm_scope(
    preparation: LauncherLinkPreparation | None, *, timeout: float
) -> Iterator[None]:
    """Wait for discovery, bind only this item's connection, always restore it.

    A boot item explicitly binds None: a long-lived worker must not lend the
    previous item's Launcher access to an unrelated construction.
    """
    if preparation is not None:
        preparation.refresh.join(timeout)
    token = app.bind_launcher_link(preparation.link if preparation is not None else None)
    try:
        yield
    finally:
        app.reset_launcher_link(token)
