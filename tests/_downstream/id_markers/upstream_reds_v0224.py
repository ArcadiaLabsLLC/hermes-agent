"""Rows (win32 only): upstream's OWN Windows reds at release tag v0.22.4 -- retired by an upstream fix.

Every id here was red on both runs of the pure tag ``v0.22.4`` (``4d04303818``, a detached worktree,
no fork code; ``scripts/classify_reds_on_tag.py --tag v0.22.4``, 2026-10-22 release merge) AND red on
the merge candidate. A per-test strict xfail, so an upstream fix turns the row into an XPASS(strict)
red that retires it. Registered in ``hooks._merge`` and the map ``tests/_downstream/id_markers/__init__.py``.
"""

from __future__ import annotations

import pytest

from tests._downstream.id_markers.reasons import _up_red, _WIN

__layer__ = "models"

_REASON = "red on pure upstream tag v0.22.4 4d04303818 on Windows (2026-10-22 release merge)"

_NODES = (
        'tests/agent/lsp/test_client_e2e.py::test_reader_failure_retires_client_and_rejects_later_work[clean_eof]',
        'tests/test_live_system_guard_self_test.py::test_host_gateway_start_blocked_but_container_exec_allowed',
        'tests/agent/test_memory_provider_caller_profile.py::test_call_from_another_profiles_scope_is_refused',
        'tests/agent/test_memory_provider_caller_profile.py::test_lifecycle_hooks_from_another_profiles_scope_are_refused',
        'tests/agent/test_memory_provider_caller_profile.py::test_multiplexed_call_with_no_known_profile_is_refused',
        'tests/agent/test_memory_provider_caller_profile.py::test_multiplexed_call_without_a_caller_scope_is_refused_even_for_the_process_profile',
        'tests/agent/test_memory_provider_caller_profile.py::test_one_provider_instance_is_never_served_to_a_second_profile',
        'tests/gateway/test_session_client_env.py::test_configured_toolchain_names_a_local_client_omitted_never_leak_from_the_daemon',
        'tests/gateway/test_session_client_env.py::test_host_values_apply_only_over_a_gateway_proven_local_attach',
        'tests/gateway/test_session_policy_remote_cwd.py::test_terminal_cwd_follows_the_backend[terminal2-params2-expected2]',
        'tests/tools/test_browser_profile_live_cdp.py::test_each_profile_drives_and_reaps_its_own_harness_daemon',
        'tests/tools/test_browser_profile_scope_edges.py::test_a_served_profile_under_an_inherited_tmp_dir_nests_inside_it',
        'tests/tools/test_browser_profile_scope_edges.py::test_installed_harness_names_a_shared_dir_socket_bu_name_sock',
        'tests/tools/test_browser_profile_scope_edges.py::test_the_short_socket_dir_is_claimed_only_when_private_and_ours',
        'tests/tools/test_session_tool_env.py::test_a_sessions_terminal_runs_with_its_clients_path',
        'tests/tools/test_session_tool_env.py::test_background_process_env_starts_from_the_sessions_toolchain',
        'tests/tools/test_session_tool_env.py::test_execute_code_child_env_starts_from_the_sessions_toolchain',
        'tests/tools/test_session_tool_env.py::test_execute_code_scrubs_after_merging_the_sessions_toolchain',
        'tests/tools/test_session_tool_env.py::test_terminal_run_env_starts_from_the_sessions_toolchain',
        'tests/tools/test_terminal_trailing_amp_auto_background.py::test_trailing_amp_runs_as_tracked_background_through_the_same_guards',
        'tests/tui_gateway/test_remote_backend_launch_cwd.py::test_sandbox_resume_drops_a_stored_desktop_launch_dir[root]',
)

ROWS: dict[str, tuple[pytest.MarkDecorator, ...]] = (
    {node: (_up_red(_REASON),) for node in _NODES} if _WIN else {}
)
