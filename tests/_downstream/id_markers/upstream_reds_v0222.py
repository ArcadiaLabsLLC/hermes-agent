"""Rows (win32 only): upstream's OWN Windows reds at release tag v0.22.2 -- retired by an upstream fix.

Every id here was red on every run of the pure tag ``v0.22.2`` (``d923a5eb48``, a detached worktree, no
fork code) AND red on the fork's main. Written by ``scripts/classify_reds_on_tag.py``; a
per-test strict xfail, so an upstream fix turns the row into an XPASS(strict) red that
retires it. Register the table in ``hooks._merge`` and the map
``tests/_downstream/id_markers/__init__.py``.
"""

from __future__ import annotations

import pytest

from tests._downstream.id_markers.reasons import _up_red, _up_red_skip, _WIN

__layer__ = "models"

_REASON = "red on pure upstream tag v0.22.2 d923a5eb48 on Windows (2026-10-15 release merge)"

_NODES = (
        'tests/gateway/test_process_cmdline_source.py::test_psutil_answers_without_forking_ps',
        'tests/scripts/desktop_update/test_desktop_update_windows_marker.py::test_script_killed_right_after_spawning_the_update_leaves_a_live_marker',
        'tests/test_scratch_dir.py::test_prune_records_removals_and_kills_in_scratch_prune_log',
        'tests/hermes_cli/test_install_state.py::test_gateway_service_definitions_name_their_homes',
        'tests/tools/test_connector_files.py::test_a_docker_path_is_read_through_its_volume_mount',
)

# Every host, a skip not a strict xfail: the red rides on LIVE models.dev data, so a host that
# cannot reach models.dev passes. models.dev now lists ``commandcode`` with env ``CMD_API_KEY``;
# ``get_provider`` prefers the models.dev entry over the plugin profile's ``COMMANDCODE_API_KEY``.
# No fork code is on the path (providers.py and models_dev.py match upstream). Retire when
# upstream's test stops reading the live catalogue (r-reds-a 2026-10-16).
_LIVE_CATALOGUE = {
    'tests/plugins/model_providers/test_commandcode_profile.py::'
    'TestCommandCodeFetchModelsPickerContract::test_resolve_provider_full': (
        _up_red_skip("reads live models.dev, which names commandcode's key CMD_API_KEY; "
                     "the test pins the plugin's COMMANDCODE_API_KEY"),
    ),
}

ROWS: dict[str, tuple[pytest.MarkDecorator, ...]] = (
    {node: (_up_red(_REASON),) for node in _NODES} if _WIN else {}
) | _LIVE_CATALOGUE
