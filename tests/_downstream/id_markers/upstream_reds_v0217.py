"""Rows (win32 only): upstream's OWN Windows reds at release tag v0.21.7 -- retired by an upstream fix.

Every id here was red on every run of the pure tag ``v0.21.7`` (``71d34bad10``, a detached worktree, no
fork code) AND red on the fork's main. Written by ``scripts/classify_reds_on_tag.py``; a
per-test strict xfail, so an upstream fix turns the row into an XPASS(strict) red that
retires it. Register the table in ``hooks._merge`` and the map
``tests/_downstream/id_markers/__init__.py``.
"""

from __future__ import annotations

import pytest

from tests._downstream.id_markers.reasons import _up_red, _WIN

__layer__ = "models"

_REASON = "red on pure upstream tag v0.21.7 71d34bad10 on Windows (2026-10-13 release merge)"

_NODES = (
        'tests/agent/test_compaction_events.py::test_a_split_that_fails_after_rewriting_history_is_still_a_compaction',
        'tests/agent/test_compaction_events.py::test_an_in_place_engine_whose_split_fails_after_the_archive_is_still_a_compaction',
        'tests/agent/test_compaction_events.py::test_rotation_publishes_after_the_split_with_the_attempts_own_session',
        'tests/ci/test_prompt_surface.py::test_committed_prompt_surface_is_current',
        'tests/hermes_cli/test_desktop_build_lock.py::test_a_held_desktop_build_lock_keeps_an_updater_off_the_checkout',
        'tests/hermes_cli/test_desktop_build_lock.py::test_gui_releases_lock_before_packaged_electron_handoff',
        'tests/hermes_cli/test_gateway_service_owner.py::TestTempHomeServiceDefinitionGuard::test_detects_tmp_home_in_systemd_unit',
        'tests/hermes_cli/test_plugin_install_ref.py::test_canonical_source_never_persists_http_credentials',
        'tests/hermes_cli/test_plugin_install_ref.py::test_cloned_origin_never_persists_http_credentials',
        'tests/hermes_cli/test_plugin_install_ref.py::test_exact_ref_installs_old_commit_and_normalizes_uppercase',
        'tests/hermes_cli/test_plugin_install_ref.py::test_git_errors_never_echo_source_credentials',
        'tests/hermes_cli/test_plugin_install_ref.py::test_invalid_ref_is_rejected_before_any_install_state[]',
        'tests/hermes_cli/test_plugin_update_transaction.py::test_failed_update_keeps_code_metadata_config_and_environment[dependencies-catalog]',
        'tests/hermes_cli/test_plugin_update_transaction.py::test_failed_update_keeps_code_metadata_config_and_environment[dependencies-custom]',
        'tests/hermes_cli/test_plugin_update_transaction.py::test_failed_update_keeps_code_metadata_config_and_environment[manifest-catalog]',
        'tests/hermes_cli/test_plugin_update_transaction.py::test_failed_update_keeps_code_metadata_config_and_environment[manifest-custom]',
        'tests/hermes_cli/test_plugin_update_transaction.py::test_failed_update_keeps_code_metadata_config_and_environment[publication-catalog]',
        'tests/hermes_cli/test_plugin_update_transaction.py::test_failed_update_keeps_code_metadata_config_and_environment[publication-custom]',
        'tests/hermes_cli/test_plugin_update_transaction.py::test_failed_update_keeps_code_metadata_config_and_environment[version-catalog]',
        'tests/hermes_cli/test_plugin_update_transaction.py::test_failed_update_keeps_code_metadata_config_and_environment[version-custom]',
        'tests/hermes_cli/test_plugin_update_transaction.py::test_interactive_update_asks_before_installing_new_python_dependencies[n-False-custom]',
        'tests/hermes_cli/test_plugin_update_transaction.py::test_interactive_update_asks_before_installing_new_python_dependencies[y-True-custom]',
        'tests/hermes_cli/test_plugin_update_transaction.py::test_successful_update_publishes_matching_code_and_durable_workspace[catalog]',
        'tests/hermes_cli/test_plugin_update_transaction.py::test_successful_update_publishes_matching_code_and_durable_workspace[custom]',
        'tests/hermes_cli/test_plugin_update_transaction.py::test_unattended_update_refuses_newly_declared_python_dependencies[catalog]',
        'tests/hermes_cli/test_plugin_update_transaction.py::test_unattended_update_refuses_newly_declared_python_dependencies[custom]',
        'tests/hermes_cli/test_plugin_update_transaction.py::test_update_rebuilds_an_accepted_node_sidecar_when_its_manifest_moves[catalog]',
        'tests/hermes_cli/test_plugin_update_transaction.py::test_update_rebuilds_an_accepted_node_sidecar_when_its_manifest_moves[custom]',
        'tests/hermes_cli/test_plugin_worker_lifecycle.py::test_active_force_reinstall_decline_preserves_entire_selection',
        'tests/hermes_cli/test_plugin_worker_lifecycle.py::test_active_reinstall_does_not_overwrite_a_later_disable[enable]',
        'tests/hermes_cli/test_plugin_worker_lifecycle.py::test_active_reinstall_does_not_overwrite_a_later_disable[no_enable]',
        'tests/hermes_cli/test_plugin_worker_lifecycle.py::test_concurrent_commands_keep_acknowledged_enables[same-profile]',
        'tests/hermes_cli/test_plugin_worker_lifecycle.py::test_concurrent_commands_keep_acknowledged_enables[sibling-profiles]',
        'tests/hermes_cli/test_plugin_worker_lifecycle.py::test_declaration_consent_admission_and_resync[pip_dependencies-yaml]',
        'tests/hermes_cli/test_plugin_worker_lifecycle.py::test_declaration_consent_admission_and_resync[pip_dependencies-yml]',
        'tests/hermes_cli/test_plugin_worker_lifecycle.py::test_declaration_consent_admission_and_resync[pyproject-yaml]',
        'tests/hermes_cli/test_plugin_worker_lifecycle.py::test_declaration_consent_admission_and_resync[python_dependencies-yaml]',
        'tests/hermes_cli/test_plugin_worker_lifecycle.py::test_declaration_consent_admission_and_resync[python_dependencies-yml]',
        'tests/hermes_cli/test_plugin_worker_lifecycle.py::test_malformed_portable_member_cannot_join_a_new_generation',
        'tests/hermes_cli/test_plugin_worker_lifecycle.py::test_pack_admits_compatible_members_and_reports_conflict',
        'tests/hermes_cli/test_plugins_admission_setter.py::test_core_conflict_names_the_plugin_and_keeps_selection',
        'tests/hermes_cli/test_plugins_admission_setter.py::test_failed_publication_preserves_selection_and_imports[config]',
        'tests/hermes_cli/test_plugins_admission_setter.py::test_failed_publication_preserves_selection_and_imports[facts]',
        'tests/hermes_cli/test_plugins_admission_setter.py::test_historical_writer_hands_off_without_mutating_config',
        'tests/hermes_cli/test_plugins_admission_setter.py::test_ui_conflict_is_reported_without_changing_selection[composite]',
        'tests/hermes_cli/test_plugins_admission_setter.py::test_ui_conflict_is_reported_without_changing_selection[dashboard]',
        'tests/scripts/install/test_install_ps1_script_suites.py::test_suite_passes[test-install-ps1-node-compatibility.ps1-pwsh]',
        'tests/scripts/install/test_install_ps1_script_suites.py::test_suite_passes[test-install-ps1-utf8.ps1-powershell]',
        'tests/scripts/install/test_install_ps1_script_suites.py::test_suite_passes[test-install-ps1-utf8.ps1-pwsh]',
        'tests/tools/test_browser_use_cli.py::TestExecHybridPrivateUrlRouting::test_private_url_runs_on_local_sidecar_or_is_refused[lan-new_tab("http://192.168.0.1:9120/login")-None]',
        'tests/tools/test_browser_use_cli.py::TestExecHybridPrivateUrlRouting::test_private_url_runs_on_local_sidecar_or_is_refused[mixed-new_tab("https://example.com/x")\\nnew_tab("http://192.168.0.1:9120/login")-None]',
        'tests/tools/test_browser_use_cli.py::TestExecHybridPrivateUrlRouting::test_private_url_runs_on_local_sidecar_or_is_refused[rebind-private-then-public-new_tab("http://rebind.example/login")-None]',
        'tests/tools/test_browser_use_cli.py::TestExecHybridPrivateUrlRouting::test_sidecar_route_has_its_own_daemon_and_sticks_for_url_less_calls',
        'tests/tools/test_known_file_write_baseline.py::test_paged_read_carries_only_when_every_page_was_read',
)

ROWS: dict[str, tuple[pytest.MarkDecorator, ...]] = (
    {node: (_up_red(_REASON),) for node in _NODES} if _WIN else {}
)
