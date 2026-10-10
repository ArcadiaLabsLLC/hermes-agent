"""D1.03 S3 — two attached Launchers no longer move the chat-lane bundle's registry component.

``visibility_bundle_rebuild_component_registry_content`` is written when the bundle key's
``registry_content`` component (``chat_lane_bundle.registry_content_revision``: tool names,
toolsets, aliases, the check_fn epoch) moved between two turns. Before D1.03 each turn of a
two-Launcher serve re-synced the registry to its own Launcher's list, so alternating turns
moved that component every time. Here the component's source is read per turn, alternating
A / B / A / B with each turn's link bound, and must not move.
"""

from __future__ import annotations

import pytest

from agent_runtime import launcher_app_functions as laf
from agent_runtime.chat_lane_bundle import registry_content_revision
from tests.agent_runtime.test_launcher_app_functions import _TOOLS, _Launcher


@pytest.fixture(autouse=True)
def _clean():
    laf._reset_for_tests()
    yield
    laf._reset_for_tests()


def _turn(link) -> tuple[str, int]:
    """One chat turn's registry read: the turn binds its link and refreshes its catalog."""

    from tools.registry import registry

    token = laf.bind_launcher_link(link)
    try:
        laf.refresh_app_function_tools(link)
        return registry_content_revision(), registry.generation
    finally:
        laf.reset_launcher_link(token)


def test_alternating_launchers_never_move_the_registry_content_component():
    stdio = laf.LauncherLink(_Launcher(), laf.ORIGIN_LOCAL)
    socket = laf.LauncherLink(_Launcher(_TOOLS[:1]), laf.ORIGIN_LOCAL)
    _turn(stdio), _turn(socket)  # both catalogs listed: the union is in place

    readings = [_turn(link) for link in (stdio, socket, stdio, socket, stdio)]

    revisions = {revision for revision, _ in readings}
    generations = {generation for _, generation in readings}
    assert len(revisions) == 1, "visibility_bundle_rebuild_component_registry_content would read 1"
    assert len(generations) == 1
