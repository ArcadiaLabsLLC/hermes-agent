"""Rows gated on an OPTIONAL distribution -- retired by installing the extra.

A table module under the floor on purpose (folding it into ``fork_marks`` would
misfile "install the extra" under "a fork change"). ``REQUIRES_DISTRIBUTION`` is
read by ``hooks._skip_if_distribution_missing``.

One ``ROWS`` table, already host-filtered; ``hooks._merge`` concatenates the four.
The map is ``tests/_downstream/id_markers/__init__.py``.
"""

from __future__ import annotations

import importlib.util

import pytest

from tests._downstream.id_markers.reasons import (
    __layer__,
    _NEEDS_ACP,
    _NEEDS_CHROME_DESKTOP_ENTRY,
    _NEEDS_NODE,
    _NEEDS_NODE_AND_PNPM,
    _NEEDS_RIPGREP,
    _NEEDS_TMUX,
)

__layer__ = "models"

ROWS: dict[str, tuple[pytest.MarkDecorator, ...]] = {
    # DEPENDENCY-bound: plugins/platforms/wecom/callback_adapter.py falls back
    # to ET=None without defusedxml; installing it retires these.
    **{
        f"tests/gateway/test_wecom_callback.py::{node}": (
            pytest.mark.skipif(
                importlib.util.find_spec("defusedxml") is None,
                reason="optional dependency 'defusedxml' is not installed",
            ),
        )
        for node in (
            "TestWecomCallbackEventConstruction::test_build_event_extracts_text_message",
            "TestWecomCallbackPollLoop::test_poll_loop_dispatches_handle_message",
        )
    },
    # A system tool, not a distribution: the live classic-CLI tests type into tmux
    # (FH-HERMES-CLI-GATEWAY-UPDATE-REDS-REMAINDER: red `FileNotFoundError: 'tmux'` on the Linux box).
    "tests/hermes_cli/test_gateway_chat_native.py::test_native_classic_fresh_resume_and_oneshot": (_NEEDS_TMUX,),
    **{
        f"tests/hermes_cli/test_gateway_chat_commands_live.py::{node}": (_NEEDS_TMUX,)
        for node in (
            "test_classic_view_title_and_usage_match_main",
            "test_classic_view_retry_undo_new_match_main",
            "test_classic_view_plan_and_goal_run_on_the_gateway",
        )
    },
    # Host tools for upstream's desktop/web build tests (FH-LINUX-BOX-SCRIPTS-NEED-NODE): each
    # asserts or spawns `node` and reds `assert None` / exit 127 on a box without it.
    "tests/scripts/test_bundle_npm.py::test_bundle_npm_runs_workspace_from_unrelated_directory": (_NEEDS_NODE,),
    "tests/scripts/test_desktop_build_cache.py::"
    "test_restored_npm_cache_installs_offline_and_excludes_job_secrets": (_NEEDS_NODE,),
    "tests/scripts/test_agent_build.py::test_payload_smoke_uses_relocated_manifest_commands": (_NEEDS_NODE,),
    "tests/scripts/test_source_build_env.py::"
    "test_posix_build_children_stamp_old_and_new_without_changing_parent[node]": (_NEEDS_NODE,),
    "tests/scripts/test_source_driver.py::"
    "test_pm_observer_accepts_ready_fixture_and_leaves_failed_fixture_untouched": (_NEEDS_NODE,),
    # Node rows, not the file: the file already carries fork_marks' timeout row (one class per key).
    **{
        f"tests/scripts/test_icon_flavors.py::{node}": (_NEEDS_NODE,)
        for node in (
            "test_canary_changes_only_desktop_background_preserving_art_and_native_geometry",
            "test_commit_icons_are_red_and_print_only_the_actual_seven_digit_prefix",
            "test_layered_macos_icon_mono_layer_and_flavor_stays_in_the_fill",
            "test_invalid_or_conflicting_build_identity_cannot_emit_icons",
            "test_msix_logos_resolve_every_slot_windows_draws",
        )
    },
    # Node (and pnpm) for upstream's photon sidecar, source-launch, web-build and desktop-reuse tests
    # (FH-LINUX-BOX-NO-NODE-UPSTREAM-REDS): red at setup or on spawn on a box without them; the
    # tests of the same files that need neither keep running.
    **{
        f"tests/plugins/platforms/photon/test_spectrum_patch.py::{node}": (_NEEDS_NODE,)
        for node in (
            "test_sidecar_patch_failure_still_reaches_health_endpoint",
            "test_spectrum_patch_rewrites_the_imessage_mapper",
        )
    },
    **{
        f"tests/hermes_cli/test_desktop_build_reuse.py::{node}": (_NEEDS_NODE,)
        for node in (
            "test_a_stamp_a_build_would_bake_differently_still_rebuilds",
            "test_update_reuses_the_packaged_app_until_a_desktop_input_changes",
        )
    },
    **{
        f"tests/hermes_cli/test_tui_npm_install.py::{node}": (_NEEDS_NODE_AND_PNPM,)
        for node in (
            "test_source_launch_prepares_base_union_but_compiles_only_tui",
            "test_source_launch_keeps_the_users_download_retries",
            "test_source_launch_ignores_an_npm_retry_count_pnpm_ignores",
            "test_source_compile_failure_stops_launch_without_reinstall",
            "test_failed_dependency_preparation_launches_the_previous_build",
            "test_fallback_names_a_refusal_that_printed_nothing",
            "test_fresh_bundle_does_not_prepare_or_compile",
            "test_prebuilt_bundle_launch_does_not_touch_missing_source",
            "test_dev_launch_builds_ink_before_running_source",
            "test_runtime_node_comes_from_pm_without_legacy_repair",
            "test_tui_rebuild_preserves_the_prepared_desktop_and_web_union",
        )
    },
    **{
        f"tests/hermes_cli/test_web_ui_build.py::{node}": (_NEEDS_NODE_AND_PNPM,)
        for node in (
            "test_web_build_prepares_once_and_skips_a_current_product",
            "test_web_failure_is_not_success_even_with_an_old_dist",
            "test_failed_preparation_never_runs_web_compilation",
            "test_web_rebuild_reuses_the_existing_desktop_union",
            "test_contended_build_waits_and_rechecks_winner",
            "test_lock_open_failure_does_not_start_an_unprotected_build",
        )
    },
    # The source-build and update-completion acceptance fixtures `assert node and pnpm`
    # (FH-LINUX-SOURCE-UPDATE-FILES-RED-ON-MAIN); both files are skip-listed `unused`, so this
    # keeps a NAMED run of them green on a box without the tools.
    **{
        f"tests/hermes_cli/test_source_build.py::{node}": (_NEEDS_NODE_AND_PNPM,)
        for node in (
            "test_installed_pnpm_does_not_authorize_missing_workspace_dependencies",
            "test_preparation_reuses_only_the_exact_completed_workspace_union",
            "test_update_builds_selected_products_after_one_union_preparation",
            "test_update_recompiles_only_products_whose_inputs_changed",
            "test_update_failure_raises_without_retries_or_replacing_live_app",
            "test_unbuilt_desktop_is_named_on_one_whole_line",
            "test_desktop_dependency_failure_still_builds_the_tui_and_web_ui",
            "test_module_cli_builds_the_requested_products",
        )
    },
    **{
        f"tests/hermes_cli/test_update_finish.py::{node}": (_NEEDS_NODE_AND_PNPM,)
        for node in (
            "test_selected_child_builds_and_finalizes_under_parent_lock",
            "test_real_compiler_failure_is_owed_build_and_completion_continues",
        )
    },
    # ripgrep (FH-LINUX-BOX-NO-RIPGREP-SEARCH-REDS): the grep fallback cannot match across lines
    # or give the zero-match hint; the doctor's parity test pins the host's own `rg`.
    "tests/tools/test_search_auto_multiline.py::TestAutoMultiline::test_newline_regex_matches_across_lines": (
        _NEEDS_RIPGREP,
    ),
    **{
        f"tests/tools/test_search_zero_match_and_multipath.py::TestZeroMatchProbe::{node}": (_NEEDS_RIPGREP,)
        for node in (
            "test_case_mismatch_hint_names_the_files",
            "test_regex_metachar_literal_hint",
            "test_hidden_only_match_gets_hint",
            "test_hidden_probe_prunes_dependency_trees_and_keeps_local_ignored",
        )
    },
    **{
        f"tests/hermes_cli/test_doctor_pm_store_probe.py::{node}": (_NEEDS_RIPGREP,)
        for node in (
            "test_rejected_store_is_not_reported_as_runtime_available",
            "test_sealed_store_extension_matches_launched_tool",
        )
    },
    # Not Node: the shim's browser choice needs an installed google-chrome.desktop (reasons.py).
    **{
        f"tests/scripts/desktop_update/test_desktop_update_shim_profile_cleanup.py::"
        f"test_shim_removes_only_its_owned_profile[{outcome}]": (_NEEDS_CHROME_DESKTOP_ENTRY,)
        for outcome in ("success", "error")
    },
    "tests/acp_adapter/test_acp_dashboard_model_switch_validation.py": (_NEEDS_ACP,),
    "tests/acp_adapter/test_edit_approval.py::"
    "test_acp_permission_tool_call_uses_edit_kind_and_diff_content": (_NEEDS_ACP,),
    # Upstream v0.23.1 (ab3afc0b89, ec24dd3556) split the one refusal test into these five.
    **{
        f"tests/acp_adapter/test_failed_turn_closure.py::{node}": (_NEEDS_ACP,)
        for node in (
            "test_acp_refusal_never_poisons_the_next_prompt",
            "test_acp_refusal_is_erased_durably_and_survives_a_reload",
            "test_acp_exception_shaped_refusal_is_also_erased",
            "test_acp_refused_turn_stays_in_the_display_tagged_content_refused",
            "test_acp_reload_replays_the_refused_ask_and_notice_to_the_editor",
        )
    },
}


#: Test directories whose modules import an OPTIONAL distribution at import. The
#: canonical test venv is the live install plus a test runner, and the live
#: install does not carry these extras, so the modules cannot collect there.
#: The probe is the import spec: the day the distribution is installed, the
#: modules collect and run again, with nothing here to delete. Only a module
#: whose collection FAILED on exactly that missing import is skipped; the rest
#: of the directory runs.
REQUIRES_DISTRIBUTION: dict[str, tuple[str, str]] = {
    "tests/acp_adapter/": ("acp", "agent-client-protocol, extra [acp]"),
}
