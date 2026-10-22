"""Rows (win32 only): upstream's OWN Windows reds at release tag v0.22.2 -- retired by an upstream fix.

Every id here was red on every run of the pure tag ``v0.22.2`` (``d923a5eb48``, a detached worktree, no
fork code) AND red on the fork's main. Written by ``scripts/classify_reds_on_tag.py``; a
per-test strict xfail, so an upstream fix turns the row into an XPASS(strict) red that
retires it. Register the table in ``hooks._merge`` and the map
``tests/_downstream/id_markers/__init__.py``.
"""

from __future__ import annotations

import os
import sys

import pytest

from tests._downstream.id_markers.reasons import _up_red, _up_red_skip, _up_red_when, _WIN

__layer__ = "models"

_REASON = "red on pure upstream tag v0.22.2 d923a5eb48 on Windows (2026-10-15 release merge)"

_NODES = (
        'tests/scripts/desktop_update/test_desktop_update_windows_marker.py::test_script_killed_right_after_spawning_the_update_leaves_a_live_marker',
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

# Windows 10 (build < 22000) maps ``nul.<ext>`` to the NUL device: upstream's fixture file
# ``nul.txt`` is never written and read_file reports ``not_found``. Windows 11 dropped the
# extension rule, so the row is keyed on the build (r-reds-a 2026-10-16).
_NUL_IS_A_DEVICE = _WIN and sys.getwindowsversion().build < 22000
_RESERVED_NAME = {
    'tests/tools/test_read_file_utf8_binary_regression.py::'
    'TestReadFileBinaryClassification::test_nul_byte_in_text_stays_binary': (
        _up_red_when(_NUL_IS_A_DEVICE, "the fixture file is named nul.txt, a reserved device "
                     "name on Windows 10; the write goes to NUL and read_file reports not_found"),
    ),
}

# Upstream's update-completion process tests on Windows, red on the pure tag and on main with the
# same 9 ids (q-reds 2026-10-18), two causes. LOCK: the bootstrap joins the checkout lock
# (``update_completion._prepare``), so ``complete_source_checkout`` in the --prepared child reads
# "its owner exited but a process it started still holds the checkout" and the tail is owed.
# RESUME: the post-commit failure paths record a ``windows_resume`` follow-up the test pins absent.
_COMPLETION_ROWS = {
    node: (_up_red(f"{_REASON}; {why}"),)
    for why, nodes in (
        ("the --prepared child's UpdateLock refuses the bootstrap's checkout lease", (
            'tests/hermes_cli/test_update_completion_process.py::'
            'test_old_process_new_git_tree_completes_in_fresh_python[None]',
            'tests/hermes_cli/test_update_completion_process.py::'
            'test_old_process_new_git_tree_completes_in_fresh_python[request]',
            'tests/hermes_cli/test_update_completion_process.py::'
            'test_old_process_new_git_tree_completes_in_fresh_python[receipt]',
            'tests/hermes_cli/test_update_completion_process.py::'
            'test_failed_build_after_commit_is_a_followup_and_later_steps_still_run',
            'tests/hermes_cli/test_update_completion_process.py::'
            'test_progress_is_forwarded_before_held_stage_is_released[selected]',
        )),
        ("Windows adds a windows_resume follow-up the test pins as ['completion']", (
            'tests/hermes_cli/test_update_completion_process.py::'
            'test_missing_child_result_is_an_owed_completion_and_releases_lock[0]',
            'tests/hermes_cli/test_update_completion_process.py::'
            'test_missing_child_result_is_an_owed_completion_and_releases_lock[23]',
            'tests/hermes_cli/test_update_completion_process.py::'
            'test_missing_child_result_is_an_owed_completion_and_releases_lock[-9]',
            'tests/hermes_cli/test_update_completion_process.py::'
            'test_completion_spawn_failure_after_commit_is_owed',
        )),
    )
    for node in nodes
}

# A host whose checkout drive has no ``\tmp`` (hosted Windows CI): upstream declares the session cwd
# as the literal "/tmp" and ``resolve_context_cwd`` rightly returns None for a missing directory
# (CI runs 38427670480 / 38439426620). Keyed on the directory, so a box that has one runs it bare.
_NO_ROOT_TMP = _WIN and not os.path.isdir("/tmp")
_ROOT_TMP_LITERAL = {
    "tests/acp_adapter/test_server.py::TestRegisterSessionMcpServers::test_registers_stdio_servers": (
        _up_red_when(_NO_ROOT_TMP, 'declares the session cwd as the literal "/tmp", which the '
                     "checkout's drive does not carry; resolve_context_cwd returns None"),
    ),
}

ROWS: dict[str, tuple[pytest.MarkDecorator, ...]] = (
    {node: (_up_red(_REASON),) for node in _NODES}
    | _COMPLETION_ROWS
    if _WIN else {}
) | _LIVE_CATALOGUE | _RESERVED_NAME | _ROOT_TMP_LITERAL
