"""Rows (win32 only): upstream's OWN Windows reds at release tag v0.22.2 -- retired by an upstream fix.

Every id here was red on every run of the pure tag ``v0.22.2`` (``d923a5eb48``, a detached worktree, no
fork code) AND red on the fork's main. Written by ``scripts/classify_reds_on_tag.py``; a
per-test strict xfail, so an upstream fix turns the row into an XPASS(strict) red that
retires it. Register the table in ``hooks._merge`` and the map
``tests/_downstream/id_markers/__init__.py``.
"""

from __future__ import annotations

import pytest

from tests._downstream.id_markers.reasons import _up_red, _WIN

__layer__ = "models"

_REASON = "red on pure upstream tag v0.22.2 d923a5eb48 on Windows (2026-10-15 release merge)"

_NODES = (
        'tests/gateway/test_process_cmdline_source.py::test_psutil_answers_without_forking_ps',
        'tests/scripts/desktop_update/test_desktop_update_windows_marker.py::test_script_killed_right_after_spawning_the_update_leaves_a_live_marker',
        'tests/test_scratch_dir.py::test_prune_records_removals_and_kills_in_scratch_prune_log',
        'tests/hermes_cli/test_install_state.py::test_gateway_service_definitions_name_their_homes',
        'tests/tools/test_connector_files.py::test_a_docker_path_is_read_through_its_volume_mount',
)

ROWS: dict[str, tuple[pytest.MarkDecorator, ...]] = (
    {node: (_up_red(_REASON),) for node in _NODES} if _WIN else {}
)
